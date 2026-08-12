# Phase 12I — Deterministic Conversational Hardening — Final Report

**Goal.** Fix the remaining conversational weaknesses found in Phase 12H
manual/automated validation, **deterministically** (NO LLM), with minimal,
additive, reversible changes on top of 11A/11B + 12D/12E/12G. Keep the
attribute-vs-search invariant intact and never fabricate.

**Result.** All targeted weaknesses fixed. Full suite **612 passed / 0 failed**
(580 baseline + 32 new). No architecture change, no touch to auth / permissions /
media / Excel schema / owner UI / Supabase.

---

## 1. What was fixed (by step)

### STEP 3 — KM
`km kitna hai?` returned the **price** because `_is_price_followup` matched the
loose phrase "kitna hai" and the price-follow-up override fired before the
odometer path. **Fix:** guard `_is_price_followup` — if the turn also carries a
km-reading (or any other attribute) intent, it is not a price-only follow-up.
Now every natural KM phrasing answers the odometer; `kam km wali` / `lowest km` /
`X km se kam` still search/sort.

### STEP 4 — Fuel attribute questions
`petrol hai?` / `डीजल है?` were treated as fuel **filters** (a browse). **Fix:**
a new **RULE D** inside the existing 12G contextual block converts a fuel filter
to a fuel **question** when the utterance is an attribute-question form with no
search cue, no other car class named, and no browse filter — mirroring the 12G
transmission rule. `petrol wali dikhao` / `diesel chahiye` / `diesel under 8 lakh`
still search.

### STEP 5 — Bare field questions
- `boot?` mapped to **category = Sedan**. **Fix:** removed bare "boot" as a sedan
  cue and added "boot"/"dicky"/"dickey" as `boot_litres` labels → now a boot-space
  attribute answer. (`dickey wali` remains the sedan cue.)
- `engine?`, `battery?`, `safety features?` dead-ended. **Fix:** a deterministic
  **ambiguous-field clarify** (`AMBIGUOUS_FIELDS` in `query_parser`, surfaced via
  `_handle_retrieval`) — asks which aspect, never guesses. Set only when nothing
  else resolves; fuller forms (`engine capacity`, `battery health`,
  `safety rating`) still resolve their real fields.

### STEP 6 — Devanagari coverage
Added the missing **Hindi** spellings alongside the existing Marathi ones:
`एयरबैग` / `कितने एयरबैग` (airbags), `डीजल`/`डीज़ल` (diesel), `कैमरा` (camera),
`मालिक` / `कितने मालिक` (owners). All now answer the pinned car.

### STEP 7 — Booking
`booking?`, `booking amount?`, `token amount?` mis-routed to **finance_details**
(its keyword list contained "booking"/"token" and it out-ranked `booking`).
**Fix:** moved booking/token words out of `_FINANCE_DETAILS` into `_BOOKING`.
Finance / loan / EMI / down-payment are unchanged.

### STEP 8 — Multi-intent
Secondary intents were silently dropped (`price aur insurance` → price only;
`km aur owners` → km only; `RC aur insurance` → insurance only). **Fix:** a
deterministic **multi-attribute combiner** in `response_formatter` — for a pinned
single car with 2+ attribute intents, it answers each in a stable order; missing
fields say "Data not available". Plus the `_is_price_followup` guard (Step 3) so a
price+X ask reaches the combiner instead of the price-only shortcut. Pure 12D
multi-field asks (`sunroof aur airbags`) keep their existing path (identical
output).

### STEP 9 — Negotiation
Indirect objections without a trigger word (`mehenga`/`expensive`/`kyun`/
`itne mein nahi`/`dusri jagah sasti`/`last kya karoge`) went to *unknown* or a
34-car budget dump. **Fix:** added specific indirect-objection phrases (Hinglish +
Devanagari) to `_NEGOTIATION` → the existing `price_fixed` policy (fixed price,
value, invite to inspect). No fake discount, no manager approval, no fake urgency,
no argument. A genuine cheapest-car browse (`sasti gaadi dikhao`) is **not**
captured.

---

## 2. New deterministic rules (summary)

1. **Fuel attribute (RULE D):** fuel filter → `fuel_query` when attribute-question
   form + no search cue + no model/make/category + no browse filter.
2. **Bare boot:** `boot` → `boot_litres` attribute (not a Sedan search).
3. **Ambiguous bare field:** `engine`/`battery`/`safety`/`safety features`/
   `features` (when nothing else resolves) → one clarify, never a guess.
4. **Booking ownership:** booking/token/reserve words belong to the `booking`
   intent, not `finance_details`.
5. **Multi-attribute answer:** pinned single car + 2+ attribute intents → answer
   each; missing → DNA; never a search.
