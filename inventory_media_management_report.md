# Phase 8H — Inventory + Media Management System: Implementation Report

**Date:** 2026-06-23
**Scope:** Build the final inventory/media management layer. **Additive only** —
no change to chatbot retrieval, Marathi, pricing, consultative selling, logging,
security, follow-up memory, or inventory search. **Not deployed. No production
data deleted.** Validated offline with a test workbook + in-memory storage.

---

## 1. Outcome vs. success criteria

| Success criterion | Status |
|-------------------|:------:|
| Owner never touches Supabase | ✅ Files upload & delete behind the panel |
| Owner never copies URLs | ✅ Public URLs are generated and written to Excel automatically |
| Owner only: edit Excel · upload media · mark sold | ✅ Everything else automatic |
| Excel remains source of truth; Supabase = storage only | ✅ No inventory in Supabase; chatbot still reads Excel |
| Chatbot reads inventory exactly as today | ✅ Per-slot media columns unchanged; loader untouched |
| Sold car disappears from chatbot | ✅ Row moves out of DNJ → not loaded |
| Build & validate only (no deploy / no prod delete) | ✅ All validation used a temp workbook + in-memory store |

---

## 2. Files created / changed

### Documentation (repo root)
| File | Purpose |
|------|---------|
| `inventory_media_schema.md` | **Step 1** — audit of the current DNJ schema, media columns, and gaps |
| `inventory_final_schema.md` | **Step 2** — final schema; 7 new management columns + `SOLD_CARS` sheet |
| `supabase_media_architecture.md` | **Step 3** — bucket, one-folder-per-vehicle layout, URL flow, deletion |
| `inventory_media_management_report.md` | **Step 9** — this report |

### Code (`app/inventory_system/`)
| File | Purpose |
|------|---------|
| `media_admin.py` | **NEW** — media management service (upload photos/videos, add IG/YT, list vehicles, mark sold) + pluggable store + HTTP glue (Steps 4, 5, 7, 6-backend) |
| `media_admin.html` | **NEW** — owner Admin Panel UI (Step 6) |
| `media_admin_validate.py` | **NEW** — end-to-end validation harness (Step 8) |
| `media_admin_tests.py` | **NEW** — unit + HTTP-route + auth-gate tests (12 tests) |
| `media_loader_mapping.py` | **CHANGED (1 surgical fix)** — `detect_media_layout` now requires a slot indicator so the new `*_URLS`/`*_URL` management headers are never mistaken for media slots (see §6) |
| `chat_api.py` | **CHANGED (additive)** — registered 4 new gated endpoints under `/admin/media/*` |

> No other production module was modified. `chat_service.py`, `inventory_loader.py`
> (logic), `retrieval_engine.py`, `media_service.py`, `security.py`, pricing,
> Marathi, consultative, and follow-up code are untouched.

---

## 3. Architecture

```
            ┌──────────────────────── SOURCE OF TRUTH ────────────────────────┐
  Staff ─▶  │  Shared Excel (IVR_Sheet.xlsx · DNJ)   AVAILABLE/RESERVED/SOLD  │
            └───────────────┬──────────────────────────────────┬─────────────┘
                            │ load_inventory()                  │ (rows leave DNJ when sold)
                            ▼                                    ▼
                   Inventory Loader ─▶ Chatbot           SOLD_CARS sheet (archive)

  Owner ─▶  Admin Panel (media_admin.html)
              ├── Upload Photos ─┐
              ├── Upload Videos ─┤   POST /admin/media/*  (admin-key gated)
              ├── Add Instagram ─┤            │
              ├── Add YouTube  ──┤            ▼
              └── Mark Sold ─────┘     media_admin.MediaAdmin
                                          │
                  ┌───────────────────────┼────────────────────────┐
                  ▼                        ▼                         ▼
          Supabase Storage      Excel auto-update           Mark-Sold workflow
          (car-photos bucket,   • per-slot media cols       • delete Supabase files
           one folder/vehicle,    (chatbot reads these)     • move row DNJ→SOLD_CARS
           {REG}/photos|videos)  • PHOTO_URLS/VIDEO_URLS     • clear media URLs
                                   mirror + MEDIA_FOLDER_ID  • refresh_inventory()
                                   + LAST_UPDATED            • car gone from chatbot
                                          │
                                          ▼
                              service.refresh_inventory()
                              (existing atomic engine swap — no restart)
```

