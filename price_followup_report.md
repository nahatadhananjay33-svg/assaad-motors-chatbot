# PHASE 7O.4 — Price Follow-up Accuracy Report

**Date:** 2026-06-19
**Scope:** Price follow-up accuracy ONLY. No LLM, no new dependencies, no DB /
schema changes. **No change to the Astor fix, Photo/Video fix, Marathi logic,
Low-KM logic, website, Excel, or inventory loader.**

---

## Goal

A price follow-up question must always answer for the **currently selected
vehicle** — never clarify when a vehicle is in context, and never dump the
catalogue.

```
Customer: Sonet hai?      Bot: 2 Sonet available hain.
Customer: Price?          Bot: 2021 Black Sonet ₹6.99 lakh.     ✅
```
```
Customer: Nexon
Customer: Kitne ka hai?    Bot: 2022 White Nexon ₹6.89 lakh.     ✅
```
(Before: a multi-car model → "2 options hain… Konsi dekhni?"; no context →
entire-inventory dump.)

---

## Root cause (see `price_followup_summary.md`)

Bare price questions were routed to the generic inventory path without pinning a
single car:
- **Multi-car model context** → `response_formatter` G-MULTI clarification
  ("N options hain… Konsi dekhni?") — **367 unnecessary clarifications**.
- **No vehicle context** → unfiltered `engine.search` → **full-catalogue dump**
  (971 no-context + 91 with-context dumps).

Code path: `handle()` → `_handle_retrieval(q)` → `engine.search` →
`response_formatter` G-MULTI / full list.

---

## Fix (surgical)

All in `chat_service.py`. A new `_price_followup()` handler is invoked from
`_conversation_override()` for a bare price question
(`_is_price_followup`: a price word — `price` / `kitne ka` / `kimat` / `daam` /
`rate` / `cost` / `how much` … — with **no** new vehicle named and **no**
budget / cheapest / low-km filter), gated to `rr.kind in ("inventory",
"unknown")` so FAQ negotiation asks (`last price`, `discount` → `price_fixed`)
are left untouched:

- **Active vehicle context** → answer the price of the selected vehicle: the
  pinned car (registration) or the **top match of the context model**. Returns
  exactly one car (`G-PRICE-FOLLOWUP`). Never multi, never dump, never clarify.
- **No active vehicle** → a short clarification `"Kis gaadi ki price chahiye?"`
  (`G-PRICE-CLARIFY`). Never a dump.

A flag `PRICE_FOLLOWUP_PIN` (default **True**) gates the behaviour; the A/B
validation flips it to reproduce the pre-fix path. Budget / `sort_cheapest` /
`sort_low_km` queries are explicitly excluded from the guard (Low-KM untouched).

The four required cases:

| Case | Example | Result |
|---|---|---|
| Single vehicle selected | `Sonet hai?` → `Price?` | `2021 Black Sonet ₹6.99 lakh.` ✓ |
| Multi-car model selected | `Nexon` → `Kitne ka hai?` | `2022 White Nexon ₹6.89 lakh.` (top match, no clarify) ✓ |
| Vague price ask | `Nexon` → `How much for that?` | `2022 White Nexon ₹6.89 lakh.` ✓ |
| No vehicle selected | `Price?` / `How much for that?` | `Kis gaadi ki price chahiye?` (no dump) ✓ |

---

## STEP 4 — Validation

Replayed **1,985 real price-follow-up conversations** from the pilot log
(`data/pilot_query_log.db`) — far above the 200-conversation minimum — in order,
context preserved, A/B via `PRICE_FOLLOWUP_PIN` (nothing else differs). A PASS =
an active vehicle context exists and the bot answers exactly one selected
vehicle's price (`count == 1`, intent `price`). Read-only on the pilot log,
isolated temp DBs.

| Metric | Before | After |
|---|--:|--:|
| Price follow-ups with active context | 1,329 | 1,347 |
| Pass (answered selected vehicle's price) | 868 | 1,346 |
| Fail | 461 | 1 |
| **Pass rate** | **65.3%** | **99.9%** |
| **Inventory-dump cases (price questions)** | **1,062** | **0** |

- **Pass rate 65.3% → 99.9%** (> 95% target).
- **Inventory dumps eliminated: 1,062 → 0.**
- The single residual "fail" is an edge case where the context model has no
  current in-stock match, so the bot clarifies instead of quoting — still no
  dump, no wrong vehicle.

*(The After context-count differs slightly from Before — 1,347 vs 1,329 —
because pinning a single vehicle on one turn establishes context for a later
price turn in the same conversation that previously had none. Every such turn
passes.)*

---

## STEP 5 — Regression

Command: `python -m pytest *_tests.py -q`

| Run | Result |
|---|---|
| **tests_before** (post-7O.3 baseline, this session) | **380 passed, 1 failed** |
| **tests_after** (Phase 7O.4) | **380 passed, 1 failed** |

**No new regressions (0).** The single failure is the pre-existing
`hardening_tests.py::TestInventoryRefresh::test_refresh_returns_ok_and_count`
(hard-coded inventory count 40 vs current 44 — data drift), identical before and
after and documented in the 7L.2 / 7O.2 / 7O.3 reports.

---

## Success criteria

| Criterion | Result |
|---|---|
| Price follow-up accuracy > 95% | ✓ **99.9%** |
| No inventory dumps | ✓ **0** (was 1,062) |
| No new regressions | ✓ 0 new failures |
| No impact on Astor fix | ✓ (attribute-clarify path untouched) |
| No impact on Photo/Video fix | ✓ (media path untouched) |
| No impact on Marathi | ✓ (no Marathi logic changed) |
| No impact on Low-KM | ✓ (`sort_low_km` / budget excluded from the guard) |

---

## Outputs

- `price_followup_audit.xlsx` — STEP 1 audit (Summary / Pass / Fail / Lost
  Context / Inventory Dump / Root Cause).
- `price_followup_summary.md` — STEP 2 root cause.
- `price_followup_report.md` — this report (STEP 4).

## Files changed / added

- **Changed:** `app/inventory_system/chat_service.py` — `_is_price_followup`,
  `_price_line`, `_price_followup()` handler, the `PRICE_FOLLOWUP_PIN` flag, and
  one branch in `_conversation_override()`.
- **Added (validation harnesses, not shipped to the bot):**
  `app/inventory_system/price_followup_audit.py`,
  `app/inventory_system/price_followup_validate.py`,
  `app/inventory_system/price_followup_validate_result.json`.
