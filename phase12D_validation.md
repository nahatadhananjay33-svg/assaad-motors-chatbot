# Phase 12D — Validation (STEP 10/14)

Deterministic, reproducible. Suite: `app/inventory_system/phase12d_field_tests.py`
(runs under the normal `*_tests.py` sweep) + a coverage table in its `__main__`.

## Recognition coverage

```
fields: 67 | utterances: 5985 | resolved: 5985 (100.0%)
min per-field: 30 | fields <30: {}
```

Every one of the 67 new fields resolves across its aliases × 15 neutral question
frames — **≥30 utterances per field, 100% resolution**, spanning English / Hindi /
Hinglish / Marathi and spelling variants baked into the alias lists.

## pytest results — 13 tests, all pass

| Test | What it proves |
|---|---|
| `test_every_field_resolves_across_frames` | 5,985 utterances, ≥30/field, ≥99% (actual 100%) |
| `test_filter_cue_makes_it_a_filter` | "sunroof/alloy/camera/cruise/android-auto **wali**" → filter, not attribute |
| `test_no_cue_is_attribute` | "sunroof/boot/airbags **kitna**" → attribute question |
| `test_airbag_count_filter_value` | "6 airbags wali" → filter airbags==6 |
| `test_alloy_filter_value` | "alloy wheels wali" → wheel_type==Alloy |
| `test_two_fields_both_detected` | multi-intent (airbags+camera, boot+GC, sunroof+alloy, LED+fog) |
| `test_no_11a_collisions` | boot≠Sedan, android-auto≠Automatic, fuel-tank≠fuel_query, ev-range≠Electric |
| `test_gearbox_still_11a_transmission` | existing 11A transmission question unchanged |
| `test_devanagari` | Marathi/Hindi terms resolve (सनरूफ, बूट स्पेस, एअरबॅग, रेंज, टचस्क्रीन) |
| `test_cold_clarifies` | no pinned car → "Sure — kis gaadi ke details chahiye?" |
| `test_pinned_answers_from_spec` | pinned Creta → boot 433, airbags 6 (from model_specs) |
| `test_pinned_missing_data_never_fabricated` | empty dealership field → "Data not available" |
| `test_filter_returns_cars` | "alloy wheels wali car" → returns matching cars |

## End-to-end behaviour (real `ChatService`)

| Ask (pinned Creta) | Reply |
|---|---|
| `boot space kitna?` | … Boot space: **433 litres**. |
| `airbags kitne?` | … Airbags: **6 airbags**. |
| `ground clearance?` | … Ground clearance: **190 mm**. |
| `mileage kitna?` | … Mileage (ARAI): **16.8 kmpl**. |
| `abs hai?` | … ABS/EBD: **haan**. |
| `led headlights hain?` | … Headlamps: **Projector**. |
| `airbags kitne aur camera hai?` | Camera: Data not available. Airbags: **6 airbags**. (multi-intent) |
| `spare key hai?` | Spare key: **Data not available** (empty dealership field — no fabrication) |

| Ask (cold, no pin) | Reply |
|---|---|
| `sunroof hai?` / `boot space kitna?` / `airbags kitne?` | **Sure — kis gaadi ke details chahiye?** |

| Filter | Result |
|---|---|
| `sunroof wali car` | 3 cars (spec-derived) |
| `6 airbags wali` | 5 cars |
| `alloy wheels wali` | 8 cars |

## STEP-by-STEP coverage

- **STEP 4 (query types):** attribute-query vs inventory-filter separated by filter cue.
- **STEP 5 (context):** pinned → answer that car; cold → clarify, never invent a car.
- **STEP 6 (multi-intent):** `attr_fields` is a list; every requested field answered.
- **STEP 7 (missing/unknown):** empty value → "Data not available"; unknown phrase → clarify.
- **STEP 8 (scoring):** new fields fed into `intent_intelligence.analyze()` (reused vocab).
- **STEP 9 (filters):** 20 `both`-role fields filterable; 47 attribute-only (documented).

## Performance (STEP 12)
| Path | Latency |
|---|---|
| `parse()` incl. field_intents | **1.80 ms/query** (was 1.36; +0.44 for the field scan) |
| `parse()` + `analyze()` | 2.50 ms/query |

Within the 1–2 ms target; no regex-cache regression (reuses the cached `_has`).
