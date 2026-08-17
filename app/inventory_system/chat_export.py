"""
chat_export.py
==============

Simple, read-only access to the customer conversation log for the dashboards:

  * a paged conversation LIST (one entry per conversation),
  * a single conversation's turns (customer message + agent reply),
  * a downloadable EXPORT of the raw conversation (CSV / XLSX).

The persistent record is deliberately minimal — only the customer message and
the agent reply are stored per turn (see `pilot_query_log.py` /
`instrumented_chat_service.py`). This module therefore exposes ONLY the
conversation itself; it never surfaces intent / filters / result_count /
latency / retrieval or any other internal metadata, and never writes anything.

Both the Developer Dashboard and the Owner Dashboard use these functions, so the
two dashboards show and export exactly the same simple data.

Export shape (long format, one message per row) — the primary CSV/XLSX layout::

    timestamp, conversation_id, speaker, message

Formats: CSV (priority 1) and XLSX (priority 2). No new dependency is added —
XLSX uses openpyxl, already vendored for the inventory workbook.
"""

from __future__ import annotations

import base64
import csv
import io
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

# Dealership clock (IST) for the "today" calendar boundary; rolling windows
# (7d/30d) are timezone-independent. Matches the Developer Dashboard convention.
_TZ_OFFSET_MIN = 330


# ─────────────────────────────────────────────────────────────────────────────
# date range → UTC cutoff
# ─────────────────────────────────────────────────────────────────────────────
def _now_utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _today_start_utc() -> datetime:
    """UTC instant of local (IST) midnight today."""
    now_local = _now_utc_naive() + timedelta(minutes=_TZ_OFFSET_MIN)
    local_mid = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_mid - timedelta(minutes=_TZ_OFFSET_MIN)


def range_cutoff(range_key: str) -> Optional[str]:
    """Return the 19-char UTC cutoff ('YYYY-MM-DDTHH:MM:SS') for a named range,
    or None for 'all' / unknown (meaning: no lower bound)."""
    rk = (range_key or "").strip().lower()
    now = _now_utc_naive()
    if rk in ("today", "1d"):
        cut = _today_start_utc()
    elif rk in ("7d", "week", "last7", "last_7_days"):
        cut = now - timedelta(days=7)
    elif rk in ("30d", "month", "last30", "last_30_days"):
        cut = now - timedelta(days=30)
    else:
        return None
    return cut.strftime("%Y-%m-%dT%H:%M:%S")


def _conn(db_path: str) -> Optional[sqlite3.Connection]:
    """Short-lived READ-ONLY connection (never the writer's)."""
    import os
    if not db_path or not os.path.exists(db_path):
        return None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None


def _where(range_key: str, keyword: str = "") -> Tuple[str, list]:
    where: List[str] = ["session_id IS NOT NULL", "session_id != ''"]
    params: list = []
    cut = range_cutoff(range_key)
    if cut:
        where.append("substr(timestamp,1,19) >= ?")
        params.append(cut)
    kw = (keyword or "").strip()
    if kw:
        term = f"%{kw.lower()}%"
        where.append("(LOWER(IFNULL(user_query,'')) LIKE ? OR "
                     "LOWER(IFNULL(bot_response,'')) LIKE ?)")
        params += [term, term]
    return " WHERE " + " AND ".join(where), params


