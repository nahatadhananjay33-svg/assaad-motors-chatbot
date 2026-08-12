# Phase 9C — Dynamic Inventory Management — Final Report

**Date:** 2026-07-29
**Goal:** Make the owner Inventory Dashboard fully dynamic — the Add/Edit/View
form is generated from the **actual Excel columns**, so new columns appear
automatically with no code change. Excel remains the single source of truth.

**Scope guardrail (honoured):** no changes to chatbot, retrieval, RAG, pricing,
Marathi, Supabase/media workflow, logging, or security. Reuses the inventory
loader, `inventory_upload.handle_status`, `refresh_inventory()`, and the media
page.

---

## 1. Files changed

| File | Change |
|------|--------|
| `app/inventory_system/inventory_edit.py` | **Rewritten** — dynamic schema discovery from Excel columns; `get_car`/`update_car`/`add_car` now keyed by column (`c<n>`); grouping + read-only classification by header keywords; new `handle_duplicate_audit`; dashboard now includes KM. |
| `app/inventory_system/chat_api.py` | Registered `POST /admin/inventory/duplicate_audit`; fixed `schema` route to pass `service`. |
| `app/inventory_system/inventory_admin.html` | **Rewritten** — dynamic grouped form (Add/Edit/View), sorting (Price/Year/KM/Last-Updated), smart brand search, View Details, Add-with-precheck, Duplicate Audit button. |
| *(media_admin.html unchanged this phase — the Phase-9B `?car=` deep-link is reused.)* | |

**Generated deliverables**
- `phase9C_excel_schema.md` — the Excel audit (STEP 1).
- `app/duplicate_inventory_report.xlsx` — duplicate CAR NUMB report (STEP 6): registration, occurrences, sheet, row, model, suggested action.
- `phase9C_validation_report.md` — validation (STEP 9).

**New / changed endpoints** (all admin-key gated)
- `GET /admin/inventory/schema` → dynamic grouped fields (`{groups, car_numb_key, field_count}`).
- `POST /admin/inventory/get_car | update_car | add_car` → values keyed by `c<col>`.
- `POST /admin/inventory/duplicate_audit` → scans workbook, writes the report.
- `GET /admin/inventory/dashboard` → summary + table (now incl. KM).

---

## 2. How it works (design)

- **Dynamic schema** — `_discover_fields()` reads the DNJ header rows (row 2 labels + row 3 descriptions) at request time and emits one field per column, each with a stable key `c<col>`, a friendly label, a **group**, and an **editable** flag. Nothing about the field list is hardcoded.
- **Grouping** — by keyword rules on the header text (Media, Status, Pricing, Documents, Vehicle Details, Vehicle Information); anything unmatched → **Other Information** (never hidden). A new column lands in the right section automatically.
- **Read-only policy** — `CAR NUMB` (identity), plus **media** and **system** columns (managed by the Media panel + Supabase + sold workflow, which the rules forbid touching). Everything else is editable. The server also **re-checks** editability on write, so a read-only column can never be changed even if posted.
- **Add precheck** — asks CAR NUMB first, checks existence; if found → "This vehicle already exists. Would you like to Edit it instead?"; the server also rejects duplicates with HTTP 409. No duplicate rows are ever created.
- **Smart search** — a brand-synonym table expands each row's search text (e.g. stored `MARU` also matches "maruti"/"suzuki"). **Stored Excel values are never modified** — only the in-memory search index.
- **Only that row is written** — `openpyxl` load → edit one row → atomic save (with backup + file lock) → `refresh_inventory()`.

---

## 3. Screenshots

Pixel screenshots could not be captured this run (the automated browser pane was
not compositing frames). Verification was done by driving the live page's real
handlers and reading the DOM. Captured states:

- Dashboard after Connect: `Cars Live 44 · Available 44 · Reserved 0 · Sold 1 · 2026-07-28 · IVR_Sheet.xlsx`; table row `MH01BK9444 · MERCEDES · E 200 · 2014 · 21000 · ₹6.10 L · AVAILABLE · [View][Edit][Media][Mark Sold]`.
- Sort Price desc → Fortuner ₹8.75 L; asc → City ₹0.88 L; Year desc → Nexon 2022.
- Smart search: maruti→10, honda→5, toyota→6.
- View Details (MH49AT3584): 94 fields across 6 groups, all read-only, Save hidden.
- Edit (MH49AT3584): 94 fields, 48 editable / 46 read-only, CAR NUMB locked, Rate editable, Save visible.

*(The page is plain HTML/JS and renders normally in any browser.)*

---

## 4. Validation

See `phase9C_validation_report.md` — **every listed feature PASS**, backend
15/15, and the extensibility claim proven live (added an Excel column → it
appeared as a new form field with no code change).

---

## 5. Performance

schema ~0.7 s · dashboard ~0.9 s · get_car ~1 s · update_car+refresh ~1.5 s ·
duplicate_audit (all sheets) ~1.5 s. Read handlers use a normal (non-`read_only`)
openpyxl load for fast random access — scales past 500 cars.

---

## 6. Regression summary

**None.** `chat_api_tests` 19 OK, `inventory_upload_tests` 8 OK. Chatbot, media,
Supabase, sold, refresh, security unchanged. A read-only media column posted to
`update_car` was correctly ignored. Workbook ends clean (44/0/1), Marazzo
restored, no test data left.

---

## 7. Future extensibility

- **Add an Excel column → it appears in Add / Edit / View automatically.** No developer needed. It lands in a sensible section by keyword, or in "Other Information".
- To make a new column land in a specific section or be numeric, extend the keyword lists in `_group_and_ro` — a one-line change, still driven by Excel.
- Media/system columns stay protected automatically (keyword-classified read-only).
- The duplicate report and smart-search brand table are simple to extend.

## Outcome

# ✅ PASS — the owner can now add, edit, and view **every** inventory field from the dashboard, and the form adapts to future Excel columns on its own, with Excel remaining the single source of truth.
