# Phase 12I — Audit (STEP 1). No code changed during the audit.

**Method.** A deterministic trace harness (`app/inventory_system/phase12i_trace.py`)
drove the **real `ChatService`** against an isolated copy of `IVR_Sheet.xlsx`
(temp data dir; live sheet untouched). Every Step-1 case group was run with the
same pinned car (Fortuner `MH04EX5958` — 2011 Diesel, 169,773 km, 7 airbags,
2 owners). For each utterance the harness printed the parsed `Query`, the route,
the conversation mode, and the response. Baseline before the audit: **580 passed
/ 0 failed** (`python -m pytest -o python_files="*_tests.py" -q`).

Legend: ✅ correct · ❌ wrong · ⚠️ works but by luck / fragile.

---

## 1. Bare field questions (car pinned)

| Utterance | Current parse → route | Verdict |
|-----------|----------------------|---------|
| `camera?` | `attr_fields=[camera_type]` → pinned answer | ✅ |
| `sunroof?` | `attr_fields=[sunroof_type]` → pinned answer | ✅ |
| `airbags?` | `attr_fields=[airbags]` → "7 airbags" | ✅ |
| `touchscreen?` | `attr_fields=[touchscreen_inches]` → pinned | ✅ |
| `abs?` | `attr_fields=[abs_ebd]` → pinned | ✅ |
| `owners?` | `ownership_query` → "2 owners" | ✅ |
| `insurance?` | `insurance_query` → pinned insurance | ✅ |
| `boot?` | **`category=Sedan`** → 9-car Sedan search | ❌ bare "boot" is a Sedan cue; should be `boot_litres` |
| `mileage?` | inventory browse (fuel-economy word) → 34 cars | ❌ ambiguous (kmpl vs odo); fuller `mileage kitna` works |
| `engine?` | nothing resolves → exhausted / offsheet_unknown | ❌ ambiguous (CC/BHP/condition) → should clarify |
| `battery?` | nothing resolves → exhausted | ❌ ambiguous (EV health / 12V) → should clarify |
| `power steering?` | nothing resolves → exhausted | ⚠️ no such schema field (honest limitation) |
| `safety features?` | nothing resolves → exhausted | ❌ vague → should clarify |

## 2. KM (car pinned)

| Utterance | Current | Verdict |
|-----------|---------|---------|
| `km kitna hai?` | **price ₹8.75 L** | ❌ `_is_price_followup` matches the phrase "kitna hai" and the price-follow-up override in `_conversation_override` fires before the km path. `km_reading_query` **is** set — it's the override that hijacks it. |
| `kitna km hai?` | 169,773 km | ✅ (no "kitna hai" substring) |
| `kitne km chali hai?` | 169,773 km | ✅ |
| `kitna chala hai?` | 169,773 km | ✅ |
| `running kitni hai?` | 169,773 km | ✅ |
| `odometer?` / `odometer reading?` | 169,773 km | ✅ |
| `kam km wali dikhao` / `lowest km` / `sabse kam km wali` | `sort_low_km` search/sort | ✅ preserve |
| `20000 km se kam wali` | `km_max=20000` search | ✅ preserve |

**Only one KM bug:** `km kitna hai?` → price. Everything else already correct.

## 3. Fuel attribute questions (car pinned)

| Utterance | Current | Verdict |
|-----------|---------|---------|
| `petrol hai?` | `fuel=Petrol` **filter** → 16-car browse | ❌ should answer pinned car's fuel |
| `ye petrol hai?` | `fuel=Petrol` filter → browse | ❌ |
| `diesel hai?` | `fuel=Diesel` filter → happens to show Fortuner | ⚠️ wrong path, right-looking output |
| `fuel kya hai?` | `fuel_query` → "fuel Diesel hai" | ✅ (already works) |
| `petrol wali dikhao` / `diesel wali dikhao` / `petrol chahiye` / `diesel wali under 8 lakh` | `fuel` filter + search cue → browse | ✅ preserve |

Root cause: 12G added contextual attribute conversion for **transmission / km /
year** but **not fuel**. Fuel `hai?` questions stay filters.