6. **Price follow-up guard:** a price word inside a larger attribute/multi-intent
   ask is not a price-only follow-up.
7. **Indirect negotiation:** listed objection phrases → fixed-price policy.

The invariant, unchanged: **attribute question (answer the pinned car) vs
search/filter (browse inventory)** — resolved by search cues / browse filters /
question form, deterministically, first match wins.

---

## 3. Files changed (all additive / reversible)

| File | Change |
|------|--------|
| `query_parser.py` | RULE D (fuel); bare "boot" removed from Sedan cue; Hindi `डीजल` in `FUEL_WORDS`; Hindi owner spellings; `AMBIGUOUS_FIELDS` + `ambiguous_field` flag + detection. |
| `field_intents.py` | `boot`/`dicky`/`dickey` labels for `boot_litres`; Hindi `एयरबैग`/`कितने एयरबैग` (airbags), `कैमरा` (camera). |
| `faq_engine.py` | booking/token words moved from `_FINANCE_DETAILS` → `_BOOKING`; indirect-objection phrases added to `_NEGOTIATION`. |
| `chat_service.py` | `_is_price_followup` guard; ambiguous-field clarify in `_handle_retrieval`; import `AMBIGUOUS_FIELDS`. |
| `response_formatter.py` | multi-attribute combiner (`_attr_intent_clauses` + gated branch). |
| `faq_router.py` | route `ambiguous_field` to inventory (so the clarify is produced). |
| **new** `phase12i_tests.py` | 32 tests (parser, FAQ, end-to-end). |
| **new** `phase12i_trace.py`, `phase12i_perf.py` | audit trace + perf harness. |

---

## 4. Test counts & regression
- New tests: **32** (`phase12i_tests.py`) — all green.
- Full suite: **612 passed / 0 failed** (was 580 / 0). See `phase12I_regression.md`.

## 5. Performance (no meaningful regression)
`app/inventory_system/phase12i_perf.py`, 12I-affected utterances:

| Metric | 12F baseline | 12I |
|--------|--------------|-----|
| `parse()` | ~2.3 ms | **1.76 ms** |
| `parse()+analyze()` | ~2 ms delta | **0.70 ms delta** |
| `conversation_policy` | ~4.4 ms (incl. parse) | **1.94 ms** |
| `handle()` end-to-end | mean ~32 / median ~29 ms | **mean 25.4 / median 24.2 / p95 36 ms** (n=6000) |

The additions are a handful of substring checks and one gated formatter branch;
overhead is within noise (numbers here are equal-or-better than 12F).

---

## 6. What was intentionally NOT changed
- **Auth, permissions, media, Excel schema, owner UI, Supabase** — untouched.
- Architecture, retrieval, memory, 11B scoring, 12E modes — unchanged (all changes
  ride on top).
- Bare `mileage?` — genuinely ambiguous (fuel-economy kmpl vs odometer); the
  fuller `mileage kitna` already answers the ARAI field and a bare `mileage` browse
  is a legitimate fuel-economy search, so it is left as-is.
- `automatic aur petrol?` (no question word) — ambiguous between "is THIS car
  auto+petrol" and "show auto+petrol cars"; kept as search. `automatic aur petrol
  hai?` (with `hai`) now answers both attributes.
- `power steering?` — no such schema column exists; cannot be answered from data.

## 7. Remaining limitations (for manual testing next)
1. **Model-only pin** (a multi-car model pinned with no single registration):
   attribute reinterpretation needs a single pinned car (registration). Same 12G
   limitation — the common single-car pin works.
2. **Blank feature columns**: most cars have blank camera/sunroof/insurance/etc.,
   so answers are correctly "Data not available" — this is **owner data entry**,
   not a code gap.
3. **Bare `mileage?` / `power steering?`** as above.
4. Intent **label** for a KM follow-up may read `price` in `meta` (the loose price
   intent) even though the **answer is the odometer** — cosmetic only; the reply is
   correct.

### Suggested manual tests next
- Real multi-turn sessions pinning a single car by registration, then asking KM /
  fuel / booking / multi-intent / indirect-negotiation across Hindi, Hinglish,
  Marathi and English.
- Owner fills a few feature columns (camera, sunroof, insurance) via the Vehicle
  Details UI, then confirm the chatbot answers the saved values (end-to-end chain
  proven in 12H).
- Edge negotiation tone ("dusri jagah 50k kam", "bhai thoda toh dekho") to confirm
  it stays polite and fixed-price.

---

**FINAL:** Phase 12I is complete. The targeted weaknesses (KM, fuel attribute,
bare fields, Devanagari, booking, multi-intent, negotiation) are fixed
deterministically with no fabrication and no regression (612/0). **No further
phase was started.** The items in §7 are the honest remaining edges to exercise in
manual testing.
