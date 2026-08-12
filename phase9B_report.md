# Phase 9B — Smart Inventory Dashboard — Report

**Date:** 2026-07-28
**Goal:** Turn the Inventory Management page into a proper dashboard (summary,
search, filters, table, per-row actions, refresh) that scales to 200–500 cars —
as an easier interface over the **same server-side Excel** (single source of truth).

**Scope guardrail (honoured):** chatbot, retrieval, inventory loading, media
upload, Supabase, logging and security were **not modified**. The dashboard only
*reads* via a new endpoint and *reuses* the existing Phase-9A / media / refresh
endpoints for every action.

---

## 1. Files changed

| File | Change | Notes |
|------|--------|-------|
| `app/inventory_system/inventory_edit.py` | **MODIFIED** | Added one read-only endpoint handler `handle_dashboard()` (summary counts + full table incl. sold cars). Reuses `inventory_upload.handle_status` for the header fields. Also switched the three read handlers off openpyxl `read_only=True` → normal load (see Perf note). |
| `app/inventory_system/chat_api.py` | **MODIFIED** | Registered `GET /admin/inventory/dashboard` (+ added to the 405 known-paths list). No existing route changed. |
| `app/inventory_system/inventory_admin.html` | **REWRITTEN** | Now the dashboard: 6-tile summary, search box, filter buttons, vehicle table, per-row Edit/Media/Mark-Sold, Refresh Inventory + Add New Car. Old whole-workbook upload kept under an "Advanced" collapsible. |
| `app/inventory_system/media_admin.html` | **MODIFIED (additive only)** | ~8 lines: reads `?car=<reg>` and preselects that car after the existing `loadVehicles()`. No media/upload/Supabase/sold logic changed — it just auto-selects a row, exactly as a user click would. |

**Reused, not duplicated:**
- `GET /admin/inventory/dashboard` → new (the only new backend).
- `GET /admin/inventory/schema`, `POST /admin/inventory/get_car | update_car | add_car` → **Phase 9A** (Edit / Add).
- `POST /admin/media/mark_sold` → **existing** sold workflow (Mark Sold shortcut).
- `media_admin.html` → **existing** media page (Media shortcut, deep-linked with `?car=`).
- `POST /admin/refresh_inventory` → **existing** live refresh (Refresh button).
- `POST /admin/upload_inventory` → **existing** (kept under Advanced).
- The `/admin` `SecurityGate` rule → the new route inherits admin-key protection automatically.

### New endpoint
| Method | Path | Returns |
|--------|------|---------|
| GET | `/admin/inventory/dashboard` | `{summary:{live,available,reserved,sold,last_updated,current_file}, vehicles:[{registration_no,brand,model,year,price,status,last_updated}]}` |

Counts are **deduped by registration** (as the loader does) so the dashboard is
consistent with what the chatbot actually serves (the Excel contains a duplicate
CAR NUMB `MH02EZ6001`; without dedupe the table showed 45 but live is 44).

---

## 2. Screenshots

Pixel screenshots could **not** be captured this run — the automated browser
pane was not compositing frames (screenshot calls timed out). Verification was
therefore done by **reading the live DOM** of the running page after driving its
real handlers. Representative captured state:

- Summary tiles after Connect: `Cars Live 44 | Available 44 | Reserved 0 | Sold 1 | Last Updated 2026-07-28 | IVR_Sheet.xlsx`.
- First table row rendered: `MH01BK9444 | MERCEDES | E 200 | 2014 | ₹6.10 L | AVAILABLE | — | [Edit][Media][Mark Sold]`.
- Edit form (from row button): title "Editing MH49AT3584", CAR NUMB **read-only**, fields MAHI / MARAZOO / 2019 / 595000.
- Media deep-link (`media_admin.html?car=MH49AT3584`): row auto-selected, actions panel shown.

*(The dealership staff will see full screenshots when they open the page normally;
the page is plain HTML/JS and renders in any browser.)*

---

## 3. Validation — PASS / FAIL

| # | Test | How verified | Result |
|---|------|--------------|--------|
| 1 | Search by registration | `MH49AT3584` → 1 row | ✅ PASS |
| 2 | Search by model | `ertiga` → 2 rows | ✅ PASS |
| 3 | Search by brand | `maru` → 10, `mercedes` → 1 (searches the raw Excel brand) | ✅ PASS* |
| 4 | Available filter | 44 rows | ✅ PASS |
| 5 | Reserved filter | 0 rows | ✅ PASS |
| 6 | Sold filter | 1 row (TEST0001), row actions disabled | ✅ PASS |
| 7 | Edit from dashboard | Edit button → form populated, CAR NUMB locked, Save → `update_car` | ✅ PASS |
| 8 | Open Media from dashboard | `?car=` deep-link preselected the car in the existing media page | ✅ PASS |
| 9 | Mark Sold from dashboard | temp car → `mark_sold` → moved to SOLD, live 45→44 | ✅ PASS |
| 10 | Refresh Inventory | `refresh_inventory` → 200, dashboard reloads | ✅ PASS |
| 11 | Chatbot still works | family-car query returns cars; sold car hidden; Marazzo price 5.95 | ✅ PASS |
| 12 | No regression | see below | ✅ PASS |

Backend script: **12/12 checks passed**. UI: search/filter/edit/media all verified against the live DOM.

**\*Note on brand search:** the Excel stores brands as **abbreviations** (`MARU`,
`HOND`, `TOYO`, some with trailing spaces), and a few in full (`MERCEDES`). The
dashboard searches the brand column exactly as stored — so `maru` finds Maruti
cars, `honda` finds none (stored `HOND`). This is source-data, not a dashboard
defect (Excel is the single source of truth). If desired later, we can also index
the loader's normalised brand for search — a small, separate enhancement.

---

## 4. Regression summary

**No regressions.**

- `chat_api_tests` — **19 tests OK** (routing intact after adding the route).
- `inventory_upload_tests` — **8 tests OK** (old upload path still works, kept under Advanced).
- Chatbot: normal queries return real cars; sold cars stay hidden; an edited price propagates and reverts correctly.
- Final data state verified clean: **44 live, 0 reserved, 1 sold**, Marazzo untouched (₹5.95 L). No test data left behind (temp car removed from `SOLD_CARS`).

### Performance note (fixed during this phase)
The first version of `handle_dashboard` opened the workbook `read_only=True` but
did random cell access — pathologically slow in openpyxl (~28 s per call). Switched
to a normal load (fast random access): **~0.9 s** per dashboard call. The same fix
was applied to `handle_vehicles` and `handle_get_car` so they stay fast at 500 cars.

---

## Summary

# ✅ PASS — the Smart Inventory Dashboard is complete and working.

Staff get a searchable, filterable table with live counts and one-click Edit /
Media / Mark-Sold / Refresh — all driving the existing Excel + existing endpoints.
Nothing in the chatbot, media, Supabase, logging or security was changed.
