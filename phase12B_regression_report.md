# Phase 12B — Regression Report

Command: `python -m pytest *_tests.py` (full suite, includes the new
`phase12b_specs_tests.py`).

## Result

```
515 passed, 2 failed  (107.9s)
```

- **515 passed** = previous 501 + the **14 new Phase 12B validation tests**.
- **Failures dropped from 5 → 2** vs the Phase 11B baseline — because the owner
  marked the test car `MH99ZZ9999` **Sold** during manual testing, which cleared
  the 3 Swift-related test-car failures.

## The 2 remaining failures — pre-existing, NOT caused by 12B

| Test | Why it fails | 12B-related? |
|---|---|---|
| `hardening_tests::test_refresh_returns_ok_and_count` | Asserts inventory count **40**; live sheet has **44** available. Stale expectation. | ❌ No |
| `media_api_tests::test_unknown_still_flagged` | `"…999"` is parsed as a **partial number-plate** (Phase 11A/11C feature) → availability search → `not_found` (test expects `unknown`). Was already in the failing-5 in Phase 11B (then as `ok`). | ❌ No |

**Proof of non-causation:** both behaviours are in `query_parser` / the sheet data,
which 12B did not touch. Verified: `parse("zzz random gobbledygook 999").reg_partial
== "999"` — the parser (unchanged) treats the trailing digits as a partial plate;
12B only added inventory *fields* + a spec library, none of which affect parsing or
retrieval status.

## Backward-compatibility verdict

- Every pre-existing test that was green stays green; **12B introduced zero new
  failures**.
- The expanded `InventoryItem`, header-located new columns, and `model_specs`
  auto-fill are fully additive.
- The live `IVR_Sheet.xlsx` was not modified by 12B.

## Suggested follow-ups (outside 12B scope)
- The two stale tests will clear naturally in the pending **cleanup** step (remove
  test cars `MH99ZZ9999`/`TEST0001`, reset counts) or by updating the two test
  expectations to reflect the current data + the partial-plate feature.
