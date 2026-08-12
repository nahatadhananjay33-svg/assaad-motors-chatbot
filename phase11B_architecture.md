# Phase 11B — Intent Architecture Audit (STEP 1)

Study of the full intent pipeline and the **single minimal insertion point** for a
deterministic Intelligence Layer. No implementation in this document.

---

## 1. The pipeline today

```
customer message
   │
   ▼
normalize_typos()                     chat_service.handle()  (regex typo folding)
   │
   ▼
_norm()                               query_parser  (lowercase, Devanagari-safe)
   │
   ▼
parse()  ──────────────►  Query       query_parser  (flags + filter fields)
   │                     (rc_query, insurance_query, fuel, color, price_max, …)
   ▼
FAQRouter.classify()  ──►  RouteResult faq_router  (faq | inventory | unknown)
   │        (detail-flags & registration bypass FAQ → inventory)
   ▼
_conversation_override()              chat_service  (contact / continuation /
   │                                   refinement / budget-confirm / price-follow-up)
   ▼
_handle_retrieval / _handle_faq / _handle_unknown
   │        (retrieval_engine.search → response_formatter.format_response)
   ▼
ChatResult (intent, response, vehicles, status, meta)
   │
   ▼
Marathi conversion · lead capture · analytics · logging → response
```

### Decision points (where meaning is committed)

| # | Location | Decision | Current logic |
|---|---|---|---|
| D1 | `normalize_typos` | fix spellings | ~45 fixed regex rules |
| D2 | `parse()` filter loops | value → filter | **first match wins** (see D-conflict) |
| D3 | `parse()` detail flags | field question → flag | keyword/phrase membership |
| D4 | `parse()` attribute-Q (11A) | bare field question | `*_query` flags when no value |
| D5 | `FAQRouter.classify` | route | registration/detail-flags → inventory; else FAQ; else signal→inventory; else unknown |
| D6 | `_attr_clarification` (11A) | no-pin attribute Q | "which car?" clarify |
| D7 | `_conversation_override` | follow-up reuse | pin/model memory, refinement merge |
| D8 | `response_formatter` | field → answer | per-flag branch, no fabrication |

### D-conflict (the gap 11B targets)

`parse()`'s filter loops (`fuel`, `transmission`, `color`, `ownership`) **break on
the first match**, so a contradictory query is silently resolved to one value:

| Query | parse() result today |
|---|---|
| `petrol diesel` | fuel = **Diesel** (silent pick) |
| `automatic manual` | transmission = **Automatic** (silent pick) |
| `white black` | color = **White** (silent pick) |
| `first owner second owner` | ownership_exact = **1** (silent pick) |

A real salesperson would ask "petrol ya diesel — kaunsa chahiye?". This is the
kind of *meaning* gap 11B addresses — **not** by rewriting the parser, but by a
layer that inspects the utterance and detects the contradiction.

---

## 2. What already works (do NOT touch)

- **Multi-field, non-conflicting** queries already set multiple values:
  `automatic diesel` → {fuel=Diesel, transmission=Automatic};
  `insurance owner` → {insurance_query, ownership_query};
  `rc insurance` → {rc_query, insurance_query}. The parser does not *lose*
  secondary fields — 11B only needs to **surface** them explicitly (STEP 4).
- **Attribute vs filter** disambiguation (11A): value → browse; bare field-name
  question → `*_query` answered from the pinned car.
- **No-pin clarification** (11A): attribute question with no vehicle → "which car?".
- **Follow-up memory / browse / variant / media / budget** — all deterministic and
  passing; 11B must remain backward compatible with every one.

---

## 3. Where the Intelligence Layer inserts (minimal change)

The layer is a **new standalone module** `intent_intelligence.py`. It **reads** the
same message and the existing `Query` (from `parse()`) and produces a structured,
deterministic `IntentAnalysis` — scores, multi-intents, cross-field families,
normalized numerics, typo resolutions, conflicts, confidence band. It **writes
nothing into** the parser, retrieval, memory, media, or browse logic.

```
message ──► parse() ──► Query
   │                      │
   └──────────► intent_intelligence.analyze(message, q)  ◄─ NEW, PURE, READ-ONLY
                          │
                          ▼
                    IntentAnalysis {scores, primary, band,
                                    multi_intents, families,
                                    numbers, typos, conflicts,
                                    recommendation}
```

Two integration seams, both **additive and backward compatible**:

1. **`chat_service.handle` tail** — attach `out.meta["intelligence"]` (scores /
   multi-intent / conflicts / confidence) and record **anonymous** intent
   analytics. This changes `meta` only — never `response`, `vehicles`, `status`,
   or `intent` — so **every existing test still passes**.

2. **`_conversation_override` (one narrow, guarded behavior)** — a *genuine
   same-dimension contradiction* (petrol+diesel, auto+manual, two colours,
   first+second owner) with no other resolving context returns a single
   clarification instead of a silent pick (STEP 3 medium/conflict → clarify).
   This is the only behavioral change, is proven a real bug (D-conflict above),
   is gated tightly, and is verified against the full regression suite before
   being kept. If any existing test depends on the silent pick, the behavior is
   downgraded to meta-only.

No other seam is modified. The parser, retrieval engine, inventory model, memory
maps, media service and browse/variant logic are untouched.

---

## 4. Determinism guarantees

- Scoring is integer/rational arithmetic over fixed vocabularies — same input →
  same scores, every run. No randomness, no ML, no probabilities, no embeddings.
- Typo resolution uses classic **Levenshtein distance** against a *closed* field
  vocabulary with a fixed threshold and a uniqueness rule — deterministic, and it
  only corrects when the nearest term is unambiguous; otherwise it defers to
  clarify (never guesses).
- Numeric normalization is pure string→int parsing of Indian/English money, km,
  owners, seats and years.

The layer is designed to be **cheaper than a re-parse** (it reuses the `Query`),
so end-to-end latency stays flat or improves (STEP 13).
