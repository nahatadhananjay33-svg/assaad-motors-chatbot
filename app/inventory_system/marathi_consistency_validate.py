"""
marathi_consistency_validate.py  —  Phase 7O.6 validation (500 convs / 10 batches)
==================================================================================

Re-runs the SAME 500 conversations in 10 batches of 50, BEFORE vs AFTER the
Phase-7O.6 session-language-stickiness fix, and reports:

  * Marathi consistency  — % of bot replies that stay Marathi on every turn AFTER
    Marathi is established in the conversation (the real defect; the 7O.5 audit
    only graded self-Marathi turns and so never saw it).
  * English regression   — Marathi% on English conversations must stay ~0 (a flip
    would mean an English chat got pushed into Marathi).
  * Hindi regression     — Hindi conversations must stay Hindi (Marathi% ~0).
  * Inventory parity     — per-turn vehicle registration lists must be IDENTICAL
    before vs after (the fix must not move a single car).
  * Follow-up memory     — same active-vehicle resolution before vs after.

BEFORE is reproduced WITHOUT reverting the source: the fix only acts when the
session has been marked Marathi in `_session_lang`, so disabling stickiness =
forcing that map to stay empty (a tiny monkeypatch of the dict's __setitem__).
The shipped to_marathi post-processor stays ON in both runs, so this isolates the
NEW fix exactly.

Read-only on the pilot log; isolated temp DBs.
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

from language_detector import detect_language
from astor_leak_audit import _speedup, _new_service
from marathi_response_audit import _classify_reply

LOG_DB = os.path.join(os.path.dirname(__file__), "..", "..", "data",
                      "pilot_query_log.db")
N_CONVS = 500
N_BATCHES = 10


def _load(predicate) -> List[Tuple[str, List[str]]]:
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
    out = [(cid, t) for cid, t in convs.items() if predicate(t)]
    out.sort(key=lambda kv: kv[0] or "")
    return out


def _is_marathi_conv(turns):
    return any(detect_language(x) == "marathi" for x in turns)


def _is_pure_lang_conv(turns, lang):
    langs = [detect_language(x) for x in turns]
    return any(l == lang for l in langs) and "marathi" not in langs


def _regs(r):
    return tuple(v.get("registration_no") for v in (r.vehicles or []))


def run_batches(convs, *, sticky: bool):
    """Replay convs in N_BATCHES batches. Returns consistency counters plus the
    per-(conv,turn) vehicle-reg fingerprint for inventory/memory parity."""
    import chat_service as CS

    graded = Counter()
    fingerprint: Dict[Tuple[str, int], tuple] = {}
    fail_by_route = Counter()
    fail_samples = []
    batch_size = (len(convs) + N_BATCHES - 1) // N_BATCHES
    batch_pct = []

    for b in range(N_BATCHES):
        chunk = convs[b * batch_size:(b + 1) * batch_size]
        if not chunk:
            batch_pct.append(None)
            continue
        svc = _new_service()
        if not sticky:
            # Disable ONLY the new fix: keep `_session_lang` permanently empty so
            # the carryover re-classify branch never fires. Nothing else changes.
            svc._session_lang = _Blackhole()
        b_graded = Counter()
        for cid, turns in chunk:
            sid = f"cv::{cid}"
            established = False
            for ti, turn in enumerate(turns):
                is_self_mar = detect_language(turn) == "marathi"
                r = svc.handle(turn, session_id=sid)
                fingerprint[(cid, ti)] = _regs(r)
                if established:
                    cl = _classify_reply(r.response)
                    graded[cl] += 1
                    b_graded[cl] += 1
                    if cl in ("hindi_hinglish", "mixed"):
                        route = r.meta.get("route", "?")
                        fail_by_route[(route, r.intent)] += 1
                        if len(fail_samples) < 60:
                            fail_samples.append(
                                (turn, detect_language(turn), r.intent, route,
                                 r.response.replace("\n", " ")[:90]))
                if is_self_mar:
                    established = True
        svc.close()
        tot = sum(b_graded.values()) or 1
        batch_pct.append(round(b_graded["pure_marathi"] / tot * 100, 1))

    return graded, fingerprint, batch_pct, fail_by_route, fail_samples


class _Blackhole(dict):
    """A dict that silently drops writes — used to disable the stickiness memory
    for the BEFORE run without touching source."""
    def __setitem__(self, k, v):
        pass


def _consistency_pct(graded) -> float:
    tot = sum(graded.values()) or 1
    return round(graded["pure_marathi"] / tot * 100, 1)


def _grade_only(convs, *, sticky: bool, established_required: bool):
    """Generic replay that grades every reply (used for English / Hindi
    regression where there is no 'established Marathi' gate)."""
    import chat_service as CS
    graded = Counter()
    fingerprint: Dict[Tuple[str, int], tuple] = {}
    svc = _new_service()
    if not sticky:
        svc._session_lang = _Blackhole()
    for cid, turns in convs:
        sid = f"rg::{cid}"
        established = False
        for ti, turn in enumerate(turns):
            is_self_mar = detect_language(turn) == "marathi"
            r = svc.handle(turn, session_id=sid)
            fingerprint[(cid, ti)] = _regs(r)
            grade_this = (not established_required) or established
            if grade_this:
                graded[_classify_reply(r.response)] += 1
            if is_self_mar:
                established = True
    svc.close()
    return graded, fingerprint


def main():
    _speedup()

    # Consistency only manifests in MULTI-turn dialogues (a single-turn chat can
    # never "switch" language), and most log conversations are single-turn — so
    # the evaluation set is the first 500 multi-turn conversations of each kind.
    marathi = _load(lambda t: len(t) >= 2 and _is_marathi_conv(t))[:N_CONVS]
    english = _load(lambda t: len(t) >= 2 and _is_pure_lang_conv(t, "english"))[:N_CONVS]
    hindi = _load(lambda t: len(t) >= 2 and _is_pure_lang_conv(t, "hindi"))[:N_CONVS]

    print(f"Marathi convs: {len(marathi)} | English convs: {len(english)} "
          f"| Hindi convs: {len(hindi)}", flush=True)

    # ── Marathi consistency, 10 batches, BEFORE vs AFTER ──
    print("\n[Marathi] BEFORE (stickiness OFF)...", flush=True)
    g_before, fp_before, bp_before, _, _ = run_batches(marathi, sticky=False)
    print("[Marathi] AFTER  (stickiness ON)...", flush=True)
    g_after, fp_after, bp_after, fail_route, fail_samples = run_batches(marathi, sticky=True)

    before_pct = _consistency_pct(g_before)
    after_pct = _consistency_pct(g_after)

    # ── inventory + follow-up parity: identical reg lists per turn ──
    keys = set(fp_before) | set(fp_after)
    inv_mismatch = [k for k in keys if fp_before.get(k) != fp_after.get(k)]

    # ── English / Hindi regression ──
    print("[English] regression BEFORE/AFTER...", flush=True)
    en_before, en_fp_before = _grade_only(english, sticky=False, established_required=False)
    en_after, en_fp_after = _grade_only(english, sticky=True, established_required=False)
    print("[Hindi] regression BEFORE/AFTER...", flush=True)
    hi_before, _ = _grade_only(hindi, sticky=False, established_required=False)
    hi_after, _ = _grade_only(hindi, sticky=True, established_required=False)

    def _marathi_share(c):
        tot = sum(c.values()) or 1
        return round((c["pure_marathi"] + c["mixed"]) / tot * 100, 1)

    en_keys = set(en_fp_before) | set(en_fp_after)
    en_inv_mismatch = [k for k in en_keys if en_fp_before.get(k) != en_fp_after.get(k)]

    result = {
        "n_marathi": len(marathi), "n_batches": N_BATCHES,
        "marathi_consistency_before_pct": before_pct,
        "marathi_consistency_after_pct": after_pct,
        "marathi_graded_before": dict(g_before),
        "marathi_graded_after": dict(g_after),
        "marathi_batch_pct_before": bp_before,
        "marathi_batch_pct_after": bp_after,
        "inventory_turns_compared": len(keys),
        "inventory_mismatches": len(inv_mismatch),
        "english_marathi_share_before": _marathi_share(en_before),
        "english_marathi_share_after": _marathi_share(en_after),
        "english_inventory_mismatches": len(en_inv_mismatch),
        "hindi_marathi_share_before": _marathi_share(hi_before),
        "hindi_marathi_share_after": _marathi_share(hi_after),
        "hindi_hinglish_remaining_after": g_after.get("hindi_hinglish", 0),
        "neutral_after": g_after.get("neutral", 0),
        "top_remaining_fail_routes": [
            {"route": k[0], "intent": k[1], "count": v}
            for k, v in fail_route.most_common(12)],
        "remaining_fail_samples": [
            {"turn": s[0], "detected": s[1], "intent": s[2],
             "route": s[3], "reply": s[4]} for s in fail_samples[:25]],
    }

    import json
    out_path = os.path.join(os.path.dirname(__file__),
                            "marathi_consistency_validate_result.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print("\n================  RESULT  ================", flush=True)
    print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)
    print(f"\nWrote {os.path.basename(out_path)}", flush=True)


if __name__ == "__main__":
    main()
