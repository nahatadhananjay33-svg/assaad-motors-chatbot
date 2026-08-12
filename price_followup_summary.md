# PHASE 7O.4 — STEP 2: Price Follow-up Root Cause

**Date:** 2026-06-19
**Audit source:** `data/pilot_query_log.db` (28,805 turns / 10,800 conversations).
The referenced `final_conversations_only.txt` and `review_batch_*_vFinal.txt` are
not present in the repo, so the pilot log was used as the available replay
dataset (same as the Phase-7O.2 / 7O.3 audits). Full breakdown in
**`price_followup_audit.xlsx`**.

A **price follow-up turn** = a bare price question that names NO new vehicle and
carries NO budget filter (matched on the bot's own `_PRICE_FOLLOWUP_WORDS`:
`price`, `price?`, `kitne ka`, `kimat`, `daam`, `rate`, `cost`, `cost kya hai`,
`kitne ki hai`, `price batao`, + Devanagari). Each was replayed in order with
conversation context preserved, through the current (pre-fix) `ChatService`.

---

## Findings (the 5 required questions)

| # | Question | Answer |
|---|---|--:|
| 1 | **Price follow-up failures** (active context existed but selected vehicle not answered) | **458** |
| 2 | **Context-loss failures** | **458** — of which **91** fully lost context (catalogue dump) + **367** kept the model but returned multiple cars (clarification) |
| 3 | **Inventory-dump cases** (price question → large catalogue slice) | **1,062** — **91** with context + **971** with no context |
| 4 | **Unnecessary clarifications** (context existed, bot re-asked / showed "multiple vehicles") | **367** |
| 5 | **Exact code path** | see below |

### Pass / fail headline (price follow-ups *with* active context)

| Metric | Value |
|---|--:|
| Price follow-ups with active context | 1,328 |
| Pass (answered selected vehicle's price) | 870 |
| Fail | 458 |
| **Pass rate (before fix)** | **65.5%** |

Separately, **1,164 bare price questions arrived with no vehicle context yet**;
**971 of those dumped the full catalogue** (the "BAD: Price? → entire inventory
dump" case), 193 clarified.

---

## Exact code path causing the failures

`chat_service.ChatService.handle()`:

1. A bare price question (`"Price?"`, `"kitne ka hai"`) is detected as a
   follow-up (`_is_attr_followup` → `_PRICE_FOLLOWUP_WORDS`), and Phase-7I.2
   appends the **session's context vehicle token** to the message.
2. `_followup_token()` returns the context **model** name when no single car is
   pinned (`_followup_ctx = {"reg": None, "model": <model>}`).
3. The message routes to inventory → `_handle_retrieval(q)` →
   `self.engine.search(q)` → `response_formatter.format_response(result)`.

The break is in steps 2–3:

- **Multiple-car model context → `G-MULTI`.** When the context model has more
  than one car in stock (e.g. KUV100×2, Nexon×2, City×2), `engine.search` returns
  all of them and `response_formatter` emits the **G-MULTI** "N options hain …
  Konsi dekhni?" clarification instead of a single price. → **367 unnecessary
  clarifications** (`response_formatter.py` multi-match branch).
- **No vehicle context → full-catalogue dump.** When `_followup_token()` returns
  `None` (no car ever selected), the price question runs as an **unfiltered**
  inventory search → `engine.search` returns the whole catalogue → the response
  lists the top of all 34 cars. → **971 no-context dumps + 91 with-context
  dumps** (`chat_service._handle_retrieval` → unfiltered `engine.search`).

In short: **the price follow-up never pins a single vehicle** — it hands a
model-or-empty query to the generic retrieval path, which then either clarifies
(multi) or dumps (empty).

---

## Fix direction (implemented in STEP 3)

Surgical, gated on `rr.kind == "inventory"` (so FAQ negotiation questions —
`last price`, `discount`, `best price` → `price_fixed` — are untouched):

- **Active context exists** → answer the price of the **selected vehicle**:
  resolve the pinned car (registration) or the **top match of the context
  model**, and return exactly that one car's price. Never multi, never dump,
  never clarify.
- **No context** → a short clarification (`"Kis gaadi ki price chahiye?"`),
  never a catalogue dump.

This targets the 458 context failures (→ pass) and removes the 1,062 price-driven
inventory dumps, without touching the Astor fix, Photo/Video fix, Marathi, or
Low-KM (budget/`sort_cheapest` queries are explicitly excluded from the guard).
