# Phase 12F — Final Vehicle-Knowledge + Conversation Validation

**Scope:** validation only. Confirm that Phase 12A → 12E work correctly together as
one system. No LLM. No redesign. No changes to auth / permissions / audit / media /
Supabase / Owner or Staff panels / Excel upload.

**One code change was made** (a genuine coverage gap found during STEP 5/6 — see
§"Fix applied"). Everything else is verified as-is.

---

## STEP 1 — Current-state audit (read from the real code, not the summaries)

| Layer | File | State confirmed |
|-------|------|-----------------|
| Inventory schema | `inventory_models.py` (+ `model_specs.py` fallback) | InventoryItem carries the Phase 12B expansion; owner-entered value wins, spec library only fills gaps, missing → `None` (never fabricated). |
| Excel source of truth | `IVR_Sheet.xlsx` | **163 columns**, 184 rows; loader yields **45** facing, **44** after 1 placeholder is quarantined. Source of truth = the sheet. |
| Deterministic parser | `query_parser.py` | `parse()` with cached `_has`/`_norm` regex (11A perf fix). ~2.3 ms/call. |
| New-field intents | `field_intents.py` | **67 fields** (47 attribute-only, 20 attribute+filter). `detect()` → `(attr_fields, feature_filters)`, filter-cue aware. |
| Intent intelligence | `intent_intelligence.py` | 11B scoring / multi-intent / conflict layer. `detect_conflicts` drives conflict-clarify. Read-only. |
| Conversation policy | `conversation_policy.py` | 12E 7-mode classifier — read-only label on `meta["conversation_mode"]`, no routing change. |
| Retrieval | `retrieval_engine.py` | filter search; feature-filter respecting. |
| Pinned-car memory | `chat_service.py` `_followup_ctx` / `_last_search` | attribute follow-ups reuse the pinned reg/model; variant refinements stay in-model; different requirements start a fresh browse. |
| Response formatting | `response_formatter.py` | `_field_answer()` renders one field per value; missing → **"Data not available"** (Marathi: **"माहिती उपलब्ध नाही"**). G-EXPOSE leak backstop intact. |

All layers are present, deterministic, and wired exactly as the 12A–12E reports
describe. No LLM anywhere in the request path.

---

## STEPS 2–8 — End-to-end conversation validation

Driven through the **real `ChatService`** on a **copy** of the workbook
(`phase12f_e2e.py`, read-only to the live sheet). A key data fact shaped the tests:
specs like **airbags / boot / engine / mileage / ground-clearance** are populated
(auto-filled by the spec library) for most cars, while **speakers (music), camera,
parking sensors, touchscreen, EV range/battery** are **empty for every car** (the
owner has not entered them yet). That makes them ideal "missing-data" probes.

### STEP 2 — Vehicle questions
- **Pinned single car (Fortuner):** every question answered about *that* car.
  Populated → the value (`Airbags: 7`, `Ground clearance: 279 mm`, `Engine: 2755 cc`,
  `2 owners`, `Wheels: Alloy`); empty → `Data not available` (sunroof, boot, music,
  camera, insurance, RC, service). **Never fabricated.** ✅
