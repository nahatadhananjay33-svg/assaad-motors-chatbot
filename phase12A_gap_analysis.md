# Phase 12A — Gap Analysis (STEP 5)

*Design only.* Current inventory vs the v2 target, classified by what it takes to
close each gap. This is the work-sizing document for phases 12B+.

---

## Summary

| Bucket | Count (approx) | Meaning |
|---|---|---|
| ✅ Already exists (model + data) | ~13 fields | Populated in Excel today |
| 🟡 Exists in model, **empty in data** | ~30 fields | Add Excel columns + fill / verify |
| 🔴 Missing entirely (new fields) | ~45 fields | Specs, features, keys, EV, extra docs |
| 🧮 Can be calculated | ~6 | Derive, don't store |
| 🏢 Needs dealership verification | subset | Legal/condition claims — must be true |

**Interpretation:** the engine is done; the effort is **data**, not architecture.
Most red items are **model-level specs** that a spec-library can auto-fill.

---

## ✅ Already exists (keep as-is)
make/model/variant/year, fuel, transmission, ownership_count, km_driven, color,
price (quotable + lakh), registration, body_type, seats, RTO/location (internal),
media (exterior/interior/video/instagram/youtube), rc_status (partial).

## 🟡 Exists in model — needs Excel column + data entry/verification
- **Insurance:** insurance_type, insurance_expiry, zero_dep, claim_history
- **Condition:** accident_free, flood_damage, repainted, body/engine/interior/tyre/brake/clutch/battery_condition
- **Service:** service_history_available, last_service_date, service_center_type
- **Documents:** hypothecation_bank, loan_closed, noc_available, finance_eligible
- **Warranty:** warranty_available, warranty_expiry, warranty_provider
- **Sales:** reason_for_sale, best_features, known_issues
- **Pricing:** price_range_low/high, negotiable
- **Usage:** claimed_mileage_kmpl

> These already produce "Data not available" today — filling them is the single
> highest-impact, lowest-risk win (no code change to answer them; Phase 11A/11B
> already route these intents).

## 🔴 Missing entirely (new fields to add)
- **Engine/spec:** engine_cc, power_bhp, torque_nm, aspiration, gears, drivetrain, mileage_arai, fuel_tank_l
- **Dimensions:** length/width/height, wheelbase, boot_litres, ground_clearance
- **Exterior:** headlamp_type, DRL, fog_lamps, wheel_type/size, sunroof_type, roof_rails
- **Interior/comfort:** upholstery, ac_type, rear_ac_vents, power_windows, adjustable_seat
- **Convenience:** push_button/keyless, cruise_control, auto_folding_orvm, rear_defogger/wiper, wireless_charging, ventilated_seats, connected_car
- **Infotainment:** touchscreen_inches, android_auto_carplay, speakers, reverse/360 camera, steering_controls
- **Safety:** airbags, abs_ebd, esp, hill_hold, parking_sensors, isofix, ncap_rating
- **Docs (extra):** puc_valid_till, road_tax_status, fitness_valid_till, duplicate_rc, keys_count
- **Ownership:** usage_type (private/taxi/corporate)
- **Condition (extra):** tyre_life_pct, battery_replaced_on
- **Keys/accessories:** spare_key, spare_tyre, toolkit, floor_mats, accessories_added
- **EV:** battery_health_pct, real_range_km, battery_warranty_till, charger_type, charging_time, battery_owned
- **Transmission:** transmission_subtype (AMT/CVT/DCT/iMT/TC)

## 🧮 Can be calculated (derive, don't store)
- on_road_estimate (price + RTO/insurance rule)
- down_payment / EMI estimate (already: 20% rule)
- running_cost_per_km (fuel type + mileage + fuel price constant)
- inspection_score (weighted from condition enums)
- vehicle age (year → age)
- "low km / less driven" ranking (already: sort)

## 🏢 Needs dealership verification (must be factually true — no guessing)
accident_free, flood_damage, repainted, ownership_count, rc_status, loan_closed,
noc_available, insurance_claim_history, service_history_available, km genuineness,
warranty_available. These are **liability-sensitive** — the schema should force an
explicit Yes/No/Unknown, and the bot must say "confirm at visit" for Unknown.

---

## Field-family readiness scorecard

| Family | Model | Data | Verdict |
|---|---|---|---|
| Identity / price / core usage | ✅ | ✅ | Ready |
| Condition / service / docs / insurance / warranty | ✅ | 🟡 empty | **Fill data (12B/12C)** |
| Specs (engine, dimensions) | 🔴 | 🔴 | **Spec-library (12B)** |
| Features (safety, comfort, infotainment, convenience) | 🔴 | 🔴 | **Spec-library + per-car overrides (12B/12C)** |
| Keys / accessories / extra docs | 🔴 | 🔴 | Per-car entry (12C) |
| EV | 🔴 | 🔴 | Conditional per-car (12C) |
| Media | ✅ | ✅ | Ready |

---

## Recommended closure strategy

1. **Fill the 🟡 fields first** — zero code risk, immediate answer quality jump
   (Phase 11 already understands the questions).
2. **Build a `model_specs` reference library** (make+model+variant+year → specs &
   standard features). Auto-fills most 🔴 spec/feature fields → tiny per-car effort.
3. **Add per-car override + condition/keys/EV fields** in the owner panel for the
   remaining 🔴 items.
4. **Keep 🧮 fields calculated** at answer time — never store derivable values.

This ordering maximises answer coverage per unit of effort and keeps the system
fully deterministic. Detailed sequencing in `phase12A_implementation_roadmap.md`.
