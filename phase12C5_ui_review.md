# Phase 12C.5 — Vehicle Details UI Review & Polish

UI/UX-only phase. The **only file changed is `vehicle_details.html`** (client-side
HTML/CSS/JS). No chatbot, intent, conversation, retrieval, media, owner panel,
auth, permissions, audit, loader, model_specs, Excel or API code was touched.

## STEP 1 — Usability issues found in the 12C page → fixed here

| Issue (12C) | Fix (12C.5) |
|---|---|
| Every attribute always visible → overwhelming for a 300–400 car workflow | **Field dependencies** hide irrelevant fields (EV vs engine, spare-key→keys, warranty details, hypothecation) + **conditional EV section** |
| Fuel/Transmission/Owners were free-text | **Dropdowns** (codes preserved) + legacy-value preservation |
| No input validation → impossible values could be saved | **Smart validation** with friendly messages, blocks save |
| No required/optional signal | **REQUIRED / RECOMMENDED badges** + Ready-for-sale |
| Small touch targets, non-sticky save on long form | **44px targets, sticky bar + Save + Summary, no horizontal scroll** |
| Could lose edits by navigating away | **Unsaved-changes warning** (beforeunload) |
| Completion was overall+section only | **+ Missing-critical list + Ready-for-sale indicator** |
| Save errors gave no guidance | **First-error scroll + highlight + inline messages** |
| Search was substring only | **Partial + synonyms + case-insensitive + auto-expand** |
| Plain collapse, minimal polish | **Section icons, collapse animation, loading skeletons, richer states** |

## STEP 2 — Field dependencies (dynamic visibility)
- **Fuel = Electric →** show EV section (Battery Health, Real Range, Battery
  Warranty, Charger Type, Charging Time, Battery Owned); hide Engine CC, Fuel
  Tank, Mileage ARAI, Claimed Mileage, Aspiration.
- **Fuel ≠ Electric →** hide the EV section entirely.
- **Spare Key = No →** hide Keys Count.
- **Warranty Available = No →** hide Warranty Expiry & Provider.
- **RC Status ≠ Hypothecated →** hide Hypothecation Bank & Loan Closed.
- Hidden fields are excluded from completion and validation (never counted/forced).

## STEP 3 — Dropdowns (free-text → controlled)
Fuel, Transmission, Owners, Insurance Type, RC Status, Road Tax, Usage Type,
Service Center, Body/Engine/Interior/Tyre/Brake/Clutch/Battery Condition, Sunroof
Type, Headlamp, Wheel Type, Camera Type, Parking Sensors, Drivetrain, Transmission
Subtype, Upholstery, AC Type, Aspiration, Power Windows, Adjustable Seat. Accident/
Flood/etc. are Yes/No checkboxes. Free-text kept only where genuinely open
(Model, Variant, Colour, RTO, Hypothecation Bank, Provider, Remarks, Accessories).
**Legacy values are preserved** — any stored value not in the option list is added
as an option so nothing is lost.

## STEP 4 — Smart validation (friendly, blocking)
Year (1990–2027), KM (0–1,000,000), Engine CC (300–8000), Mileage (2–50), Fuel
Tank (5–120), Airbags (0–12), NCAP (0–5), Touchscreen (4–20"), Speakers (0–20),
Gears (4–10), Wheel Size (10–24"), Battery % (0–100), Tyre % (0–100), Real Range
(20–1000), Charging Time (needs a number), Price ranges (≥0), and dates
(YYYY-MM-DD / DD/MM/YYYY). Impossible values are rejected with a clear message.

## STEP 5 — Conditional sections
The **EV** section appears only for electric cars. Other sections always apply to a
used car, so they stay available (never hidden in a way that blocks entry) — the
overwhelm is solved by dependencies + collapse, not by hiding needed sections.

## STEP 6 — Mobile / tablet
44px min touch targets, single-column grid ≤680px, sticky header + action bar +
Summary, larger checkboxes (24px), `inputmode` on numbers, no horizontal scroll,
smooth section collapse.

## STEP 7–13 (summary)
- **7 Unsaved protection:** `beforeunload` warns when dirty (cleared on save/logout).
- **8 Completion:** overall %, per-section %, **Missing required** (clickable to
  jump), **Ready-for-sale** badge (all required filled).
- **9 First-error nav:** failed validation scrolls to + highlights the first
  invalid field and expands its section.
- **10 Keyboard:** Tab through controls; **Ctrl/Cmd+S saves**; section headers are
  focusable and toggle on Enter/Space (a11y).
- **11 Required vs Optional:** REQUIRED (red) / RECOMMENDED (amber) badges; optional
  never forced; partial save always allowed.
- **12 Search:** partial + synonyms (mileage→km, gearbox→transmission, camera→
  reverse/360, papers→rc/noc/puc, ev→battery/charging…) + case-insensitive +
  auto-expands the matching section and scrolls to the first hit.
- **13 Polish:** section icons, animated collapse, loading skeletons, and clear
  No-changes → Unsaved → Saving… → ✓ Saved / ✗ error states — same design language.

## Not changed (by design)
No redesign, no AI/LLM, no auto-population, no workflow/API change. The dealership
remains the single source of truth; get_car still returns raw saved cells.
