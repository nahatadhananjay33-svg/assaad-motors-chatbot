# Phase 12D — Intent Audit (STEP 1)

Audit of the existing engine before adding recognition for the new vehicle fields.

## Files reviewed
`query_parser.py`, `intent_intelligence.py`, `chat_service.py`,
`response_formatter.py`, `retrieval_engine.py`, `inventory_models.py`,
`inventory_loader.py`, `vehicle_details.html`, plus the Phase 12A/12B/12C reports.

## What already existed (Phase 11A/11B — untouched)
- Deterministic parser → router → retrieval → formatter, ~1.4 ms parse (cached `_has`).
- Field intents already handled: **km, owners, colour, fuel, transmission, seats,
  price/budget, insurance, RC/documents, service, warranty, condition
  (accident/flood), year**, plus media (photo/video/instagram/youtube).
- Phase 11B intelligence: scoring, confidence bands, multi-intent, conflict
  detection, numeric normalization, typo (Levenshtein), analytics.
- Attribute-vs-filter already separated for colour/fuel/transmission/seats.

## New fields derived from the ACTUAL schema (Phase 12B `InventoryItem`)
Introspected from the code, **67 customer-facing fields had NO recognition**:
engine (cc/power/torque/aspiration), transmission detail (subtype/gears/drivetrain),
economy (mileage-ARAI/fuel-tank), dimensions (boot/ground-clearance/wheelbase/L/W/H),
exterior & lights (sunroof/headlamp/DRL/fog/wheels/wheel-size/roof-rails/spoiler),
interior & comfort (upholstery/AC-type/rear-AC/power-windows/seat-adjust/ventilated/
cruise/keyless/push-button/ORVM/defogger/rear-wiper/wireless-charging/connected),
infotainment (touchscreen/android-auto-carplay/speakers/camera/steering-controls),
safety (airbags/ABS-EBD/ESP/hill-hold/parking-sensors/ISOFIX/NCAP), keys
(keys-count/spare-key), accessories (spare-tyre/toolkit/floor-mats/accessories),
extra documents (PUC/road-tax/fitness/duplicate-RC/usage/tyre-life), EV
(battery-health/range/battery-warranty/charger/charging-time/battery-owned).

## Collisions found (must deconflict)
The new vocabulary overlaps a few loose Phase-11A substrings:

| New phrase | Old 11A signal | Resolution |
|---|---|---|
| "boot space" | `boot` → category **Sedan** | clear category when boot_litres asked & no "sedan" |
| "android auto" | `auto` → transmission **Automatic** | clear transmission unless explicit gear word |
| "fuel tank" | `fuel` → `fuel_query` | clear fuel_query when fuel_tank_l asked |
| "ev range" | `ev` → fuel **Electric** | clear fuel unless explicit "electric" |
| "sunroof" / "airbag(s)" | in `OFFSHEET_TOPICS` → **off_sheet** | **removed** from OFFSHEET_TOPICS (now answerable fields) |
| "gearbox" | `transmission_query` (11A) | left as-is (still a valid transmission question) |

## Design decision (reported, per the phase rule)
`sunroof` / `airbag(s)` were previously routed **off-sheet** ("team will confirm").
Phase 12B made them real data fields, and Phase 12D STEP 4 requires "Sunroof hai?"
to be an **attribute question**. They were therefore removed from `OFFSHEET_TOPICS`
and 3 tests that asserted the old off-sheet behaviour were updated to the new
(answerable) behaviour. This is an intentional, documented improvement — see
`phase12D_regression.md`.

## Insertion point (minimal, additive)
A new module `field_intents.py` (data-driven vocab) is consulted at the end of
`query_parser.parse()`, setting `q.attr_fields` (attribute questions) and
`q.feature_filters` (inventory filters). `response_formatter` answers `attr_fields`
from the pinned car; `retrieval_engine` applies `feature_filters`; `chat_service` /
`faq_router` route + clarify; `intent_intelligence` scores them (reusing the same
vocab). No redesign; the engine, auth, permissions, panels, media and Supabase are
untouched.
