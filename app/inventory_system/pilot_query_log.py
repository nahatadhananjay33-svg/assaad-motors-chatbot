"""
pilot_query_log.py
===================

Phase 5B — pilot query-level logging. Purely additive: a new SQLite table
(`query_log`) and a CSV exporter for unresolved ("unknown") queries. Does not
touch retrieval, parser, FAQ, inventory-matching, or `analytics.py` /
`unknown_query_store.py` (which remain in place for the existing lead funnel
reports).

Schema (one row per `ChatService.handle()` call):

    timestamp, conversation_id, session_id, user_query, detected_language,
    detected_intent, route, unknown_flag, matched_inventory, response_time_ms,
    bot_response, lead_level, visit_ready, vehicle_selected

Phase 8C: the last four columns were added so a complete (customer message +
bot reply) conversation can be reconstructed from production logs. They are
purely additive — existing rows keep NULLs and `_ensure_columns()` migrates an
existing DB in place (SQLite ADD COLUMN, no table rewrite). No other logging,
retrieval, parser, FAQ, inventory, or lead logic is changed.
"""

from __future__ import annotations

import csv
import sqlite3
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

DEFAULT_DB = "pilot_query_log.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS query_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp         TEXT,
    conversation_id   TEXT,
    session_id        TEXT,
    user_query        TEXT,
    detected_language TEXT,
    detected_intent   TEXT,
    route             TEXT,
    unknown_flag      INTEGER DEFAULT 0,
    matched_inventory INTEGER DEFAULT 0,
    response_time_ms  REAL,
    bot_response      TEXT,
    lead_level        TEXT,
    visit_ready       INTEGER DEFAULT 0,
    vehicle_selected  TEXT,
    filters           TEXT,
    result_count      INTEGER DEFAULT 0
);
"""

# Columns added after the table first shipped — migrated in place (SQLite ADD
# COLUMN is non-destructive; existing rows get NULL/default).
_ADDED_COLUMNS = {
    "bot_response": "TEXT",
    "lead_level": "TEXT",
    "visit_ready": "INTEGER DEFAULT 0",
    "vehicle_selected": "TEXT",
    # applied inventory filters (JSON of the active filter dict) + result count,
    # for monitoring which filters customers use and how many cars matched.
    "filters": "TEXT",
    "result_count": "INTEGER DEFAULT 0",
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
    detected_language: Optional[str]
    detected_intent: Optional[str]
    route: str
    unknown_flag: bool
    matched_inventory: bool
    response_time_ms: Optional[float]
    # Phase 8C — optional (default None/False) so every existing caller keeps working.
    bot_response: Optional[str] = None
    lead_level: Optional[str] = None
    visit_ready: bool = False
    vehicle_selected: Optional[str] = None
    filters: Optional[str] = None          # JSON of the active filter dict
    result_count: int = 0                  # number of vehicles matched this turn


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
                "(timestamp, conversation_id, session_id, user_query, "
                " detected_language, detected_intent, route, unknown_flag, "
                " matched_inventory, response_time_ms, "
                " bot_response, lead_level, visit_ready, vehicle_selected, "
                " filters, result_count) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (entry.timestamp, entry.conversation_id, entry.session_id,
                 entry.user_query, entry.detected_language, entry.detected_intent,
                 entry.route, int(entry.unknown_flag), int(entry.matched_inventory),
                 entry.response_time_ms,
                 entry.bot_response, entry.lead_level, int(bool(entry.visit_ready)),
                 entry.vehicle_selected, entry.filters, int(entry.result_count or 0)))
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
