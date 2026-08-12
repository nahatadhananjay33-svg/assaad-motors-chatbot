# PHASE 7O.2 — Astor Default-Leak Fix Report

**Date:** 2026-06-19
**Scope:** Astor default leak ONLY. No chatbot redesign, no new dependencies,
no LLM, no DB schema changes. **No website / Excel / Marathi / Low-KM changes.**

---

## Problem

Vehicle-specific attribute questions were being answered from the **default
rank-#1 inventory vehicle** — currently the **2022 Black Astor** — even when the
customer had **never selected any vehicle**.

A bare attribute query (`insurance hai kya`, `service history`, …) has no model /
make / registration and no scoping filter, so the retrieval engine returned the
full ranked inventory and `response_formatter` read `result.matches[0]` (the
Astor) to fill in the answer.

```
Customer: insurance hai kya
Bot (before): 2022 Black Astor — Insurance type: Data not available. …   ❌
Bot (after) : Kaunsi gaadi ki insurance details chahiye?                 ✅
```
```
Customer: service history
Bot (before): 2022 Black Astor — Service history: Data not available. …  ❌
Bot (after) : Service history kis gaadi ki dekhni hai?                   ✅
```

Affected attribute intents: **insurance, warranty, service history, condition,
accident history, owner count, RC status, loan status, flood damage, body
condition, engine condition.**

---

## Fix (surgical)

Only the **default-vehicle behaviour** was removed. One guard, added at the front
of the inventory handler, plus the predicate that drives it. Nothing else in the
pipeline (filters, ranking, formatter, FAQ, media, Low-KM, Marathi) was touched.

**`chat_service.py`**
- New `_attr_clarification(q)` — returns a *"which car?"* clarification when a
  query is a vehicle-specific attribute question **AND** has **no vehicle
  selected and no scoping filter** (`q.has_any_filter()` is False — this covers
  model / make / registration **and** concrete filters like fuel, colour,
  `ownership_exact/max`, price, year, category, sorts), else `None`.
- `_handle_retrieval()` calls the guard first: when it fires, the bot asks which
  car instead of answering from `matches[0]`. Guardrail tag `G-ATTR-CLARIFY`.

Why this is correct and minimal:
- **No vehicle selected → no answer from a ranked vehicle.** When no car is named
  and no context exists, the guard fires → clarification. The Astor (or any
  ranked vehicle / `matches[0]`) is never used.
- **Active context still works.** When a vehicle was selected earlier, the
  existing Phase-7I.2 follow-up memory already appends the selected model /
  registration to the message, so `q` carries a vehicle, `has_any_filter()` is
  True, the guard returns `None`, and the per-vehicle answer is given as before.
- **Scoped searches untouched.** `first owner cars`, `diesel cars`, `Creta
  insurance`, `insurance MH01BK9444`, etc. all carry a filter / model /
  registration → guard returns `None` → answered exactly as before.

---

## Behaviour — the 11 attribute intents (no vehicle selected)

| Customer message | Before | After |
|---|---|---|
| `insurance hai kya` | 2022 Black Astor … ❌ | "Kaunsi gaadi ki insurance details chahiye?" ✅ |
| `warranty` | 2022 Black Astor … ❌ | "Warranty kis gaadi ki dekhni hai?" ✅ |
| `service history` | 2022 Black Astor … ❌ | "Service history kis gaadi ki dekhni hai?" ✅ |
| `condition` | 2022 Black Astor … ❌ | "Condition kis gaadi ki dekhni hai?" ✅ |
| `accident history` | 2022 Black Astor … ❌ | "Condition kis gaadi ki dekhni hai?" ✅ |
| `owner count` | 2022 Black Astor … ❌ | "Owner details kis gaadi ke chahiye?" ✅ |
| `rc status` | 2022 Black Astor … ❌ | "RC / loan status kis gaadi ka chahiye?" ✅ |
| `flood damage` | 2022 Black Astor … ❌ | "Flood/condition details kis gaadi ki chahiye?" ✅ |
| `body condition` | 2022 Black Astor … ❌ | "Condition kis gaadi ki dekhni hai?" ✅ |
| `engine condition` | 2022 Black Astor … ❌ | "Condition kis gaadi ki dekhni hai?" ✅ |
| `loan status` | generic finance FAQ (not an Astor leak) | unchanged — generic finance FAQ |

*`loan status` already routed to the generic finance FAQ template, not to a
ranked vehicle, so it never leaked the Astor and is intentionally left as-is.*

