# -*- coding: utf-8 -*-
"""
pilot_triage.py
==================

Phase 5C — classify pilot failures (unresolved / unmatched turns) into one of:

    parser gap     - generic phrasing the parser/FAQ router never saw
    faq gap        - routed to faq but no concrete intent resolved
    inventory gap  - routed to inventory but no vehicle matched
    media gap      - a photo/video/media ask that could not be resolved
    memory gap     - a follow-up / reference turn needing session memory
                      ("same model", "uska price", "white wali", etc.)

Classification is a pure, read-only heuristic over `pilot_query_log.db` rows
(or `conversation_turn_results.csv` rows from Phase 5A) — no parser/retrieval/
FAQ/inventory code is touched or modified.

Usage:
    python pilot_triage.py [--db PATH] [--out pilot_failure_triage.csv]
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from collections import Counter
from typing import Any, Dict, Optional

DEFAULT_DB = "pilot_query_log.db"

# ── memory/follow-up reference markers (EN/HI/HiEN/MR) ──
_MEMORY_PATTERNS = [
    r"\bsame\b", r"\bsame model\b", r"\bdusri wali\b", r"\bisi\b", r"\bwahi\b",
    r"\buska\b", r"\biska\b", r"\bwo wala\b", r"\bvo wala\b", r"\bwhite wali\b",
    r"\bkonsi achi\b", r"\bcompare karo\b", r"\bdono\b", r"\bfarak\b",
    r"\bother option\b", r"\bkoi aur\b", r"\bvarchi\b",
]
_MEMORY_RE = re.compile("|".join(_MEMORY_PATTERNS), re.IGNORECASE)

# ── media-intent markers (EN/HI/HiEN/MR incl. Devanagari) ──
_MEDIA_PATTERNS = [
    r"\bphoto", r"\bphotos", r"\bpic\b", r"\bpics\b", r"\bvideo", r"\breel\b",
    r"\bimage", r"फोटो", r"फोटोज", r"व्हिडिओ", r"वीडियो", r"फोटो भेजो",
    r"photo pathva", r"send.*photo", r"\bmedia\b",
]
_MEDIA_RE = re.compile("|".join(_MEDIA_PATTERNS), re.IGNORECASE)


def classify_row(row: Dict[str, Any]) -> Optional[str]:
    """Return a gap category for a failed/unresolved row, or None if the row
    is not a failure (route != unknown, faq resolved, inventory matched)."""
    route = (row.get("route") or "").lower()
    intent = (row.get("detected_intent") or row.get("intent") or "").lower()
    query = row.get("user_query") or row.get("message") or ""
    matched_inventory = row.get("matched_inventory")
    status = (row.get("status") or "").lower()

    is_unknown = route == "unknown" or intent == "unknown"
    is_faq_unresolved = route == "faq" and intent in ("", "unknown", "faq_unknown")
    if route == "inventory":
        if matched_inventory is not None:
            # Phase 5D: matched_inventory already reflects the refined
            # "count > 0 and status != not_found" rule from
            # instrumented_chat_service.py -- trust it directly.
            inv_unmatched = matched_inventory in (0, "0", False, "False")
        else:
            inv_unmatched = status == "not_found"
    else:
        inv_unmatched = False

    if not (is_unknown or is_faq_unresolved or inv_unmatched):
        return None

    if _MEMORY_RE.search(query):
        return "memory gap"
    if _MEDIA_RE.search(query) or intent == "media_clarify":
        return "media gap"
    if inv_unmatched:
        return "inventory gap"
    if is_faq_unresolved:
        return "faq gap"
    return "parser gap"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out", default="pilot_failure_triage.csv")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.execute("SELECT * FROM query_log ORDER BY id")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    out_rows = []
    cat_counter = Counter()
    for r in rows:
        cat = classify_row(r)
        if cat is None:
            continue
        cat_counter[cat] += 1
        out_rows.append({
            "conversation_id": r.get("conversation_id"),
            "timestamp": r.get("timestamp"),
            "query": r.get("user_query"),
            "language": r.get("detected_language"),
            "route": r.get("route"),
            "detected_intent": r.get("detected_intent"),
            "gap_category": cat,
        })

    if out_rows:
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
            w.writeheader()
            w.writerows(out_rows)

    total = len(rows)
    failed = len(out_rows)
    print(f"Total turns: {total}, failed/unresolved turns: {failed} "
          f"({failed/total*100:.2f}% if total else 0)")
    for cat, n in cat_counter.most_common():
        print(f"  {cat}: {n} ({n/failed*100:.2f}% of failures)" if failed else f"  {cat}: {n}")
    print(f"\nWrote {failed} row(s) to {args.out}")


if __name__ == "__main__":
    main()
