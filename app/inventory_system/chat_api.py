"""
chat_api.py
===========

Production HTTP API for the chatbot backend. Dependency-free (Python stdlib
`http.server`) so it runs and is testable anywhere — the same endpoint a
website chatbot, WhatsApp bot, Android app, or future voice agent can call.

Endpoints
---------
  GET  /health   -> {"status":"ok","inventory_count":N,...}
  POST /chat     -> body {"message": "..."} ->
                    {"intent","response","vehicles",...}

All request handling routes through `ChatService` (chat_service.py), which owns
the parse -> retrieve -> format pipeline. No LLM, no voice, no WhatsApp, no
frontend here — just a thin, well-logged, error-handled JSON transport.

The routing logic lives in the pure `route()` function so it can be unit-tested
without opening a socket; `run()` / `make_handler()` wrap it for real serving.

Run:  python chat_api.py            # serves on 0.0.0.0:8000
"""

from __future__ import annotations

import os
import sys
import json
import time
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Tuple

from chat_service import ChatService, ChatInputError, get_service, _build_logger, _log
from instrumented_chat_service import InstrumentedChatService
import config
import inventory_upload
import inventory_edit
import vehicle_detail
import media_admin
import owner_panel
import user_management
import permissions
import auth
import audit
import developer_auth
import developer_dashboard
from security import SecurityGate, RateLimiter

ACCESS_LOG = _build_logger()


def default_gate() -> SecurityGate:
    """Build the security gate from config (auth/rate-limit/CORS)."""
    return SecurityGate(
        api_keys=config.API_KEYS, admin_keys=config.ADMIN_API_KEYS,
        limiter=RateLimiter(config.RATE_LIMIT_MAX, config.RATE_LIMIT_WINDOW),
        allowed_origins=config.CORS_ALLOWED_ORIGINS)


def check_startup_security() -> None:
    """Emit loud startup warnings for insecure-for-production settings, and
    (in CHAT_ENV=production) refuse to start while hard blockers remain.
    Security-only; does not touch chatbot behavior."""
    warnings = config.security_warnings()
    for w in warnings:
        _log(ACCESS_LOG, logging.WARNING, "security_warning", detail=w)
    blockers = config.production_blockers()
    if warnings:
        print("\n" + "=" * 72, file=sys.stderr)
        print(f"  SECURITY — environment: {config.ENV}", file=sys.stderr)
        for w in warnings:
            print(f"  [WARN] {w}", file=sys.stderr)
        if config.IS_PRODUCTION and blockers:
            print("  [FATAL] production blockers:", file=sys.stderr)
            for b in blockers:
                print(f"          - {b}", file=sys.stderr)
        print("=" * 72 + "\n", file=sys.stderr)
    if config.IS_PRODUCTION and blockers:
        _log(ACCESS_LOG, logging.ERROR, "security_startup_refused", blockers=blockers)
        raise SystemExit(
            "Refusing to start in production with insecure settings: "
            + "; ".join(blockers))


