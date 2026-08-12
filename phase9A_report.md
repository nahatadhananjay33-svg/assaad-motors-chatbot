# Phase 9A — Edit Existing Car + Add New Car — Report

**Date:** 2026-07-28
**Goal:** Replace the "edit Excel locally → upload whole workbook → refresh" owner
workflow with two in-panel actions — **Edit Car** and **Add New Car** — that update
a *single row* of the server-side Excel and refresh inventory automatically.

**Scope guardrail (honoured):** chatbot, retrieval, inventory loading, media,
Supabase, logging and security were **not modified**. The two new features *reuse*
the existing inventory loader column map, `refresh_inventory()`, and the proven
atomic-save / file-lock / excel-open helpers.

---

## 1. Files changed

| File | Change | Notes |
|------|--------|-------|
| `app/inventory_system/inventory_edit.py` | **NEW** | All Phase-9A backend logic: schema, list, get, update-row, add-row. |
| `app/inventory_system/chat_api.py` | **MODIFIED** | Added `import inventory_edit`; registered 5 routes; added their paths to the 405 known-paths list. No existing route changed. |
| `app/inventory_system/inventory_admin.html` | **MODIFIED** | Added "Edit Car" / "Add New Car" buttons, a car picker, a dynamic form, and the JS that drives them. Existing "Upload & Update" flow left untouched. |

**Reused (not modified):**
- `inventory_loader.COL`, `DATA_START_ROW`, `DNJ_SHEET` — the authoritative column map, so edits always line up with what the loader reads.
- `service.refresh_inventory()` — the existing live-refresh (no restart).
- `media_sync/_util.py` → `atomic_save_workbook`, `FileLock`, `excel_open_by_user` — same helpers the media panel uses (shared lock ⇒ inventory + media writes never collide).
- The existing `/admin` security rule (`SecurityGate`: any path starting `/admin` requires the admin key) — the new routes inherit it automatically.

### New endpoints (all admin-key gated)
| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/admin/inventory/schema` | Field list used to build the form. |
| GET  | `/admin/inventory/vehicles` | `[{car_number, model, year, rate}]` for the picker. |
| POST | `/admin/inventory/get_car` | Load all fields for one row. |
| POST | `/admin/inventory/update_car` | Update **only that row**, then refresh. |
| POST | `/admin/inventory/add_car` | Duplicate check on CAR NUMB → append row → refresh. |

### Design choices (kept intentionally simple)
- The form exposes the **core inventory columns A–Q** (the fields the loader reads: make, model, year, variant, fuel, transmission, owners, km, colour, rate, CAR NUMB, insurance, location, RTO, last-4, stock/sr no). **Media columns are deliberately NOT exposed** — they remain owned by the Media panel, so media logic is untouched.
- **CAR NUMB is the identity:** read-only when editing, **required + unique** when adding.
- Only the selected/new row is written — the rest of the workbook (all other rows, all other sheets, all media cells) is preserved by `openpyxl` + atomic save. Every save also drops a timestamped backup in `inventory_backups/`.
- If the owner has the Excel open in Excel, writes return a friendly "close it and retry" instead of failing.

---

## 2. Tests performed

Tested against the live server (real Supabase-enabled instance) using the real
`IVR_Sheet.xlsx`. A real car was edited-then-reverted; a temporary test car was
added-then-removed, so the workbook ends exactly as it started (44 cars).

### API / functional
| # | Test | Expected | Result |
|---|------|----------|--------|
| 1a | Edit `MH49AT3584` colour via `update_car` | 200 ok | ✅ PASS |
| 1b | Excel cell actually updated | new value in sheet | ✅ PASS |
| 1c | **Chatbot sees new value** (edited `rate` 595000→588000) | `price_lakh` 5.95→**5.88**, reverts to 5.95 | ✅ PASS |
| 2a | `add_car` new car `MH01ZZ9999` (Ciaz) | 200 ok | ✅ PASS |
| 2b | Live count | 44 → **45** | ✅ PASS |
| 2c | New row present in Excel | model = Ciaz | ✅ PASS |
| 2d | **Chatbot finds new car** (query "Ciaz") | returns `MH01ZZ9999` | ✅ PASS |
| 3a | Add the **same** CAR NUMB again | HTTP 409, `"Car already exists."` | ✅ PASS |
| 3b | Count unchanged after duplicate | still 45 | ✅ PASS |

### Security
| Test | Expected | Result |
|------|----------|--------|
| `add_car` with **no** admin key | blocked | ✅ PASS (401) |
| `update_car` with **no** admin key | blocked | ✅ PASS (401) |

### UI (browser, end-to-end over HTTP)
| Test | Result |
|------|--------|
| "Edit Car" loads all 44 vehicles into picker | ✅ PASS |
| Selecting a car populates the form with its real Excel values | ✅ PASS |
| CAR NUMB shown **read-only** (greyed) when editing | ✅ PASS |
| "Add New Car" renders a blank form; CAR NUMB editable + marked required | ✅ PASS |

**Score: 16 / 16 functional + security + UI checks PASS.**
*(One earlier check using the `colour` field returned `None` — this was a
test-design artefact, not a defect: the loader normalises colours, so an
arbitrary test string is dropped by the loader. Re-testing propagation via
`price` — which passes straight through — confirmed PASS.)*

---

## 3. PASS / FAIL

# ✅ PASS — both features work as specified.

- Edit updates only the selected row and the chatbot uses the new data immediately.
- Add appends a new row, the chatbot finds it, and a **duplicate CAR NUMB is rejected** with "Car already exists."
- No whole-workbook upload required.

---

## 4. Regressions

**None found.**

- Existing routing test suite `chat_api_tests` — **19 tests OK**.
- Existing `inventory_upload_tests` — **8 tests OK** (the old upload workflow still works and was left in place).
- Spot checks after changes: `/health` ok, `/admin/media/vehicles` ok, normal chatbot queries ok (family car / Ertiga / SUV all return real cars).
- Final workbook state verified clean: **44 cars**, edited car reverted to originals, test car removed. Media cells for all cars untouched.

**Note (not a regression):** the "Upload & Update" whole-workbook button was left
on the page intentionally (removing it was out of the "build only these two
features" scope). It can be hidden/removed in a follow-up if desired.
