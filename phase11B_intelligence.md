# Phase 11B — Intelligence Capabilities (STEP 4 / 5 / 6 / 7 / 9 / 10)

All capabilities live in `intent_intelligence.py`, are deterministic, and are
surfaced additively via `chat_service` `meta["intelligence"]` + anonymous
analytics. Only ONE behavioural change ships (conflict → clarify, STEP 9).

---

## STEP 4 — Multi-intent detection

`multi_intents` lists every family scoring in the HIGH band, ordered by score, so
a secondary field is never lost.

| Query | multi_intents |
|---|---|
| `automatic diesel` | `[transmission, fuel]` |
| `7 seater diesel` | `[fuel, seats]` |
| `insurance owner` | `[insurance, ownership]` |
| `rc insurance` | `[insurance, rc]` |
| `service warranty` | `[service, warranty]` |
| `photos video` | `[photo, video]` |

Validated over 40+ pairs in both orders and with connectors ("aur", "and … dono").

## STEP 5 — Cross-field reasoning (relationships, NOT merging)

`related` surfaces fields that a salesperson associates with the asked field —
without merging them. Relationship graph (`CROSS_FIELD`):

```
finance   → loan → hypothecation → noc → rc → emi → budget → price
condition → accident → flood → touchup → paint → body → engine → km
price     → negotiable → budget → finance → emi
media     → photo → video → instagram → youtube
insurance → rc → claim → documents
warranty  ↔ service ↔ condition
km        → condition → service
```

Example: `analyze("finance").related` ⊇ {loan, hypothecation, noc, rc, emi,
budget, price}. This is understanding context, not changing what is answered.

## STEP 6 — Advanced numeric understanding

`normalize_amount()` folds every money format to the same integer rupees;
`normalize_numbers()` extracts price / km / owners / seats / year.

| Input | → rupees |
|---|---|
| `8L`, `8 l`, `8lac`, `8 lakh`, `₹8 lakh`, `rs 8 lakh`, `800000`, `8,00,000`, `0.8 million`, `8 lakhs` | **800000** |
| `12.5 lakh`, `12.5L`, `1250000`, `12,50,000` | **1250000** |
| `1 crore`, `1cr`, `1,00,00,000` | **10000000** |
| `50k`, `50 thousand` | **50000** |

Guards: a 4-digit **model year** (`2019`) is never read as ₹2019; a **km**
quantity (`20000 km`) is never read as rupees. 30+ format assertions pass 100 %.

## STEP 7 — Advanced typo intelligence (deterministic, no fuzzy AI)

Classic **Levenshtein** distance against a *closed* field vocabulary, with a fixed
threshold (1 for ≤6-char tokens, 2 otherwise) and a **uniqueness** rule: a token
is corrected only when a single nearest vocab word is strictly closer than the
next. Otherwise it is left alone → clarify (never a wrong guess).

Resolved: `insurence→insurance`, `transmision→transmission`,
`autometic→transmission`, `warenty/guarentee→warranty`, `registretion→rc`,
`documnts→rc`, `colourr→color`, `millage→km`, `serivce→service`. Ambiguous tokens
(`clear`, `thing`) are deliberately **not** corrected.

## STEP 9 — Conflict resolution

A same-dimension contradiction is detected when two distinct canonical values fill
one slot **without** a disjunction connector:

| Query | conflict | bot asks |
|---|---|---|
| `petrol diesel` | fuel | "Petrol ya Diesel — kaunsa fuel chahiye?" |
| `automatic manual` | transmission | "Automatic ya Manual — kaunsa chahiye?" |
| `white black` | color | "White ya Black — kaunsa colour chahiye?" |
| `first owner second owner` | ownership | "1 owner ya 2 owner — kaunsa chahiye?" |

A disjunction ("petrol **ya** diesel", "manual **or** automatic") is a *choice
question*, not a contradiction — those flow to the 11A `fuel_query` /
`transmission_query` answer path and are **never** flagged as conflicts.

**Proven-bug basis (per the phase's bug protocol):** `parse()`'s value loops
`break` on first match, so `petrol diesel` silently became `fuel=Diesel` and the
bot dumped diesel cars — guessing. No existing test relied on that silent pick
(verified). The fix is deterministic, gated to genuine conflicts, flows through
the normal reply tail, and the full suite stays green — so it is kept. It can be
disabled with `chat_service.INTEL_CONFLICT_CLARIFY = False`.

## STEP 10 — Conversation intelligence

`classify_turn(message, prev_ctx)` labels a turn deterministically **without
changing the memory architecture** — it mirrors the signals `chat_service`
already acts on, for meta/analytics:

| Turn (with a pinned Swift) | label |
|---|---|
| `Creta price` | new_vehicle |
| `RC?`, `owner?` | attribute_followup (same car) |
| `any blue one`, `automatic?` | same_model_variant |
| `7 seater`, `under 8 lakh` | new_browse |
| `aur`, `haan` | continuation |

This validates the spec's example (`Swift → Price? → Insurance? → Owner? → RC? →
Any blue one? → Automatic?`) is interpreted as the same car for attribute
questions and a fresh variant/browse for the last two — which the live 11A memory
flow already does; 11B only makes the interpretation explicit and testable.

## Integration (backward compatible)

`chat_service.handle` attaches `meta["intelligence"]` (scores, bands, multi-intent,
conflicts, related, numbers, typos) and records anonymous analytics on every
request. It never alters `response` / `vehicles` / `status` / `intent` except the
single gated conflict-clarify. All wiring is wrapped in a guard so a fault in the
layer can never break a customer reply.
