# Phase 12J — Audit (STEP 1). No code changed during the audit.

**Method.** A deterministic trace harness (`app/inventory_system/phase12j_trace.py`,
real `ChatService` on an isolated workbook copy) plus direct inventory/UI
inspection. Pinned single car = Fortuner `MH04EX5958` (2011 Diesel, 169,773 km,
Manual, 7 airbags). Multi-car model = **Ertiga** (2 cars):

| Ertiga | Year | Fuel | Trans | Seats | Airbags | Mileage | KM | Price |
|--------|------|------|-------|-------|---------|---------|----|-------|
| A `MH03DA7934` | 2019 | Hybrid | Automatic | 7 | 2 | 20.5 | 80,000 | 7.99 L |
| B `MH04HF6648` | 2016 | Petrol | Manual | 7 | 2 | 20.5 | 39,000 | (varies) |

Baseline before any change: **612 passed / 0 failed**.
Legend: ✅ correct · ❌ wrong · ⚠️ works but fragile.

---

## A. Mileage / KM (pinned)

| Utterance | Current parse → response | Verdict |
|-----------|--------------------------|---------|
| `mileage?` | nothing resolves → **34-car browse** | ❌ ambiguous → should clarify (kmpl vs odometer) |
| `mileage kitna hai?` | `mileage_arai_kmpl` → "14.2 kmpl" | ✅ fuel-efficiency |
| `mileage kya hai?` | `mileage_arai_kmpl` → "14.2 kmpl" | ✅ |
| `average kitna hai?` / `kitna average deti hai?` | `mileage_arai_kmpl` → kmpl | ✅ |
| `kitne km chali?` | `km_reading_query` → odometer | ✅ |
| `running kitni hai?` | `km_reading_query` → odometer | ✅ |

**Only `mileage?` (bare) is wrong.** "mileage kitna/kya" already answer kmpl;
"kitne km chali"/"running" already answer the odometer. So the only ambiguity is
the bare word.

## B. Multi-attribute (pinned)

| Utterance | Current | Verdict |
|-----------|---------|---------|
| `automatic aur petrol hai?` | both → "Fuel Diesel. Manual (gear)." | ✅ (12I combiner) |
| `diesel aur manual hai?` | both answered | ✅ |
| `automatic petrol wali dikhao` | search | ✅ |
| `automatic petrol chahiye` | search | ✅ |
| `automatic diesel` | search | ✅ (preserve) |
| `automatic aur petrol?` | **search** (consultative) | ❌ no `hai`, no search cue → genuinely ambiguous → should clarify |

**Only bare `automatic aur petrol?` (no `hai`, no search word) is wrong.** With
`hai` it answers both; with `wali/chahiye` it searches.

## C. Model-only pin (Ertiga = 2 cars)

| Utterance (ctx = model Ertiga, reg = None) | Current | Verdict |
|--------------------------------------------|---------|---------|
| `automatic hai?` | "2019 Blue Ertiga Hybrid available" (silently the automatic one) | ❌ picks one car |
| `petrol hai?` | "2016 Blue Ertiga Petrol available" (silently the petrol one) | ❌ picks one car |
| `price?` | "2019 Blue Ertiga ₹7.99 lakh" (matches[0]) | ❌ picks one car |
| `RC?` | answers matches[0]'s RC (count 2) | ❌ picks one car |
| `kitne km chali?` | "2 options…" dump | ⚠️ no fabrication but unhelpful |
| `kitne seater hai?` | **34-car browse** (`seats_query` not set for "kitne seater") | ❌ vocab gap + wrong |
| `airbags kitne?` | "2 options…" dump | ⚠️ unhelpful (both are 2 → could answer common) |
| `kaunsa year hai?` | "2 options…" dump | ⚠️ unhelpful (differ → should clarify) |

**Model-only multi is broken:** attribute follow-ups silently answer one car
(`matches[0]` or a filtered pick), or dump. Desired: **clarify which** when values
differ; answer the **common value** when provably identical (both Ertigas are
7-seat / 2-airbag / 20.5 kmpl).

