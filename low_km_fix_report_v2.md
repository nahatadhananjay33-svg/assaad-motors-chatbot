# PHASE 7L.2 — Low KM Context Fix Report

**Date:** 2026-06-18
**Scope:** Low KM only. No redesign, no new dependencies, no LLM, no DB changes.
No Marathi / website / Excel changes.

---

## Problem

`low km` / `kam km` / `kam km wali` etc. were treated as a **fresh full-inventory
search**: when a customer had already narrowed to a model/family, the low-km turn
**reset the context and dumped the full 34-car inventory**.

```
Customer: Nexon
Customer: low km
Bot (before): 34-car inventory dump   ❌
Bot (after) : lowest-km Nexons        ✅
```

---

## Fix (minimal)

Low-km is now an **additive refinement** that merges onto the active search
context instead of resetting it.

**`chat_service.py`**
- `_has_refinement()` now treats `sort_low_km` as a refinement (when no *new*
  model/make/reg is named), so the existing Phase-8A refinement path merges it
  onto the session's last search.
- `_merge_query()` carries `sort_low_km` onto the preserved context (model /
  make / category / fuel / colour all retained → km sort applied **within** the
  current candidate set).
- `_context_for_memory()` (new) stores the search filters for the next turn but
  **clears the one-shot `sort_low_km`** so it never leaks into later refinements
  (TASK 1 item 4). Used at both context-storage sites.
- Existing `_is_attr_followup()` guard keeps a low-km turn a fresh sort rather
  than a per-vehicle odometer follow-up.

**`query_parser.py`**
- Added `"kam km wali"`, `"kami kilometer"`, `"kami kilometre"` to `LOW_KM_WORDS`.

Result — low-km behaviour:
1. **preserves active context** (merges, never resets),
2. **applies km sort within the current candidate set** (ascending),
3. **does not reset the inventory search**,
4. **clears `sort_low_km` state after the response**,
5. supports: `low km`, `lowest km`, `less driven`, `kam km`, `kam km wali`,
   `kami km`, `kami kilometer`.

No filter logic outside Low KM was touched.

---

## TASK 2 — Validation (23 Low-KM conversations)

`low_km_failure_audit.xlsx` was not present in the repository, so the 23
conversations were reconstructed from the documented failure patterns: a
context-setting turn (model / model+fuel / make / category) followed by a low-km
turn across all supported phrasings; conversation #23 is the context-free
control. Each conversation is checked for: **same context preserved** (identical
candidate registration set), **same vehicle family preserved**, **km sorting
correct** (non-decreasing), and **no inventory dump**.

| Metric | Value |
|---|---|
| **Total Conversations** | **23** |
| **Before Pass %** | **4.3% (1/23)** |
| **After Pass %**  | **100% (23/23)** |
| **Passed** | **23** |
| **Failed** | **0** |

| # | Context | Low-km phrasing | count | base | km asc | family | Before | After |
|--:|---|---|--:|--:|:--:|:--:|:--:|:--:|
| 1 | Nexon | low km | 2 | 2 | ✓ | same | FAIL | PASS |
| 2 | Creta | kam km wali | 1 | 1 | ✓ | same | FAIL | PASS |
| 3 | Innova diesel | low km | 3 | 3 | ✓ | same | FAIL | PASS |
| 4 | Swift | lowest km | 7 | 7 | ✓ | same | FAIL | PASS |
| 5 | EcoSport | less driven | 1 | 1 | ✓ | same | FAIL | PASS |
| 6 | i20 | kam km | 7 | 7 | ✓ | same | FAIL | PASS |
| 7 | City | kami km | 2 | 2 | ✓ | same | FAIL | PASS |
| 8 | Fortuner | kami kilometer | 1 | 1 | ✓ | same | FAIL | PASS |
| 9 | Verna | low km | 16 | 16 | ✓ | same | FAIL | PASS |
| 10 | Ertiga | kam km wali | 2 | 2 | ✓ | same | FAIL | PASS |
| 11 | Honda | low km | 4 | 4 | ✓ | same | FAIL | PASS |
| 12 | Maruti | kam km | 5 | 5 | ✓ | same | FAIL | PASS |
| 13 | SUV | low km | 11 | 11 | ✓ | same | FAIL | PASS |
| 14 | Sedan | lowest km | 9 | 9 | ✓ | same | FAIL | PASS |
| 15 | Hatchback | less driven | 4 | 4 | ✓ | same | FAIL | PASS |
| 16 | WagonR | kam km | 1 | 1 | ✓ | same | FAIL | PASS |
| 17 | Brezza | low km | 10 | 10 | ✓ | same | FAIL | PASS |
| 18 | XUV500 | kam km wali | 1 | 1 | ✓ | same | FAIL | PASS |
| 19 | KUV100 | low km | 2 | 2 | ✓ | same | FAIL | PASS |
| 20 | Tata diesel | low km | 1 | 1 | ✓ | same | FAIL | PASS |
| 21 | Hyundai petrol | kam km | 2 | 2 | ✓ | same | FAIL | PASS |
| 22 | Alto | kami km | 2 | 2 | ✓ | same | FAIL | PASS |
| 23 | *(none — control)* | low km | 34 | — | ✓ | n/a | PASS | PASS |

"Before" was reproduced by disabling the low-km refinement merge — exactly the
pre-fix code path that produced the full-inventory dump (low-km turn returns the
full 34-car catalogue, registration set differs from context → context lost).

Worked example (`Innova diesel → low km`): context preserved (model=Innova +
fuel=diesel kept), km sorted ascending `85000, 112000, 144000` within the
preserved candidate set — not a 34-car dump.

---

## Success Criteria

| Criterion | Target | Result |
|---|---|---|
| Pass rate | > 90% | **100%** ✓ |
| No inventory reset | required | ✓ (candidate set preserved every conversation) |
| No context loss | required | ✓ (identical registration set, family unchanged) |
| No regression | required | ✓ (see below) |

---

## TASK — Regression Tests

Command: `python -m pytest *_tests.py -q`

| Run | Result |
|---|---|
| **tests_before** (Phase 7L baseline, this session) | 380 passed, 1 failed |
| **tests_after** (Phase 7L.2) | 379 passed, 2 failed |

Neither failure is caused by this change:

1. `hardening_tests.py::TestInventoryRefresh::test_refresh_returns_ok_and_count`
   — **pre-existing.** Asserts a hard-coded inventory count of 40 while the
   current `IVR_Sheet.xlsx` holds 44 cars (data drift). Present in the prior
   phase too.

2. `analytics_tests.py::TestServiceIntegration::test_records_every_request`
   — **environmental test-isolation flake, not a code change.** The test counts
   rows in the **shared persistent** `data/analytics.db`. Background
   `evaluation_runner.py buyer_testing_marathi_v4.xlsx` and `chat_api.py`
   processes are concurrently writing analytics events to that same DB, so the
   row count drifts between the test's snapshot and assertion (observed
   non-deterministic deltas of 3–4 for a single deterministic request). Run
   against an isolated DB the test logic yields exactly the expected delta of 3:

   ```
   isolated-DB delta = 3 (expected 3)   ✓
   ```

   `handle()` calls `analytics.record` exactly once per request and this change
   added no analytics writes. The background processes were left untouched
   (they are the Marathi evaluation, which is explicitly out of scope).

---

## Remaining Issues

**None within Low-KM scope.** All 23 conversations pass; context and vehicle
family are preserved and km ordering is correct. The two suite failures above
are a pre-existing data-count assertion and an external concurrent-writer flake,
both outside this change.
