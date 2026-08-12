# Phase 9C — Validation Report

**Date:** 2026-07-29
Tested against the live server (real Supabase-enabled) using the real
`IVR_Sheet.xlsx`. All edits were reverted and all test cars removed, so the
workbook ends exactly as it started (**44 live, 0 reserved, 1 sold**).

## Validation checklist

| Feature | How verified | Result |
|---------|--------------|--------|
| ✓ **Add Car** | Dynamic form built from schema; new car `MH01ZZ7777` added → chatbot found it; removed after | ✅ PASS |
| ✓ **Edit Car** | Dynamic grouped form; 94 fields, 48 editable / 46 read-only; edited price via UI → chatbot 5.95→(saved)→reverted; CAR NUMB locked | ✅ PASS |
| ✓ **Duplicate Detection** | Add-precheck: existing reg → HTTP 409 "This vehicle already exists."; workbook scan → 5 duplicate regs, 10 rows | ✅ PASS |
| ✓ **Dynamic Fields** | 94 fields discovered from Excel; **added a column to Excel → appeared as field #95 (group "Other Information") with no code change**; removed after | ✅ PASS |
| ✓ **Dashboard** | Summary tiles 44/44/0/1 + last-updated + file; 45-row table with KM column | ✅ PASS |
| ✓ **Search** | Smart brand aliases: `maruti`→10 (MARU), `honda`→5 (HOND), `toyota`→6 (TOYO); reg/model search intact | ✅ PASS |
| ✓ **Filters** | All / Available (44) / Reserved (0) / Sold (1) | ✅ PASS |
| ✓ **Refresh Inventory** | `refresh_inventory` → 200, dashboard reloads (no restart) | ✅ PASS |
| ✓ **Media Shortcut** | `media_admin.html?car=` deep-link preselects the car in the existing media page | ✅ PASS |
| ✓ **Chatbot** | family-car query returns cars; edited price propagates; sold car hidden; Marazzo 5.95 | ✅ PASS |
| + **Sorting** | Price desc→Fortuner ₹8.75L, asc→City ₹0.88L; Year desc→Nexon 2022; KM & Last-Updated sortable | ✅ PASS |
| + **View Details** | Opens the full dynamic form read-only: 94 fields, 6 groups, Save hidden, nothing hidden | ✅ PASS |

**Backend automated checks:** 15/15 passed.
**Read-only protection:** attempt to write a media column (`PHOTO_URLS`) via `update_car` was ignored (value unchanged) — media/Supabase workflow untouched.

## Regression

**No regressions.**
- `chat_api_tests` — **19 OK**
- `inventory_upload_tests` — **8 OK**
- Chatbot behaviour, media workflow, sold workflow, refresh, security all unchanged.
- Final workbook verified clean (44/0/1), Marazzo restored, no test cars left behind.

## Performance

| Endpoint | Time |
|----------|------|
| `GET /admin/inventory/schema` | ~0.7 s |
| `GET /admin/inventory/dashboard` | ~0.9 s |
| `POST /admin/inventory/get_car` | ~1 s |
| `POST /admin/inventory/update_car` (+ refresh) | ~1.5 s |
| `POST /admin/inventory/duplicate_audit` (all sheets) | ~1.5 s |

All read handlers use a normal openpyxl load (fast random access) rather than
`read_only` mode, keeping them fast well beyond 500 cars.