# ─────────────────────────────────────────────────────────────────────────────
# Pure routing (socket-free, unit-testable)
# ─────────────────────────────────────────────────────────────────────────────
def route(method: str, path: str, body: bytes, service: ChatService,
          content_type: str = "", acting_user: str = None,
          session_token: str = None
          ) -> Tuple[int, Dict[str, Any]]:
    """Return (http_status, json_body). Never raises."""
    raw_path = path or "/"
    query_string = raw_path.split("?", 1)[1] if "?" in raw_path else ""
    path = raw_path.split("?", 1)[0].rstrip("/") or "/"

    # ── Phase 10D: authentication (login / logout / who-am-i) ──
    # These are public at the gate; the handlers themselves validate the token.
    if method == "POST" and path == "/auth/login":
        try:
            return auth.handle_login(body)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "auth_login_error", error=str(e))
            return 500, {"error": "auth_login_failed", "detail": str(e)}
    if method == "POST" and path == "/auth/logout":
        return auth.handle_logout(session_token)
    if method == "GET" and path == "/auth/me":
        return auth.handle_me(session_token)

    # ── Developer Dashboard (read-only monitoring / observability) ──
    # Its OWN separate authorization layer: EVERY /developer/* endpoint requires
    # an active "Developer" session (developer_auth.authorize) — customers,
    # staff, and even the Owner are rejected. All handlers are strictly
    # read-only; nothing here mutates inventory/media/Excel/users/sessions.
    if path == "/developer" or path.startswith("/developer/"):
        denial = developer_auth.authorize(session_token)
        if denial is not None:
            _log(ACCESS_LOG, logging.WARNING, "developer_denied",
                 path=path, status=denial[0])
            return denial
        if method != "GET":
            return 405, {"error": "method_not_allowed",
                         "detail": f"{method} not allowed on {path}."}
        try:
            if path == "/developer/overview":
                return developer_dashboard.handle_overview(service)
            if path == "/developer/chats":
                return developer_dashboard.handle_chats(service, query_string)
            if path == "/developer/chats/export":
                return developer_dashboard.handle_chat_export(service, query_string)
            if path.startswith("/developer/chats/"):
                sid = path[len("/developer/chats/"):]
                return developer_dashboard.handle_chat_detail(service, sid)
            if path == "/developer/activity":
                return developer_dashboard.handle_activity(query_string)
            if path == "/developer/inventory":
                return developer_dashboard.handle_inventory(service)
            if path == "/developer/inventory/history":
                return developer_dashboard.handle_inventory_history(query_string)
            if path == "/developer/health":
                return developer_dashboard.handle_health(service)
            if path == "/developer/errors":
                return developer_dashboard.handle_errors(query_string)
            if path == "/developer/analytics":
                return developer_dashboard.handle_analytics(service, query_string)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "developer_error", path=path, error=str(e))
            return 500, {"error": "developer_failed",
                         "detail": "Monitoring query failed."}
        return 404, {"error": "not_found", "detail": f"No route for {method} {path}."}

    # ── Phase 10C: role-based permission gate (single choke point) ──
    # Identity is the logged-in session (Phase 10D); the legacy X-Acting-User
    # header is still accepted as a fallback so existing tooling keeps working.
    if path.startswith("/admin"):
        denial = permissions.enforce(method, path, acting_user, service, body)
        if denial is not None:
            _log(ACCESS_LOG, logging.WARNING, "permission_denied",
                 path=path, user=acting_user)
            return denial

    if method == "GET" and path == "/admin/users/my_permissions":
        try:
            return permissions.describe(acting_user or "", service)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "my_permissions_error", error=str(e))
            return 500, {"error": "my_permissions_failed", "detail": str(e)}

    # ── health ──
    if method == "GET" and path in ("/", "/health"):
        return 200, service.health()

    # ── customer vehicle detail (public, read-only): GET /vehicle?reg=<reg> ──
    # Card click -> exact vehicle by registration -> CURRENT record, customer-safe
    # fields + that car's media. Sold/removed -> "no longer available". Never
    # reuses the admin get_car (which returns internal columns).
    if method == "GET" and path == "/vehicle":
        try:
            return vehicle_detail.handle_vehicle_detail(service, query_string)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "vehicle_detail_error", error=str(e))
            return 500, {"error": "vehicle_detail_failed", "detail": str(e)}

    # ── chat ──
    if method == "POST" and path == "/chat":
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return 400, {"error": "invalid_json",
                         "detail": "Request body must be valid JSON."}
        if not isinstance(payload, dict):
            return 400, {"error": "invalid_body",
                         "detail": "JSON body must be an object."}
        message = payload.get("message")
        session_id = payload.get("session_id")          # optional; enables lead capture
        try:
            result = service.handle(message, session_id=session_id)
            return 200, result.to_dict()
        except ChatInputError as e:
            return 400, {"error": "bad_request", "detail": str(e)}
        except Exception as e:                       # last-resort safety net
            _log(ACCESS_LOG, logging.ERROR, "unhandled_error",
                 path=path, error=str(e), error_type=type(e).__name__)
            return 500, {"error": "internal_error",
                         "detail": "Something went wrong handling the request."}

    # ── admin: runtime inventory refresh (no restart) ──
    if method == "POST" and path == "/admin/refresh_inventory":
        try:
            return 200, service.refresh_inventory()
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "refresh_error", error=str(e))
            return 500, {"error": "refresh_failed", "detail": str(e)}

    # ── admin: inventory status (for the upload page header) ──
    if method == "GET" and path == "/admin/inventory_status":
        try:
            return inventory_upload.handle_status(service)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "inventory_status_error", error=str(e))
            return 500, {"error": "status_failed", "detail": str(e)}

    # ── admin: owner inventory upload (validate -> backup -> replace -> refresh) ──
    if method == "POST" and path == "/admin/upload_inventory":
        try:
            return inventory_upload.handle_upload(service, body, content_type)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "upload_error", error=str(e))
            return 500, {"error": "upload_failed", "detail": str(e)}

    # ── admin: inventory dashboard data (Phase 9B) — gated by the same admin key ──
    if method == "GET" and path == "/admin/inventory/dashboard":
        try:
            return inventory_edit.handle_dashboard(service)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "inv_dashboard_error", error=str(e))
            return 500, {"error": "inv_dashboard_failed", "detail": str(e)}

    # ── admin: inventory row edit / add (Phase 9A) — gated by the same admin key ──
    if method == "GET" and path == "/admin/inventory/schema":
        try:
            return inventory_edit.handle_schema(service)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "inv_schema_error", error=str(e))
            return 500, {"error": "inv_schema_failed", "detail": str(e)}

    if method == "GET" and path == "/admin/inventory/vehicles":
        try:
            return inventory_edit.handle_vehicles(service)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "inv_vehicles_error", error=str(e))
            return 500, {"error": "inv_vehicles_failed", "detail": str(e)}

    if method == "POST" and path == "/admin/inventory/get_car":
        try:
            return inventory_edit.handle_get_car(service, body)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "inv_get_car_error", error=str(e))
            return 500, {"error": "inv_get_car_failed", "detail": str(e)}

    if method == "POST" and path == "/admin/inventory/update_car":
        try:
            return inventory_edit.handle_update_car(service, body)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "inv_update_car_error", error=str(e))
            return 500, {"error": "inv_update_car_failed", "detail": str(e)}

    if method == "POST" and path == "/admin/inventory/add_car":
        try:
            return inventory_edit.handle_add_car(service, body)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "inv_add_car_error", error=str(e))
            return 500, {"error": "inv_add_car_failed", "detail": str(e)}

    if method == "POST" and path == "/admin/inventory/restore_car":
        try:
            return inventory_edit.handle_restore_car(service, body)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "inv_restore_error", error=str(e))
            return 500, {"error": "inv_restore_failed", "detail": str(e)}

    if method == "POST" and path == "/admin/inventory/duplicate_audit":
        try:
            return inventory_edit.handle_duplicate_audit(service)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "inv_dup_audit_error", error=str(e))
            return 500, {"error": "inv_dup_audit_failed", "detail": str(e)}

    # ── admin: Owner Panel (Phase 10A) — Excel management, same admin gate ──
    if method == "GET" and path == "/admin/owner/status":
        try:
            return owner_panel.handle_status(service)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "owner_status_error", error=str(e))
            return 500, {"error": "owner_status_failed", "detail": str(e)}

    if method == "POST" and path == "/admin/owner/upload":
        try:
            return owner_panel.handle_upload(service, body, content_type)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "owner_upload_error", error=str(e))
            return 500, {"error": "owner_upload_failed", "detail": str(e)}

    if method == "POST" and path == "/admin/owner/rollback":
        try:
            return owner_panel.handle_rollback(service, body)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "owner_rollback_error", error=str(e))
            return 500, {"error": "owner_rollback_failed", "detail": str(e)}

    if method == "POST" and path == "/admin/owner/delete_backup":
        try:
            return owner_panel.handle_delete_backup(service, body)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "owner_delete_backup_error", error=str(e))
            return 500, {"error": "owner_delete_backup_failed", "detail": str(e)}

    if method == "GET" and path == "/admin/owner/download":
        try:
            _slot = "live"
            for _kv in query_string.split("&"):
                if _kv.startswith("slot="):
                    _slot = _kv.split("=", 1)[1]
            return owner_panel.handle_download(service, _slot)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "owner_download_error", error=str(e))
            return 500, {"error": "owner_download_failed", "detail": str(e)}

    # ── admin: Owner customer-conversation log (read-only + export, owner-only) ──
    if method == "GET" and path == "/admin/owner/chat_logs":
        try:
            return owner_panel.handle_chat_logs(service, query_string)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "owner_chat_logs_error", error=str(e))
            return 500, {"error": "owner_chat_logs_failed", "detail": str(e)}

    if method == "GET" and path == "/admin/owner/chat_logs/detail":
        try:
            return owner_panel.handle_chat_logs_detail(service, query_string)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "owner_chat_detail_error", error=str(e))
            return 500, {"error": "owner_chat_detail_failed", "detail": str(e)}

    if method == "GET" and path == "/admin/owner/chat_logs/export":
        try:
            return owner_panel.handle_chat_logs_export(service, query_string)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "owner_chat_export_error", error=str(e))
            return 500, {"error": "owner_chat_export_failed", "detail": str(e)}

    # ── admin: User Management (Phase 10B) — same admin gate ──
    if method == "GET" and path == "/admin/users/list":
        try:
            return user_management.handle_list()
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "users_list_error", error=str(e))
            return 500, {"error": "users_list_failed", "detail": str(e)}

    if method == "POST" and path in ("/admin/users/create", "/admin/users/update",
                                     "/admin/users/set_active",
                                     "/admin/users/reset_password",
                                     "/admin/users/delete"):
        handler = {"/admin/users/create": user_management.handle_create,
                   "/admin/users/update": user_management.handle_update,
                   "/admin/users/set_active": user_management.handle_set_active,
                   "/admin/users/reset_password": user_management.handle_reset_password,
                   "/admin/users/delete": user_management.handle_delete}[path]
        try:
            return handler(body)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "users_action_error",
                 path=path, error=str(e))
            return 500, {"error": "users_action_failed", "detail": str(e)}

    # ── admin: Audit Logs (Phase 10E) — READ-ONLY. Owner-only automatically:
    #    this is an unmapped /admin path, so permissions.enforce() already
    #    restricts it to the Owner (ALL) and 403s every other role. ──
    if method == "GET" and path == "/admin/audit/list":
        try:
            return audit.handle_list(query_string)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "audit_list_error", error=str(e))
            return 500, {"error": "audit_list_failed", "detail": str(e)}

    # ── admin: media management (Phase 8H) — gated by the same admin key ──
    if method == "GET" and path == "/admin/media/vehicles":
        try:
            return media_admin.handle_vehicles(service)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "media_vehicles_error", error=str(e))
            return 500, {"error": "media_vehicles_failed", "detail": str(e)}

    if method == "POST" and path in ("/admin/media/upload_photos", "/admin/media/upload_videos"):
        kind = "photos" if path.endswith("photos") else "videos"
        try:
            return media_admin.handle_upload(service, body, content_type, kind=kind)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "media_upload_error", error=str(e))
            return 500, {"error": "media_upload_failed", "detail": str(e)}

    if method == "POST" and path == "/admin/media/add_link":
        try:
            return media_admin.handle_add_link(service, body)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "media_add_link_error", error=str(e))
            return 500, {"error": "media_add_link_failed", "detail": str(e)}

    if method == "POST" and path == "/admin/media/mark_sold":
        try:
            return media_admin.handle_mark_sold(service, body)
        except Exception as e:
            _log(ACCESS_LOG, logging.ERROR, "media_mark_sold_error", error=str(e))
            return 500, {"error": "media_mark_sold_failed", "detail": str(e)}

    # ── method/path not found ──
    if path in ("/auth/login", "/auth/logout", "/auth/me",
                "/chat", "/health", "/admin/refresh_inventory",
                "/admin/upload_inventory", "/admin/inventory_status",
                "/admin/inventory/dashboard",
                "/admin/inventory/schema", "/admin/inventory/vehicles",
                "/admin/inventory/get_car", "/admin/inventory/update_car",
                "/admin/inventory/add_car", "/admin/inventory/duplicate_audit",
                "/admin/inventory/restore_car",
                "/admin/owner/status", "/admin/owner/upload",
                "/admin/owner/rollback", "/admin/owner/delete_backup",
                "/admin/owner/download", "/admin/owner/chat_logs",
                "/admin/owner/chat_logs/detail", "/admin/owner/chat_logs/export",
                "/admin/users/list", "/admin/users/create", "/admin/users/update",
                "/admin/users/set_active", "/admin/users/reset_password",
                "/admin/users/delete", "/admin/users/my_permissions",
                "/admin/media/vehicles", "/admin/media/upload_photos",
                "/admin/media/upload_videos", "/admin/media/add_link",
                "/admin/media/mark_sold", "/admin/audit/list"):
        return 405, {"error": "method_not_allowed",
                     "detail": f"{method} not allowed on {path}."}
    return 404, {"error": "not_found", "detail": f"No route for {method} {path}."}