- **No pinned car (fresh session):** every one of the same questions **clarifies**
  ("Sure — kis gaadi ke details chahiye?" / field-specific "Kaunsi gaadi ki
  insurance…?"). Never a random rank-#1 car. ✅

### STEP 3 — Filter vs attribute
| Utterance | Pinned? | Result | Correct? |
|-----------|---------|--------|----------|
| `sunroof hai?` | yes | attribute (this car) | ✅ |
| `sunroof wali car chahiye` | — | inventory filter (3 cars) | ✅ |
| `6 airbags hain?` | yes | attribute (answered `7`) | ✅ |
| `6 airbags wali car chahiye` | — | inventory filter (5 cars) | ✅ |
| `2019 model hai?` | yes | **fresh 2019 search** | ⚠️ see known limitation |
| `2019 model chahiye` | — | inventory filter | ✅ |
| `sabse kam km wali car` | — | low-km sort search (34) | ✅ |
| `kam km chali hai?` | yes | **low-km search** | ⚠️ see known limitation |

Feature attribute/filter separation is correct. Year and the "kam km" phrasing
lean to search (pre-existing 11A/7L design — see below).

### STEP 4 — Conversation flow (the STEP 9 sequence)
`Show me Ertiga` → 2 options → `automatic wali?` (same-model variant, stays on
Ertiga) → `petrol wali?` (resolves to the 2016 Petrol Ertiga) → `RC?` (that
Ertiga's RC) → `sunroof?` (that Ertiga's sunroof) → `7 seater chahiye`
(**fresh browse**, 8 options). Context is retained across variant/attribute turns
and correctly replaced on a new class of search. ✅
- `petrol diesel` → **conflict → clarify** ("Petrol ya Diesel — kaunsa fuel chahiye?"). ✅
- `petrol ya diesel?` → **not a conflict**, stays a normal question. ✅

### STEP 5 — Multi-intent (no secondary intent lost)
| Utterance | Fields answered |
|-----------|-----------------|
| `sunroof aur airbags hain?` | Sunroof + Airbags ✅ |
| `boot space aur ground clearance?` | Boot + Ground clearance ✅ |
| `camera aur parking sensors hain?` | Camera + Parking sensors ✅ *(after fix)* |
| `automatic hai aur kitne owners hain?` | Owners answered; `automatic` absorbed as a transmission variant ⚠️ |

### STEP 6 — Language coverage (natural variations, not dictionary phrases)
English / Hindi / Hinglish / Marathi all answer the pinned car:
`sunroof hai kya?`, `sunroof milta hai?`, `roof khulti hai?` *(after fix)*,
`isme kitne airbags hai?`, `kitne malik rahe?`, `gaadi kitna chali?`,
`running kitni hai?`, `camera laga hai?` *(after fix)*, `sunroof aahe ka?`,
`किती एअरबॅग आहेत?`, `बूट स्पेस किती?`. Marathi missing-data renders
**"माहिती उपलब्ध नाही"**. ✅

### STEP 7 — Missing data
Every genuinely empty field (music/speakers, camera, parking sensors, touchscreen,
battery health, EV range) → **"Data not available"** on the pinned car. No
fabrication of any spec. ✅

### STEP 8 — Unknown / off-sheet
Astrology / "chaand par ja sakti hai" / horoscope / "which engine oil brand" /
"resale value in 2030" → safe clarify, `unknown`, or "similar gaadi dikha doon?"
— **never a fabricated specification**. ✅

---

## Fix applied (the only code change in 12F)

**File:** `field_intents.py` — synonym additions only (data, not logic):
- `camera_type`: added `camera` (bare), `camera laga`, `rear cam`, `back cam`, `कॅमेरा आहे`.
- `sunroof_type`: added `roof khulti`, `chhat khulta`, `chat khulti`, `छत खुलता`.

**Why:** STEP 5/6 buyer phrasings explicitly listed in the brief —
`camera aur parking sensors hain?`, `camera laga hai?`, `roof khulti hai?` — were
not recognised (bare "camera" and the feminine "khulti"/masculine "khulta" gender
variants were missing), so they fell to a safe-but-unhelpful continuation reply.
This is a genuine 12D dictionary coverage gap, not a new feature.

**Safety of the fix:** `_has` matches on word boundaries (won't match `camerawala`);
bare "camera" does not collide with media/photo intent (verified); filter routing
still works (`camera wali car chahiye` → filter, not attribute). Verified: the 3
target phrases now answer correctly, and **the full regression is unchanged at
551 pass / 2 (pre-existing) fail**.

---

## Known limitations (pre-existing design, documented — NOT 12F regressions)

1. **`2019 model hai?` and `kam km chali hai?` while pinned** are treated as fresh
   searches (year is a browse filter; "kam km" is a low-km sort) rather than "is
   *this* car a 2019 / low-km one". The car's odometer *is* answerable via
   `gaadi kitna chali?` / `running kitni hai?` (verified working). Pre-dates Phase 12.
2. **`automatic hai?` while pinned** is treated as a transmission variant, not a
   yes/no attribute of the pinned car. Pre-existing 11A transmission-filter
   behaviour; the well-tested filter path was intentionally left untouched.
3. **Empty feature columns** (music/speakers, camera, parking sensors, touchscreen,
   EV fields) answer "Data not available" for *every* car because the owner has
   not entered them. This is correct no-fabrication behaviour — the fix is
   **data entry via the Vehicle Details UI**, not code.

None of these fabricate data or misroute to a wrong car; all degrade to a safe
clarify or a truthful "Data not available".

## Performance — see `phase12F_report.md`.