### C2 — same-model variant search (must stay)
| `automatic wali dikhao` / `petrol wali dikhao` / `kam km wali dikhao` | same_model_variant search | ✅ preserve |

### C3 — single-car model (Fortuner) still pins
| `automatic hai?` / `price?` / `kitne km chali?` | pinned answer | ✅ preserve |

## D. Data completeness (inventory + Vehicle Details UI)

### D1 — actual field population (45 cars)
| Field | Populated | Note |
|-------|-----------|------|
| fuel / transmission | 45/45 | core — always present |
| year / km / owners / price | 44/45 | core |
| colour | 42/45 | core |
| airbags / abs / boot / ground clearance / mileage / engine cc | 32–37/45 | **spec-derived** (12B `model_specs`), partial |
| wheel_type | 9/45 | owner-entered |
| sunroof | 3/45 | owner-entered |
| **camera / parking sensors / speakers / touchscreen / android-auto / cruise / keyless** | **0/45** | owner-entered — **blank** |
| **insurance_type / rc_status / warranty** | **0/45** | owner-entered — **blank** |

The blank buyer-facing fields are exactly the ones the chatbot correctly answers
"Data not available" for. **This is a data-entry gap, not a code gap** — and the
phase rule forbids auto-populating them.

### D2 — the existing Vehicle Details UI (`vehicle_details.html`)
The UI **already has a full deterministic completeness system:**
- **Required / Recommended / Optional** per-field badges (`REQUIRED`,
  `RECOMMENDED`, `priOf`).
- Per-section **% complete** bars + an **overall %** bar (`recompute`).
- **"Ready for sale" / "N required left"** gate + clickable **"Missing required"**
  list.
- A **buyer-facing feature ✓/✗ summary** chip row (`SUMMARY`: Sunroof, Camera,
  Android-Auto/CarPlay, Cruise, ABS, Airbags, Alloy, Keyless, Push-button,
  Rear-AC).
- Blank fields get a visual `.miss` marker; field-level validators; EV/non-EV
  conditional fields.

**Verdict:** the completeness *system* is already sufficient — no redesign needed.
The only gap is **breadth**: several buyer-facing feature/document fields that the
chatbot answers (Parking Sensors, Touchscreen, Speakers/Music, Boot Space, Ground
Clearance, Mileage, Insurance Type, RC Status, Warranty…) are currently classified
**Optional** (no badge) and most are absent from the ✓/✗ summary, so staff isn't
nudged to fill the very fields that are blank. A **minimal, additive** widening of
the `RECOMMENDED` set and the `SUMMARY` chip row (no new fields, nothing made
mandatory, no auto-population) closes this without a redesign.

---

## Fix plan (STEP 2–5)

1. **Mileage** — bare `mileage?` → ambiguous clarify ("running (km chali) ya
   mileage (km/l)?"). `mileage kitna/kya`→kmpl and `kitne km chali`/`running`→
   odometer stay unchanged. Never price / random search.
2. **automatic aur petrol?** — a coordinated two-attribute (transmission+fuel)
   FILTER form with no `hai` and no search cue → deterministic clarify. `...hai?`
   (both attrs) and `...wali/chahiye` (search) unchanged.
3. **Model-only multi** — when the pinned context is a model with >1 facing car and
   the turn is an attribute question (no new vehicle, no search cue): if the asked
   attribute(s) are **identical across all matches** → answer the common value;
   else → clarify which variant (year + fuel + transmission). Single-car pins and
   variant searches unchanged. Add `kitne seater` etc. to the seats vocabulary.
4. **Data completeness** — the UI system is sufficient; make a **minimal additive**
   widening of `RECOMMENDED` + the buyer-facing `SUMMARY` so blank buyer-facing
   fields are badged and shown ✓/✗. No auto-population, nothing made mandatory.

## Intentionally left as-is
- `mileage kitna/kya hai?` = kmpl (the ARAI field) — deterministic and populated
  for 33/45; not treated as odometer.
- `automatic diesel` / `automatic petrol` without a coordinator/`hai`/search word —
  a quick two-filter browse (unchanged).
- Blank owner-entered fields stay "Data not available" — never fabricated.