# ─────────────────────────────────────────────────────────────────────────────
# HTTP handler
# ─────────────────────────────────────────────────────────────────────────────
def make_handler(service: ChatService, gate: SecurityGate = None):
    gate = gate or default_gate()

    class ChatHTTPRequestHandler(BaseHTTPRequestHandler):
        server_version = "VasantOasisChat/1.0"

        def log_message(self, *args, **kwargs):  # silence default stderr logging
            return

        def _cors(self) -> Dict[str, str]:
            return gate.cors(self.headers.get("Origin"))

        def _respond(self, status: int, payload: Dict[str, Any],
                     extra: Dict[str, str] = None) -> None:
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _read_body(self) -> bytes:
            length = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(length) if length > 0 else b""

        def _client_id(self) -> str:
            try:
                return self.client_address[0]
            except Exception:
                return "unknown"

        def _dispatch(self, method: str) -> None:
            t0 = time.perf_counter()
            cors = self._cors()

            # ── Phase 10D: resolve the logged-in user from the session token ──
            session_token = self.headers.get("X-Session-Token")
            session_user = auth.resolve_user(session_token)
            # Identity for the permission engine: the session wins; the legacy
            # X-Acting-User header is only a fallback for un-migrated tooling.
            acting_user = session_user or self.headers.get("X-Acting-User")

            # ── auth + rate limiting ──
            denial = gate.authorize(method, self.path, dict(self.headers),
                                    self._client_id(), session_user=session_user)
            if denial is not None:
                status, payload = denial
                self._respond(status, payload, cors)
                _log(ACCESS_LOG, logging.WARNING, "request_denied",
                     method=method, path=self.path.split("?", 1)[0], status=status)
                return

            body = self._read_body() if method == "POST" else b""
            try:
                status, payload = route(method, self.path, body, service,
                                        self.headers.get("Content-Type", ""),
                                        acting_user=acting_user,
                                        session_token=session_token)
            except Exception as e:                   # absolute backstop
                status, payload = 500, {"error": "internal_error", "detail": str(e)}
            self._respond(status, payload, cors)
            # ── Phase 10E: passively record the action AFTER responding, so
            #    auditing never delays or breaks a request. observe() itself is
            #    fully guarded and writes 0 or 1 row. ──
            try:
                audit.observe(method, self.path, acting_user, status,
                              body=body, payload=payload,
                              pre_session_user=session_user)
            except Exception:
                pass
            _log(ACCESS_LOG, logging.INFO, "http_access",
                 method=method, path=self.path.split("?", 1)[0], status=status,
                 ms=round((time.perf_counter() - t0) * 1000, 1))

        def do_OPTIONS(self):                        # CORS preflight (no auth)
            self._respond(204, {}, self._cors())

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

    return ChatHTTPRequestHandler


