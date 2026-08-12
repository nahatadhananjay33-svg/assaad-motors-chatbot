# Phase 12C — Validation

Two layers of validation: (1) automated persistence tests on a **copy** of the
workbook (`phase12c_tests.py`, in the regression suite), and (2) a full-flow
integration check (`scratchpad/phase12c_validate.py`). No live data was polluted.

## STEP 15 checklist

| Item | How verified | Result |
|---|---|---|
| ✓ Add Car | `add_car` with new reg + fields → get_car returns them | ✅ |
| ✓ Edit Car | `get_car` populates all saved values; controls mapped by header | ✅ |
| ✓ Partial Save | only dirty fields sent; untouched fields stay empty | ✅ |
| ✓ Reload | `refresh_inventory()` + get_car after save | ✅ |
| ✓ Data persists | values survive save → reload → re-read | ✅ |
| ✓ Completion % | filled ÷ total per section + overall (live recompute) | ✅ |
| ✓ Search | field-def `data-search` index → jump/highlight | ✅ (logic verified) |
| ✓ Summary Card | ✓/✗ derived from saved values | ✅ (logic verified) |
| ✓ Every section | 20 sections render from field-defs; 0 unmapped editable cols | ✅ |
| ✓ Every control | checkbox/enum/number/text/date/textarea per field type | ✅ |

## Automated results

```
phase12c_tests.py ......  6 passed
  • schema exposes new headers (Engine CC, Airbags, Sunroof Type, Keys Count, RC Status)
  • migration added every one of the 68 grouped columns (all discoverable)
  • partial save + reload persists
  • incremental partial save keeps earlier fields
  • persists across refresh_inventory()
  • add_car with new fields persists
```

Full-flow harness (`phase12c_validate.py`) on a copy: **14 / 14 passed** —
Edit + partial (Safety only), second partial (Interior) keeping Safety, reload
persistence, and Add-car, all green. A test car (`MH02EZ6001`) showed **60
non-empty cells** feeding the completion meter.

## Field-mapping audit (deterministic)

- **113** form field-definitions; **every editable Excel column maps to a control**
  — 0 columns fall through to "Other Information".
- No dead field-defs after removing one stray duplicate header.
- Media / system / URL / STATUS / LAST_UPDATED columns are correctly excluded from
  the data-entry form (media stays in its own workflow — untouched).

## Serving / access

- `vehicle_details.html` → HTTP **200**; `auth_guard.js` → **200**.
- `/admin/inventory/schema` without a token → **403** (permissions untouched and
  still enforced).

## Design-principle compliance
- **No auto-population** in the form — get_car returns raw saved cells (the 12B
  model_specs auto-fill affects only the chatbot's in-memory answers, never the
  Excel or this form).
- **Never forces** a field — partial save is first-class; missing fields are only
  softly highlighted.
- **Dealership is source of truth** — every attribute is manually editable.
