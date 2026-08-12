"""
media_experience_audit.py  —  Phase 7O.3 validation harness
===========================================================

Validates the Photo / Video experience improvement against the REAL pilot
conversation log (`data/pilot_query_log.db`). Every conversation that contains at
least one photo or video request is replayed **in order** (context preserved, one
ChatService session per conversation_id), once with the pre-7O.3 wording
(`MEDIA_CRISP_REPLIES = False`) and once with the shipped behaviour
(`MEDIA_CRISP_REPLIES = True`). Nothing else differs between the two passes.

For each photo / video request turn we classify the bot's reply:

  * direct        — a vehicle was identified, no re-ask (media_status ok /
                    media_unavailable).
  * crisp direct  — direct AND the reply is the short, vehicle-named media line
                    (not the long generic availability boilerplate).
  * clarification — the bot re-asked the vehicle (media_status multiple_matches /
                    vehicle_not_identified).

The fix should turn generic direct replies into **crisp** direct replies for the
single-vehicle case, without changing which turns legitimately clarify.

Reuses the parse/normalize memoization + lead/analytics no-op from
`astor_leak_audit` so the multi-thousand-turn replay is fast. Isolated temp DBs;
the pilot log is read-only.
"""
from __future__ import annotations

import os
import sqlite3
import time
from collections import defaultdict
from typing import Dict, List, Tuple

import chat_service as CS
import media_lookup as ml
from astor_leak_audit import _speedup, _new_service

LOG_DB = os.path.join(os.path.dirname(__file__), "..", "..", "data",
                      "pilot_query_log.db")
PHOTO, VIDEO = "photo_request", "video_request"
_GENERIC_MARKERS = ("Vasant Oasis", "aap aaj aa ke", "options hain")


def _load_media_conversations() -> List[Tuple[str, List[str]]]:
    c = sqlite3.connect(LOG_DB)
    rows = c.execute(
        "SELECT conversation_id, user_query FROM query_log ORDER BY conversation_id, id"
    ).fetchall()
    c.close()
    convs: Dict[str, List[str]] = defaultdict(list)
    for cid, uq in rows:
        if uq:
            convs[cid].append(uq)
    out = []
    for cid, turns in convs.items():
        if any(ml.detect_media_intent(t) in (PHOTO, VIDEO) for t in turns):
            out.append((cid, turns))
    return out


def _is_crisp(resp: str) -> bool:
    """A short, vehicle-named media line — not the long generic boilerplate."""
    return len(resp) <= 90 and not any(m in resp for m in _GENERIC_MARKERS)


def run(crisp: bool, convs) -> Dict[str, int]:
    CS.MEDIA_CRISP_REPLIES = crisp
    svc = _new_service()
    m = {"photo_total": 0, "photo_direct": 0, "photo_crisp": 0, "photo_clarify": 0,
         "video_total": 0, "video_direct": 0, "video_crisp": 0, "video_clarify": 0}
    t0 = time.time()
    for n, (cid, turns) in enumerate(convs, 1):
        sid = f"media::{cid}"
        for turn in turns:
            mi = ml.detect_media_intent(turn)
            r = svc.handle(turn, session_id=sid)
            if mi not in (PHOTO, VIDEO):
                continue
            pre = "photo" if mi == PHOTO else "video"
            m[f"{pre}_total"] += 1
            status = (r.media or {}).get("status")
            if status in ("ok", "media_unavailable"):          # vehicle identified
                m[f"{pre}_direct"] += 1
                if _is_crisp(r.response):
                    m[f"{pre}_crisp"] += 1
            elif status in ("multiple_matches", "vehicle_not_identified"):
                m[f"{pre}_clarify"] += 1
        if n % 300 == 0:
            print(f"  ...{n}/{len(convs)} convs ({round(time.time()-t0,1)}s)",
                  flush=True)
    svc.close()
    return m


def main() -> None:
    _speedup()
    convs = _load_media_conversations()
    print(f"Replaying {len(convs)} media conversations.", flush=True)
    print("BEFORE (MEDIA_CRISP_REPLIES=False)...", flush=True)
    before = run(False, convs)
    print("BEFORE:", before, flush=True)
    print("AFTER (MEDIA_CRISP_REPLIES=True)...", flush=True)
    after = run(True, convs)
    print("AFTER:", after, flush=True)
    CS.MEDIA_CRISP_REPLIES = True

    import json
    with open(os.path.join(os.path.dirname(__file__),
                           "media_experience_audit_result.json"), "w") as f:
        json.dump({"conversations": len(convs), "before": before, "after": after},
                  f, indent=2)
    print("Wrote media_experience_audit_result.json", flush=True)


if __name__ == "__main__":
    main()
