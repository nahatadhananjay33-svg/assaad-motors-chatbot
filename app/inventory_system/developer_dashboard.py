"""
developer_dashboard.py
======================

Developer Dashboard — the read-only monitoring / observability layer.

This module is a *pure reader*. It never writes to the chatbot, inventory,
media, Excel, Supabase, users, or any operational store, and it never mutates a
request. It aggregates data that the system ALREADY records:

  * chat conversations   -> data/pilot_query_log.db  (query_log + unknown_log),
                            written per turn by InstrumentedChatService;
  * admin activity       -> data/audit.db            (audit.py `observe()`);
  * live inventory       -> the running ChatService's RetrievalEngine + the
                            inventory workbook's mtime (last refresh proxy);
  * errors / denials     -> an in-process ring buffer fed by a passive logging
                            handler attached to the "chat" logger (WARNING+),
                            sanitised so no secret or PII ever surfaces.

Every handler returns ``(http_status, json_payload)`` and is called only AFTER
``developer_auth.authorize()`` has confirmed a Developer session — see the
``/developer/*`` block in chat_api.route().

Nothing here changes existing behaviour; the dashboard is strictly additive.
"""

from __future__ import annotations

import collections
import json
import logging
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs

import audit
import config

try:
    import security  # for mask_pii — never leak a customer phone/name in errors
    _mask = security.mask_pii
except Exception:                                    # pragma: no cover
    def _mask(t):  # type: ignore
        return t

# ─────────────────────────────────────────────────────────────────────────────
# process/runtime facts
# ─────────────────────────────────────────────────────────────────────────────
_STARTED_AT = time.time()

# Local timezone offset (minutes) for "today"/"this week" calendar boundaries.
# Default 330 = IST, the dealership's clock. Rolling windows (24h/7d/30d) are
# timezone-independent and used everywhere else.
try:
    _TZ_OFFSET_MIN = int(os.getenv("DEV_DASHBOARD_TZ_OFFSET_MIN", "") or 330)
except ValueError:
    _TZ_OFFSET_MIN = 330

# "Slow request" threshold (ms). Chat turns at/above this show up as slow.
try:
    SLOW_MS = int(os.getenv("DEV_SLOW_MS", "") or 1500)
except ValueError:
    SLOW_MS = 1500

# A session is "active/recent" if it saw a turn within this many minutes.
ACTIVE_WINDOW_MIN = 30

_PAGE_DEFAULT = 25
_PAGE_MAX = 100


# ─────────────────────────────────────────────────────────────────────────────
# error ring buffer + passive logging handler (additive; no core log change)
# ─────────────────────────────────────────────────────────────────────────────
_ERROR_RING: "collections.deque" = collections.deque(maxlen=1000)
_ERROR_LOCK = threading.Lock()
_SENSITIVE_KEY_RE = re.compile(r"pass|token|secret|key|authorization|api[_-]?key", re.I)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sanitize_text(v: Any) -> str:
    """Redact PII (phone/name) from a free-text error/detail string."""
    try:
        return _mask(str(v)) if v is not None else ""
    except Exception:
        return ""


class DevErrorHandler(logging.Handler):
    """Passively mirrors WARNING+ events from the 'chat' logger into an
    in-memory ring for the Developer Dashboard's Errors view. It parses the
    JSON event line, keeps only safe fields, and NEVER raises into logging."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.levelno < logging.WARNING:
                return
            raw = record.getMessage()
            data: Dict[str, Any] = {}
            if raw and raw[:1] == "{":
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        data = parsed
                except Exception:
                    data = {}
            event = str(data.get("event") or (raw[:200] if raw else ""))
            severity = "HIGH" if record.levelno >= logging.ERROR else "MEDIUM"
            entry = {
                "ts": _utcnow_iso(),
                "level": record.levelname,
                "severity": severity,
                "event": event,
                "endpoint": str(data.get("path") or ""),
                "method": str(data.get("method") or ""),
                "error_type": str(data.get("error_type") or ""),
                "status": data.get("status"),
                "session": str(data.get("session_id") or data.get("request_id") or ""),
                # message: only non-sensitive fields, PII-masked
                "message": _sanitize_text(
                    data.get("error") or data.get("detail") or data.get("reason") or ""),
            }
            # Defensive: drop any accidentally-sensitive extra field.
            for k, v in list(data.items()):
                if _SENSITIVE_KEY_RE.search(k):
                    continue
            with _ERROR_LOCK:
                _ERROR_RING.append(entry)
        except Exception:
            pass


def install_error_capture(logger_name: str = "chat") -> None:
    """Attach the passive error handler once. Safe to call repeatedly."""
    lg = logging.getLogger(logger_name)
    if any(isinstance(h, DevErrorHandler) for h in lg.handlers):
        return
    h = DevErrorHandler()
    h.setLevel(logging.WARNING)
    lg.addHandler(h)


def _recent_errors() -> List[Dict[str, Any]]:
    with _ERROR_LOCK:
        return list(_ERROR_RING)


# ─────────────────────────────────────────────────────────────────────────────
# time helpers
# ─────────────────────────────────────────────────────────────────────────────
def _now_utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _cut(dt: datetime) -> str:
    """19-char UTC key 'YYYY-MM-DDTHH:MM:SS' for comparison against the first
    19 chars of a stored ISO timestamp (both are UTC)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _local_day_start_utc(days_ago: int = 0) -> datetime:
    """UTC instant of local (IST) midnight, `days_ago` days back."""
    now_local = _now_utc_naive() + timedelta(minutes=_TZ_OFFSET_MIN)
    local_mid = now_local.replace(hour=0, minute=0, second=0, microsecond=0) \
        - timedelta(days=days_ago)
    return local_mid - timedelta(minutes=_TZ_OFFSET_MIN)


