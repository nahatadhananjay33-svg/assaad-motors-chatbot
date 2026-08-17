"""
pilot_query_log.py
===================

Pilot query-level logging. A SQLite table (`query_log`) holding the customer
conversation, plus a small `unknown_log` kept for backward compatibility.

SIMPLIFICATION (chat-log slim-down): the persistent conversation record is now
deliberately minimal — the chatbot writes only the customer message and the
agent reply per turn:

    timestamp, conversation_id, session_id, user_query, bot_response

The chatbot still computes intent / filters / retrieval / result_count etc.
internally to answer the customer — those runtime values are simply no longer
persisted (runtime intelligence != persistent chat history). See
`instrumented_chat_service.py`.

Historical rows are preserved untouched. The older monitoring columns
(`detected_language, detected_intent, route, unknown_flag, matched_inventory,
response_time_ms, lead_level, visit_ready, vehicle_selected`) remain in the
table schema so existing databases open unchanged and their historical values
stay readable, but the chatbot no longer populates them (they default to
NULL/0 on new rows). No destructive migration is performed. The never-deployed
`filters` / `result_count` columns have been removed from the code entirely.

`record()` still accepts and writes the legacy columns when a caller supplies
them (used only by tests / direct seeding); production logging goes through the
minimal path above.
"""

from __future__ import annotations

import csv
import sqlite3
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

DEFAULT_DB = "pilot_query_log.db"

# The core, minimal conversation columns (timestamp + conversation ids +
# customer message + agent reply) come first. The remaining columns are legacy
# monitoring fields kept ONLY so pre-existing databases open unchanged and their
# historical values stay readable — the chatbot no longer writes them.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS query_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp         TEXT,
    conversation_id   TEXT,
    session_id        TEXT,
    user_query        TEXT,
    bot_response      TEXT,
    detected_language TEXT,
    detected_intent   TEXT,
    route             TEXT,
    unknown_flag      INTEGER DEFAULT 0,
    matched_inventory INTEGER DEFAULT 0,
    response_time_ms  REAL,
    lead_level        TEXT,
    visit_ready       INTEGER DEFAULT 0,
    vehicle_selected  TEXT
);
"""

# Columns that older databases may be missing — added in place if absent (SQLite
# ADD COLUMN is non-destructive; existing rows get NULL/default). `bot_response`
# is the one genuinely required to reconstruct a conversation; the rest are
# legacy/dormant. filters/result_count were never deployed and are intentionally
# absent here so no new column is ever created for them.
_ADDED_COLUMNS = {
    "bot_response": "TEXT",
    "lead_level": "TEXT",
    "visit_ready": "INTEGER DEFAULT 0",
    "vehicle_selected": "TEXT",
}

_UNKNOWN_SCHEMA = """
CREATE TABLE IF NOT EXISTS unknown_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    query             TEXT,
    language          TEXT,
    reason            TEXT,
    timestamp         TEXT,
    conversation_id   TEXT
);
"""


@dataclass
class QueryLogEntry:
    timestamp: str
    conversation_id: Optional[str]
    session_id: Optional[str]
    user_query: str
    bot_response: Optional[str] = None
    # ── legacy monitoring fields (optional; NOT written by the production
    #    chatbot any more — kept so direct-seeding callers / tests still work
    #    and historical rows keep their meaning). ──
    detected_language: Optional[str] = None
    detected_intent: Optional[str] = None
    route: str = ""
    unknown_flag: bool = False
    matched_inventory: bool = False
    response_time_ms: Optional[float] = None
    lead_level: Optional[str] = None
    visit_ready: bool = False
    vehicle_selected: Optional[str] = None


class PilotQueryLog:
    """Append-only SQLite log of every chat turn, plus an unresolved-query log."""

    def __init__(self, path: str = DEFAULT_DB):
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEMA)
        self._conn.execute(_UNKNOWN_SCHEMA)
        self._ensure_columns()
        self._conn.commit()

    def _ensure_columns(self) -> None:
        """Add any Phase 8C columns missing from a pre-existing query_log table.
        SQLite ADD COLUMN is in-place (no rewrite); existing rows get NULL."""
        existing = {r[1] for r in self._conn.execute(
            "PRAGMA table_info(query_log)").fetchall()}
        for col, decl in _ADDED_COLUMNS.items():
            if col not in existing:
                self._conn.execute(f"ALTER TABLE query_log ADD COLUMN {col} {decl}")

    def record(self, entry: QueryLogEntry) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO query_log "
                "(timestamp, conversation_id, session_id, user_query, bot_response, "
                " detected_language, detected_intent, route, unknown_flag, "
                " matched_inventory, response_time_ms, "
                " lead_level, visit_ready, vehicle_selected) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (entry.timestamp, entry.conversation_id, entry.session_id,
                 entry.user_query, entry.bot_response,
                 entry.detected_language, entry.detected_intent,
                 entry.route, int(entry.unknown_flag), int(entry.matched_inventory),
                 entry.response_time_ms,
                 entry.lead_level, int(bool(entry.visit_ready)),
                 entry.vehicle_selected))
            self._conn.commit()
            row_id = cur.lastrowid

        if entry.unknown_flag:
            reason = entry.detected_intent or "unresolved"
            with self._lock:
                self._conn.execute(
                    "INSERT INTO unknown_log (query, language, reason, timestamp, conversation_id) "
                    "VALUES (?,?,?,?,?)",
                    (entry.user_query, entry.detected_language, reason,
                     entry.timestamp, entry.conversation_id))
                self._conn.commit()

        return row_id

    # ── reads ──
    def all(self) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM query_log ORDER BY id")
            return [dict(r) for r in cur.fetchall()]

    def by_day(self, day: str) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM query_log WHERE substr(timestamp,1,10)=? ORDER BY id", (day,))
            return [dict(r) for r in cur.fetchall()]

    def unknown_all(self) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM unknown_log ORDER BY id")
            return [dict(r) for r in cur.fetchall()]

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM query_log").fetchone()[0]

    def export_unknown_csv(self, path: str = "unknown_queries.csv") -> int:
        rows = self.unknown_all()
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["query", "language", "reason",
                                               "timestamp", "conversation_id"])
            w.writeheader()
            for r in rows:
                w.writerow({
                    "query": r["query"],
                    "language": r["language"],
                    "reason": r["reason"],
                    "timestamp": r["timestamp"],
                    "conversation_id": r["conversation_id"],
                })
        return len(rows)

    def close(self) -> None:
        self._conn.close()
