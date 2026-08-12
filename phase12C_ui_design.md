# Phase 12C — Vehicle Details Management UI (Design)

A clean, dealership-friendly data-entry screen for filling **every** vehicle
attribute manually. Built as a single self-contained page
`app/inventory_system/vehicle_details.html` served on the static site (:8080).

**Scope honoured — NOT modified:** chatbot, retrieval/RAG, intent engine,
conversation engine, authentication, permissions, audit logs, media upload
workflow, Supabase, owner panel, user management. The only backend touch is one
**additive** line in `inventory_edit._discover_fields` (exposes the raw column
header so the form can map controls). No auto-population in the form — the
dealership is the single source of truth.

---

## How it connects (reuses existing endpoints)

```
vehicle_details.html
   │  auth_guard.js  → session token
   ├─ GET  /admin/inventory/schema      → columns (key, header, label, editable, type)
   ├─ POST /admin/inventory/get_car     → current saved values  {c<col>: value}
   ├─ POST /admin/inventory/update_car  → save (edit)   partial allowed
   └─ POST /admin/inventory/add_car     → save (add)    partial allowed
```

Persistence is real: the Phase-12C migration added the 68 grouped columns to the
DNJ sheet, and the existing dynamic backend reads/writes them by column. **No
backend rewrite.**

## STEP 2 — Grouped, collapsible sections
20 independent collapsible sections in a fixed order: Vehicle Basics · Pricing ·
Ownership · Registration · Insurance · Engine · Transmission · Exterior · Interior ·
Comfort · Infotainment · Safety · Accessories · Mechanical Condition · Documents ·
Keys · Warranty · Finance · Remarks · Other Information. A staffer can open just
one section ("today I only do Safety") and ignore the rest.

## STEP 3–4 — Proper controls
A frontend field-definition map (header → section + control) renders the right
control per field:
- **Yes/No feature fields → checkboxes:** Sunroof, ABS/EBD, ESP, Hill-hold,
  Fog Lamps, DRL, Android Auto/CarPlay, Cruise Control, Keyless Entry, Push-button
  Start, Rear AC, Ventilated Seats, Steering Controls, ISOFIX, Rear Wiper/Defogger,
  Wireless Charging, Connected Car, Spare Key/Tyre, Toolkit, Floor Mats, etc.
- **Dropdowns (enum):** Fuel-adjacent enums, Sunroof Type, Headlamp Type, Wheel
  Type, Camera Type, Parking Sensors, RC Status, Insurance Type, Body/Engine/
  Interior/Tyre/Brake/Clutch/Battery Condition, Service Center, Drivetrain,
  Transmission Subtype, Upholstery, AC Type, Road Tax, Usage Type, etc.
- **Number:** Airbags, Engine CC, Power, Torque, Speakers, Touchscreen, dimensions,
  KM, Owners, Keys Count, NCAP, Tyre Life %.
- **Text / Date-like:** RTO, Hypothecation Bank, expiry/validity dates.
- **Textarea:** Reason for Sale, Best Features, Known Issues, Accessories Added.

Every editable Excel column maps to a control (0 fall-through verified); anything
unmapped would land in "Other Information."

## STEP 5 — Independent sections
Each section is a self-contained collapsible card with its own completion meter, so
work can be split across days/people.

## STEP 6 — Save-state indicator (UI only)
A live pill shows **No changes → Unsaved changes → Saving… → ✓ Saved successfully**
(or an error). No background autosave — saving is on the **Save** button; the
indicator only reflects the dirty/committed state as required.

## STEP 7 — Edit Car
`vehicle_details.html?reg=MH01AB1234` loads all saved values via get_car and
populates every control correctly. Reached from a per-row **Details** button added
to the inventory dashboard.

## STEP 8 — Add Car
`vehicle_details.html?add=1` starts empty except the mandatory registration; saves
via add_car, then reopens in edit mode on the new reg.

## STEP 9 — Partial save
Only fields the user actually changed (dirty-tracked) are sent. Nothing is forced;
you can fill Safety today, Interior tomorrow, Documents next week.

## STEP 10 — Completion %
An overall meter plus a per-section meter (filled ÷ total in that section), e.g.
"Safety 100% · Interior 40% · Documents 75%", recomputed live as you type.

## STEP 11 — Missing-field highlighting
Empty editable fields get a soft amber highlight — a gentle nudge, never a block.

## STEP 12 — In-form search
The search box filters and jumps: typing `sunroof` scrolls to and highlights the
Sunroof field; typing `insurance` opens the Insurance section.

## STEP 13 — Quick Summary card
A top card shows ✓/✗ for key features (Sunroof, Android Auto, Reverse/360 Camera,
Cruise Control, ABS, Airbags count, Alloy Wheels, Keyless, Push-button, Rear AC)
so staff can verify at a glance.

## STEP 14 — Low clicks
Single scrollable page, sections collapsible, everything inline — no modal
hopping, no page reloads between fields; one Save commits the batch.

## Determinism & safety
No AI/LLM, no auto-population, no workflow changes. Empty fields persist as empty
("Data not available" downstream) — the dealership remains the source of truth.
