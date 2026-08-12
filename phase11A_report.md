# Phase 11A — Universal Inventory Intent Engine (Report)

## Objective

Make the chatbot **deterministically** understand a question about *any* inventory
field, phrased however a real Mumbai dealership customer would — in English,
Hindi, Hinglish or Marathi, short or long, spoken, misspelled — and answer with
the correct value from that field. **No LLM. No redesign. No retrieval / ranking /
memory / follow-up rewrite.** Only inventory-field intent recognition was improved,
reusing the existing parser → router → formatter architecture.

## Outcome

| Metric | Before | After |
|---|---|---|
| Example-phrase coverage (parser) | 62 % (70/112) | 98 % (110/112)* |
| Per-field test coverage (1,982 utterances, ≥50/field) | — | **100 %** |
| End-to-end pinned + cold behaviour | partial | **verified** |
| Regression (`*_tests.py`) | 464 pass / 5 pre-existing fail | **481 pass / same 5** |
| Parse latency | ~300 ms | **~1.5 ms** (≈200×) |

*the two residual parser cases are a malformed test string and `Final?` (handled
at the follow-up layer) — both resolve correctly in practice; end-to-end is 100 %.

## What changed (files)

- **`query_parser.py`** — the intent engine. Added attribute-**question** intents
  `color_query / fuel_query / transmission_query / seats_query` (distinct from the
  same-named *filter* fields); broadened RC/documents/transfer/fitness/NOC, KM/
  odometer, condition (touch-up/denting), insurance (claim/NCB), warranty
  (guarantee), finance (kist/installment), and bare English budget ("below 8");
  added the singular "kitna" price word. Moved "papers" from insurance → documents.
  **Perf:** cached compiled patterns (`_has_pattern`) and `_norm`.
- **`media_lookup.py`** — YouTube "shorts / yt shorts / youtube shorts".
- **`response_formatter.py`** — new answer branches for colour / fuel /
  transmission / seats questions on the pinned car (no fabrication).
- **`faq_router.py`** — routes the new attribute questions to inventory so the
  formatter (or the "which car?" clarifier) handles them instead of FAQ/unknown.
- **`chat_service.py`** — new attribute intents added to the follow-up-reuse set,
  the "which car?" clarifier set (STEP 6), and `Final?` to the price follow-up.
- **`phase11a_intent_tests.py`** *(new)* — 1,982-utterance field coverage suite.

## How it works (STEP 4 — deterministic, no LLM)

1. **Normalization / typo-folding** (`normalize_typos`, `_norm`) — lowercasing,
   Devanagari-safe stripping, phonetic spellings.
2. **Field-alias mapping** — per-field vocabularies matched with word-boundary
   regex (`_has`), longest-phrase-first for models.
3. **Value vs question disambiguation** — a *value* ("white", "petrol", "7 seater")
   is a filter/browse; a bare field *question* ("kaunsa rang?", "fuel?", "how many
   seats") sets an attribute-query flag only when no value resolved. "petrol ya
   diesel" / "manual ya automatic" are recognised as questions and clear the
   spurious filter.
4. **Precedence** — media > RC > insurance > service > warranty > ownership > km >
   condition > downpayment > attribute questions > filters > budget > price.

## Behaviour guarantees

- **Pinned car + field intent → that car's value** (STEP 5). Empty column →
  "Data not available" / "visit pe confirm" — never fabricated.
- **No car pinned + attribute question → one crisp clarification** (STEP 6), e.g.
  "Kis gaadi ka colour poochh rahe hain?" — never a wrong default-rank answer.

## Constraints honoured

No LLM · no chatbot/retrieval rewrite · no prompt engineering · reused the existing
architecture · only genuine intent-recognition weaknesses fixed · memory, browse,
variant, follow-up, budget, search, media, owner and inventory paths all still pass.

## Deliverables

- `phase11A_intent_audit.md` — before/after coverage audit (STEP 1 + 3)
- `phase11A_intent_dictionary.md` — full per-field alias dictionary (STEP 2)
- `phase11A_validation.md` — 50-per-field tests, e2e, regression (STEP 7 + 8)
- `phase11A_report.md` — this summary (STEP 9)
- `app/inventory_system/phase11a_intent_tests.py` — executable field suite
