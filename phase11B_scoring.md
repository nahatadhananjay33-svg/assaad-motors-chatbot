# Phase 11B — Intent Scoring Engine (STEP 2 / 3 / 8)

Module: `app/inventory_system/intent_intelligence.py`. Pure, deterministic,
read-only. No LLM, no ML, no probabilities — integer/rational arithmetic over
fixed vocabularies.

## From "keyword → intent" to "intent → score"

Before 11B the system was effectively `keyword found → intent`. 11B adds a
deterministic confidence **score** per candidate intent, e.g. for `"RC?"`:

```
rc          0.90
insurance   0.00
owner       0.00
price       0.00
```

`analyze(message)` returns an `IntentAnalysis` with `scores` (all candidates),
`primary`, `confidence`, `band`, `recommendation`, `multi_intents`, `related`,
`numbers`, `typos`, and `conflicts`.

## Intent families (STEP 8)

Each canonical intent is defined as a **family** with tiered vocabularies, so
maintenance is a matter of adding a phrase to the right tier rather than editing
scattered parser code. Tiers and their base scores:

| Tier | Base | Meaning | Example (rc) |
|---|---|---|---|
| `strong` | 0.97 | specific, unambiguous multi-word phrase | "rc transfer status", "loan closed" |
| `exact` | 0.90 | canonical field-name token | "rc", "registration", "noc" |
| `synonym` | 0.82 | alias / other-language equivalent | "kagzat", "आरसी" |
| `weak` | 0.55 | broad, needs context | "papers", "docs" |
| `vague` | 0.30 | very ambiguous | (reserved) |

19 families ship today: rc, insurance, ownership, km, condition, color, fuel,
transmission, seats, price, budget, finance, warranty, service, photo, video,
instagram, youtube, availability.

## Scoring formula (deterministic)

For each family the best matching tier is found (checked strong→exact→synonym→
weak→vague, highest first), then:

```
score = tier_base
      + 0.02  if the matched phrase is multi-word     (specificity)
      + 0.01  if the matched phrase length >= 8        (specificity)
      (capped at 0.99)
```

A **typo-corrected** match (STEP 7) contributes `0.90 − 0.15 × edit_distance`
(min 0.50) — always ranked below a clean exact match, so the layer prefers real
matches and treats corrections as lower-confidence evidence.

`primary = argmax(scores)`; `confidence = scores[primary]`.

## Confidence thresholds (STEP 3)

```
confidence >= 0.80          -> band HIGH   -> recommendation "answer"
0.45 <= confidence < 0.80   -> band MEDIUM -> recommendation "clarify"
confidence <  0.45          -> band LOW    -> recommendation "ask"
a detected CONFLICT          -> band MEDIUM -> recommendation "clarify"  (overrides)
```

Reproduces the spec's examples exactly:

| Query | primary | confidence | band | action |
|---|---|---|---|---|
| `RC?` | rc | 0.90 | high | answer |
| `Paper?` | rc | 0.55 | medium | clarify |
| `Clear?` | — | 0.00 | low | ask |
| `insurence` (typo) | insurance | 0.90 | high | answer |
| `petrol diesel` | fuel | 0.90 → **conflict** | medium | clarify |

The bot **never fabricates**: low confidence asks, medium clarifies, only high
answers — and even a high-confidence answer that touches an empty spreadsheet
column renders "Data not available" (11A no-fabrication guardrails preserved).

## Validation

2,210 scoring assertions (every strong/exact family term × 10 neutral question
frames) resolve to the correct family in the HIGH band — **100 %**. See
`phase11B_validation.md`.
