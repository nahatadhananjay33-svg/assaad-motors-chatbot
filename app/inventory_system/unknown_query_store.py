"""
unknown_query_store.py
=====================

Append-only SQLite store for every UNRESOLVED query (route = "unknown"). These
are the questions the deterministic system could not answer — the raw material
for future FAQ expansion and future LLM routing.

Captures: session_id, query, language, timestamp, lead_score, route,
detected_intent. Append-only (INSERT only) and searchable (LIKE + grouping).
"""

from __future__ import annotations

import sqlite3
import threading
from typing import Any, Dict, List, Optional

DEFAULT_DB = "unknown_queries.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS unknown_queries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT,
    query           TEXT NOT NULL,
    language        TEXT,
    timestamp       TEXT,
    lead_score      TEXT,
    route           TEXT DEFAULT 'unknown',
    detected_intent TEXT
);
"""


class UnknownQueryStore:
    def __init__(self, path: str = DEFAULT_DB):
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    # ── append-only write ──
    def record(self, query: str, *, session_id: Optional[str] = None,
               language: Optional[str] = None, timestamp: Optional[str] = None,
               lead_score: Optional[str] = None, route: str = "unknown",
               detected_intent: Optional[str] = None) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO unknown_queries "
                "(session_id, query, language, timestamp, lead_score, route, detected_intent) "
                "VALUES (?,?,?,?,?,?,?)",
                (session_id, query, language, timestamp, lead_score, route, detected_intent))
            self._conn.commit()
            return cur.lastrowid

    # ── reads ──
    def all(self) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM unknown_queries ORDER BY id")
            return [dict(r) for r in cur.fetchall()]

    def recent(self, n: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM unknown_queries ORDER BY id DESC LIMIT ?", (n,))
            return [dict(r) for r in cur.fetchall()]

    def search(self, term: str) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM unknown_queries WHERE query LIKE ? ORDER BY id",
                (f"%{term}%",))
            return [dict(r) for r in cur.fetchall()]

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM unknown_queries").fetchone()[0]

    def top_queries(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Most frequent unresolved questions (case-insensitive grouping)."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT LOWER(TRIM(query)) AS q, COUNT(*) AS n "
                "FROM unknown_queries GROUP BY q ORDER BY n DESC, q LIMIT ?", (limit,))
            return [{"query": row["q"], "count": row["n"]} for row in cur.fetchall()]

    def by_language(self) -> Dict[str, int]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT language, COUNT(*) FROM unknown_queries GROUP BY language")
            return {lang: n for lang, n in cur.fetchall()}

    def close(self) -> None:
        self._conn.close()
