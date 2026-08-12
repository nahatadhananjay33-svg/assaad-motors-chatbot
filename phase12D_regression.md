# Phase 12D — Regression (STEP 11)

Command: `python -m pytest *_tests.py` (full suite, incl. new `phase12d_field_tests.py`).

## Result

```
534 passed, 2 failed  (151s)
```

- **534 passed** = Phase 12C's 521 + **13 new Phase 12D tests**.
- **2 failed** = the same pre-existing/stale failures — **no new failures from 12D**.

| BEFORE (12C) | AFTER (12D) |
|---|---|
| 521 passed, 2 failed | **534 passed, 2 failed** |

## Intentional behaviour change (documented, not a silent break)

Three existing tests asserted the OLD behaviour that **"sunroof" / "airbag(s)"
route off-sheet**. Phase 12B made these real answerable fields and Phase 12D
STEP 4 requires them to be attribute questions, so `sunroof`/`airbag(s)` were
removed from `OFFSHEET_TOPICS`. The three tests were updated to the new behaviour
(and still pass):

- `chat_api_tests::test_intent_classification` — "Creta mein sunroof hai?" now
  `availability` (was `off_sheet`).
- `inventory_retrieval_tests::test_offsheet_detection` — asserts sunroof is now a
  field (`attr_fields`), and genuine off-sheet topics (finance, exchange) still route off-sheet.
- `inventory_retrieval_tests::test_offsheet_never_fabricates` — re-pointed at a
  genuine off-sheet query (`finance milega?`) to keep testing off-sheet safety.

## The 2 remaining failures — pre-existing, NOT 12D

| Test | Cause |
|---|---|
| `hardening_tests::test_refresh_returns_ok_and_count` | asserts count 40; live sheet has 44 (stale). |
| `media_api_tests::test_unknown_still_flagged` | `"…999"` parsed as a partial number-plate (Phase 11A) → `not_found` vs expected `unknown`. Pre-dates 12B. |

Both are tracked for the pending cleanup step (remove test cars / update the two
stale expectations).

## Regression-safety summary
No auth / permissions / owner-panel / staff-panel / media / Supabase / Excel-upload
code touched. Changes were additive (new `field_intents.py`; new `attr_fields` /
`feature_filters` on `Query`; a formatter branch; a retrieval filter; router +
chat_service routing; scoring hook) plus the one documented off-sheet change. All
11A/11B/12B/12C suites remain green.
