# Phase 12C.5 — Validation

The change is client-side only (`vehicle_details.html`). Backend persistence was
already proven in Phase 12C (14/14 + 6 pytest). Here we validate the new UX layer
deterministically where possible; visual/device checks are listed for the operator
(the Browser pane could not be rendered in this environment).

## Deterministic checks (automated)

| Check | Result |
|---|---|
| Field-def ↔ live schema mapping (header **or** label) | **114 defs, 0 editable columns fall through** |
| All REQUIRED ids resolve to a real column | ✅ Model, Year, Fuel Type, Transmission, Owners, KM Driven, Rate (Rs), Colour, RC Status |
| Dependency field-keys resolve (Fuel Type, Spare Key, Warranty Available, RC Status) | ✅ |
| Page + assets served | `vehicle_details.html` 200, `auth_guard.js` 200 |
| API gating intact | `/admin/inventory/schema` → 403 without token |

## STEP 14 — feature validation

| Item | How verified |
|---|---|
| Add Car / Edit Car | shares 12C's proven get_car/add_car/update_car (14/14) |
| Partial Save | only dirty fields sent; hidden/irrelevant excluded from completion |
| Reload / persist | 12C persistence tests (`phase12c_tests.py`) still green |
| Search (partial+synonym) | synonym map + substring over section+name+label; auto-expands section |
| Dependencies | EV↔engine swap, spare-key→keys, warranty details, hypothecation — all keyed to resolved fields |
| Dropdowns | enum control with legacy-value preservation (no data loss) |
| Validation | 20 range validators + date pattern; blocks save, scrolls to first error |
| Completion | overall + per-section + missing-required + Ready-for-sale |
| Unsaved warning | `beforeunload` when dirty |

## Operator visual pass (recommended)
Log in → Inventory → a car's **Details**, then confirm on **desktop / tablet /
mobile**: sticky Save & Summary, collapse animation, dropdowns, changing Fuel to
Electric swaps Engine↔EV, entering Year 3000 shows a validation message and blocks
Save (scrolls to it), search "gearbox" jumps to Transmission, and leaving with
unsaved edits prompts a warning.

## Design-principle compliance
No redesign · no AI/LLM · no auto-population · no workflow/API changes · optional
fields never forced · dealership remains source of truth.
