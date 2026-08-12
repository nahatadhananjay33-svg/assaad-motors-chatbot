# -*- coding: utf-8 -*-
"""
pilot_dashboard.py
===================

Phase 5B — pilot dashboard. Reads `pilot_query_log.db` (written by
`InstrumentedChatService`, see inventory_system/instrumented_chat_service.py)
and prints a daily summary:

    Total Conversations, Total Messages, Inventory Success %, FAQ Success %,
    Unknown %, Lead Capture %, Top Unknown Queries, Top Languages, Top Intents

Lead Capture % is computed via `inventory_system/analytics.py`'s
`AnalyticsEngine.funnel()` over `inventory_system/data/analytics.db` (the
existing lead-funnel store, untouched), keyed to the same conversation_ids
seen on `day`.

Usage:
    python pilot_dashboard.py [--db PATH] [--day YYYY-MM-DD]

If --day is omitted, the most recent day present in the log is used.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from typing import Any, Dict, List, Optional

sys.path.insert(0, "inventory_system")

DEFAULT_DB = "pilot_query_log.db"


def _pct(n: int, total: int) -> float:
    return round(100.0 * n / total, 2) if total else 0.0


def load_rows(db_path: str, day: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    if day:
        cur = conn.execute(
            "SELECT * FROM query_log WHERE substr(timestamp,1,10)=? ORDER BY id", (day,))
    else:
        cur = conn.execute("SELECT * FROM query_log ORDER BY id")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def latest_day(db_path: str) -> Optional[str]:
    conn = sqlite3.connect(db_path)
    cur = conn.execute("SELECT MAX(substr(timestamp,1,10)) FROM query_log")
    day = cur.fetchone()[0]
    conn.close()
    return day


def load_unknown_queries(db_path: str, day: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    if day:
        cur = conn.execute(
            "SELECT LOWER(TRIM(query)) AS q, COUNT(*) AS n FROM unknown_log "
            "WHERE substr(timestamp,1,10)=? GROUP BY q ORDER BY n DESC, q LIMIT ?",
            (day, limit))
    else:
        cur = conn.execute(
            "SELECT LOWER(TRIM(query)) AS q, COUNT(*) AS n FROM unknown_log "
            "GROUP BY q ORDER BY n DESC, q LIMIT ?", (limit,))
    out = [{"query": q, "count": n} for q, n in cur.fetchall()]
    conn.close()
    return out


def lead_capture_pct(conversation_ids: set, analytics_db: str = "inventory_system/data/analytics.db") -> Optional[float]:
    """Best-effort: % of the day's conversation_ids that reached Medium/High
    lead level in the existing lead-funnel analytics store. Returns None if
    the analytics DB is unavailable (does not block the dashboard)."""
    try:
        conn = sqlite3.connect(analytics_db)
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT session_id, lead_level FROM events")
        levels: Dict[str, str] = {}
        rank = {None: -1, "": -1, "Low": 0, "Medium": 1, "High": 2}
        for r in cur.fetchall():
            sid = r["session_id"]
            lvl = r["lead_level"]
            if rank.get(lvl, -1) > rank.get(levels.get(sid), -1):
                levels[sid] = lvl
        conn.close()
    except sqlite3.OperationalError:
        return None

    relevant = {cid: levels.get(cid) for cid in conversation_ids}
    if not relevant:
        return 0.0
    captured = sum(1 for lvl in relevant.values() if lvl in ("Medium", "High"))
    return _pct(captured, len(relevant))


def build_dashboard(db_path: str = DEFAULT_DB, day: Optional[str] = None) -> Dict[str, Any]:
    if day is None:
        day = latest_day(db_path)

    rows = load_rows(db_path, day)
    total_messages = len(rows)
    conv_ids = set(r["conversation_id"] for r in rows if r["conversation_id"])
    total_conversations = len(conv_ids)

    route_counter = Counter(r["route"] for r in rows)
    inventory_total = route_counter.get("inventory", 0)
    faq_total = route_counter.get("faq", 0)
    unknown_total = route_counter.get("unknown", 0)

    inventory_matched = sum(1 for r in rows if r["matched_inventory"])
    faq_resolved = sum(1 for r in rows if r["route"] == "faq" and r["detected_intent"]
                        not in (None, "", "unknown", "faq_unknown"))

    inventory_success_pct = _pct(inventory_matched, inventory_total)
    faq_success_pct = _pct(faq_resolved, faq_total)
    unknown_pct = _pct(unknown_total, total_messages)

    lang_counter = Counter(r["detected_language"] for r in rows if r["detected_language"])
    intent_counter = Counter(r["detected_intent"] for r in rows if r["detected_intent"])

    top_unknown = load_unknown_queries(db_path, day, limit=10)

    lead_pct = lead_capture_pct(conv_ids)

    return {
        "day": day,
        "total_conversations": total_conversations,
        "total_messages": total_messages,
        "inventory_success_pct": inventory_success_pct,
        "faq_success_pct": faq_success_pct,
        "unknown_pct": unknown_pct,
        "lead_capture_pct": lead_pct,
        "top_unknown_queries": top_unknown,
        "top_languages": [{"language": l, "count": n} for l, n in lang_counter.most_common(10)],
        "top_intents": [{"intent": i, "count": n} for i, n in intent_counter.most_common(10)],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--day", default=None)
    args = ap.parse_args()

    dashboard = build_dashboard(args.db, args.day)
    out = json.dumps(dashboard, indent=2, ensure_ascii=False)
    sys.stdout.buffer.write(out.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
