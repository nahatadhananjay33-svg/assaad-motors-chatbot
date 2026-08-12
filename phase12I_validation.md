# Phase 12I — Validation (before vs after)

**Method.** The same deterministic trace harness used for the audit
(`app/inventory_system/phase12i_trace.py`, real `ChatService` on an isolated
workbook copy) was re-run after the changes. Pinned car = Fortuner `MH04EX5958`
(2011 Diesel, 169,773 km, 7 airbags, 2 owners, ₹8.75 lakh). Every row below is an
actual observed response. Automated: **32** focused tests in `phase12i_tests.py`,
all green; full suite **612 passed / 0 failed**.

Legend: **B** = before (12H), **A** = after (12I).

---

## STEP 3 — KM

| Utterance (pinned) | B | A |
|--------------------|---|---|
| `km kitna hai?` | **price ₹8.75 lakh** ❌ | "169,773 km chali hai" ✅ |
| `kitna km hai?` / `kitne km chali hai?` / `running kitni hai?` / `odometer?` | km ✅ | km ✅ (unchanged) |
| `kam km wali dikhao` / `sabse kam km wali car` / `20000 km se kam wali` | search/sort ✅ | search/sort ✅ (preserved) |

## STEP 4 — Fuel attribute vs search

| Utterance | B | A |
|-----------|---|---|
| `petrol hai?` (pinned) | 16-car petrol browse ❌ | "fuel Diesel hai" ✅ |
| `ye petrol hai?` / `diesel hai?` | browse ❌ | pinned car's fuel ✅ |
| `पेट्रोल है?` / `डीजल है?` | browse / **unrecognised** ❌ | pinned car's fuel ✅ |
| `petrol wali dikhao` / `diesel wali dikhao` / `petrol chahiye` / `diesel wali under 8 lakh` | search ✅ | search ✅ (preserved) |

## STEP 5 — Bare field questions

| Utterance (pinned) | B | A |
|--------------------|---|---|
| `boot?` | 9-car **Sedan** search ❌ | "Boot space: Data not available" ✅ |
| `engine?` | exhausted dead-end ❌ | clarify: "capacity (CC), power (BHP), ya engine condition?" ✅ |
| `battery?` | exhausted ❌ | clarify: "12V battery ya EV battery health?" ✅ |
| `safety features?` | exhausted ❌ | clarify: "airbags, ABS, ya NCAP rating?" ✅ |
| `camera?` `sunroof?` `airbags?` `owners?` `insurance?` `touchscreen?` `abs?` | pinned answer ✅ | pinned answer ✅ (unchanged) |
| `mileage?` / `power steering?` | browse / dead-end | **unchanged** (documented limitations — see report) |

## STEP 6 — Devanagari (Hindi spellings)

| Utterance (pinned) | B | A |
|--------------------|---|---|
| `कितने एयरबैग हैं?` / `एयरबैग कितने हैं?` | exhausted ❌ | "Airbags: 7 airbags" ✅ |
| `डीजल है?` | **unrecognised** ❌ | "fuel Diesel hai" ✅ |
| `कैमरा है?` | exhausted ❌ | "Camera: Data not available" ✅ |
| `कितने मालिक हैं?` | exhausted ❌ | "yeh 2 owners wali gaadi hai" ✅ |
| `कितने किलोमीटर चली है?` / `किती km चालली आहे?` (Marathi) | km ✅ | km ✅ (unchanged) |

## STEP 7 — Booking

| Utterance | B | A |
|-----------|---|---|
| `booking?` | **finance/EMI** answer ❌ | booking policy ✅ |
| `booking kaise karni hai?` | finance/EMI ❌ | booking ✅ |
| `booking amount?` | finance/EMI ❌ | booking ✅ |
| `token amount?` | finance/EMI ❌ | booking ✅ |
| `loan?` / `finance?` / `EMI?` / `down payment?` | finance ✅ | finance ✅ (preserved) |

## STEP 8 — Multi-intent (both answered)

| Utterance (pinned) | B | A |
|--------------------|---|---|
| `price aur insurance?` | price only ❌ | "Price ₹8.75 lakh. Insurance: Data not available." ✅ |
| `price aur km batao` | price only ❌ | "Price ₹8.75 lakh. 169,773 km chali hai." ✅ |
| `km aur owners?` | km only ❌ | "169,773 km chali hai. 2 owners." ✅ |
| `RC aur insurance batao` | insurance only ❌ | "Insurance: … RC status: …" ✅ |
| `sunroof aur airbags?` / `camera aur parking sensors?` | both ✅ | both ✅ (unchanged) |
| `automatic aur petrol?` (no `hai`) | search | **unchanged** (ambiguous — `automatic aur petrol hai?` now answers both) |

## STEP 9 — Negotiation (indirect objections)

| Utterance | B | A |
|-----------|---|---|
| `bhai mehengi hai` | unknown ❌ | fixed-price/value policy ✅ |
| `bahut expensive hai` | unknown ❌ | fixed-price policy ✅ |
| `itna mehenga kyun?` / `why so expensive?` | unknown ❌ | fixed-price policy ✅ |
| `itne mein nahi lunga` | unknown ❌ | fixed-price policy ✅ |
| `last kya karoge?` | unknown ❌ | fixed-price policy ✅ |
| `dusri jagah sasti mil rahi hai` | **34-car budget dump** ❌ | fixed-price policy ✅ |
| `discount?` / `final price?` / `kuch kam karo` | price_fixed ✅ | price_fixed ✅ (preserved) |
| `sasti gaadi dikhao` (real cheapest browse) | search ✅ | search ✅ (NOT captured by negotiation) |

---

## No fabrication / no accidental search (safety re-checked)

- Every missing field still renders **"Data not available"** — the fixes never
  invent a value (camera/sunroof/insurance/boot all DNA on the test car).
- Attribute questions answer **exactly one pinned car** (`count == 1`); none was
  converted into a fresh inventory dump.
- All search/sort/filter phrasings (`...wali/dikhao/chahiye`, budgets, km ceilings,
  low-km sorts, cheapest) still search — verified in the trace and by the
  `*_preserved` / `*_still_searches` tests.
- Unpinned attribute questions still **clarify**, never fabricate (existing 12G
  behaviour, unchanged).