# ─────────────────────────────────────────────────────────────────────────────
# Server entry
# ─────────────────────────────────────────────────────────────────────────────
def run(host: str = None, port: int = None) -> None:
    host = host or config.HOST
    port = port or config.PORT
    check_startup_security()        # warn (dev) / refuse (production) on insecure config
    # Developer Dashboard startup (additive, non-fatal):
    #   * mirror WARNING+ log events into the in-process error ring for the
    #     Errors view (passive; does not change any existing logging behaviour);
    #   * env-required Developer account seeding (no-op unless DEV_DASHBOARD_USER
    #     and DEV_DASHBOARD_PASSWORD are both set).
    try:
        developer_dashboard.install_error_capture()
    except Exception as e:
        _log(ACCESS_LOG, logging.WARNING, "dev_error_capture_failed", error=str(e))
    try:
        if developer_auth.seed_developer():
            _log(ACCESS_LOG, logging.INFO, "developer_account_seeded")
    except Exception as e:
        _log(ACCESS_LOG, logging.WARNING, "developer_seed_failed", error=str(e))
    _root_data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
    service = InstrumentedChatService(pilot_log_db=os.path.join(_root_data_dir, "pilot_query_log.db"))
    httpd = ThreadingHTTPServer((host, port), make_handler(service, default_gate()))
    _log(ACCESS_LOG, logging.INFO, "server_start", host=host, port=port,
         inventory_count=service.inventory_count, config=config.snapshot())
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        _log(ACCESS_LOG, logging.INFO, "server_stop")
        httpd.shutdown()


if __name__ == "__main__":
    run()
