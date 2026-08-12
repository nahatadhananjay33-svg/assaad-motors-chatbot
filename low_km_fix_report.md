# PHASE 7L — Low KM + Inventory Fix Report

**Date:** 2026-06-18
**Scope:** Deterministic only. No redesign, no new dependencies, no LLM, no DB changes.

---

## Summary

Two deterministic gaps were fixed:

1. **Low-km / less-driven queries** were either mis-handled (treated as a *condition
   report* for one car and returned in the default "newest first" rank, **not** sorted
   by km) or fell through to `unknown` (`lowest km`, `less driven`).
2. **`inventory`** as a bare keyword fell through to `unknown` instead of showing the
   catalogue.

A new `sort_low_km` route now sorts the inventory by `km_driven` **ascending**, and all
five trigger phrasings reach it. `inventory`/`stock` now resolve to the catalogue.

---

## Pass Rate

| Metric | Value |
|---|---|
| **before_pass_rate** | **3 / 9 = 33.3%** |
| **after_pass_rate**  | **9 / 9 = 100%** |

---

## Queries Tested

| Query | Before | After |
|---|---|---|
| `low km car`         | ❌ inventory, condition path, **not km-sorted** (kms `20000, 45065, 39989, …`) | ✅ `low_km`, km asc `11284, 14000, 20000, 21000, 32706` |
| `lowest km car`      | ❌ `unknown` | ✅ `low_km`, km asc |
| `less driven car`    | ❌ `unknown` | ✅ `low_km`, km asc |
| `kam km wali gadi`   | ❌ inventory, condition path, not km-sorted | ✅ `low_km`, km asc |
| `kami km chi gadi`   | ❌ inventory, condition path, not km-sorted | ✅ `low_km`, km asc |
| `inventory`          | ❌ `unknown` | ✅ `catalogue` (44 cars) |
| `catalogue`          | ✅ `catalogue` | ✅ `catalogue` |
| `stock`              | ✅ inventory listing | ✅ `catalogue` |
| `all cars`           | ✅ `catalogue` | ✅ `catalogue` |

All five low-km phrasings (`low km`, `lowest km`, `less driven`, `kam km`, `kami km`)
now reach the **same** km-ascending retrieval route.

---

## Changes (minimal)

**`query_parser.py`**
- Added `Query.sort_low_km: bool` field; included it in `has_any_filter()` so the
  router treats it as a concrete inventory signal.
- Added `LOW_KM_WORDS` (English + broken-Hindi + Marathi) and detection that sets
  `sort_low_km` + intent `low_km`.
- Removed `low km` / `kam km` / `kami km` / `kam kilometer` from `CONDITION_WORDS`
  (they are a sort request, not a single-car condition report) and guarded condition
  detection with `if not q.sort_low_km`.

**`retrieval_engine.py`**
- Added `_low_km_key` (km ascending, unknown km sinks to bottom) and applied it in
  `search()` when `q.sort_low_km` is set.

**`chat_service.py`**
- `classify_intent` returns `"low_km"` for these queries.
- `_is_attr_followup` returns `False` for `sort_low_km` so a low-km ask is always a
  fresh inventory sort, never a per-vehicle odometer follow-up.
- Added `inventory`, `stock`, `full inventory`, `current inventory`, etc. to
  `_CATALOGUE_PHRASES`.

No LLM, no new dependency, no schema/DB change.

---

## Regression

Full suite: `python -m pytest *_tests.py -q`

```
1 failed, 380 passed in 90.61s
```

The single failure — `hardening_tests.py::TestInventoryRefresh::test_refresh_returns_ok_and_count`
(`AssertionError: 44 != 40`) — is **pre-existing and unrelated**: it asserts a hard-coded
inventory count of 40 while the current `IVR_Sheet.xlsx` workbook contains 44
customer-facing cars (data drift). It was the sole entry in the pre-existing pytest
`lastfailed` cache and is untouched by this change (no loader/count logic was modified).

### Edge cases verified (no regressions)

| Query | low_km | condition |
|---|---|---|
| `kitne km chali hai` (how many km) | False | **True** (odometer report preserved) |
| `kiti km chalali` (Marathi) | False | **True** |
| `Creta accident free?` | False | **True** |
| `car condition kya hai` | False | **True** |
| `low km swift` | **True** | False (sorts Swifts by km asc) |
| `lowest km creta` | **True** | False |
| `diesel suv under 8 lakh` | False | False (unchanged) |

## Remaining Failures

**None** among the targeted queries (9/9 pass). The one suite failure above is a
pre-existing data-count assertion, outside the scope of this fix.
