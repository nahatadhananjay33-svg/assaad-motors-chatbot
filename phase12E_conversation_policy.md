# Phase 12E — Deterministic Conversation Policy

A thin, READ-ONLY labelling layer (`conversation_policy.py`) on top of the existing
Phase 11A/11B/12D engine. It decides WHICH conversation mode a turn is, from
signals the parser already produced, so the behaviour can be observed (meta) and
tested. **No LLM, no redesign, no routing/retrieval/memory changes.** The actual
behaviour for each mode was already implemented in earlier phases — 12E names it,
verifies it, and exposes it as `meta["conversation_mode"]`.

## STEP 1 — Audit (existing behaviour reused, unchanged)
| Behaviour | Where it already lives |
|---|---|
| Pinned-car answers | 11A/7D flags + 12D `attr_fields` → `response_formatter` |
| Same-model variant vs fresh browse | `chat_service._conversation_override` (7L/11C) |
| Follow-up memory | `_followup_ctx` (Phase 7I.2) |
| Multi-intent | 12D `attr_fields` list |
| Conflict → clarify | 11B `INTEL_CONFLICT_CLARIFY` |
| No-pin clarify | `_attr_clarification` (11A/12D) |
| FAQ / off-sheet | `faq_router` / `response_formatter` |

## STEP 2 — The seven modes
| Mode | Meaning | Deterministic signal |
|---|---|---|
| `current_car` | attribute question about the pinned car | 1 attribute intent + a pinned ctx |
| `same_model_variant` | another version of the pinned model | variant field (colour/fuel/trans/owner/low-km) + pin, no browse field |
| `new_search` | a different model / class / budget / filter | model/make/category/seats/km/price/year/feature-filter/registration |
| `multi_intent` | two+ attributes at once | ≥2 attribute intents |
| `clarify` | not enough info, or a same-dimension conflict | attribute intent + no pin, OR `detect_conflicts()` |
| `faq` | finance / negotiation / location / visit / … | router verdict = faq |
| `offsheet_unknown` | off-sheet topic or unknown; never fabricate | `q.off_sheet` or router = unknown |

Precedence: conflict → faq → off-sheet/unknown → multi-intent → new-search →
same-model-variant → current-car → clarify.

## STEP 3 — Current-car behaviour
With a pinned car, `insurance? / sunroof? / airbags? / boot space? / RC? / owners?
/ km? / music system?` all answer **about that car** (no fresh search). Verified.

## STEP 4 — Same-model variant
`automatic wali? / petrol wali? / kam km wali? / first owner wali? / white wali?`
stay within the pinned model (existing `_conversation_override`). If none match,
retrieval returns 0 and the formatter offers other options. A pure fuel/
transmission/low-km refinement (e.g. "diesel automatic", "lowest km car") is also
treated as same-model — the established engine behaviour.

## STEP 5 — Fresh search
A different **class** of requirement (`7 seater / SUV under 8 lakh / Creta dikhao /
sunroof wali car / cars under 5 lakh`) triggers a fresh browse and is **not** stuck
on the previous car.

## STEP 6 — Multi-intent
`sunroof aur airbags hain? / boot space aur ground clearance? / airbags kitne aur
camera hai?` → all requested fields answered (12D `attr_fields` list); no secondary
intent lost.

## STEP 7 — Clarification
`sunroof? / RC? / price?` with **no** pinned car → "Sure — kis gaadi ke details
chahiye?". Never selects a random car.

## STEP 8 — Conflicts (reused 11B)
`petrol diesel / automatic manual / white black` → clarify. `petrol ya diesel?`
(disjunction) is a **question**, not a conflict — unchanged.

## STEP 9 — Follow-up memory (verified sequence)
```
Show me Ertiga     -> new_search       (Ertiga results)
automatic wali?    -> same_model_variant (Ertiga automatics)
petrol wali?       -> same_model_variant (narrows to one)
RC?                -> current_car        (that Ertiga)
7 seater chahiye   -> new_search         (fresh browse)
```
Context is retained for attribute/variant turns and intentionally replaced on a
new class of search.
