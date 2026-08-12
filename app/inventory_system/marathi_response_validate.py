"""
marathi_response_validate.py  —  Phase 7O.5 STEP 4 (validation)
===============================================================

Replays the real Marathi conversations from the pilot log and measures the
Marathi reply rate BEFORE vs AFTER the fix. "Before" is reproduced by disabling
ONLY the Phase-7O.5 post-processor (`chat_service.to_marathi` → identity); the
"after" run uses the shipped converter. Nothing else differs.
"""
from __future__ import annotations

import time

import chat_service as CS
from language_detector import detect_language
from astor_leak_audit import _speedup, _new_service
from marathi_response_audit import _classify_reply, _load_marathi_conversations


def run(enabled: bool, convs):
    real = CS.to_marathi
    CS.to_marathi = real if enabled else (lambda x: x)
    try:
        svc = _new_service()
        from collections import Counter
        cls = Counter()
        t0 = time.time()
        for n, (cid, turns) in enumerate(convs, 1):
            sid = f"mv::{cid}"
            for turn in turns:
                is_mar = detect_language(turn) == "marathi"
                r = svc.handle(turn, session_id=sid)
                if is_mar:
                    cls[_classify_reply(r.response)] += 1
            if n % 400 == 0:
                print(f"  ...{n}/{len(convs)} ({round(time.time()-t0,1)}s)", flush=True)
        svc.close()
        total = sum(cls.values()) or 1
        return {"total": total, "pure": cls["pure_marathi"], "mixed": cls["mixed"],
                "hindi_hinglish": cls["hindi_hinglish"], "neutral": cls["neutral"],
                "marathi_reply_pct": round((cls["pure_marathi"] + cls["mixed"]) / total * 100, 1),
                "pure_pct": round(cls["pure_marathi"] / total * 100, 1)}
    finally:
        CS.to_marathi = real


def main():
    _speedup()
    convs = _load_marathi_conversations()
    print(f"Replaying {len(convs)} Marathi conversations.", flush=True)
    print("BEFORE (post-processor disabled)...", flush=True)
    before = run(False, convs)
    print("BEFORE:", before, flush=True)
    print("AFTER (post-processor enabled)...", flush=True)
    after = run(True, convs)
    print("AFTER:", after, flush=True)
    import json, os
    with open(os.path.join(os.path.dirname(__file__),
                           "marathi_response_validate_result.json"), "w") as f:
        json.dump({"conversations": len(convs), "before": before, "after": after},
                  f, indent=2)
    print("Wrote marathi_response_validate_result.json", flush=True)


if __name__ == "__main__":
    main()
