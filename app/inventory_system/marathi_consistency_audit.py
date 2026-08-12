"""
marathi_consistency_audit.py  —  Marathi CONSISTENCY (whole-conversation)
=========================================================================

The Phase-7O.5 audit only graded turns whose CURRENT message was detected as
Marathi. It therefore never measured the real defect: a Marathi customer's
*short / ambiguous follow-up* turn ("Nexon", "photo", "haan", "2019", "1") is
detected as english/hindi/hinglish, so the per-turn Marathi post-processor does
not fire and the reply reverts to Hinglish — the conversation switches language
mid-stream.

This harness measures CONSISTENCY: take every conversation that contains a
Marathi turn, replay it in order through the live ChatService, and grade the
bot reply on EVERY turn AFTER Marathi has been established in that conversation
(i.e. once the customer has spoken Marathi at least once). A Hindi/Hinglish/mixed
reply on such a turn is a consistency failure.

It also splits the failures by whether the current turn's own message detects as
Marathi ("self-marathi" — already covered by 7O.5) vs NOT ("carryover" — the new
gap). Read-only on the pilot log; isolated temp DBs.
"""
from __future__ import annotations

import os
import sys
import sqlite3
from collections import Counter, defaultdict
from typing import Dict, List, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import chat_service as CS
from language_detector import detect_language
from astor_leak_audit import _speedup, _new_service
from marathi_response_audit import _classify_reply

LOG_DB = os.path.join(os.path.dirname(__file__), "..", "..", "data",
                      "pilot_query_log.db")


def load_marathi_conversations(limit: int | None = None
                               ) -> List[Tuple[str, List[str]]]:
    c = sqlite3.connect(LOG_DB)
    rows = c.execute(
        "SELECT conversation_id, user_query FROM query_log "
        "ORDER BY conversation_id, id"
    ).fetchall()
    c.close()
    convs: Dict[str, List[str]] = defaultdict(list)
    for cid, uq in rows:
        if uq:
            convs[cid].append(uq)
    out = [(cid, t) for cid, t in convs.items()
           if any(detect_language(x) == "marathi" for x in t)]
    out.sort(key=lambda kv: kv[0] or "")
    if limit:
        out = out[:limit]
    return out


def audit(convs, *, enabled: bool):
    """Grade reply language on every turn once Marathi is established.

    Returns counters. `enabled` toggles the shipped to_marathi post-processor so
    the same harness produces BEFORE (False) and AFTER (True) figures.
    """
    real = CS.to_marathi
    CS.to_marathi = real if enabled else (lambda x: x)
    try:
        svc = _new_service()
        graded = Counter()           # all graded turns
        carry = Counter()            # turns whose own message is NOT marathi
        selfm = Counter()            # turns whose own message IS marathi
        carry_lang = Counter()       # detected language of carryover turns
        carry_fail_lang = Counter()  # detected language of FAILING carryover turns
        fail_samples = []
        for cid, turns in convs:
            sid = f"mc::{cid}"
            established = False
            for turn in turns:
                lang = detect_language(turn)
                is_self_mar = lang == "marathi"
                r = svc.handle(turn, session_id=sid)
                if established:
                    cl = _classify_reply(r.response)
                    graded[cl] += 1
                    (selfm if is_self_mar else carry)[cl] += 1
                    if not is_self_mar:
                        carry_lang[lang] += 1
                        if cl in ("hindi_hinglish", "mixed"):
                            carry_fail_lang[lang] += 1
                    if cl in ("hindi_hinglish", "mixed") and not is_self_mar \
                            and len(fail_samples) < 40:
                        fail_samples.append(
                            (turn, lang, r.intent, r.meta.get("route", "?"),
                             r.response.replace("\n", " ")[:80]))
                if is_self_mar:
                    established = True
        svc.close()
        return {"graded": graded, "carry": carry, "selfm": selfm,
                "carry_lang": carry_lang, "carry_fail_lang": carry_fail_lang,
                "fail_samples": fail_samples}
    finally:
        CS.to_marathi = real


def _pct(cnt: Counter) -> Tuple[int, int, float]:
    total = sum(cnt.values()) or 1
    mar = cnt["pure_marathi"]
    return mar, total, round(mar / total * 100, 1)


def main():
    _speedup()
    convs = load_marathi_conversations()
    print(f"Marathi conversations: {len(convs)}", flush=True)

    before = audit(convs, enabled=False)
    after = audit(convs, enabled=True)

    for label, res in (("BEFORE", before), ("AFTER", after)):
        gm, gt, gp = _pct(res["graded"])
        cm, ct, cp = _pct(res["carry"])
        sm, st, sp = _pct(res["selfm"])
        print(f"\n== {label} ==", flush=True)
        print(f"  ALL established turns : pure_marathi {gm}/{gt} = {gp}%  "
              f"(hindi/hinglish {res['graded']['hindi_hinglish']}, "
              f"mixed {res['graded']['mixed']}, neutral {res['graded']['neutral']})",
              flush=True)
        print(f"  carryover (own turn NOT marathi): pure {cm}/{ct} = {cp}%  "
              f"(hindi/hinglish {res['carry']['hindi_hinglish']})", flush=True)
        print(f"  self-marathi (own turn IS marathi): pure {sm}/{st} = {sp}%",
              flush=True)

    print("\nCarryover turns by detected language (BEFORE):",
          dict(before["carry_lang"]), flush=True)
    print("Carryover FAILING turns by detected language (BEFORE):",
          dict(before["carry_fail_lang"]), flush=True)

    print("\nTop carryover failures (AFTER):", flush=True)
    for s in after["fail_samples"][:25]:
        print("  ", s, flush=True)


if __name__ == "__main__":
    main()