## 4. Devanagari (car pinned)

| Utterance | Current | Verdict |
|-----------|---------|---------|
| `कितने किलोमीटर चली है?` / `कितने km है?` | km reading | ✅ |
| `किती km चालली आहे?` (Marathi) | km reading | ✅ |
| `सनरूफ है?` | `sunroof_type` | ✅ |
| `पेट्रोल है?` | `fuel=Petrol` filter → browse | ❌ (same fuel bug) |
| `डीजल है?` | **not recognised at all** → exhausted | ❌ Hindi `डीजल` missing from `FUEL_WORDS` (only Marathi `डिझेल` present) |
| `कितने एयरबैग हैं?` / `एयरबैग कितने हैं?` | exhausted | ❌ Hindi `एयरबैग` missing (only Marathi `एअरबॅग`) |
| `कैमरा है?` | exhausted | ❌ Hindi `कैमरा` missing (only Marathi `कॅमेरा`) |
| `कितने मालिक हैं?` | exhausted | ❌ Hindi `मालिक` missing (only Marathi `मालक`) |

Marathi Devanagari works; the **Hindi Devanagari spellings** of a handful of key
fields are missing.

## 5. Booking

| Utterance | Current route | Verdict |
|-----------|---------------|---------|
| `booking?` | **finance_details** (EMI answer) | ❌ |
| `booking kaise karni hai?` | **finance_details** | ❌ |
| `booking amount?` | **finance_details** | ❌ |
| `token amount?` | **finance_details** | ❌ |
| `car book kar sakte hain?` | booking | ✅ |
| `reserve kar sakte hain?` | booking | ✅ |

Root cause: in `faq_engine._INTENT_TABLE`, **`finance_details` is listed before
`booking`** and its keyword list contains `"booking"`, `"booking amount"`,
`"token amount"`, `"minimum booking"`. So any bare booking word is swallowed by
finance_details.

**Must preserve:** `loan?`→finance, `finance?`→finance, `EMI?`→finance_details,
`down payment?`→finance_details (all ✅ today).

## 6. Multi-intent (car pinned)

| Utterance | Current | Verdict |
|-----------|---------|---------|
| `sunroof aur airbags?` | both answered (12D attr_fields join) | ✅ |
| `camera aur parking sensors?` | both answered | ✅ |
| `price aur insurance?` | **price only** | ❌ price-follow-up override swallows it |
| `price aur km batao` | **price only** | ❌ same |
| `km aur owners?` | **km only** | ❌ formatter early-returns on the km branch |
| `RC aur insurance batao` | **insurance only** | ❌ formatter early-returns (documented since 12F) |
| `automatic aur petrol?` | 4-car browse | ❌ both are filters, no attr-question word (`hai`) present → stays search |

Two mechanisms drop secondaries: (a) the **price-follow-up override** in
`chat_service._conversation_override` returns the price and stops; (b) the
**formatter** answers the first matching old-style attribute branch and returns.
New 12D `attr_fields` already multi-answer correctly.

## 7. Negotiation

| Utterance | Current | Verdict |
|-----------|---------|---------|
| `final price?` | negotiation → price_fixed | ✅ |
| `discount?` | discount → price_fixed | ✅ |
| `kuch kam karo` | negotiation → price_fixed | ✅ |
| `bhai mehengi hai` | **unknown** | ❌ |
| `bahut expensive hai` | **unknown** | ❌ |
| `itna mehenga kyun?` / `why so expensive?` | **unknown** | ❌ |
| `last kya karoge?` | **unknown** | ❌ |
| `itne mein nahi lunga` | **unknown** | ❌ |
| `dusri jagah sasti mil rahi hai` | **budget browse (34 cars)** | ❌ |

Explicit `discount`/`kam karo`/`final price` are handled; **indirect objections
without those trigger words** fall to unknown or a budget dump.

---

## Root-cause summary (what STEP 3–9 must fix)

1. **KM `km kitna hai?`** — `_is_price_followup` matches "kitna hai"; guard it so a
   km-reading question never becomes a price follow-up.
