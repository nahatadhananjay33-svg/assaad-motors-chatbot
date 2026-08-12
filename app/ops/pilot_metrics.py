# -*- coding: utf-8 -*-
"""
pilot_metrics.py
==================

Phase 5C — daily KPI summary over `pilot_query_log.db` (written by
`InstrumentedChatService`, see inventory_system/instrumented_chat_service.py).
Read-only; no parser/retrieval/FAQ/inventory changes.

For each day present in the log, computes:
    - total_conversations, total_messages
    - inventory_success_pct
    - faq_success_pct
    - unknown_pct
    - lead_capture_pct  (cross-referenced from inventory_system/data/analytics.db)

Usage:
    python pilot_metrics.py [--db PATH] [--out pilot_kpi_daily.csv]
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from collections import Counter
from typing import Dict, List

sys.path.insert(0, ".")
from pilot_dashboard import build_dashboard, DEFAULT_DB  # noqa: E402


def all_days(db_path: str) -> List[str]:
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "SELECT DISTINCT substr(timestamp,1,10) AS d FROM query_log ORDER BY d")
    days = [r[0] for r in cur.fetchall() if r[0]]
    conn.close()
    return days


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out", default="pilot_kpi_daily.csv")
    args = ap.parse_args()

    days = all_days(args.db)
    if not days:
        print("No data in", args.db)
        return

    fieldnames = ["day", "total_conversations", "total_messages",
                   "inventory_success_pct", "faq_success_pct", "unknown_pct",
                   "lead_capture_pct"]
    rows = []
    for day in days:
        d = build_dashboard(args.db, day)
        rows.append({k: d.get(k) for k in fieldnames})

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    for r in rows:
        print(r)
    print(f"\nWrote {len(rows)} day(s) to {args.out}")


if __name__ == "__main__":
    main()
