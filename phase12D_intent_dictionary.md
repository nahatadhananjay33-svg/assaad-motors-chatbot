# Phase 12D — Intent Dictionary (STEP 2/3)

The deterministic field → intent map for the 67 NEW vehicle-detail fields, from
`app/inventory_system/field_intents.py` (`FIELD_SPECS`). Each field maps to an
`InventoryItem` attribute; answers come straight from the record (spec-auto-filled
or dealership-entered) — never fabricated.

**Languages:** English, Hindi, Hinglish, Marathi (Devanagari) aliases per field
(the table shows a sample; the module holds the full set). The test suite expands
each alias across 15 neutral question frames → 5,985 utterances, 100% resolved.

**Roles (STEP 9):**
- `both` (20) = ATTRIBUTE_QUERY **and** FILTERABLE (e.g. "sunroof hai?" answers the
  car; "sunroof wali car" filters inventory).
- `attr` (47) = ATTRIBUTE_QUERY only (dimensions, engine, EV specifics, keys, extra
  docs — filtering these adds no business value / data is sparse).

**Attribute vs filter** is decided by a filter cue (wali/wale/chahiye/with/dikhao/
वाली/पाहिजे…): cue + a `both` field → filter; otherwise → attribute question.

**Deconfliction:** boot↔Sedan, android-auto↔Automatic, fuel-tank↔fuel_query,
ev-range↔Electric, sunroof/airbag↔off_sheet are all resolved (see audit).

---

