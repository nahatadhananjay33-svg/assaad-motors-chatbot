# Phase 12A — Current Inventory & System Analysis (STEP 1)

*Research only. No code, schema, UI, API or Excel was modified.*

Grounded in the live code: `inventory_models.py` (`InventoryItem`), `inventory_loader.py`,
`final_excel_columns.md` (IVR_Sheet.xlsx / DNJ), `query_parser.py` + `intent_intelligence.py`
(intent engine), `chat_service.py` (conversation engine), `response_formatter.py`,
`media_lookup.py` / `media_service.py` (media), and `faq_engine.py` (FAQ).

---

## 1. The two-layer reality

There is an important distinction that drives everything below:

| Layer | State |
|---|---|
| **Data model** (`InventoryItem`, 69 fields) | **Rich.** Phase 7C already defined structured columns for condition, service, documents, warranty, insurance, sales intelligence. |
| **Excel source data** (IVR_Sheet.xlsx, cols A–Q + media) | **Thin.** Only ~13 business columns are actually populated; most structured fields are blank → the bot honestly answers *"Data not available."* |

So the primary gap is **not model design** — it is **(a) Excel columns for the rich fields and (b) real data entry**, plus a few genuinely new fields (features/specs). This reframes later phases as *data + UI* work more than *schema* work.

---

## 2. Current inventory fields (what exists today)

### Populated in Excel (reliable)
`make` · `model` · `year_int` · `fuel_norm` · `transmission_norm` · `ownership_count` ·
`km_driven` · `color_norm` · `price_lakh`/`price_quotable` · `registration_no` ·
`location_code`+`location_type` (internal) · `rto` · `variant` (cryptic) ·
`insurance_hint` (free-text blob) · media URLs (exterior×10, interior×10, video×5,
instagram×5, youtube×5).

### Defined in the model but usually EMPTY in Excel
- **Pricing ext:** `price_range_low/high`, `negotiable`
- **Usage:** `claimed_mileage_kmpl`
- **Insurance (structured):** `insurance_type`, `insurance_expiry`, `zero_dep`, `insurance_claim_history`
- **Condition:** `accident_free`, `flood_damage`, `repainted`, `repaint_panels`, `body_condition`, `engine_condition`, `interior_condition`, `tyre_condition`, `brake_condition`, `clutch_condition`, `battery_condition`
- **Service:** `service_history_available`, `last_service_date`, `service_center_type`
- **Documents:** `rc_status`, `hypothecation_bank`, `loan_closed`, `noc_available`, `finance_eligible`
- **Warranty:** `warranty_available`, `warranty_expiry`, `warranty_provider`
- **Sales intelligence:** `reason_for_sale`, `best_features`, `known_issues`
- **Media summary:** `photo_count`, `video_count`
- **Body:** `body_type`, `seats`

### Internal / system (never shown to customer)
`id`, `stock_no`, `reg_last4`, `color_confidence`, `customer_viewable`,
`listing_status`, `is_ivr_eligible`, `is_placeholder`, `source_sheet`, `raw`,
`as_of`, `created_at`, `updated_at`.

---

## 3. Missing fields (not in the model at all)

The buyer research (STEP 3) surfaces whole categories the schema has **no** field for:

- **Vehicle specs:** engine cc, power (bhp), torque, mileage (ARAI), gears, drivetrain, ground clearance, boot space, fuel-tank capacity, kerb weight, dimensions (L×W×H), wheelbase, turning radius.
- **Features / equipment:** sunroof, touchscreen size, Android Auto/CarPlay, reverse camera, parking sensors (front/rear), number of airbags, ABS/EBD, ESP, hill-hold, cruise control, climate/AC type, push-button start, keyless entry, alloy wheels, LED/projector lights, DRLs, fog lamps, rear wiper/defogger, sunroof type, seat upholstery (fabric/leather), power windows, power steering, ORVM (electric/folding), music system/speakers, steering-mounted controls, connected-car, wireless charging, ventilated seats, 360 camera, ADAS.
- **Keys & accessories:** number of keys, spare key, spare tyre, toolkit, floor mats, accessories added.
- **Documents (extra):** PUC validity, road-tax status/validity, fitness certificate (commercial), duplicate RC, form-35 (loan closure), invoice/first-owner papers.
- **EV-specific:** battery health %, battery warranty, real range, charger type (AC/DC), charging time, battery lease vs owned.
- **Running cost / ownership:** service cost estimate, tyre life left, expected mileage in city/highway.
- **Commercial:** exchange accepted?, test-drive available?, home-delivery?, RC-transfer time/cost, expected delivery time after booking.

---

## 4. Weak areas

| Area | Weakness | Impact |
|---|---|---|
| Excel `INS` (col F) | Free-text blob (date / "COMP" / "THIRD PARTY" / blank) | Can't be queried deterministically; structured insurance cols exist but unfilled |
| `variant` (col G) | Cryptic dealer code, never shown | No human-readable trim/features; `best_features` empty |
| `rate` (col M) | Dual-use price **or** status code | Handled by loader but fragile; non-quotable cars have no range |
| Condition/service/docs/warranty | Modelled but empty in Excel | Bot says "Data not available" for real, common buyer questions |
| Specs & features | **No fields exist** | Cannot answer sunroof/airbags/mileage/camera etc. — a huge share of real questions |
| `reg_last4`, `sr_no` | Redundant columns | Wasted; earmarked for repurposing in `final_excel_columns.md` |

---

## 5. Strengths (keep and build on)

- **Deterministic, no-LLM pipeline** — parser → router → retrieval → formatter, fast (~1.4 ms parse) and explainable.
- **Phase 11A field-intent recognition** — 100% on 1,982 test utterances across EN/HI/Hinglish/Marathi incl. typos.
- **Phase 11B intelligence layer** — scoring, confidence bands, multi-intent, conflict detection, numeric normalization, analytics.
- **No-fabrication guardrails** — empty field → "Data not available"/"visit pe confirm"; internal fields never leak (G-EXPOSE).
- **Media model already complete** — exterior/interior/video/instagram/youtube via Supabase, verified working.
- **Structured schema foundation** — condition/service/docs/warranty fields already exist, so expansion is mostly additive.
- **Excel = single source of truth** with header-located media columns (robust to column shifts) and idempotent UUIDv5 keys.
- **Role-based access + audit trail** (Phase 10) and 4-language replies.

---

## 6. Conclusion

The engine is strong; the **data breadth** is the bottleneck. The v2 design (STEP 4)
should (a) add feature/spec fields the model lacks, (b) turn the empty structured
fields into real Excel columns with easy owner-panel entry, and (c) keep every new
field deterministically answerable. See `phase12A_gap_analysis.md`.
