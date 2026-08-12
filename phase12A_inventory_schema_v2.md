# Phase 12A — Ideal Inventory Schema v2 (STEP 4)

*Design only. Nothing implemented.* The target knowledge model for a professional
used-car dealership chatbot, grouped into logical sections. Every field is chosen
so it can be answered **deterministically (no LLM)**.

**Legend** (per field):
`M` Mandatory · `C` Customer-visible · `E` Editable in owner panel · `S` Searchable ·
`F` Filterable · `A` Answerable by chatbot. ✓ = yes, – = no, ~ = conditional.

Design principles: reuse existing fields where possible; every customer field
maps to a chatbot answer; booleans stored as Yes/No/Unknown (Unknown → "Data not
available", never fabricated); enums fixed for deterministic matching; internal
fields never customer-visible.

---

## 1. Vehicle Identity  *(mostly exists)*
| Field | Type | Example | M C E S F A |
|---|---|---|---|
| registration_no | text (PK) | MH01AB1234 | ✓ – ~ ✓ – ~ |
| make / make_full | code/text | HYUN / Hyundai | ✓ ✓ ✓ ✓ ✓ ✓ |
| model | text | Creta | ✓ ✓ ✓ ✓ ✓ ✓ |
| variant / trim | text | SX(O) | ~ ✓ ✓ ✓ ✓ ✓ |
| year_int | int | 2019 | ✓ ✓ ✓ ✓ ✓ ✓ |
| color_norm | enum | White | ✓ ✓ ✓ ✓ ✓ ✓ |
| body_type | enum | SUV | ✓ ✓ ✓ ✓ ✓ ✓ |
| stock_no / id | int/uuid | 42 | ✓ – – – – – (internal) |

## 2. Pricing  *(mostly exists)*
| Field | Type | Example | M C E S F A |
|---|---|---|---|
| price_inr / price_lakh | int/float | 950000 / 9.5 | ✓ ✓ ✓ – ✓ ✓ |
| price_quotable | bool | true | ✓ ~ ✓ – – ✓ |
| price_range_low/high | int | 9–10 L | ~ ✓ ✓ – ✓ ✓ |
| negotiable | bool | No (fixed) | ~ ✓ ✓ – – ✓ |
| on_road_estimate | calc | ~10.2 L | – ✓ – – – ✓ (CALC) |

## 3. Engine  *(NEW)*
| Field | Type | Example | M C E S F A |
|---|---|---|---|
| engine_cc | int | 1497 | ~ ✓ ✓ ✓ ✓ ✓ |
| power_bhp | number | 113 | – ✓ ✓ – ✓ ✓ |
| torque_nm | number | 144 | – ✓ ✓ – – ✓ |
| cylinders / aspiration | enum | Turbo | – ✓ ✓ – – ✓ |

## 4. Transmission  *(exists + NEW subtype)*
| Field | Type | Example | M C E S F A |
|---|---|---|---|
| transmission_norm | enum | Automatic | ✓ ✓ ✓ ✓ ✓ ✓ |
| transmission_subtype | enum | CVT/AMT/DCT/iMT/TC | – ✓ ✓ ✓ ✓ ✓ |
| gears | int | 6 | – ✓ ✓ – – ✓ |
| drivetrain | enum | FWD/AWD/4WD | – ✓ ✓ – ✓ ✓ |

## 5. Fuel & Economy  *(exists + NEW)*
| Field | Type | Example | M C E S F A |
|---|---|---|---|
| fuel_norm | enum | Petrol | ✓ ✓ ✓ ✓ ✓ ✓ |
| cng_kit_type | enum | Company/After-market/None | – ✓ ✓ ✓ ✓ ✓ |
| mileage_arai_kmpl | number | 17.4 | – ✓ ✓ – ✓ ✓ |
| claimed_mileage_kmpl | number | 15 | – ✓ ✓ – ✓ ✓ (exists) |
| fuel_tank_l | int | 50 | – ✓ ✓ – – ✓ |

## 6. Dimensions & Capacity  *(NEW)*
| Field | Type | Example | M C E S F A |
|---|---|---|---|
| seats | int | 7 | ✓ ✓ ✓ ✓ ✓ ✓ (exists) |
| length/width/height_mm | int | 4300 | – ✓ ✓ – – ✓ |
| wheelbase_mm | int | 2610 | – ✓ ✓ – – ✓ |
| boot_litres | int | 433 | – ✓ ✓ – ✓ ✓ |
| ground_clearance_mm | int | 190 | – ✓ ✓ – ✓ ✓ |

## 7. Exterior & Lights  *(NEW)*
| Field | Type | Example | M C E S F A |
|---|---|---|---|
| headlamp_type | enum | LED/Projector/Halogen | – ✓ ✓ – ✓ ✓ |
| drl / fog_lamps | bool | Yes | – ✓ ✓ – ✓ ✓ |
| wheel_type / size | enum/int | Alloy / 16" | – ✓ ✓ – ✓ ✓ |
| sunroof_type | enum | None/Single/Panoramic | – ✓ ✓ ✓ ✓ ✓ |
| roof_rails / spoiler | bool | Yes | – ✓ ✓ – – ✓ |

## 8. Interior & Comfort  *(NEW)*
| Field | Type | Example | M C E S F A |
|---|---|---|---|
| upholstery | enum | Fabric/Leather/Leatherette | – ✓ ✓ – ✓ ✓ |
| ac_type | enum | Manual/Auto-climate | – ✓ ✓ – ✓ ✓ |
| rear_ac_vents | bool | Yes | – ✓ ✓ – ✓ ✓ |
| power_windows | enum | All 4 / Front | – ✓ ✓ – – ✓ |
| adjustable_seat | enum | Height/Manual/Power | – ✓ ✓ – – ✓ |

## 9. Convenience  *(NEW)*
| Field | Type | Example | M C E S F A |
|---|---|---|---|
| push_button_start / keyless | bool | Yes | – ✓ ✓ – ✓ ✓ |
| cruise_control | bool | Yes | – ✓ ✓ – ✓ ✓ |
| auto_folding_orvm | bool | Yes | – ✓ ✓ – – ✓ |
| rear_defogger / wiper | bool | Yes | – ✓ ✓ – – ✓ |
| wireless_charging / ventilated_seats / connected_car | bool | Yes | – ✓ ✓ – ✓ ✓ |

## 10. Infotainment  *(NEW)*
| Field | Type | Example | M C E S F A |
|---|---|---|---|
| touchscreen_inches | number | 10.25 | – ✓ ✓ – ✓ ✓ |
| android_auto_carplay | bool | Yes | – ✓ ✓ – ✓ ✓ |
| speakers | int | 6 | – ✓ ✓ – – ✓ |
| reverse_camera / camera_360 | enum | Reverse/360/None | – ✓ ✓ ✓ ✓ ✓ |
| steering_controls | bool | Yes | – ✓ ✓ – – ✓ |

## 11. Safety  *(NEW)*
| Field | Type | Example | M C E S F A |
|---|---|---|---|
| airbags | int | 6 | – ✓ ✓ ✓ ✓ ✓ |
| abs_ebd / esp / hill_hold | bool | Yes | – ✓ ✓ – ✓ ✓ |
| parking_sensors | enum | Rear/Front+Rear/None | – ✓ ✓ – ✓ ✓ |
| isofix | bool | Yes | – ✓ ✓ – – ✓ |
| ncap_rating | int (stars) | 5 | – ✓ ✓ – ✓ ✓ |

## 12. Documents  *(exists + NEW)*
| Field | Type | Example | M C E S F A |
|---|---|---|---|
| rc_status | enum | Clear/Hypothecated/Pending | ✓ ✓ ✓ – ✓ ✓ (exists) |
| hypothecation_bank / loan_closed / noc_available | text/bool | HDFC / Yes | ~ ✓ ✓ – – ✓ (exists) |
| finance_eligible | bool | Yes | – ✓ ✓ – ✓ ✓ (exists) |
| puc_valid_till | date | 2026-12 | – ✓ ✓ – – ✓ (NEW) |
| road_tax_status | enum | Paid/Lifetime | – ✓ ✓ – – ✓ (NEW) |
| fitness_valid_till | date | (commercial) | – ✓ ✓ – – ✓ (NEW) |
| duplicate_rc / keys_count | bool/int | No / 2 | – ✓ ✓ – – ✓ (NEW) |

## 13. Ownership  *(exists)*
| Field | Type | Example | M C E S F A |
|---|---|---|---|
| ownership_count | int | 1 | ✓ ✓ ✓ ✓ ✓ ✓ |
| usage_type | enum | Private/Taxi/Corporate | – ✓ ✓ ✓ ✓ ✓ (NEW) |

## 14. Insurance  *(exists — needs data)*
| Field | Type | Example | M C E S F A |
|---|---|---|---|
| insurance_type | enum | Comprehensive/TP/Expired | – ✓ ✓ – ✓ ✓ |
| insurance_expiry | date | 2026-03 | – ✓ ✓ – – ✓ |
| zero_dep / insurance_claim_history | bool | No | – ✓ ✓ – – ✓ |

## 15. Warranty  *(exists — needs data)*
| Field | Type | Example | M C E S F A |
|---|---|---|---|
| warranty_available / warranty_expiry / warranty_provider | bool/date/text | Yes / 2026 / OEM | – ✓ ✓ – ✓ ✓ |

## 16. Condition & Inspection  *(exists — needs data)*
| Field | Type | Example | M C E S F A |
|---|---|---|---|
| accident_free / flood_damage / repainted | bool | Yes/No | – ✓ ✓ – ✓ ✓ |
| body/engine/interior/tyre/brake/clutch/battery_condition | enum | Excellent/Good/Fair | – ✓ ✓ – ~ ✓ |
| tyre_life_pct / battery_replaced_on | int/date | 70% / 2024 | – ✓ ✓ – – ✓ (NEW) |
| inspection_score | int (calc) | 8/10 | – ✓ – – ✓ ✓ (CALC/NEW) |

## 17. Keys & Accessories  *(NEW)*
| Field | Type | Example | M C E S F A |
|---|---|---|---|
| keys_count / spare_key | int/bool | 2 / Yes | – ✓ ✓ – – ✓ |
| spare_tyre / toolkit / floor_mats | bool | Yes | – ✓ ✓ – – ✓ |
| accessories_added | text | 7D mats, camera | – ✓ ✓ – – ✓ |

## 18. EV-Specific  *(NEW, conditional on fuel=Electric)*
| Field | Type | Example | M C E S F A |
|---|---|---|---|
| battery_health_pct | int | 92 | ~ ✓ ✓ – ✓ ✓ |
| real_range_km / battery_warranty_till | int/date | 350 / 2029 | ~ ✓ ✓ – ✓ ✓ |
| charger_type / charging_time | enum/text | AC 7kW / 6h | ~ ✓ ✓ – – ✓ |
| battery_owned | bool | Yes | ~ ✓ ✓ – – ✓ |

## 19. Sales Intelligence / Dealer Notes  *(exists)*
| Field | Type | Example | M C E S F A |
|---|---|---|---|
| reason_for_sale | text | Upgrade | – ✓ ✓ – – ✓ |
| best_features | text | Sunroof, 1 owner | – ✓ ✓ ✓ – ✓ |
| known_issues | text | Minor scratch | – ✓ ✓ – – ✓ |

## 20. Media  *(exists — complete)*
| Field | Type | Example | M C E S F A |
|---|---|---|---|
| exterior/interior photos, video, instagram, youtube URLs | urls | … | – ✓ ✓ – – ✓ |
| photo_count / video_count | int | 8 / 1 | – ✓ – – – ✓ |

## 21. System Fields  *(exists — internal)*
`listing_status`, `customer_viewable`, `is_placeholder`, `location_code/type`,
`rto`, `source_sheet`, `as_of`, timestamps, `raw`. → **C = –** (never shown), used
for retrieval/audit only.

---

## Data-entry burden control

To keep this maintainable, group fields by entry effort in the owner panel:

- **Tier 1 (must fill / already fill):** identity, price, fuel, transmission, km, owners, colour, condition booleans, RC status.
- **Tier 2 (fill per car, high value):** airbags, sunroof, camera, key features, service/insurance/warranty, keys count.
- **Tier 3 (auto-fill by make+model+variant lookup):** engine cc, power, mileage(ARAI), dimensions, standard features — these are **model-level specs**, so a small `model_specs` reference table can populate them automatically, drastically cutting manual entry. *(Recommended design: a spec library keyed by make+model+variant+year.)*

This spec-library idea is the single biggest lever for answering Sections D–Q
without heavy per-car data entry. See gap analysis + roadmap.
