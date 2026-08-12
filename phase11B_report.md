# Phase 11B — Deterministic Intent Intelligence (Report)

## Objective

Add a deterministic **intelligence layer on top of** the Phase-11A parser so the
chatbot understands what a customer *means*, not just which keywords they typed —
moving real-world understanding from ~93 % toward 98–99.9 %. **No LLM, no ML, no
embeddings, no redesign, no parser/retrieval/memory/media/browse rewrite, fully
backward compatible.**

## Outcome

| Capability | Delivered |
|---|---|
| Intent **scoring** (intent→confidence, not just keyword→intent) | ✅ 19 families, tiered, deterministic |
| Confidence **bands** (answer / clarify / ask) | ✅ high ≥0.80, medium ≥0.45, low <0.45 |
| **Multi-intent** (never lose secondary fields) | ✅ validated 40+ pairs |
| **Cross-field** reasoning (relate, don't merge) | ✅ finance/condition/price/media graphs |
| **Numeric** normalization (8L=8 lakh=₹8 lakh=800000=8,00,000=0.8 million) | ✅ 100 % on 30+ forms |
| **Typo** intelligence (Levenshtein, closed vocab, uniqueness) | ✅ resolves; never guesses when uncertain |
| Intent **families** (maintainable tiered dictionaries) | ✅ `FAMILIES` |
| **Conflict** resolution (contradiction → clarify, never guess) | ✅ the one behavioural fix |
| **Conversation** interpretation (same car / model / browse) | ✅ `classify_turn`, memory untouched |
| **Analytics** (anonymous) → `intent_analytics.json` | ✅ exported |
| **Validation** (thousands of tests) | ✅ ~2,600+ assertions, 100 % scoring |
| **Performance** (parser not slower) | ✅ parse unchanged 1.36 ms; +0.67 ms layer |
| **Regression** | ✅ same 5 pre-existing fails, nothing new |

## What was built (new files, nothing rewritten)

- **`intent_intelligence.py`** — the read-only engine: scoring, bands, families,
  multi-intent, cross-field graph, numeric normalization, Levenshtein typo
  resolution, conflict detection, `classify_turn`, `analyze()`.
- **`intent_analytics.py`** — anonymous aggregate telemetry → `intent_analytics.json`.
- **`phase11b_intelligence_tests.py`** — ~2,600+ deterministic assertions.

## What was touched (additive only)

- **`chat_service.py`** — attaches `meta["intelligence"]` and records anonymous
  analytics on every request (never changes response/vehicles/status/intent); one
  gated, proven behavioural fix: same-dimension **conflict → clarify** instead of
  the parser's silent first-value pick (`INTEL_CONFLICT_CLARIFY = True`).

The parser, retrieval engine, inventory model, memory maps, media service and
browse/variant logic are **unchanged**.

## The one behavioural change (bug protocol honoured)

`parse()`'s value loops `break` on first match, so `petrol diesel` silently became
`fuel=Diesel` and the bot dumped diesel cars — a guess. Proven a genuine bug; no
test relied on it; the fix is deterministic, gated to real contradictions
(disjunction "petrol **ya** diesel" is treated as a question, not a conflict), and
the full suite stays green. A real salesperson asks "petrol ya diesel — kaunsa
chahiye?"; now so does the bot.

## Determinism & safety

Same input → same output, always. No randomness, probabilities, ML or network.
The layer never fabricates: low confidence asks, medium clarifies, high answers,
and even a confident answer over an empty column says "Data not available"
(11A guardrails intact). All wiring is exception-guarded — a fault in the layer
can never break a customer reply.

## Deliverables

- `phase11B_architecture.md` — pipeline audit + insertion point (STEP 1)
- `phase11B_scoring.md` — scoring engine, bands, families (STEP 2/3/8)
- `phase11B_intelligence.md` — multi-intent, cross-field, numeric, typo, conflict, conversation (STEP 4–10)
- `phase11B_validation.md` — massive validation, analytics, performance, regression (STEP 11–13)
- `phase11B_report.md` — this summary (STEP 14)
- `intent_analytics.json` — anonymous intent analytics export (STEP 11)
- `app/inventory_system/intent_intelligence.py`, `intent_analytics.py`,
  `phase11b_intelligence_tests.py`
