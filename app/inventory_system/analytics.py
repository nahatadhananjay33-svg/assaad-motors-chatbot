"""
analytics.py
===========

Backend analytics for the chatbot — ingestion, durable storage, and report
generation. No UI, no dashboards, no charts. JSON-compatible structures only.

Tracks per request: route (inventory/faq/unknown), intent, language, lead
status, visit-ready, media requests, and vehicle interest. Unresolved queries
are also forwarded to the append-only `UnknownQueryStore`.

    AnalyticsEvent  — one record per request
    AnalyticsStore  — durable SQLite event log (append-only)
    AnalyticsEngine — records events + builds daily/weekly/summary reports
                      (calculations delegated to conversation_metrics)
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass, asdict
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import conversation_metrics as cm
from unknown_query_store import UnknownQueryStore

DEFAULT_DB = "analytics.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT,
    query       TEXT,
    route       TEXT,
    intent      TEXT,
    language    TEXT,
    lead_level  TEXT,
    visit_ready INTEGER DEFAULT 0,
    is_media    INTEGER DEFAULT 0,
    vehicle     TEXT,
    timestamp   TEXT,
    day         TEXT
);
"""


@dataclass
class AnalyticsEvent:
    session_id: Optional[str]
    query: str
    route: str                       # inventory | faq | unknown
    intent: Optional[str] = None
    language: Optional[str] = None
    lead_level: Optional[str] = None  # High | Medium | Low | None
    visit_ready: bool = False
    is_media: bool = False
    vehicle: Optional[str] = None     # interested model/category
    timestamp: Optional[str] = None   # ISO-8601

    def to_row(self) -> Dict[str, Any]:
        d = asdict(self)
        d["visit_ready"] = 1 if self.visit_ready else 0
        d["is_media"] = 1 if self.is_media else 0
        d["day"] = (self.timestamp or "")[:10]
        return d

    def to_event(self) -> Dict[str, Any]:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# Durable event store (append-only)
# ─────────────────────────────────────────────────────────────────────────────
class AnalyticsStore:
    def __init__(self, path: str = DEFAULT_DB):
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def record(self, event: AnalyticsEvent) -> int:
        row = event.to_row()
        cols = ("session_id, query, route, intent, language, lead_level, "
                "visit_ready, is_media, vehicle, timestamp, day")
        ph = ":session_id, :query, :route, :intent, :language, :lead_level, " \
             ":visit_ready, :is_media, :vehicle, :timestamp, :day"
        with self._lock:
            cur = self._conn.execute(
                f"INSERT INTO events ({cols}) VALUES ({ph})", row)
            self._conn.commit()
            return cur.lastrowid

    def _decode(self, row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        d["visit_ready"] = bool(d.get("visit_ready"))
        d["is_media"] = bool(d.get("is_media"))
        return d

    def all(self) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM events ORDER BY id")
            return [self._decode(r) for r in cur.fetchall()]

    def by_day(self, day: str) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM events WHERE day=? ORDER BY id", (day,))
            return [self._decode(r) for r in cur.fetchall()]

    def by_days(self, days: List[str]) -> List[Dict[str, Any]]:
        if not days:
            return []
        marks = ",".join("?" * len(days))
        with self._lock:
            cur = self._conn.execute(
                f"SELECT * FROM events WHERE day IN ({marks}) ORDER BY id", days)
            return [self._decode(r) for r in cur.fetchall()]

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def close(self) -> None:
        self._conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Analytics engine
# ─────────────────────────────────────────────────────────────────────────────
class AnalyticsEngine:
    def __init__(self, store: Optional[AnalyticsStore] = None,
                 unknown_store: Optional[UnknownQueryStore] = None):
        self.store = store or AnalyticsStore(":memory:")
        self.unknown_store = unknown_store or UnknownQueryStore(":memory:")

    def record(self, event: AnalyticsEvent) -> None:
        self.store.record(event)
        if event.route == "unknown":
            self.unknown_store.record(
                event.query, session_id=event.session_id, language=event.language,
                timestamp=event.timestamp, lead_score=event.lead_level,
                route=event.route, detected_intent=event.intent)

    # ── reports (JSON-compatible) ──
    def summary_report(self) -> Dict[str, Any]:
        events = self.store.all()
        report = cm.compute(events)
        report["report_type"] = "summary"
        report["top_unknown_questions"] = self.unknown_store.top_queries(10)
        report["total_events"] = self.store.count()
        return report

    def daily_report(self, day: str) -> Dict[str, Any]:
        report = cm.compute(self.store.by_day(day))
        report["report_type"] = "daily"
        report["day"] = day
        return report

    def weekly_report(self, end_day: str) -> Dict[str, Any]:
        end = date.fromisoformat(end_day)
        days = [(end - timedelta(days=i)).isoformat() for i in range(7)]
        report = cm.compute(self.store.by_days(days))
        report["report_type"] = "weekly"
        report["days"] = sorted(days)
        return report

    # ── direct accessors ──
    def top_unknown_questions(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self.unknown_store.top_queries(limit)

    def vehicle_ranking(self, limit: int = 10) -> List[Dict[str, Any]]:
        return cm.compute(self.store.all())["top_requested_models"][:limit]

    def funnel(self) -> Dict[str, Any]:
        return cm.funnel(self.store.all())
