"""
audit.py
========

Phase 10E — simple, centralised Audit Log / activity history.

"Who did what, when, on which vehicle." No analytics, no charts — one clean,
append-only, read-only activity trail the Owner can browse.

Design (deliberately small and non-invasive):
  * ONE passive interceptor, `observe()`, is called from the single HTTP choke
    point (`chat_api._dispatch`) AFTER a request is handled. It maps the
    (method, path) to a human action, pulls the vehicle / target / result out of
    the request body or the handler's own response, and writes exactly ONE row.
    It never changes a response and never raises into the request path.
  * Storage is a tiny SQLite table (`data/audit.db`) — same `data/` dir as the
    other stores. Append-only: there is deliberately NO update or delete API, so
    logs cannot be altered or erased from anywhere in the system.
  * Reading is `query()` (newest-first, optional search + category filter). The
    HTTP surface exposes only a GET; because `/admin/audit/*` is an *unmapped*
    admin path, the existing Phase 10C permission rule already restricts it to
    the Owner — no change to permissions.py.

Nothing here touches the chatbot, inventory, media, Excel, Supabase, login,
permissions, user management, or any existing API. It only observes and records.
Passwords are never read or stored.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import user_management

# Storage lives next to the other data stores. Overridable for tests.
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DATA_DIR, "audit.db")

# Filter buckets shown in the Owner Panel.
CATEGORIES = ["Inventory", "Media", "Users", "Excel", "Login"]

_lock = threading.Lock()


# ─────────────────────────────────────────────────────────────────────────────
# (method, path) -> action definition
#   label     : human action name (or a callable(body, payload) -> label)
#   category  : one of CATEGORIES
# The optional extras (vehicle / new_value / detail) are pulled by _extract().
# Only paths listed here are ever logged; everything else (reads, health, chat,
# my_permissions, the audit view itself) is silently ignored.
# ─────────────────────────────────────────────────────────────────────────────
def _link_label(body, payload):
    plat = (payload.get("platform") or body.get("platform") or "").strip().lower()
    return ("Add Instagram Link" if plat == "instagram"
            else "Add YouTube Link" if plat == "youtube"
            else "Add Media Link")


def _active_label(body, payload):
    return "Enable User" if bool(body.get("active")) else "Disable User"


ACTIONS: Dict[Tuple[str, str], Dict[str, Any]] = {
    ("POST", "/auth/login"):  {"label": "Login",  "category": "Login"},
    ("POST", "/auth/logout"): {"label": "Logout", "category": "Login"},

    ("POST", "/admin/owner/upload"):        {"label": "Upload New Excel",      "category": "Excel"},
    ("POST", "/admin/upload_inventory"):    {"label": "Upload New Excel",      "category": "Excel"},
    ("POST", "/admin/owner/rollback"):      {"label": "Restore Previous Excel", "category": "Excel"},
    ("POST", "/admin/owner/delete_backup"): {"label": "Delete Backup Excel",   "category": "Excel"},

    ("POST", "/admin/inventory/add_car"):     {"label": "Add New Car",     "category": "Inventory"},
    ("POST", "/admin/inventory/update_car"):  {"label": "Edit Car",        "category": "Inventory"},
    ("POST", "/admin/inventory/restore_car"): {"label": "Restore Vehicle", "category": "Inventory"},

    ("POST", "/admin/media/upload_photos"): {"label": "Upload Photos",     "category": "Media"},
    ("POST", "/admin/media/upload_videos"): {"label": "Upload Videos",     "category": "Media"},
    ("POST", "/admin/media/add_link"):      {"label": _link_label,         "category": "Media"},
    ("POST", "/admin/media/mark_sold"):     {"label": "Mark Vehicle Sold", "category": "Media"},

    ("POST", "/admin/users/create"):         {"label": "Create User",   "category": "Users"},
    ("POST", "/admin/users/update"):         {"label": "Edit User",     "category": "Users"},
    ("POST", "/admin/users/reset_password"): {"label": "Reset Password", "category": "Users"},
    ("POST", "/admin/users/set_active"):     {"label": _active_label,    "category": "Users"},
    ("POST", "/admin/users/delete"):         {"label": "Delete User",   "category": "Users"},
}


# ─────────────────────────────────────────────────────────────────────────────
# storage
# ─────────────────────────────────────────────────────────────────────────────
def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS audit_events (
               id        INTEGER PRIMARY KEY AUTOINCREMENT,
               ts        TEXT NOT NULL,
               username  TEXT,
               role      TEXT,
               action    TEXT NOT NULL,
               category  TEXT,
               vehicle   TEXT,
               old_value TEXT,
               new_value TEXT,
               status    TEXT,
               detail    TEXT
           )""")
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record(username: Optional[str], role: Optional[str], action: str,
           category: Optional[str] = None, *, vehicle: Optional[str] = None,
           old_value: Optional[str] = None, new_value: Optional[str] = None,
           status: str = "success", detail: Optional[str] = None) -> int:
    """Append exactly one audit row. Returns its id. Append-only — there is no
    corresponding update or delete anywhere in this module."""
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                """INSERT INTO audit_events
                   (ts, username, role, action, category, vehicle,
                    old_value, new_value, status, detail)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (_now(), username, role, action, category, vehicle,
                 old_value, new_value, status, detail))
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def query(search: Optional[str] = None, category: Optional[str] = None,
          limit: int = 500) -> List[Dict[str, Any]]:
    """Read the trail, newest first. `search` matches username / vehicle /
    action (case-insensitive substring). `category` filters to one bucket
    ('all'/None = every category). Read-only."""
    where, params = [], []
    if category and category.strip().lower() != "all":
        where.append("LOWER(category) = ?")
        params.append(category.strip().lower())
    if search and search.strip():
        term = f"%{search.strip().lower()}%"
        # username, vehicle, action — plus detail, so searching a username also
        # finds user-management actions whose SUBJECT is that account
        # (stored as "target user: <name>" in detail).
        where.append("(LOWER(IFNULL(username,'')) LIKE ? OR "
                     "LOWER(IFNULL(vehicle,'')) LIKE ? OR "
                     "LOWER(IFNULL(action,'')) LIKE ? OR "
                     "LOWER(IFNULL(detail,'')) LIKE ?)")
        params += [term, term, term, term]
    sql = "SELECT * FROM audit_events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(int(limit or 500), 5000)))
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def count() -> int:
    with _lock:
        conn = _connect()
        try:
            return int(conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0])
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# extraction helpers
# ─────────────────────────────────────────────────────────────────────────────
def _as_dict(raw) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        d = json.loads((raw or b"").decode("utf-8") if isinstance(raw, (bytes, bytearray))
                       else (raw or "{}"))
        return d if isinstance(d, dict) else {}
    except (ValueError, UnicodeDecodeError, AttributeError):
        return {}


def _role_for(username: Optional[str]) -> Optional[str]:
    if not username:
        return None
    try:
        data = user_management._load()
        u = user_management._find(data, username)
        return u.get("role") if u else None
    except Exception:
        return None


def _extract(path: str, body: Dict[str, Any], payload: Dict[str, Any]
             ) -> Dict[str, Optional[str]]:
    """Pull vehicle / old / new / detail for a given action from the request
    body and the handler's own response payload (no business logic touched)."""
    out: Dict[str, Optional[str]] = {"vehicle": None, "old_value": None,
                                     "new_value": None, "detail": None}

    # vehicle: handlers echo it as car_number (inventory) or vehicle (media)
    veh = (payload.get("car_number") or payload.get("vehicle")
           or body.get("car_number") or body.get("registration"))
    if veh:
        out["vehicle"] = str(veh)

    if path in ("/admin/owner/upload", "/admin/upload_inventory"):
        n = payload.get("vehicles_loaded")
        if n is not None:
            out["new_value"] = f"{n} vehicles live"
    elif path == "/admin/owner/rollback":
        n = payload.get("vehicles_loaded")
        out["new_value"] = f"{n} vehicles live" if n is not None else None
        out["detail"] = payload.get("message")
    elif path == "/admin/inventory/update_car":
        vals = body.get("values") or {}
        if isinstance(vals, dict) and vals:
            out["detail"] = f"{len(vals)} field(s) updated"
    elif path == "/admin/media/add_link":
        out["new_value"] = payload.get("url") or body.get("url")
    elif path in ("/admin/media/upload_photos", "/admin/media/upload_videos"):
        up = payload.get("uploaded")
        if up is not None:
            out["new_value"] = f"{up} file(s)"
    elif path == "/admin/media/mark_sold":
        fd = payload.get("files_deleted")
        if fd is not None:
            out["detail"] = f"{fd} media file(s) deleted"
    elif path.startswith("/admin/users/"):
        # subject of the action is another user account, not a vehicle
        target = (body.get("username")
                  or (payload.get("user") or {}).get("username"))
        if target:
            out["detail"] = f"target user: {target}"
        role = (payload.get("user") or {}).get("role") or body.get("role")
        if role and path in ("/admin/users/create", "/admin/users/update"):
            out["new_value"] = f"role: {role}"
        if path == "/admin/users/set_active":
            out["new_value"] = "active" if bool(body.get("active")) else "inactive"

    return out


