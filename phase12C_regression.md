# Phase 12C — Regression Report

Command: `python -m pytest *_tests.py` (full suite, includes new `phase12c_tests.py`).

## Result

```
521 passed, 2 failed  (148s)
```

- **521 passed** = Phase 12B's 515 + the **6 new Phase 12C tests**.
- **2 failed** — identical to the Phase 12B baseline; **12C added zero new failures.**

## The 2 remaining failures — pre-existing, NOT caused by 12C

| Test | Cause | 12C-related? |
|---|---|---|
| `hardening_tests::test_refresh_returns_ok_and_count` | asserts inventory count **40**; live sheet has 44. Stale expectation. | ❌ No |
| `media_api_tests::test_unknown_still_flagged` | `"…999"` parsed as a partial number-plate (Phase 11A feature) → `not_found` vs expected `unknown`. Already failing since Phase 11B. | ❌ No |

## Why 12C is regression-safe

12C's changes are almost entirely **non-code**:
- `vehicle_details.html` — new static page (not exercised by pytest).
- `inventory_admin.html` — one additive Details button (HTML only).
- `IVR_Sheet.xlsx` — 68 **empty** optional columns appended (header-located → the
  loader reads them as `None`; counts, values and media positions unchanged; backup
  taken).
- `inventory_edit.py` — **one additive line** exposing the raw column header in the
  discovered schema (extra dict key; no consumer breaks).

The two consecutive full runs confirm it:

| Run | Result |
|---|---|
| Before adding `phase12c_tests.py` (base suite vs migrated Excel + header line) | 515 passed, 2 failed |
| After adding `phase12c_tests.py` | **521 passed, 2 failed** |

Memory, browse, variant, follow-up, budget, search, media, owner, inventory,
intent (11A/11B) and schema (12B) suites all stay green.

## Follow-ups (outside 12C scope)
The two stale tests will clear in the pending cleanup step (remove test cars,
reset counts) or by updating the two outdated expectations.