# ─────────────────────────────────────────────────────────────────────────────
# conversation LIST + DETAIL (used by both dashboards)
# ─────────────────────────────────────────────────────────────────────────────
def list_conversations(db_path: str, *, range_key: str = "", keyword: str = "",
                       page: int = 0, page_size: int = 25) -> Dict[str, Any]:
    """One entry per conversation: id, when it started / last activity, and how
    many messages. No technical fields."""
    conn = _conn(db_path)
    if conn is None:
        return {"available": False, "conversations": [], "total": 0,
                "page": 0, "page_size": page_size, "pages": 0}
    page = max(0, int(page or 0))
    page_size = max(1, min(int(page_size or 25), 200))
    clause, params = _where(range_key, keyword)
    try:
        total = int(conn.execute(
            f"SELECT COUNT(*) FROM (SELECT 1 FROM query_log{clause} GROUP BY session_id)",
            tuple(params)).fetchone()[0] or 0)
        rows = conn.execute(
            f"""SELECT session_id,
                       COALESCE(MAX(conversation_id), session_id) AS conversation_id,
                       COUNT(*)       AS messages,
                       MIN(timestamp) AS started,
                       MAX(timestamp) AS last_activity
                FROM query_log{clause}
                GROUP BY session_id
                ORDER BY MAX(timestamp) DESC
                LIMIT ? OFFSET ?""",
            (*params, page_size, page * page_size)).fetchall()
        convos = [{
            "conversation_id": r["conversation_id"] or r["session_id"],
            "session_id": r["session_id"],
            "messages": int(r["messages"] or 0),
            "started": r["started"],
            "last_activity": r["last_activity"],
        } for r in rows]
        return {"available": True, "conversations": convos, "total": total,
                "page": page, "page_size": page_size,
                "pages": (total + page_size - 1) // page_size if page_size else 0}
    except Exception:
        return {"available": False, "conversations": [], "total": 0,
                "page": 0, "page_size": page_size, "pages": 0}
    finally:
        conn.close()


def conversation_detail(db_path: str, session_id: str) -> Optional[Dict[str, Any]]:
    """A single conversation as a plain customer/agent transcript."""
    conn = _conn(db_path)
    if conn is None or not session_id:
        return None
    try:
        rows = conn.execute(
            "SELECT timestamp, conversation_id, session_id, user_query, bot_response "
            "FROM query_log WHERE session_id = ? ORDER BY id ASC",
            (session_id,)).fetchall()
        if not rows:
            return None
        turns = [{
            "timestamp": r["timestamp"],
            "customer": r["user_query"],
            "agent": r["bot_response"],
        } for r in rows]
        return {
            "conversation_id": rows[0]["conversation_id"] or session_id,
            "session_id": session_id,
            "started": turns[0]["timestamp"],
            "last_activity": turns[-1]["timestamp"],
            "messages": len(turns),
            "turns": turns,
        }
    except Exception:
        return None
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# raw rows → export (CSV / XLSX)
# ─────────────────────────────────────────────────────────────────────────────
def _fetch_messages(db_path: str, range_key: str = "", keyword: str = "",
                    ) -> List[Dict[str, Any]]:
    """Chronological long-format message rows: one dict per customer message and
    one per agent reply. Empty messages are skipped."""
    conn = _conn(db_path)
    if conn is None:
        return []
    clause, params = _where(range_key, keyword)
    try:
        rows = conn.execute(
            f"""SELECT timestamp,
                       COALESCE(conversation_id, session_id) AS conversation_id,
                       user_query, bot_response
                FROM query_log{clause}
                ORDER BY id ASC""",
            tuple(params)).fetchall()
    except Exception:
        return []
    finally:
        conn.close()
    out: List[Dict[str, Any]] = []
    for r in rows:
        ts, cid = r["timestamp"], r["conversation_id"]
        q = (r["user_query"] or "").strip()
        a = (r["bot_response"] or "").strip()
        if q:
            out.append({"timestamp": ts, "conversation_id": cid,
                        "speaker": "customer", "message": q})
        if a:
            out.append({"timestamp": ts, "conversation_id": cid,
                        "speaker": "agent", "message": a})
    return out


_HEADERS = ["timestamp", "conversation_id", "speaker", "message"]


def to_csv_bytes(messages: List[Dict[str, Any]]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=_HEADERS, extrasaction="ignore")
    w.writeheader()
    for m in messages:
        w.writerow(m)
    # utf-8-sig so Excel opens Hindi / Marathi text correctly.
    return buf.getvalue().encode("utf-8-sig")


def to_xlsx_bytes(messages: List[Dict[str, Any]]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = "Conversations"
    ws.append(_HEADERS)
    for c in ws[1]:
        c.font = Font(bold=True)
    for m in messages:
        ws.append([m.get(h, "") for h in _HEADERS])
    # sensible column widths
    for col, width in zip("ABCD", (20, 26, 12, 90)):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A2"
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


_MIME = {
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def export_payload(db_path: str, *, fmt: str = "csv", range_key: str = "all",
                   keyword: str = "") -> Tuple[int, Dict[str, Any]]:
    """Build a download payload for the chat log. Returns (status, json) where
    the file bytes are base64-encoded in `content_b64` — the same JSON transport
    the Owner Excel download already uses, so the browser decodes it to a real
    file. Never raises."""
    fmt = (fmt or "csv").strip().lower()
    if fmt not in _MIME:
        return 400, {"status": "error",
                     "detail": "Unsupported format (use csv or xlsx)."}
    rk = (range_key or "all").strip().lower()
    try:
        messages = _fetch_messages(db_path, rk, keyword)
        data = to_csv_bytes(messages) if fmt == "csv" else to_xlsx_bytes(messages)
    except Exception as e:                                    # pragma: no cover
        return 500, {"status": "error", "detail": f"Export failed: {e}"}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    name = f"assad_motors_chat_logs_{rk}_{stamp}.{fmt}"
    return 200, {
        "status": "ok",
        "file_name": name,
        "format": fmt,
        "range": rk,
        "rows": len(messages),
        "size": len(data),
        "mime": _MIME[fmt],
        "content_b64": base64.b64encode(data).decode("ascii"),
    }
