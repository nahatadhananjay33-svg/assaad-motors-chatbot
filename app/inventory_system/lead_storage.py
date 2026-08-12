"""
lead_storage.py
==============

Persistent storage for captured leads. Stdlib `sqlite3` only — no external
dependencies. One row per conversation `session_id` (idempotent upsert), so a
multi-turn conversation accumulates into a single, current lead record.

Use `LeadStore(":memory:")` for tests/ephemeral, or a file path for production.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any, Dict, List, Optional

DEFAULT_DB = "leads.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    lead_id            TEXT PRIMARY KEY,
    session_id         TEXT UNIQUE NOT NULL,
    phone              TEXT,
    name               TEXT,
    interested_vehicle TEXT,
    budget_min         INTEGER,
    budget_max         INTEGER,
    finance_interest   INTEGER DEFAULT 0,
    exchange_interest  INTEGER DEFAULT 0,
    visit_intent       INTEGER DEFAULT 0,
    language           TEXT,
    score_level        TEXT,
    score_points       INTEGER DEFAULT 0,
    visit_ready        INTEGER DEFAULT 0,
    observed_signals   TEXT,
    visit_signals      TEXT,
    created_at         TEXT,
    updated_at         TEXT
);
"""

_BOOL_FIELDS = ("finance_interest", "exchange_interest", "visit_intent", "visit_ready")
_JSON_FIELDS = ("observed_signals", "visit_signals")
_COLUMNS = [
    "lead_id", "session_id", "phone", "name", "interested_vehicle",
    "budget_min", "budget_max", "finance_interest", "exchange_interest",
    "visit_intent", "language", "score_level", "score_points", "visit_ready",
    "observed_signals", "visit_signals", "created_at", "updated_at",
]


class LeadStore:
    def __init__(self, path: str = DEFAULT_DB):
        self.path = path
        # Single connection shared across threads (ThreadingHTTPServer). sqlite3
        # is not safe for concurrent use of one connection, so serialize every
        # access with a lock — mirrors AnalyticsStore / UnknownQueryStore.
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    # ── serialization helpers ──
    @staticmethod
    def _encode(record: Dict[str, Any]) -> Dict[str, Any]:
        r = dict(record)
        for f in _BOOL_FIELDS:
            r[f] = 1 if r.get(f) else 0
        for f in _JSON_FIELDS:
            r[f] = json.dumps(r.get(f) or ([] if f == "observed_signals" else {}),
                              ensure_ascii=False)
        return r

    @staticmethod
    def _decode(row: sqlite3.Row) -> Dict[str, Any]:
        r = dict(row)
        for f in _BOOL_FIELDS:
            r[f] = bool(r.get(f))
        for f in _JSON_FIELDS:
            try:
                r[f] = json.loads(r.get(f) or "null")
            except (json.JSONDecodeError, TypeError):
                r[f] = None
        return r

    # ── writes ──
    def upsert(self, record: Dict[str, Any]) -> None:
        r = self._encode(record)
        cols = ", ".join(_COLUMNS)
        placeholders = ", ".join(f":{c}" for c in _COLUMNS)
        updates = ", ".join(f"{c}=excluded.{c}" for c in _COLUMNS
                            if c not in ("lead_id", "session_id", "created_at"))
        sql = (f"INSERT INTO leads ({cols}) VALUES ({placeholders}) "
               f"ON CONFLICT(session_id) DO UPDATE SET {updates}")
        with self._lock:
            self._conn.execute(sql, {c: r.get(c) for c in _COLUMNS})
            self._conn.commit()

    # ── reads ──
    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM leads WHERE session_id=?", (session_id,))
            row = cur.fetchone()
        return self._decode(row) if row else None

    def all(self) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM leads ORDER BY updated_at DESC")
            rows = cur.fetchall()
        return [self._decode(r) for r in rows]

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]

    def count_by_level(self) -> Dict[str, int]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT score_level, COUNT(*) FROM leads GROUP BY score_level")
            return {lvl: n for lvl, n in cur.fetchall()}

    def count_visit_ready(self) -> int:
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(*) FROM leads WHERE visit_ready=1").fetchone()[0]

    def close(self) -> None:
        self._conn.close()
