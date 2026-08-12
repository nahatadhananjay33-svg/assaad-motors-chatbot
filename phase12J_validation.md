# Phase 12J — Validation (before vs after)

**Method.** The audit trace harness (`app/inventory_system/phase12j_trace.py`,
real `ChatService` on an isolated workbook copy) was re-run after the changes.
Pins: single car = Fortuner `MH04EX5958`; multi-car model = **Ertiga** (2019
Hybrid Automatic 7-seat 2-airbag 20.5 kmpl · 2016 Petrol Manual 7-seat 2-airbag
20.5 kmpl). Automated: **21** focused tests (`phase12j_tests.py`), all green.
Legend **B** = before (12I), **A** = after (12J).

---

## Item 1 — Mileage

| Utterance (pinned) | B | A |
|--------------------|---|---|
| `mileage?` (bare) | **34-car browse** ❌ | clarify: "running (kitne km chali) ya mileage (km/l)?" ✅ |
| `mileage kitna hai?` / `mileage kya hai?` | kmpl ✅ | kmpl ✅ (unchanged) |
| `average kitna hai?` / `kitna average deti hai?` | kmpl ✅ | kmpl ✅ |
| `kitne km chali?` / `running kitni hai?` | odometer ✅ | odometer ✅ |
| `good mileage car` (cold) | browse ✅ | browse ✅ (preserved) |

**Never** price, never a random search.

## Item 2 — automatic + petrol

| Utterance | B | A |
|-----------|---|---|
| `automatic aur petrol?` (no `hai`) | **search** (consultative) ❌ | clarify: ask `hai?` to question / `wali dikhao` to search ✅ |
| `automatic aur petrol hai?` | both answered ✅ | both answered ✅ |
| `automatic petrol wali dikhao` | search ✅ | search ✅ |
| `automatic petrol chahiye` | search ✅ | search ✅ |
| `automatic diesel` | search ✅ | search ✅ (preserved) |

## Item 3 — Model-only pin, MULTIPLE cars (Ertiga ×2)

| Utterance (ctx = model Ertiga) | B | A |
|--------------------------------|---|---|
| `automatic hai?` | silently "2019 … Hybrid" ❌ | clarify: "2 Ertiga hain — 2019 Automatic Hybrid ya 2016 Manual Petrol. Kaunsi wali?" ✅ |
| `petrol hai?` | silently "2016 … Petrol" ❌ | clarify ✅ |
| `price?` | silently matches[0] ₹7.99 L ❌ | clarify (prices differ) ✅ |
| `kaunsa year hai?` / `kitne km chali?` | dump / one car ❌ | clarify (values differ) ✅ |
| `kitne seater hai?` | **34-car browse** ❌ | "Dono Ertiga — 7 seater." (common) ✅ |
| `airbags kitne?` | "2 options" dump ❌ | "Dono Ertiga — Airbags: 2 airbags." (common) ✅ |
| `RC?` | matches[0] RC ❌ | "Dono Ertiga — RC status: Data not available." (common DNA) ✅ |
| `automatic wali dikhao` / `petrol wali dikhao` / `kam km wali dikhao` | variant search ✅ | variant search ✅ (preserved) |

### Single-car model (Fortuner) still pins
| `automatic hai?` / `price?` / `kitne km chali?` | pinned answer ✅ | pinned answer ✅ (unchanged) |

## Item 4 — Data completeness (Vehicle Details UI)

The UI **already** had a full deterministic completeness system (Required/
Recommended/Optional badges, per-section + overall % bars, "Ready for sale / N
required left", "Missing required" list, buyer-facing ✓/✗ summary). **B**: several
buyer-facing feature/document fields the chatbot answers (Parking Sensors,
Touchscreen, Speakers, Boot Space, Ground Clearance, Mileage, RC Status,
Warranty…) were **Optional** (unbadged) and mostly absent from the ✓/✗ summary.
**A**: those fields are added to `RECOMMENDED` (badged, not mandatory) and the
buyer-facing `SUMMARY` (✓/✗ chip), so staff immediately sees the blank ones.
No new fields, nothing made mandatory, **no auto-population**.

- Chatbot **no-fabrication** re-verified: a blank field still answers "Data not
  available"; after an owner edit → save → refresh, the chatbot answers the saved
  value (test `test_edit_save_refresh_answer`).

---

## Safety re-check (STEP 6)
- **No fabrication:** blank fields → "Data not available" everywhere; the model
  "common value" answer is only produced when the value is **provably identical**
  across all matching cars.
- **Correct pinned vehicle / model context:** single-car pin answers that car;
  multi-car model never silently picks one.
- **Correct filter behaviour:** all `...wali/dikhao/chahiye`, budgets, km ceilings,
  low-km sorts still search (same-model variant preserved).
- **Correct clarification:** ambiguous bare `mileage?`, `automatic aur petrol?`,
  and differing multi-car attributes all clarify instead of guessing.
- **Multilingual:** Devanagari airbags → common value; Devanagari fuel → clarify;
  Marathi replies still convert.
- **No accidental price routing / fresh search:** `mileage?` no longer dumps;
  model-multi `price?` clarifies instead of picking one car.
