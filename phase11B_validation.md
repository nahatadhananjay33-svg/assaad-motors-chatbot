# Phase 11B — Validation & Performance (STEP 12 / 13)

No LLM. Every result is deterministic and reproducible.

## STEP 12 — Massive validation

Suite: `app/inventory_system/phase11b_intelligence_tests.py` (runs under the
normal `*_tests.py` sweep). **17 test methods, ~2,600+ generated assertions.**

```
pytest phase11b_intelligence_tests.py  ->  17 passed in ~6s
```

| Area | What is asserted | Result |
|---|---|---|
| Scoring / primary | every strong+exact family term × 10 question/voice frames → correct family, HIGH band | **2210/2210 = 100 %** |
| Confidence bands | high→answer, medium→clarify, low→ask examples | pass |
| Multi-intent | 10 field pairs × 4 orderings/connectors → both intents present | pass (40+) |
| Cross-field | finance→{loan,rc,emi}; condition→{accident,flood,km}; media→{video,…} | pass |
| Numeric formats | 30+ money forms fold to identical rupees; km/owner/seat/year; year≠rupees; km≠rupees | pass |
| Typo intelligence | 13 misspellings resolve to right family; ambiguous tokens NOT corrected | pass |
| Conflicts | 8 contradictions detected; 5 disjunction questions NOT flagged; singletons NOT flagged | pass |
| Languages | Devanagari (Hindi/Marathi) terms for 11 fields resolve | pass |
| Turn classification | new_vehicle / attribute_followup / same_model_variant / new_browse | pass |
| Determinism | `analyze(x) == analyze(x)` across a sample | pass |
| Backward compat | parser flags (fuel/transmission/color/seats/price) unchanged | pass |

Coverage spans every category the phase requested: English, Hindi, Hinglish,
Marathi, typos, short & long phrases, voice style, incomplete questions, mixed
language, multiple intents, contradictions, numeric formats, attribute questions,
filters, browse, memory-turn interpretation, variant and regression.

## STEP 12 — End-to-end behaviour (real `ChatService`)

| Ask | Reply |
|---|---|
| `petrol diesel` | Petrol ya Diesel — kaunsa fuel chahiye? *(clarify, was silent-pick)* |
| `automatic manual` | Automatic ya Manual — kaunsa chahiye? |
| `white black` | White ya Black — kaunsa colour chahiye? |
| `first owner second owner` | 1 owner ya 2 owner — kaunsa chahiye? |
| `petrol ya diesel` | (question, not conflict) → fuel answer / "which car?" |
| `automatic diesel` | combination browse (multi-field, unchanged) |
| `7 seater diesel` | family browse (multi-field, unchanged) |

Every response carries `meta["intelligence"]` = {primary, confidence, band,
recommendation, multi_intents, related, numbers, typos, conflicts, top_scores}.

## STEP 11 — Intent analytics

`intent_analytics.json` (repo root) — anonymous, aggregate only, generated from a
989-query corpus:

```
bands        : {high: 977, medium: 7, low: 5}
conflicts    : {fuel, transmission, color, ownership}
multi_intents: {"2": 28}
top_intents  : rc, condition, km, insurance, price, ownership, …
```

No session ids, names or phone numbers are stored; unknown/low-confidence phrases
are PII-masked and truncated. At runtime `chat_service` flushes the same snapshot
to `data/intent_analytics.json` every 100 requests and on shutdown.

## STEP 13 — Performance (parser latency must NOT regress)

Warm-cache benchmark over a 15-query mix (4,000 iterations):

| Path | Latency |
|---|---|
| **Parser `parse()`** (must not regress) | **1.36 ms/query** |
| Parser + intelligence `analyze()` | 2.03 ms/query |
| Intelligence overhead | **0.67 ms/query** |

The parser itself is untouched in 11B, so its latency is unchanged from Phase 11A
(and still ~200× faster than the pre-11A ~300 ms). The intelligence layer adds
<1 ms and reuses the already-computed `Query` (no re-parse in the live path).

## STEP 8 — Regression (nothing broken)

Full suite `python -m pytest *_tests.py`:

| Run | Result | Time |
|---|---|---|
| Before 11B (after 11A) | 481 passed, 5 failed | 99 s |
| After 11B (+ intelligence suite) | **498 passed, 5 failed** | ~110 s |

The **5 failures are the identical pre-existing test-car / stale-count cases**
(`MH99ZZ9999` fake Swift + expects-40 count) — none introduced by 11B. Memory,
browse, variant, follow-up, budget, search, media, owner and inventory paths all
remain green, and the parser's own filter/flag behaviour is unchanged.