| Field (attr) | Display | Type | Role | Sample aliases |
|---|---|---|---|---|
| engine_cc | Engine | int | attr | engine cc, engine capacity, cc kitna, kitna cc |
| power_bhp | Power | float | attr | power bhp, bhp, horsepower, kitni power |
| torque_nm | Torque | float | attr | torque, nm torque, kitna torque, टॉर्क |
| aspiration | Aspiration | enum | attr | aspiration, turbo hai, turbo, naturally aspirated |
| transmission_subtype | Gearbox type | enum | both | amt, cvt, dct, dsg |
| gears | Gears | int | attr | number of gears, kitne gears, how many gears, gear count |
| drivetrain | Drive type | enum | both | drivetrain, drive type, fwd, rwd |
| mileage_arai_kmpl | Mileage (ARAI) | float | attr | mileage kitna, mileage kitni, kitna mileage, average kitna |
| fuel_tank_l | Fuel tank | int | attr | fuel tank, tank capacity, fuel tank capacity, tank kitna |
| boot_litres | Boot space | int | attr | boot space, boot capacity, boot litres, dicky space |
| ground_clearance_mm | Ground clearance | int | attr | ground clearance, clearance kitna, gc kitna, high clearance kitna |
| wheelbase_mm | Wheelbase | int | attr | wheelbase, wheel base, व्हीलबेस |
| length_mm | Length | int | attr | length kitni, car length, kitni lambi, lambai |
| width_mm | Width | int | attr | width kitni, car width, kitni chaudi, chaudai |
| height_mm | Height | int | attr | height kitni, car height, kitni unchi, उंची किती |
| sunroof_type | Sunroof | enum | both | sunroof, sun roof, moonroof, panoramic roof |
| headlamp_type | Headlamps | enum | both | led headlight, led headlights, led lights, projector headlamp |
| drl | DRLs | bool | both | drl, drls, daytime running lamp, daytime running lights |
| fog_lamps | Fog lamps | bool | both | fog lamp, fog lamps, fog light, fog lights |
| wheel_type | Wheels | enum | both | alloy, alloys, alloy wheel, alloy wheels |
| wheel_size_inch | Wheel size | int | attr | wheel size, tyre size, rim size, kitne inch tyre |
| roof_rails | Roof rails | bool | attr | roof rail, roof rails, रूफ रेल |
| spoiler | Spoiler | bool | attr | spoiler, स्पॉयलर |
| upholstery | Upholstery | enum | both | leather seats, leather seat, leather interior, fabric seats |
| ac_type | AC | enum | attr | climate control, automatic climate control, auto ac, ac type |
| rear_ac_vents | Rear AC vents | bool | both | rear ac, rear ac vents, back ac, rear vents |
| power_windows | Power windows | enum | attr | power window, power windows, auto windows, पॉवर विंडो |
| adjustable_seat | Seat adjust | enum | attr | adjustable seat, height adjust, seat height, power seat |
| ventilated_seats | Ventilated seats | bool | both | ventilated seat, ventilated seats, cooled seats, व्हेंटिलेटेड सीट |
| cruise_control | Cruise control | bool | both | cruise control, cruise, क्रूझ कंट्रोल |
| keyless_entry | Keyless entry | bool | both | keyless entry, keyless, smart key, smart entry |
| push_button_start | Push-button start | bool | both | push button, push button start, start stop button, button start |
| auto_folding_orvm | Auto-folding mirrors | bool | attr | auto folding mirror, auto fold orvm, electric mirror, folding mirror |
| rear_defogger | Rear defogger | bool | attr | defogger, rear defogger, demister, डिफॉगर |
| rear_wiper | Rear wiper | bool | attr | rear wiper, back wiper, मागचा वायपर |
| wireless_charging | Wireless charging | bool | attr | wireless charging, wireless charger, वायरलेस चार्जिंग |
| connected_car | Connected car | bool | attr | connected car, connected tech, car connectivity, remote start app |
| touchscreen_inches | Touchscreen | float | attr | touchscreen, touch screen, infotainment, display screen |
| android_auto_carplay | Android Auto / CarPlay | bool | both | android auto, apple carplay, carplay, car play |
| speakers | Speakers | int | attr | speakers, music system, stereo, sound system |
| camera_type | Camera | enum | both | reverse camera, rear camera, back camera, 360 camera |
| steering_controls | Steering controls | bool | attr | steering control, steering mounted, steering buttons, audio controls on steering |
| airbags | Airbags | int | both | airbag, airbags, kitne airbag, how many airbags |
| abs_ebd | ABS/EBD | bool | both | abs, ebd, anti lock brakes, abs ebd |
| esp | ESP | bool | both | esp, esc, stability control, traction control |
| hill_hold | Hill-hold | bool | attr | hill hold, hill assist, hill start assist |
| parking_sensors | Parking sensors | enum | both | parking sensor, parking sensors, rear sensor, reverse sensor |
| isofix | ISOFIX | bool | attr | isofix, child seat mount, child seat anchor |
| ncap_rating | NCAP rating | int | attr | ncap, ncap rating, safety rating, crash rating |
| keys_count | Keys | int | attr | number of keys, how many keys, kitni chabi, kitni keys |
| spare_key | Spare key | bool | attr | spare key, duplicate key, extra key, second key |
| spare_tyre | Spare tyre | bool | attr | spare tyre, spare wheel, stepney, extra tyre |
| toolkit | Toolkit | bool | attr | toolkit, tool kit, jack, tools |
| floor_mats | Floor mats | bool | attr | floor mat, floor mats, 7d mats, car mats |
| accessories_added | Accessories | text | attr | accessories, extra fitting, after market, accessories added |
| puc_valid_till | PUC | text | attr | puc, puc valid, pollution certificate, pollution valid |
| road_tax_status | Road tax | enum | attr | road tax, tax paid, lifetime tax, road tax status |
| fitness_valid_till | Fitness | text | attr | fitness certificate, fitness valid, fc valid, फिटनेस |
| duplicate_rc | Duplicate RC | bool | attr | duplicate rc, duplicate registration |
| usage_type | Usage | enum | both | private use, taxi use, commercial use, corporate car |
| tyre_life_pct | Tyre life | int | attr | tyre life, tyre condition percent, tyre percent, tyres kitne percent |
| battery_health_pct | Battery health | int | attr | battery health, battery condition percent, battery percent, soh |
| real_range_km | Range | int | attr | real range, ev range, driving range, full charge range |
| battery_warranty_till | Battery warranty | text | attr | battery warranty, battery guarantee, बॅटरी वॉरंटी |
| charger_type | Charger | text | attr | charger type, charger included, ac charger, dc charger |
| charging_time | Charging time | text | attr | charging time, charge time, kitni der charging, charge hone mein |
| battery_owned | Battery owned | bool | attr | battery owned, battery lease, battery leased, battery rented |
