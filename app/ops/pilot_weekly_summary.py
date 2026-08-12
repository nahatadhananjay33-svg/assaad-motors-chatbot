# -*- coding: utf-8 -*-
"""
pilot_weekly_summary.py
==========================

Phase 5C — generate a management-facing weekly summary from
`pilot_query_log.db`. Combines:
    - daily KPIs (via pilot_metrics.build_dashboard / all_days)
    - failure triage breakdown (via pilot_triage.classify_row)
    - top unresolved queries (via pilot_review_report)

into `pilot_weekly_summary.md`. Read-only; no parser/retrieval/FAQ/inventory
changes.

Usage:
    python pilot_weekly_summary.py [--db PATH] [--days 7] [--out pilot_weekly_summary.md]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, ".")
from pilot_dashboard import build_dashboard, DEFAULT_DB  # noqa: E402
from pilot_metrics import all_days  # noqa: E402
from pilot_triage import classify_row  # noqa: E402


def _avg(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out", default="pilot_weekly_summary.md")
    args = ap.parse_args()

    days = all_days(args.db)
    if not days:
        print("No data in", args.db)
        return
    window = days[-args.days:]

    daily = [build_dashboard(args.db, d) for d in window]

    total_conv = sum(d["total_conversations"] for d in daily)
    total_msgs = sum(d["total_messages"] for d in daily)
    avg_inv = _avg([d["inventory_success_pct"] for d in daily])
    avg_faq = _avg([d["faq_success_pct"] for d in daily])
    avg_unknown = _avg([d["unknown_pct"] for d in daily])
    avg_lead = _avg([d["lead_capture_pct"] for d in daily])

    # ── failure triage over the window ──
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    marks = ",".join("?" * len(window))
    cur = conn.execute(
        f"SELECT * FROM unknown_log WHERE substr(timestamp,1,10) IN ({marks})", window)
    unknown_rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    cat_counter = Counter()
    for r in unknown_rows:
        cat = classify_row({"route": "unknown", "user_query": r["query"],
                             "detected_intent": r.get("reason")}) or "parser gap"
        cat_counter[cat] += 1

    top_queries = Counter((r["query"] or "").strip().lower() for r in unknown_rows)

    lines = []
    lines.append("# Pilot Weekly Summary")
    lines.append("")
    lines.append(f"**Window:** {window[0]} to {window[-1]} ({len(window)} day(s) with data)")
    lines.append("")
    lines.append("## Headline KPIs")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Total Conversations | {total_conv} |")
    lines.append(f"| Total Messages | {total_msgs} |")
    lines.append(f"| Avg Inventory Success % | {avg_inv} |")
    lines.append(f"| Avg FAQ Success % | {avg_faq} |")
    lines.append(f"| Avg Unknown % | {avg_unknown} |")
    lines.append(f"| Avg Lead Capture % | {avg_lead} |")
    lines.append("")
    lines.append("## Daily Breakdown")
    lines.append("")
    lines.append("| Day | Conversations | Messages | Inventory % | FAQ % | Unknown % | Lead Capture % |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for d in daily:
        lines.append(f"| {d['day']} | {d['total_conversations']} | {d['total_messages']} | "
                      f"{d['inventory_success_pct']} | {d['faq_success_pct']} | "
                      f"{d['unknown_pct']} | {d['lead_capture_pct']} |")
    lines.append("")
    lines.append("## Failure Gap Breakdown (unresolved queries this window)")
    lines.append("")
    total_unknown = len(unknown_rows)
    if total_unknown:
        lines.append("| Gap Category | Count | % of Unresolved |")
        lines.append("|---|---:|---:|")
        for cat, n in cat_counter.most_common():
            lines.append(f"| {cat} | {n} | {round(n/total_unknown*100,2)} |")
    else:
        lines.append("_No unresolved queries in this window._")
    lines.append("")
    lines.append("## Top 10 Recurring Unresolved Queries")
    lines.append("")
    if top_queries:
        lines.append("| Query | Count |")
        lines.append("|---|---:|")
        for q, n in top_queries.most_common(10):
            lines.append(f"| {q} | {n} |")
    else:
        lines.append("_None._")
    lines.append("")
    lines.append("## Recommendation")
    lines.append("")
    if avg_unknown <= 20 and total_conv > 0:
        lines.append("Metrics within Phase 5A baseline expectations "
                      "(unknown % <= 20, see `conversation_eval_report.md`). "
                      "Continue pilot; address top gap categories above via "
                      "keyword-table updates per `improvement_opportunities.md`.")
    else:
        lines.append("Unknown % above the 20% baseline target — prioritize the "
                      "top gap category in this window before expanding pilot scope.")

    content = "\n".join(lines) + "\n"
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(content)

    sys.stdout.buffer.write(content.encode("utf-8"))


if __name__ == "__main__":
    main()