2. **Fuel `hai?`** — extend the 12G contextual-attribute reinterpretation to fuel
   (new RULE D), mirroring transmission; keep `...wali/chahiye/dikhao` as search.
3. **Bare `boot?`** — drop bare "boot" as a Sedan cue; add "boot" as a
   `boot_litres` attribute label.
4. **Devanagari** — add Hindi spellings `डीजल`, `एयरबैग`(+`कितने एयरबैग`),
   `कैमरा`, `मालिक`(+`कितने मालिक`).
5. **Booking** — remove booking/token words from `_FINANCE_DETAILS`; make the
   `booking` intent own them (precedence).
6. **Multi-intent** — stop the price-follow-up override from swallowing when other
   attribute intents co-exist; add a deterministic multi-attribute combiner in the
   formatter for a pinned single car.
7. **Negotiation** — add indirect-objection vocabulary (mehenga/expensive/
   kyun/itne mein nahi/dusri jagah sasti/last kya karoge) → `price_fixed`.
8. **Ambiguous bare words** (`engine?`, `battery?`, `safety features?`) — a
   deterministic clarify instead of a dead-end. Never guess.

## Intentionally NOT changed (documented limitations)

- Bare `mileage?` — genuinely ambiguous (fuel-economy kmpl vs odometer). The
  fuller `mileage kitna` already answers the ARAI field; a bare `mileage` browse
  is a legitimate fuel-economy search, so it is left alone.
- `automatic aur petrol?` (no `hai`) — ambiguous between "is THIS car auto+petrol"
  and "show me automatic petrol cars"; kept as search. `automatic aur petrol hai?`
  (with the question word) resolves to both attributes after the fix.
- `power steering?` — no such schema column exists; cannot be answered from data.
- Pinned-by-**model-only** context (reg unknown, multi-car model): attribute
  reinterpretation needs a single pinned car (registration). Same 12G limitation.

---

## STEP 2 — Deterministic decision table (written before implementation)

The one invariant we never break: **attribute question vs search/filter.**

| Signal in the utterance | Classification | Behaviour |
|-------------------------|----------------|-----------|
| field word **+ question form** (`hai`, `hain`, `kya`, `है`, `आहे`, `kitna/kitni/kitne`) and **no** search cue and **no** other car class named | ATTRIBUTE | answer the pinned car's field (reg-pinned). No car pinned → clarify "which car?" |
| field word **+ value** as a filter (`petrol wali`, `automatic wali`, `6 airbags wali`, `sunroof wali`) | SEARCH/FILTER | search inventory (unchanged) |
| explicit search cue (`wali/wale/vali`, `chahiye`, `dikhao`, `cars`, `koi hai`, `sabse`, `options`, `दाखवा`, `पाहिजे`) | SEARCH | search inventory (unchanged) |
| browse filter present (`under X lakh`, `X km se kam`, `N seater`, category) | SEARCH | search inventory (unchanged) |
| two+ attribute questions on a pinned car | MULTI-ATTRIBUTE | answer each; missing field → say "Data not available" for it |
| same-dimension conflict (`petrol diesel`, `automatic manual`) | CLARIFY | ask which (11B, unchanged) |
| disjunction (`petrol ya diesel`) | ATTRIBUTE question | answer pinned car (unchanged) |
| genuinely ambiguous bare word (`engine`, `battery`, `safety features`) | CLARIFY | ask which aspect — never guess |
| booking words (`booking`, `booking amount`, `token amount`, `reserve`, `book kar`) | FAQ booking | booking template (distinct from finance/EMI/down-payment) |
| indirect price objection (`mehenga`, `expensive`, `kyun`, `itne mein nahi`, `dusri jagah sasti`, `last kya karoge`) | FAQ negotiation | fixed-price/value policy (never a discount, never a browse) |

Resolution order for the field-word cases (deterministic, first match wins):
search cue / browse filter → conflict → attribute-question form → bare-ambiguous
clarify. If none resolve, fall back to existing behaviour. **Never fabricate;
never turn an attribute question into a fresh inventory search.**