def _windows() -> Dict[str, str]:
    """Named UTC cutoff keys used across the overview/analytics."""
    now = _now_utc_naive()
    return {
        "today": _cut(_local_day_start_utc(0)),
        "yesterday": _cut(_local_day_start_utc(1)),
        "d7": _cut(now - timedelta(days=7)),
        "d30": _cut(now - timedelta(days=30)),
        "active": _cut(now - timedelta(minutes=ACTIVE_WINDOW_MIN)),
    }


# ─────────────────────────────────────────────────────────────────────────────
# storage access (short-lived read-only connections — never the writer's)
# ─────────────────────────────────────────────────────────────────────────────
def _pilot_path(service: Any) -> Optional[str]:
    pl = getattr(service, "pilot_log", None)
    p = getattr(pl, "path", None)
    return p if p and os.path.exists(p) else None


def _pilot_conn(service: Any) -> Optional[sqlite3.Connection]:
    path = _pilot_path(service)
    if not path:
        return None
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None


def _audit_conn() -> Optional[sqlite3.Connection]:
    try:
        if not os.path.exists(audit.DB_PATH):
            return None
        conn = sqlite3.connect(audit.DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> Any:
    try:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# chat filters (shared by the Chats list and analytics)
# ─────────────────────────────────────────────────────────────────────────────
_RANGE_TO_CUT = {
    "today": lambda w: w["today"],
    "yesterday": lambda w: w["yesterday"],
    "7d": lambda w: w["d7"],
    "30d": lambda w: w["d30"],
}


def _row_where(q: Dict[str, List[str]]) -> Tuple[str, list]:
    """Build a message-level WHERE clause from query params. A session matches
    when it has >=1 message satisfying every active filter."""
    w = _windows()
    where: List[str] = []
    params: list = []

    rng = (q.get("range", [""])[0] or "").strip().lower()
    if rng in _RANGE_TO_CUT:
        cut = _RANGE_TO_CUT[rng](w)
        if rng == "yesterday":
            where.append("substr(timestamp,1,19) >= ? AND substr(timestamp,1,19) < ?")
            params += [cut, w["today"]]
        else:
            where.append("substr(timestamp,1,19) >= ?")
            params.append(cut)

    since = (q.get("since", [""])[0] or "").strip()
    if since:
        where.append("substr(timestamp,1,19) >= ?")
        params.append(since[:19])
    until = (q.get("until", [""])[0] or "").strip()
    if until:
        where.append("substr(timestamp,1,19) <= ?")
        params.append(until[:19])

    kw = (q.get("q", [""])[0] or "").strip()
    if kw:
        term = f"%{kw.lower()}%"
        where.append("(LOWER(IFNULL(user_query,'')) LIKE ? OR "
                     "LOWER(IFNULL(bot_response,'')) LIKE ?)")
        params += [term, term]

    intent = (q.get("intent", [""])[0] or "").strip()
    if intent:
        where.append("LOWER(IFNULL(detected_intent,'')) = ?")
        params.append(intent.lower())

    lang = (q.get("language", [""])[0] or "").strip()
    if lang:
        where.append("LOWER(IFNULL(detected_language,'')) = ?")
        params.append(lang.lower())

    model = (q.get("model", [""])[0] or "").strip()
    if model:
        term = f"%{model.lower()}%"
        where.append("(LOWER(IFNULL(vehicle_selected,'')) LIKE ? OR "
                     "LOWER(IFNULL(user_query,'')) LIKE ?)")
        params += [term, term]

    sess = (q.get("session", [""])[0] or "").strip()
    if sess:
        where.append("session_id = ?")
        params.append(sess)

    if (q.get("errors_only", [""])[0] or "").strip() in ("1", "true", "yes"):
        where.append("unknown_flag = 1")

    if (q.get("slow_only", [""])[0] or "").strip() in ("1", "true", "yes"):
        where.append("IFNULL(response_time_ms,0) >= ?")
        params.append(SLOW_MS)

    clause = (" WHERE " + " AND ".join(where)) if where else ""
    return clause, params


# ─────────────────────────────────────────────────────────────────────────────
# inventory snapshot (live, read-only, from the running engine)
# ─────────────────────────────────────────────────────────────────────────────
def _inventory_snapshot(service: Any) -> Dict[str, Any]:
    try:
        items = list(getattr(getattr(service, "engine", None), "all_facing", []) or [])
    except Exception:
        items = []
    models = sorted({(getattr(i, "model", None) or "").strip()
                     for i in items if getattr(i, "model", None)})
    brands = sorted({(getattr(i, "make_full", None) or getattr(i, "make", None) or "").strip()
                     for i in items if (getattr(i, "make_full", None) or getattr(i, "make", None))})
    xlsx = getattr(service, "xlsx_path", None)
    last_refresh = None
    if xlsx and os.path.exists(xlsx):
        try:
            last_refresh = datetime.fromtimestamp(
                os.path.getmtime(xlsx), timezone.utc).isoformat(timespec="seconds")
        except Exception:
            last_refresh = None
    return {
        "count": int(getattr(service, "inventory_count", len(items)) or len(items)),
        "models": models,
        "brands": brands,
        "model_count": len(models),
        "brand_count": len(brands),
        "workbook": os.path.basename(xlsx) if xlsx else None,
        "last_refresh": last_refresh,          # workbook mtime = last load/edit
        "reg_lookup_ready": bool(getattr(service, "_reg_lookup", None)),
    }


def _audit_recent(category: Optional[str] = None, actions: Optional[List[str]] = None,
                  limit: int = 10) -> List[Dict[str, Any]]:
    """Recent audit rows, optionally filtered to a category and/or action set."""
    conn = _audit_conn()
    if conn is None:
        return []
    try:
        sql = "SELECT * FROM audit_events"
        where, params = [], []
        if category:
            where.append("LOWER(category) = ?")
            params.append(category.lower())
        if actions:
            marks = ",".join("?" * len(actions))
            where.append(f"action IN ({marks})")
            params += actions
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except Exception:
        return []
    finally:
        conn.close()


def _audit_count_since(cut: str, actions: Optional[List[str]] = None,
                       category: Optional[str] = None) -> int:
    conn = _audit_conn()
    if conn is None:
        return 0
    try:
        where = ["substr(ts,1,19) >= ?"]
        params: list = [cut]
        if actions:
            marks = ",".join("?" * len(actions))
            where.append(f"action IN ({marks})")
            params += actions
        if category:
            where.append("LOWER(category) = ?")
            params.append(category.lower())
        sql = "SELECT COUNT(*) FROM audit_events WHERE " + " AND ".join(where)
        return int(_scalar(conn, sql, tuple(params)) or 0)
    except Exception:
        return 0
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# chat aggregates
# ─────────────────────────────────────────────────────────────────────────────
def _chat_counts(service: Any) -> Dict[str, Any]:
    conn = _pilot_conn(service)
    if conn is None:
        return {"available": False}
    w = _windows()
    try:
        def msgs_since(cut, extra="", p=()):
            return int(_scalar(conn,
                f"SELECT COUNT(*) FROM query_log WHERE substr(timestamp,1,19) >= ?{extra}",
                (cut, *p)) or 0)

        def sessions_since(cut):
            return int(_scalar(conn,
                "SELECT COUNT(*) FROM (SELECT 1 FROM query_log "
                "WHERE session_id IS NOT NULL AND session_id != '' "
                "AND substr(timestamp,1,19) >= ? GROUP BY session_id)", (cut,)) or 0)

        total_msgs = int(_scalar(conn, "SELECT COUNT(*) FROM query_log") or 0)
        total_sessions = int(_scalar(conn,
            "SELECT COUNT(*) FROM (SELECT 1 FROM query_log "
            "WHERE session_id IS NOT NULL AND session_id != '' GROUP BY session_id)") or 0)
        avg_today = _scalar(conn,
            "SELECT AVG(response_time_ms) FROM query_log "
            "WHERE response_time_ms IS NOT NULL AND substr(timestamp,1,19) >= ?",
            (w["today"],))
        avg_all = _scalar(conn,
            "SELECT AVG(response_time_ms) FROM query_log WHERE response_time_ms IS NOT NULL")
        return {
            "available": True,
            "messages_today": msgs_since(w["today"]),
            "messages_7d": msgs_since(w["d7"]),
            "conversations_today": sessions_since(w["today"]),
            "conversations_7d": sessions_since(w["d7"]),
            "active_sessions": sessions_since(w["active"]),
            "total_messages": total_msgs,
            "total_sessions": total_sessions,
            "avg_response_ms_today": round(float(avg_today), 1) if avg_today is not None else None,
            "avg_response_ms_all": round(float(avg_all), 1) if avg_all is not None else None,
            "unanswered_today": msgs_since(w["today"], " AND unknown_flag = 1"),
            "slow_today": msgs_since(w["today"], " AND IFNULL(response_time_ms,0) >= ?", (SLOW_MS,)),
        }
    except Exception:
        return {"available": False}
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# version / supabase facts (no secrets)
# ─────────────────────────────────────────────────────────────────────────────
def _git_head_short() -> Optional[str]:
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        for root in (here, os.path.join(here, ".."), os.path.join(here, "..", "..")):
            gitdir = os.path.join(root, ".git")
            head = os.path.join(gitdir, "HEAD")
            if not os.path.exists(head):
                continue
            with open(head, encoding="utf-8") as f:
                ref = f.read().strip()
            if ref.startswith("ref:"):
                refpath = os.path.join(gitdir, ref.split(" ", 1)[1].strip())
                if os.path.exists(refpath):
                    with open(refpath, encoding="utf-8") as f:
                        return f.read().strip()[:12]
                return None
            return ref[:12]
    except Exception:
        return None
    return None


def _version_info() -> Dict[str, Any]:
    return {
        "version": os.getenv("APP_VERSION") or "unknown",
        "commit": os.getenv("GIT_COMMIT") or os.getenv("APP_COMMIT") or _git_head_short() or "unknown",
        "environment": config.ENV,
        "started_at": datetime.fromtimestamp(_STARTED_AT, timezone.utc).isoformat(timespec="seconds"),
        "uptime_seconds": int(time.time() - _STARTED_AT),
    }


_SUPA_PROBE: Dict[str, Any] = {"ts": 0.0, "reachable": None, "detail": "", "checking": False}
_SUPA_LOCK = threading.Lock()
_SUPA_TTL = 30.0        # cache the probe result this long between refreshes


def _probe_supabase(url: str, key: str) -> Tuple[bool, str]:
    """READ-ONLY reachability check — lists storage buckets. It never writes or
    uploads. Returns (reachable, short_detail with no secret). Runs in a
    background thread (see below), so the timeout can be generous without ever
    blocking the dashboard. Fully guarded; never raises."""
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request(
            url.rstrip("/") + "/storage/v1/bucket",
            headers={"apikey": key, "Authorization": "Bearer " + key})
        with urllib.request.urlopen(req, timeout=8) as r:
            return (200 <= r.status < 300), "HTTP %s" % r.status
    except urllib.error.HTTPError as e:
        return False, "HTTP %s" % e.code      # host reached but rejected (e.g. 401)
    except Exception as e:
        return False, type(e).__name__


def _supabase_refresh_async(url: str, key: str) -> None:
    """Kick off ONE background probe (deduped) that updates the cache. The
    dashboard never waits on it."""
    with _SUPA_LOCK:
        if _SUPA_PROBE["checking"]:
            return
        _SUPA_PROBE["checking"] = True

    def _run():
        reachable, detail = _probe_supabase(url, key)
        with _SUPA_LOCK:
            _SUPA_PROBE.update(ts=time.time(), reachable=reachable,
                               detail=detail, checking=False)
    threading.Thread(target=_run, daemon=True).start()


def _supabase_health() -> Dict[str, Any]:
    """Report Supabase status WITHOUT ever exposing the URL/key values.

    When configured, a cached (30s), READ-ONLY reachability probe (lists buckets;
    never writes/uploads) runs in the BACKGROUND so the card reflects ACTUAL
    connectivity without ever blocking the dashboard. First load shows
    'checking' and flips to 'ok'/'unreachable' on the next refresh."""
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")
    if not (url and key):
        return {"configured": False, "mode": "offline (in-memory fallback)",
                "status": "not_configured", "reachable": None}
    now = time.time()
    with _SUPA_LOCK:
        reachable = _SUPA_PROBE["reachable"]
        detail = _SUPA_PROBE["detail"]
        fresh = reachable is not None and (now - _SUPA_PROBE["ts"]) < _SUPA_TTL
    if not fresh:
        _supabase_refresh_async(url, key)          # non-blocking
    if reachable is None:
        return {"configured": True, "mode": "supabase", "status": "checking",
                "reachable": None, "detail": "probing…"}
    return {"configured": True, "mode": "supabase",
            "status": "ok" if reachable else "unreachable",
            "reachable": bool(reachable), "detail": detail}


# ─────────────────────────────────────────────────────────────────────────────
# HTTP handlers — each returns (status, payload). Read-only.
# ─────────────────────────────────────────────────────────────────────────────
def handle_overview(service: Any) -> Tuple[int, Dict[str, Any]]:
    inv = _inventory_snapshot(service)
    chat = _chat_counts(service)
    w = _windows()
    errs = _recent_errors()
    errors_today = sum(1 for e in errs
                       if e.get("severity") == "HIGH" and e.get("ts", "")[:19] >= w["today"])

    admin = {
        "logins_today": _audit_count_since(w["today"], actions=["Login"]),
        "inventory_edits_today": _audit_count_since(
            w["today"], actions=["Edit Car", "Add New Car", "Restore Vehicle"]),
        "uploads_today": _audit_count_since(w["today"], category="Excel"),
        "media_actions_today": _audit_count_since(w["today"], category="Media"),
        "recent": _audit_recent(limit=8),
    }

    # NEEDS ATTENTION — only meaningful items, no alarm fatigue.
    attention: List[Dict[str, str]] = []
    if errors_today:
        attention.append({"level": "red",
                          "text": f"{errors_today} system error(s) today"})
    unanswered = chat.get("unanswered_today") or 0
    if unanswered:
        attention.append({"level": "yellow",
                          "text": f"{unanswered} unanswered/unclear question(s) today"})
    slow = chat.get("slow_today") or 0
    if slow:
        attention.append({"level": "yellow",
                          "text": f"{slow} slow response(s) today (≥{SLOW_MS} ms)"})
    if inv.get("last_refresh"):
        try:
            age_h = (datetime.now(timezone.utc)
                     - datetime.fromisoformat(inv["last_refresh"])).total_seconds() / 3600
            if age_h >= 24:
                attention.append({"level": "yellow",
                                  "text": f"Inventory last refreshed {int(age_h)}h ago"})
        except Exception:
            pass
    if not inv.get("count"):
        attention.append({"level": "red", "text": "Inventory is EMPTY (0 vehicles loaded)"})
    sup = _supabase_health()
    if not sup["configured"]:
        attention.append({"level": "yellow", "text": "Supabase not configured (offline media fallback)"})
    elif sup.get("status") == "unreachable":
        attention.append({"level": "red",
                          "text": "Supabase configured but UNREACHABLE (%s)" % (sup.get("detail") or "")})
    if not attention:
        attention.append({"level": "green", "text": "All systems healthy"})

    ver = _version_info()
    return 200, {
        "system": {
            "api_status": "ok",
            "environment": ver["environment"],
            "version": ver["version"],
            "commit": ver["commit"],
            "uptime_seconds": ver["uptime_seconds"],
            "started_at": ver["started_at"],
            "inventory_count": inv["count"],
            "last_inventory_refresh": inv["last_refresh"],
        },
        "chatbot": chat,
        "inventory": {
            "count": inv["count"], "model_count": inv["model_count"],
            "brand_count": inv["brand_count"], "last_refresh": inv["last_refresh"],
        },
        "admin": admin,
        "health": {
            "api": "ok",
            "inventory": "ok" if inv["count"] else "empty",
            "supabase": sup["status"],
            "errors_today": errors_today,
        },
        "needs_attention": attention,
        "generated_at": _utcnow_iso(),
    }


def handle_chats(service: Any, query_string: str = "") -> Tuple[int, Dict[str, Any]]:
    q = parse_qs(query_string or "")
    conn = _pilot_conn(service)
    if conn is None:
        return 200, {"available": False, "sessions": [], "total": 0,
                     "page": 0, "page_size": _PAGE_DEFAULT, "pages": 0}
    try:
        page = max(0, int((q.get("page", ["0"])[0]) or 0))
    except ValueError:
        page = 0
    try:
        size = int((q.get("page_size", [str(_PAGE_DEFAULT)])[0]) or _PAGE_DEFAULT)
    except ValueError:
        size = _PAGE_DEFAULT
    size = max(1, min(size, _PAGE_MAX))

    clause, params = _row_where(q)
    base = ("FROM query_log" + clause +
            (" AND " if clause else " WHERE ") +
            "session_id IS NOT NULL AND session_id != ''")
    try:
        total = int(_scalar(conn,
            f"SELECT COUNT(*) FROM (SELECT 1 {base} GROUP BY session_id)", tuple(params)) or 0)
        rows = conn.execute(
            f"""SELECT session_id,
                       COUNT(*)                         AS messages,
                       MIN(timestamp)                   AS started,
                       MAX(timestamp)                   AS last_activity,
                       MAX(IFNULL(response_time_ms,0))  AS max_ms,
                       AVG(response_time_ms)            AS avg_ms,
                       SUM(unknown_flag)                AS unknown_count,
                       MAX(matched_inventory)           AS matched,
                       GROUP_CONCAT(DISTINCT detected_language) AS languages
                {base}
                GROUP BY session_id
                ORDER BY MAX(timestamp) DESC
                LIMIT ? OFFSET ?""",
            (*params, size, page * size)).fetchall()
        sessions = []
        for r in rows:
            d = dict(r)
            langs = [x for x in (d.get("languages") or "").split(",") if x]
            sessions.append({
                "session_id": d["session_id"],
                "messages": int(d["messages"] or 0),
                "started": d["started"],
                "last_activity": d["last_activity"],
                "max_response_ms": round(float(d["max_ms"]), 1) if d["max_ms"] is not None else None,
                "avg_response_ms": round(float(d["avg_ms"]), 1) if d["avg_ms"] is not None else None,
                "unknown_count": int(d["unknown_count"] or 0),
                "matched_inventory": bool(d["matched"]),
                "languages": langs,
                "slow": bool(d["max_ms"] and d["max_ms"] >= SLOW_MS),
            })
        return 200, {
            "available": True, "sessions": sessions, "total": total,
            "page": page, "page_size": size,
            "pages": (total + size - 1) // size if size else 0,
            "slow_ms": SLOW_MS,
        }
    except Exception as e:
        return 500, {"error": "chats_failed", "detail": str(e)}
    finally:
        conn.close()


def handle_chat_detail(service: Any, session_id: str) -> Tuple[int, Dict[str, Any]]:
    conn = _pilot_conn(service)
    if conn is None:
        return 404, {"error": "not_found", "detail": "No conversation log available."}
    if not session_id:
        return 400, {"error": "bad_request", "detail": "session_id required."}
    try:
        rows = conn.execute(
            "SELECT * FROM query_log WHERE session_id = ? ORDER BY id ASC",
            (session_id,)).fetchall()
        if not rows:
            return 404, {"error": "not_found", "detail": "Unknown session."}
        turns = []
        langs = set()
        for r in rows:
            d = dict(r)
            if d.get("detected_language"):
                langs.add(d["detected_language"])
            turns.append({
                "timestamp": d.get("timestamp"),
                "customer": d.get("user_query"),
                "bot": d.get("bot_response"),
                "intent": d.get("detected_intent"),
                "language": d.get("detected_language"),
                "route": d.get("route"),
                "matched_inventory": bool(d.get("matched_inventory")),
                "unknown": bool(d.get("unknown_flag")),
                "vehicles": d.get("vehicle_selected"),
                "response_ms": d.get("response_time_ms"),
                "lead_level": d.get("lead_level"),
                "visit_ready": bool(d.get("visit_ready")),
            })
        started, last = turns[0]["timestamp"], turns[-1]["timestamp"]
        duration = None
        try:
            duration = int((datetime.fromisoformat(last) - datetime.fromisoformat(started)).total_seconds())
        except Exception:
            duration = None
        return 200, {
            "session_id": session_id,
            "started": started, "last_activity": last, "duration_seconds": duration,
            "messages": len(turns), "languages": sorted(langs),
            "unanswered": sum(1 for t in turns if t["unknown"]),
            "visit_ready": any(t["visit_ready"] for t in turns),
            "turns": turns, "slow_ms": SLOW_MS,
        }
    except Exception as e:
        return 500, {"error": "chat_detail_failed", "detail": str(e)}
    finally:
        conn.close()


# ── Admin-activity card drill-down ──────────────────────────────────────────
# Authoritative card -> audit filter. Mirrors audit.py's action labels /
# categories EXACTLY and is the SINGLE source of truth for BOTH the card counts
# and the click-to-filter table, so a card's number always equals the number of
# rows its filter returns. Every filter is additionally scoped to "today".
# NOTE: in audit.py "Mark Vehicle Sold" is a Media-category action, so the Media
# card legitimately includes Upload Photos/Videos, media links AND Mark Vehicle
# Sold; the Sold card is the Mark-Vehicle-Sold subset. This matches the existing
# counts exactly (no count value changes).
ACTIVITY_TYPES: Dict[str, Dict[str, Any]] = {
    "login":  {"label": "Logins",          "actions": ["Login"]},
    "excel":  {"label": "Excel uploads",   "category": "Excel"},
    "edit":   {"label": "Car edits",       "actions": ["Edit Car"]},
    "add":    {"label": "Car adds",        "actions": ["Add New Car"]},
    "sold":   {"label": "Sold",            "actions": ["Mark Vehicle Sold"]},
    "media":  {"label": "Media",           "category": "Media"},
    "users":  {"label": "User management", "category": "Users"},
    "failed": {"label": "Failed",          "status": "failed"},
}


def _activity_where(spec: Dict[str, Any]) -> Tuple[List[str], list]:
    """Translate a card spec into a SQL WHERE fragment (without the today cut)."""
    where: List[str] = []
    params: list = []
    if spec.get("actions"):
        marks = ",".join("?" * len(spec["actions"]))
        where.append(f"action IN ({marks})")
        params += spec["actions"]
    if spec.get("category"):
        where.append("LOWER(category) = ?")
        params.append(spec["category"].lower())
    if spec.get("status"):
        where.append("status = ?")
        params.append(spec["status"])
    return where, params


def _activity_count_today(spec: Dict[str, Any]) -> int:
    conn = _audit_conn()
    if conn is None:
        return 0
    try:
        where, params = _activity_where(spec)
        sql = "SELECT COUNT(*) FROM audit_events WHERE substr(ts,1,19) >= ?"
        if where:
            sql += " AND " + " AND ".join(where)
        return int(_scalar(conn, sql, (_windows()["today"], *params)) or 0)
    finally:
        conn.close()


def _activity_events_today(spec: Dict[str, Any], limit: int = 1000) -> List[Dict[str, Any]]:
    conn = _audit_conn()
    if conn is None:
        return []
    try:
        where, params = _activity_where(spec)
        sql = "SELECT * FROM audit_events WHERE substr(ts,1,19) >= ?"
        if where:
            sql += " AND " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        return [dict(r) for r in
                conn.execute(sql, (_windows()["today"], *params, limit)).fetchall()]
    finally:
        conn.close()


def handle_activity(query_string: str = "") -> Tuple[int, Dict[str, Any]]:
    q = parse_qs(query_string or "")
    type_ = (q.get("type", [""])[0] or "").strip().lower()
    search = (q.get("search", [""])[0]) or None
    category = (q.get("category", [""])[0]) or None
    try:
        limit = int(q.get("limit", ["100"])[0])
    except (TypeError, ValueError):
        limit = 100
    limit = max(1, min(limit, 1000))

    # card counts — same classification the drill-down uses (one source of truth)
    today = {
        "logins": _activity_count_today(ACTIVITY_TYPES["login"]),
        "logouts": _audit_count_since(_windows()["today"], actions=["Logout"]),
        "excel_uploads": _activity_count_today(ACTIVITY_TYPES["excel"]),
        "car_edits": _activity_count_today(ACTIVITY_TYPES["edit"]),
        "car_adds": _activity_count_today(ACTIVITY_TYPES["add"]),
        "sold": _activity_count_today(ACTIVITY_TYPES["sold"]),
        "media": _activity_count_today(ACTIVITY_TYPES["media"]),
        "user_mgmt": _activity_count_today(ACTIVITY_TYPES["users"]),
        "failed": _activity_count_today(ACTIVITY_TYPES["failed"]),
    }

    # table: a card drill-down (today + that type) OR the default recent list
    if type_ in ACTIVITY_TYPES:
        events = _activity_events_today(ACTIVITY_TYPES[type_])
    else:
        type_ = ""
        events = audit.query(search=search, category=category, limit=limit)

    return 200, {"events": events, "categories": audit.CATEGORIES,
                 "today": today, "count": len(events), "type": type_,
                 "types": {k: v["label"] for k, v in ACTIVITY_TYPES.items()}}


def handle_inventory(service: Any) -> Tuple[int, Dict[str, Any]]:
    inv = _inventory_snapshot(service)
    w = _windows()
    recent_added = _audit_recent(actions=["Add New Car"], limit=10)
    recent_modified = _audit_recent(actions=["Edit Car"], limit=10)
    recent_removed = _audit_recent(actions=["Mark Vehicle Sold"], limit=10)
    last_change = None
    both = _audit_recent(category="Inventory", limit=1) + _audit_recent(category="Excel", limit=1)
    if both:
        last_change = max((e.get("ts") for e in both if e.get("ts")), default=None)

    # sync-pipeline health (derived from the live engine — read-only)
    healthy = bool(inv["count"] > 0 and inv["reg_lookup_ready"])
    sync = {
        "status": "healthy" if healthy else ("empty" if inv["count"] == 0 else "degraded"),
        "cars_loaded": inv["count"],
        "models": inv["model_count"],
        "last_refresh": inv["last_refresh"],
        "retrieval_index": "ready" if inv["count"] > 0 else "empty",
        "registration_lookup": "ready" if inv["reg_lookup_ready"] else "unavailable",
        "model_recognizer": "ready" if inv["model_count"] > 0 else "empty",
        "workbook": inv["workbook"],
    }
    return 200, {
        "count": inv["count"], "models": inv["models"], "brands": inv["brands"],
        "model_count": inv["model_count"], "brand_count": inv["brand_count"],
        "last_refresh": inv["last_refresh"], "last_change": last_change,
        "added_today": _audit_count_since(w["today"], actions=["Add New Car"]),
        "modified_today": _audit_count_since(w["today"], actions=["Edit Car"]),
        "removed_today": _audit_count_since(w["today"], actions=["Mark Vehicle Sold"]),
        "recent_added": recent_added,
        "recent_modified": recent_modified,
        "recent_removed": recent_removed,
        "sync": sync,
    }


def handle_inventory_history(query_string: str = "") -> Tuple[int, Dict[str, Any]]:
    """Inventory + Excel change history from the durable audit trail."""
    q = parse_qs(query_string or "")
    try:
        limit = int(q.get("limit", ["100"])[0])
    except (TypeError, ValueError):
        limit = 100
    limit = max(1, min(limit, 1000))
    conn = _audit_conn()
    if conn is None:
        return 200, {"events": [], "count": 0}
    try:
        rows = conn.execute(
            "SELECT * FROM audit_events WHERE LOWER(category) IN ('inventory','excel') "
            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        events = [dict(r) for r in rows]
        return 200, {"events": events, "count": len(events)}
    except Exception as e:
        return 500, {"error": "inventory_history_failed", "detail": str(e)}
    finally:
        conn.close()


def handle_health(service: Any) -> Tuple[int, Dict[str, Any]]:
    inv = _inventory_snapshot(service)
    chat = _chat_counts(service)
    ver = _version_info()
    errs = _recent_errors()
    w = _windows()
    errors_today = sum(1 for e in errs if e.get("ts", "")[:19] >= w["today"])
    high_today = sum(1 for e in errs
                     if e.get("severity") == "HIGH" and e.get("ts", "")[:19] >= w["today"])
    refresh_failures = sum(1 for e in errs if "refresh" in (e.get("event") or "").lower())
    return 200, {
        "backend": {
            "status": "ok",
            "uptime_seconds": ver["uptime_seconds"],
            "started_at": ver["started_at"],
            "total_requests_logged": chat.get("total_messages") if chat.get("available") else None,
            "errors_today": errors_today,
            "high_severity_today": high_today,
            "avg_response_ms": chat.get("avg_response_ms_all") if chat.get("available") else None,
        },
        "inventory": {
            "loaded": bool(inv["count"]),
            "count": inv["count"],
            "last_refresh": inv["last_refresh"],
            "refresh_failures_seen": refresh_failures,
            "reg_lookup_ready": inv["reg_lookup_ready"],
        },
        "supabase": _supabase_health(),
        "application": {
            "environment": ver["environment"], "version": ver["version"],
            "commit": ver["commit"], "started_at": ver["started_at"],
        },
        "generated_at": _utcnow_iso(),
    }


def handle_errors(query_string: str = "") -> Tuple[int, Dict[str, Any]]:
    q = parse_qs(query_string or "")
    try:
        limit = int(q.get("limit", ["200"])[0])
    except (TypeError, ValueError):
        limit = 200
    limit = max(1, min(limit, 1000))
    sev = (q.get("severity", [""])[0] or "").strip().upper()
    errs = list(reversed(_recent_errors()))          # newest first
    if sev in ("HIGH", "MEDIUM"):
        errs = [e for e in errs if e.get("severity") == sev]

    # also surface failed admin actions from the durable audit trail
    failed_admin = []
    conn = _audit_conn()
    if conn is not None:
        try:
            rows = conn.execute(
                "SELECT ts, username, action, category, detail FROM audit_events "
                "WHERE status = 'failed' ORDER BY id DESC LIMIT 50").fetchall()
            failed_admin = [dict(r) for r in rows]
        except Exception:
            failed_admin = []
        finally:
            conn.close()
    return 200, {"errors": errs[:limit], "count": len(errs),
                 "failed_admin_actions": failed_admin, "capacity": _ERROR_RING.maxlen}


def handle_analytics(service: Any, query_string: str = "") -> Tuple[int, Dict[str, Any]]:
    conn = _pilot_conn(service)
    if conn is None:
        return 200, {"available": False}
    w = _windows()
    try:
        def count_since(cut, extra=""):
            return int(_scalar(conn,
                f"SELECT COUNT(*) FROM query_log WHERE substr(timestamp,1,19) >= ?{extra}",
                (cut,)) or 0)

        conversations = {
            "today": count_since(w["today"]),
            "yesterday": int(_scalar(conn,
                "SELECT COUNT(*) FROM query_log WHERE substr(timestamp,1,19) >= ? "
                "AND substr(timestamp,1,19) < ?", (w["yesterday"], w["today"])) or 0),
            "last_7d": count_since(w["d7"]),
            "last_30d": count_since(w["d30"]),
        }
        top_intents = [dict(r) for r in conn.execute(
            "SELECT detected_intent AS intent, COUNT(*) AS n FROM query_log "
            "WHERE detected_intent IS NOT NULL AND detected_intent != '' "
            "GROUP BY detected_intent ORDER BY n DESC LIMIT 15").fetchall()]
        top_langs = [dict(r) for r in conn.execute(
            "SELECT detected_language AS language, COUNT(*) AS n FROM query_log "
            "WHERE detected_language IS NOT NULL AND detected_language != '' "
            "GROUP BY detected_language ORDER BY n DESC LIMIT 10").fetchall()]
        top_models = [dict(r) for r in conn.execute(
            "SELECT vehicle_selected AS model, COUNT(*) AS n FROM query_log "
            "WHERE vehicle_selected IS NOT NULL AND vehicle_selected != '' "
            "GROUP BY vehicle_selected ORDER BY n DESC LIMIT 15").fetchall()]
        # unanswered / clarification questions — extremely valuable
        unanswered = [dict(r) for r in conn.execute(
            "SELECT query, language, reason, timestamp FROM unknown_log "
            "ORDER BY id DESC LIMIT 50").fetchall()]
        unanswered_total = int(_scalar(conn, "SELECT COUNT(*) FROM unknown_log") or 0)
        # last 14 calendar days (local) trend
        trend = []
        for d in range(13, -1, -1):
            start = _cut(_local_day_start_utc(d))
            end = _cut(_local_day_start_utc(d - 1))     # next local midnight (exclusive)
            n = int(_scalar(conn,
                "SELECT COUNT(*) FROM query_log WHERE substr(timestamp,1,19) >= ? "
                "AND substr(timestamp,1,19) < ?", (start, end)) or 0)
            trend.append({"day": start[:10], "messages": n})
        return 200, {
            "available": True,
            "conversations": conversations,
            "top_intents": top_intents,
            "top_languages": top_langs,
            "top_models": top_models,
            "unanswered": unanswered,
            "unanswered_total": unanswered_total,
            "trend_14d": trend,
        }
    except Exception as e:
        return 500, {"error": "analytics_failed", "detail": str(e)}
    finally:
        conn.close()
