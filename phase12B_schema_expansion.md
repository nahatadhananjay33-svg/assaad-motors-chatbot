# Phase 12B — Expanded Inventory Schema

Implements the Phase 12A v2 design as real fields on `InventoryItem`
(`inventory_models.py`), wired to Excel via header-located columns
(`inventory_loader.py`). **No chatbot / intent / conversation / media / auth
changes.** Fully additive and backward compatible.

## What changed

- **`inventory_models.py`** — added ~68 new optional fields (all default `None`,
  so every existing constructor call and test still works). Grouped exactly as the
  v2 design: engine, transmission detail, fuel & economy, dimensions, exterior &
  lights, interior & comfort, convenience, infotainment, safety, documents-extra,
  ownership-extra, condition-extra, keys & accessories, EV.
- **`inventory_loader.py`** — every new field is read from the Excel by **header
  text** (`_NEW_EXT_FIELDS` → registered into `_EXT_HEADER_MAP`). Columns are
  **optional**: an absent column is a no-op (field stays `None`). Existing columns
  A–Q and the media block are untouched.
- **`model_specs.apply_specs(item)`** is called once at the end of `build_item`
  (single choke point) to auto-fill standard specs — see the library report.

## Field groups (new)

| Group | Fields | Source |
|---|---|---|
| Engine | engine_cc, power_bhp, torque_nm, aspiration | **spec** (auto-fill) |
| Transmission detail | transmission_subtype, gears, drivetrain | spec |
| Fuel & economy | mileage_arai_kmpl, fuel_tank_l, cng_kit_type | spec (cng_kit dealership) |
| Dimensions | length/width/height_mm, wheelbase_mm, boot_litres, ground_clearance_mm | spec |
| Exterior & lights | headlamp_type, drl, fog_lamps, wheel_type, wheel_size_inch, sunroof_type, roof_rails, spoiler | spec |
| Interior & comfort | upholstery, ac_type, rear_ac_vents, power_windows, adjustable_seat | spec |
| Convenience | push_button_start, keyless_entry, cruise_control, auto_folding_orvm, rear_defogger, rear_wiper, wireless_charging, ventilated_seats, connected_car | spec |
| Infotainment | touchscreen_inches, android_auto_carplay, speakers, camera_type, steering_controls | spec |
| Safety | airbags, abs_ebd, esp, hill_hold, parking_sensors, isofix, ncap_rating | spec |
| Documents (extra) | puc_valid_till, road_tax_status, fitness_valid_till, duplicate_rc, keys_count | **dealership** |
| Ownership (extra) | usage_type | dealership |
| Condition (extra) | tyre_life_pct, battery_replaced_on | dealership |
| Keys & accessories | spare_key, spare_tyre, toolkit, floor_mats, accessories_added | dealership |
| EV | battery_health_pct, real_range_km, battery_warranty_till, charger_type, charging_time, battery_owned | dealership |

## Precedence (deterministic)

```
Excel column value   (owner override)     ── highest
   ↓ (if that field is still None)
model_specs library  (standard factory spec)
   ↓ (if unknown model / field)
None  →  chatbot says "Data not available"  ── never fabricated
```

Implemented in `build_item`: construct → read new Excel columns (override) →
`apply_specs()` (fill remaining standard specs) → return.

## Backward compatibility

- All new fields are optional with defaults → no constructor/tests break.
- Loader is header-located → absent columns are ignored; the live `IVR_Sheet.xlsx`
  is **unchanged**.
- No customer-facing / chatbot / API behaviour changes (12B is data-layer only;
  surfacing these in answers is Phase 12D, in the UI is Phase 12C).

## Deliverable files
- `app/inventory_system/inventory_models.py` (expanded model)
- `app/inventory_system/inventory_loader.py` (header-located reads + auto-fill hook)
- `app/inventory_system/model_specs.py` (library — see next report)
- `app/inventory_system/phase12b_migrate.py` (readiness utility)
- `app/inventory_system/phase12b_specs_tests.py` (validation tests)
