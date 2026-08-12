# Phase 12I — Regression Report

Run exactly as previous phases:
```bash
cd app/inventory_system
python -m pytest -o python_files="*_tests.py" -q
```

## Results

| Run | Passed | Failed | Wall time |
|-----|--------|--------|-----------|
| Phase 12I baseline (before any change) | 580 | 0 | 159.2 s |
| **Phase 12I (post-change, full suite)** | **612** | **0** | 169.7 s |
| New in 12I (`phase12i_tests.py`) | +32 | 0 | 4.6 s (isolated) |

**612 = 580 (baseline) + 32 new Phase 12I tests. Zero failures, zero new
regressions.**

> Note on the "580/0" baseline: the two long-standing stale tests documented in
> 11B→12G (`hardening_tests` inventory-count 40 vs 44, and the `…999` partial-plate
> media test) both pass against the **current** live sheet, so the true starting
> point this phase is a clean **580 / 0** (confirmed by running the suite before
> touching any code).

## Failure classification
- **Genuine new failures:** 0
- **Pre-existing stale:** 0 (both historically-stale tests currently pass)
- **Transient/environment:** 0

## Why no existing test broke
Every change is **additive and gated**:

| Change | Guard that protects existing behaviour |
|--------|----------------------------------------|
| Fuel RULE D (`query_parser`) | only inside the existing 12G block: no search cue, no model/make/category, no browse filter, requires a question word. `petrol wali/chahiye/under X` untouched. |
| Bare-ambiguous clarify | set **only** when nothing else resolved (no filter, no attr flag, no attr_fields, no price). Fuller forms resolve real fields first. |
| `boot` Sedan-cue removal | `dickey wali` remains the sedan cue; `boot` becomes a `boot_litres` label. |
| Devanagari additions | pure vocabulary additions (Hindi spellings) — no collisions with existing Marathi entries. |
| Booking precedence | booking/token words **moved** out of `finance_details`; `_BOOKING` already owned `booking`/`token`. Finance/EMI/down-payment words untouched. |
| Negotiation objections | specific multi-word phrases only; a real `sasti gaadi dikhao` browse is never captured (asserted). |
| Multi-attribute combiner | fires only for `count == 1` **and** 2+ intents **and** ≥1 non-field/price intent. Pure `attr_fields` multi and all single-intent branches are untouched. |
| `_is_price_followup` guard | returns False only when another attribute intent co-exists; pure `price?`/`final?` still take the fast path. |

## Anti-regression evidence (phrasings most at risk, all asserted green)
- `parse("petrol wali dikhao").fuel is not None and not fuel_query` — search preserved.
- `parse("boot space kitna hai?")` still → `boot_litres`.
- `parse("engine capacity kitna hai?")` → `engine_cc`, `ambiguous_field is None`.
- `faq_engine.detect_intent("EMI?") == "finance_details"`, `"loan?" == "loan"`.
- `faq_engine.detect_intent("sasti gaadi dikhao") is None` (still an inventory browse).
- `"kam km wali dikhao"` / `"sabse kam km wali car"` still `sort_low_km`, still multi.
- 12G suite (year/km/transmission attribute vs search) fully green.
- 12D/12E/12F suites (new-field attrs, conversation modes, e2e) fully green.

## Verdict
**612 passed / 0 failed.** No new regressions; no pre-existing red tests. The
suite is clean.