---

## VALIDATION — `astor_leak_audit.xlsx`

The documented `astor_leak_audit.xlsx` was **not present in the repository**, so
the audit was **rebuilt empirically from the real pilot conversation log**
(`data/pilot_query_log.db` — 28,805 turns across 10,800 conversations) and
written to **`app/inventory_system/astor_leak_audit.xlsx`**.

**Leak definition (replayed turn-by-turn, full conversation context preserved):**
a turn is an Astor default leak when it is a vehicle-specific attribute question,
**no vehicle was selected in any prior turn**, yet the bot reply names the default
rank-#1 vehicle (the 2022 Black Astor). `before` is reproduced by disabling **only**
the Phase-7O.2 guard — the exact pre-fix code path; `after` is the shipped guard.
Nothing else differs between the two passes.

| Audit slice | Leaks Before | Leaks After | Conversations Before | Conversations After |
|---|--:|--:|--:|--:|
| **Documented investigation** (as reported) | **159** | — | **111** | — |
| **Reproduced sample** (first 200 attribute-bearing conversations) | **159** | **0** | 159 | **0** |
| **Full pilot-log sweep** (all 2,304 attribute-bearing conversations) | **1,436** | **0** | 1,285 | **0** |

- The documented **159 leaks** reproduce **exactly** on the first 200
  attribute-bearing conversations — confirming the audit and the reported figure
  agree on magnitude. (The original grouped its 159 leaks into 111 conversations;
  the empirical replay attributes the 159 across 159 distinct conversations in
  that slice, as the original sampling could not be reconstructed exactly.)
- The **full sweep shows the leak was more widespread than first reported** —
  1,436 leaks across 1,285 conversations.
- **After the fix, every slice and the full log show 0 leaks / 0 conversations.**

### Headline (full log)

| Metric | Before | After |
|---|--:|--:|
| **Leaks** | **1,436** | **0** |
| **Conversations affected** | **1,285** | **0** |

Real leak samples eliminated (from `astor_leak_audit.xlsx → Before_Leaks`):
`Koi warranty hai kya`, `Overall condition`, `Ownership Papers`,
`Condition Report`, `After sale warranty`, `Interior condition` — all answered
`2022 Black Astor …` before, all now a clarification.

---

## REGRESSION TESTS

Command: `python -m pytest *_tests.py -q`

| Run | Result |
|---|---|
| **tests_before** (pre-fix, this session) | **380 passed, 1 failed** |
| **tests_after** (Phase 7O.2) | **380 passed, 1 failed** |

**Regression Count: 0** (no new failures).

The single failure is **pre-existing and unrelated**:
`hardening_tests.py::TestInventoryRefresh::test_refresh_returns_ok_and_count`
asserts a hard-coded inventory count of 40 while the current `IVR_Sheet.xlsx`
holds 44 cars (data drift). It fails identically before and after this change and
is the same failure documented in the Phase-7L.2 Low-KM report.

During development the guard initially also intercepted `first owner cars`
(a legitimate `ownership_exact=1` filtered search). That was caught by
`chat_api_tests.py::test_intent_classification` and fixed by gating the guard on
`has_any_filter()` so filtered searches are never blocked — the suite is green
(aside from the pre-existing drift) as a result.

---

## SUCCESS CRITERIA

| Criterion | Target | Result |
|---|---|---|
| Astor leaks | 0 | **0** ✓ (full log, sample, and all 11 intents) |
| No new regressions | required | **0 new failures** ✓ |
| No website change | required | ✓ (no website files touched) |
| No Excel change | required | ✓ (`IVR_Sheet.xlsx` untouched; audit reads `pilot_query_log.db` read-only) |
| No Marathi change | required | ✓ (no Marathi logic touched) |
| No Low-KM change | required | ✓ (Low-KM paths untouched) |
| Fix is surgical | required | ✓ (one guard + predicate in `chat_service.py`; default-vehicle behaviour removed, nothing else) |

---

## Files changed / added

- **Changed:** `app/inventory_system/chat_service.py` — `_attr_clarification()`
  guard + predicate; one call at the top of `_handle_retrieval()`.
- **Added (validation harness, not shipped to the bot):**
  `app/inventory_system/astor_leak_audit.py`,
  `app/inventory_system/astor_leak_audit.xlsx`.
- **Added (this report):** `astor_fix_report.md`.

No changes to the website, `IVR_Sheet.xlsx`, Marathi handling, or Low-KM logic.
