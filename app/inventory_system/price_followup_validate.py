"""
price_followup_validate.py  —  Phase 7O.4 STEP 4 (validation)
=============================================================

Replays the real price-follow-up conversations from the pilot log and measures
the pass rate BEFORE vs AFTER the fix, via the `PRICE_FOLLOWUP_PIN` toggle
(nothing else differs). A price follow-up is counted as a PASS when an active
vehicle context exists and the bot answers exactly ONE selected vehicle's price
(count == 1, intent == "price"). Also tracks inventory dumps on price questions.

Read-only on the pilot log; isolated temp DBs; parse/lead memoization reused.
"""
from __future__ import annotations

import time

import chat_service as CS
from astor_leak_audit import _speedup, _new_service
from price_followup_audit import _is_price_followup, _ctx_after, _load_conversations, DUMP_THRESHOLD


def run(pin: bool, convs):
    CS.PRICE_FOLLOWUP_PIN = pin
    svc = _new_service()
    m = {"followups_ctx": 0, "pass": 0, "fail": 0, "dump": 0, "noctx": 0}
    t0 = time.time()
    for n, (cid, turns) in enumerate(convs, 1):
        sid = f"pval::{cid}"
        ctx = None
        for turn in turns:
            price_fu = _is_price_followup(turn)   # audit helper (parses internally)
            r = svc.handle(turn, session_id=sid)
            if price_fu:
                if r.count >= DUMP_THRESHOLD:
                    m["dump"] += 1
                    if ctx:
                        m["followups_ctx"] += 1
                        m["fail"] += 1
                    else:
                        m["noctx"] += 1
                elif ctx:
                    m["followups_ctx"] += 1
                    if r.count == 1 and r.intent == "price":
                        m["pass"] += 1
                    else:
                        m["fail"] += 1
                else:
                    m["noctx"] += 1
            nctx = _ctx_after(turn, r)
            if nctx:
                ctx = nctx
        if n % 400 == 0:
            print(f"  ...{n}/{len(convs)} ({round(time.time()-t0,1)}s)", flush=True)
    svc.close()
    m["pass_rate"] = round(m["pass"] / m["followups_ctx"] * 100, 1) if m["followups_ctx"] else 0.0
    return m


def main():
    _speedup()
    convs = _load_conversations()
    print(f"Replaying {len(convs)} price-follow-up conversations.", flush=True)
    print("BEFORE (PRICE_FOLLOWUP_PIN=False)...", flush=True)
    before = run(False, convs)
    print("BEFORE:", before, flush=True)
    print("AFTER (PRICE_FOLLOWUP_PIN=True)...", flush=True)
    after = run(True, convs)
    print("AFTER:", after, flush=True)
    CS.PRICE_FOLLOWUP_PIN = True
    import json, os
    with open(os.path.join(os.path.dirname(__file__),
                           "price_followup_validate_result.json"), "w") as f:
        json.dump({"conversations": len(convs), "before": before, "after": after},
                  f, indent=2)
    print("Wrote price_followup_validate_result.json", flush=True)


if __name__ == "__main__":
    main()
