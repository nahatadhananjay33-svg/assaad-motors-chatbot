"""
consultative_sales_validate.py  —  Phase 7P.1 STEP 5 (validation)
=================================================================

Replays the REAL pilot conversation log BEFORE vs AFTER the consultative layer
(via the `CONSULTATIVE_LAYER` toggle — nothing else differs) and proves:

  NEW (must go UP)
    * Recommendation Coverage       — entry-intent inventory turns that now lead
                                      with a recommendation
    * Consultative Question Coverage — entry-intent inventory turns that now ask
                                      exactly ONE follow-up question

  REGRESSION GUARDS (must stay identical, before == after)
    * Inventory Accuracy   — the set of vehicles returned per turn is unchanged
    * Follow-up Memory     — context-resolved single-vehicle turns unchanged
    * Price Accuracy       — price-follow-up answers unchanged
    * Media Accuracy       — media status/vehicle per turn unchanged
    * Lead Capture         — lead level per turn unchanged

The brief names `customer_agent_ALL.txt` and a "500-conversation benchmark".
Those files are not in the repository (as with the Phase-7O.* audits), so the
pilot log (`data/pilot_query_log.db`) is the replay dataset and the benchmark is
a deterministic 500-conversation slice of it.

Read-only on the pilot log; isolated temp DBs.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from collections import defaultdict
from typing import Dict, List, Tuple

import tempfile

import chat_service as CS
from chat_service import ChatService
from astor_leak_audit import _speedup
from consultative_sales_audit import _audit_intent, _is_dump, _is_consultative

LOG_DB = os.path.join(os.path.dirname(__file__), "..", "..", "data",
                      "pilot_query_log.db")


def _new_service() -> ChatService:
    """Isolated service with REAL lead capture (so the Lead Capture regression
    guard is meaningful) but isolated temp DBs and silenced analytics writes."""
    d = tempfile.mkdtemp(prefix="cval_")
    svc = ChatService(analytics_db=os.path.join(d, "a.db"),
                      leads_db=os.path.join(d, "l.db"),
                      unknown_db=os.path.join(d, "u.db"))
    svc.analytics.record = lambda *a, **k: None     # writes only; never the reply
    return svc


def _load_conversations(limit: int = None) -> List[Tuple[str, List[str]]]:
    c = sqlite3.connect(LOG_DB)
    rows = c.execute(
        "SELECT conversation_id, user_query FROM query_log ORDER BY conversation_id, id"
    ).fetchall()
    c.close()
    convs: Dict[str, List[str]] = defaultdict(list)
    for cid, uq in rows:
        if uq:
            convs[cid].append(uq)
    items = list(convs.items())
    return items[:limit] if limit else items


def _sig(r) -> Tuple:
    """Turn signature for the regression guards: the exact vehicles returned
    (by registration), media status+vehicle, lead level, price-answer shape."""
    vehset = tuple(sorted(v.get("registration_no") or "" for v in r.vehicles))
    media = (r.media or {}).get("status"), (r.media or {}).get("registration_no")
    lead = r.meta.get("lead_level")
    price = (r.intent, r.count) if r.intent == "price" else None
    return (vehset, media, lead, price)


def replay(layer_on: bool, convs) -> Dict:
    CS.CONSULTATIVE_LAYER = layer_on
    svc = _new_service()
    per_turn: Dict[str, Tuple] = {}
    flags: Dict[str, Dict] = {}
    t0 = time.time()
    for n, (cid, turns) in enumerate(convs, 1):
        sid = f"cval::{cid}"
        for ti, turn in enumerate(turns):
            r = svc.handle(turn, session_id=sid)
            key = f"{cid}#{ti}"
            per_turn[key] = _sig(r)
            # A "broad entry inventory turn" = a turn whose ORIGINAL message is a
            # broad entry intent AND that returned a listing. Measured identically
            # in both runs (it depends on the message + the returned cards, not on
            # the wording), so it is a fair shared denominator for coverage.
            entry = bool(_audit_intent(turn)) and bool(r.vehicles)
            flags[key] = {"entry": entry, "dump": _is_dump(r),
                          "consultative": bool(r.meta.get("consultative")),
                          "asked_q": _is_consultative(r)}
        if n % 1500 == 0:
            print(f"  ...{n}/{len(convs)} convs ({round(time.time()-t0,1)}s)",
                  flush=True)
    svc.close()
    return {"per_turn": per_turn, "flags": flags}


def compare(before: Dict, after: Dict) -> Dict:
    keys = set(before["per_turn"]) & set(after["per_turn"])
    diffs = {"inventory": [], "media": [], "lead": [], "price": []}
    for k in keys:
        b, a = before["per_turn"][k], after["per_turn"][k]
        if b[0] != a[0]:
            diffs["inventory"].append(k)
        if b[1] != a[1]:
            diffs["media"].append(k)
        if b[2] != a[2]:
            diffs["lead"].append(k)
        if b[3] != a[3]:
            diffs["price"].append(k)
    n = len(keys) or 1
    # Shared denominator: turns that are a broad entry inventory listing in the
    # BEFORE run (independent of wording).
    entry_keys = [k for k in keys if before["flags"][k]["entry"]]
    e = len(entry_keys) or 1
    rec_before = sum(before["flags"][k]["consultative"] for k in entry_keys)
    rec_after = sum(after["flags"][k]["consultative"] for k in entry_keys)
    q_before = sum(before["flags"][k]["asked_q"] for k in entry_keys)
    q_after = sum(after["flags"][k]["asked_q"] for k in entry_keys)
    # "Dump-text" = a broad entry listing whose REPLY is a raw inventory dump
    # (no consultative recommendation/question). Cards are intentionally kept in
    # both runs, so dump is measured on the WORDING via the consultative flag.
    dump_before = sum(1 for k in entry_keys if not before["flags"][k]["consultative"])
    dump_after = sum(1 for k in entry_keys if not after["flags"][k]["consultative"])
    # Follow-up memory: turns that resolved to a SINGLE vehicle BEFORE (a
    # context-resolved follow-up) must resolve to the SAME single vehicle AFTER.
    single_before = [k for k in keys if len(before["per_turn"][k][0]) == 1]
    sb = len(single_before) or 1
    followup_ok = sum(before["per_turn"][k][0] == after["per_turn"][k][0]
                      for k in single_before)
    return {
        "turns_compared": len(keys),
        "broad_entry_inventory_turns": len(entry_keys),
        "recommendation_coverage_before": f"{rec_before/e*100:.1f}%",
        "recommendation_coverage_after": f"{rec_after/e*100:.1f}%",
        "consultative_question_coverage_before": f"{q_before/e*100:.1f}%",
        "consultative_question_coverage_after": f"{q_after/e*100:.1f}%",
        "dump_text_turns_before": dump_before,
        "dump_text_turns_after": dump_after,
        "inventory_accuracy": f"{(len(keys)-len(diffs['inventory']))/n*100:.2f}%",
        "media_accuracy": f"{(len(keys)-len(diffs['media']))/n*100:.2f}%",
        "lead_capture_accuracy": f"{(len(keys)-len(diffs['lead']))/n*100:.2f}%",
        "price_accuracy": f"{(len(keys)-len(diffs['price']))/n*100:.2f}%",
        "followup_memory_turns": len(single_before),
        "followup_memory_accuracy": f"{followup_ok/sb*100:.2f}%",
        "regressions": {k: len(v) for k, v in diffs.items()},
        "regression_examples": {k: v[:5] for k, v in diffs.items() if v},
    }


def run_dataset(name: str, convs) -> Dict:
    print(f"[{name}] BEFORE (CONSULTATIVE_LAYER=False)...", flush=True)
    before = replay(False, convs)
    print(f"[{name}] AFTER  (CONSULTATIVE_LAYER=True)...", flush=True)
    after = replay(True, convs)
    res = compare(before, after)
    res["conversations"] = len(convs)
    print(f"[{name}] {json.dumps(res, indent=2)}", flush=True)
    return res


def main() -> None:
    _speedup()
    full = _load_conversations()
    bench = full[:500]                       # deterministic 500-conversation benchmark
    out = {
        "benchmark_500": run_dataset("benchmark_500", bench),
        "full_pilot_log": run_dataset("full_pilot_log", full),
    }
    CS.CONSULTATIVE_LAYER = True
    path = os.path.join(os.path.dirname(__file__),
                        "consultative_sales_validate_result.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print("Wrote", path, flush=True)


if __name__ == "__main__":
    main()