**Key invariant:** the chatbot continues to read media from the **existing
per-slot columns** (`EXTERIOR/INTERIOR/VIDEO/INSTAGRAM/YOUTUBE`). The management
layer writes those same columns, so there is **zero loader change**. The new
consolidated columns (`PHOTO_URLS`, `VIDEO_URLS`, `YOUTUBE_URL`, `INSTAGRAM_URL`,
`MEDIA_FOLDER_ID`, `LAST_UPDATED`, `STATUS`) are an owner-facing mirror/control,
not read by the chatbot.

---

## 4. Workflow detail

### Upload (photos / videos) — Steps 4 + 5
1. Owner selects files in the panel → `POST /admin/media/upload_photos|videos`.
2. Service hashes each file → object path `{REG}/{photos|videos}/{sha1}.{ext}`.
3. Store uploads (idempotent) → **public URL**.
4. URL written into the next empty per-slot column (`EXTERIOR`/`VIDEO`).
5. `PHOTO_URLS`/`VIDEO_URLS` mirror, `MEDIA_FOLDER_ID`, and `LAST_UPDATED` updated.
6. Workbook saved atomically under a cross-process lock; `refresh_inventory()`
   makes the new media live with no restart.

### Add Instagram / YouTube link
JSON `{car_number, platform, url}` → validated → written to per-slot
`INSTAGRAM`/`YOUTUBE` columns + mirror + `LAST_UPDATED`.

### Mark Sold — Step 7
1. Panel asks for confirmation; API requires `confirm:true` (`confirm_required`
   is returned otherwise).
2. All Supabase objects under `{REG}/` are deleted.
3. The DNJ row is snapshotted (media + mirror cells cleared, `STATUS=SOLD`,
   `SOLD_AT`/`SOLD_BY` appended) and **appended to the `SOLD_CARS` sheet**.
4. The row is **deleted from DNJ**.
5. `refresh_inventory()` runs; the API verifies and returns
   `disappeared_from_chatbot: true`.

### Safety
- Atomic writes (`temp + os.replace`) under a `FileLock`; writes are **deferred**
  if a human has the workbook open in Excel (`~$` lock file detected).
- Storage is pluggable: `InMemoryMediaStore` (offline/validation) vs.
  `SupabaseMediaStore` (live) — selected by `SUPABASE_URL`/`SUPABASE_KEY`.
- All `/admin/media/*` endpoints sit behind the existing **fail-closed admin
  gate** (no admin key ⇒ endpoints disabled).

---

## 5. Validation results (Step 8)

Harness: `media_admin_validate.py` — full owner journey on a **test workbook**
with the **in-memory store** (no Supabase, no production data).

```
32 / 32 checks passed   (all_passed: true)
```

Highlights verified:
- Photo upload (2 valid + 1 bad-extension rejected) → 2 stored, 2 in EXTERIOR slots.
- Video upload → 1 stored, 1 in VIDEO slot.
- Instagram + YouTube links written; bad (non-URL) link rejected.
- Auto-update: `PHOTO_URLS` (×2), `VIDEO_URLS` (×1), `YOUTUBE_URL`,
  `INSTAGRAM_URL`, `MEDIA_FOLDER_ID`, `LAST_UPDATED`, `STATUS=AVAILABLE` all set.
- **Chatbot read path** (`load_inventory`) surfaces the uploaded photos, video,
  and YouTube link — proving the per-slot write is consumed with no loader change.
- Mark Sold: confirm gate enforced; 3 media files deleted; store emptied for the
  reg; row present in `SOLD_CARS`; **vehicle gone from chatbot**.
- **Regression in-harness:** the other two cars still load with correct
  model/price after the sold move.

Test suite `media_admin_tests.py`: **12 / 12 passed** (service ops, HTTP routes
incl. live refresh, and admin-gate fail-closed behavior).

---

## 6. The one loader-adjacent change (and why it's safe)