# ─────────────────────────────────────────────────────────────────────────────
# the interceptor — one call per handled request; writes 0 or 1 row
# ─────────────────────────────────────────────────────────────────────────────
def observe(method: str, path: str, actor_username: Optional[str], status: int,
            body: Any = b"", payload: Any = None,
            pre_session_user: Optional[str] = None) -> Optional[int]:
    """Record one audit row for a mapped action, or return None if the request
    is not an auditable action. Never raises."""
    try:
        path = (path or "/").split("?", 1)[0].rstrip("/") or "/"
        spec = ACTIONS.get((method.upper(), path))
        if spec is None:
            return None

        body_d = _as_dict(body)
        payload_d = _as_dict(payload)

        # who performed it
        if path == "/auth/login":
            user = ((payload_d.get("user") or {}).get("username")
                    or body_d.get("username"))
            role = ((payload_d.get("user") or {}).get("role")
                    or _role_for(user))
        elif path == "/auth/logout":
            user = pre_session_user or actor_username
            role = _role_for(user)
        else:
            user = actor_username or pre_session_user
            role = _role_for(user)

        label = spec["label"]
        action = label(body_d, payload_d) if callable(label) else label
        ok = 200 <= int(status) < 300
        ex = _extract(path, body_d, payload_d)
        detail = ex["detail"]
        if not ok:
            # keep the failure reason visible without overwriting a good detail
            reason = payload_d.get("detail") or payload_d.get("error")
            detail = reason or detail

        return record(user, role, action, spec["category"],
                      vehicle=ex["vehicle"], old_value=ex["old_value"],
                      new_value=ex["new_value"],
                      status="success" if ok else "failed", detail=detail)
    except Exception:
        # Auditing must NEVER break or slow a real request.
        return None


# ─────────────────────────────────────────────────────────────────────────────
# HTTP read handler (Owner-only via the existing unmapped-admin-path rule)
# ─────────────────────────────────────────────────────────────────────────────
def handle_list(query_string: str = "") -> Tuple[int, Dict[str, Any]]:
    """GET /admin/audit/list?search=&category=&limit= -> {events, categories}."""
    from urllib.parse import parse_qs
    q = parse_qs(query_string or "")
    search = (q.get("search", [""])[0]) or None
    category = (q.get("category", [""])[0]) or None
    try:
        limit = int(q.get("limit", ["500"])[0])
    except (TypeError, ValueError):
        limit = 500
    events = query(search=search, category=category, limit=limit)
    return 200, {"events": events, "categories": CATEGORIES, "count": len(events)}