The requested management headers `VIDEO_URLS`, `YOUTUBE_URL`, `INSTAGRAM_URL`
begin with media keywords (`VIDEO`, `YOUTUBE`, `INSTAGRAM`). The original
`detect_media_layout` matched headers by raw prefix, so once these columns exist
it would mis-read them as media slots and **pollute the chatbot's media** with
the joined-URL blob.

Fix (root cause, surgical): a media header is now recognized only when the
keyword is followed by a **slot indicator** — a space, the end of the text, or a
digit anywhere (`"VIDEO 1"`, `"VIDEO_1"`, `"EXTERIOR_PHOTO_3"`, bare
`"INSTAGRAM"`). Digit-less suffixes (`"VIDEO_URLS"`, `"YOUTUBE_URL"`) no longer
match. This **strengthens** detection without changing any existing result.

Proven safe:
- Real `IVR_Sheet.xlsx` still yields **31 media records / 5 cars with media**
  (identical to the pre-change audit in Step 1).
- `customer_facing` count is **independent of media attachment** (44 with media,
  44 without) — so the change cannot affect inventory counts or selection.

---

## 7. Regression results

Full suite run (`pytest *_tests.py` in `inventory_system`, plus `media_sync` and
`media_sync_poc`):

| Suite | Result |
|-------|--------|
| `inventory_system/*_tests.py` (incl. media, loader, retrieval, FAQ, router, chat_api, hardening, lead, consultative, Marathi, new media_admin) | **416 passed, 1 failed** |
| `media_sync/media_sync_tests.py` | **57 passed** |
| `media_sync_poc/media_sync_poc_tests.py` | **29 passed** |
| `media_loader_tests + media_tests + media_api_tests + inventory_loader_tests + inventory_retrieval_tests` (focused re-run) | **174 / 135 passed** |

### The single failure is pre-existing and unrelated to Phase 8H
`hardening_tests.py::TestInventoryRefresh::test_refresh_returns_ok_and_count`
asserts `inventory_count == 40`, but the live sheet now loads **44** cars.

- The test file dates **2026-06-11**; `IVR_Sheet.xlsx` was edited **2026-06-17**
  (≈4 cars added afterward) — the hard-coded `40` is stale.
- Proven not caused by this phase: the count is identical with media on/off
  (44 = 44), and `detect_media_layout` only feeds media attachment, never the
  customer-facing count.
- **Recommendation (out of scope):** update the assertion to the current count
  (or make it tolerance-based) — a test-data refresh, not a code defect.

No chatbot behavior regressed.

---

## 8. Configuration (for later, live deployment — not done here)

| Var | Purpose | Default |
|-----|---------|---------|
| `CHAT_MEDIA_BUCKET` | Supabase storage bucket | `car-photos` |
| `SUPABASE_URL` / `SUPABASE_KEY` | Enable the live store (else in-memory) | unset |
| `CHAT_ADMIN_API_KEYS` | Gate the admin panel + media endpoints | unset ⇒ admin disabled |
| `CHAT_MAX_UPLOAD_MB` | Per-file cap (shared with inventory upload) | `10` |

Serve `media_admin.html` behind the reverse proxy; the owner enters the server
address + admin key once (kept only in the browser tab).

---

## 9. Endpoints added (all admin-gated, fail-closed)

| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/admin/media/vehicles` | List cars: car number, model, status |
| POST | `/admin/media/upload_photos` | Multipart `car_number` + file(s) → photos |
| POST | `/admin/media/upload_videos` | Multipart `car_number` + file(s) → videos |
| POST | `/admin/media/add_link` | JSON `{car_number, platform, url}` (instagram/youtube) |
| POST | `/admin/media/mark_sold` | JSON `{car_number, confirm}` → sold workflow |

---

## 10. Conclusion

The final inventory/media management architecture is built and validated offline.
The owner edits Excel as before and now uses a simple Admin Panel for media and
sold cars; Supabase storage, URL writing, Excel mirroring, and chatbot refresh
are all automatic. The chatbot's read path is unchanged and fully regression-
tested. Nothing was deployed and no production data was deleted.
