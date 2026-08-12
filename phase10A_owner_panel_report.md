# Phase 10A — Owner Panel (Excel Management) — Report

**Date:** 2026-08-06
**Goal:** A dead-simple panel where the owner uploads the latest `IVR_Sheet.xlsx`
and everything updates automatically. Excel stays the single source of truth.
The system keeps **exactly two files: one LIVE, one BACKUP** — never more.

**Scope guardrail (honoured):** chatbot, inventory loader, retrieval, media,
Supabase, dashboard logic, security, logging, and every existing API are
**unchanged**. The Owner Panel is fully separate from the staff Inventory
Dashboard. Regression: 127 tests across 5 suites all OK.

---

## 1. Files changed

| File | Status | Purpose |
|---|---|---|
| `app/inventory_system/owner_panel.py` | **NEW** | All Owner-Panel backend logic (status / upload / rollback / delete-backup). |
| `app/inventory_system/owner_panel.html` | **NEW** | The owner's page: white background, big cards, big blue buttons, plain wording. |
| `app/inventory_system/chat_api.py` | **MODIFIED** | Registered 4 `/admin/owner/*` routes (+405 list). No existing route touched. |

**Reused, not rewritten:** `inventory_upload.validate_workbook` (DNJ sheet /
columns / readability / vehicle-count checks), `media_admin.parse_multipart`,
`service.refresh_inventory()` (live refresh, no restart), the media_sync
`FileLock`, and the existing `/admin` key gate.

## 2. Architecture

```
owner_panel.html  ──►  /admin/owner/status          (live + backup cards)
 (owner's browser)     /admin/owner/upload          (multipart "file")
                       /admin/owner/rollback        {confirm:true}
                       /admin/owner/delete_backup   {confirm:true}
                              │
                              ▼
                 app/IVR_Sheet.xlsx              ← LIVE (path the chatbot reads —
                 app/IVR_Sheet_OWNER_BACKUP.xlsx ← BACKUP (exactly one)  unchanged)
                 app/owner_panel_meta.json       ← names/dates/counts per slot
```

- The **live path never changes**, so the chatbot/loader keep working untouched.
- `owner_panel_meta.json` is a plain dict — later phases can add users,
  permissions, and audit fields to it without changing this phase's API.
- All file swaps run under the same `FileLock` the media panel uses (atomic
  `os.replace`, no torn states) and are guarded so a failure mid-swap restores
  the live slot.

## 3. Upload flow

1. Owner picks `IVR_Sheet.xlsx` → **Upload**.
2. File staged and **validated first** (DNJ sheet exists, CAR NUMB column,
   workbook readable, vehicle count > 0). **Any failure → rejected, live
   inventory untouched** (verified with a garbage file).
3. Old backup (if any) **deleted automatically** — two-file rule.
4. Current live → becomes **BACKUP**.
5. New file → becomes **LIVE**.
6. `refresh_inventory()` → chatbot serves the new data instantly, **no restart**.
7. Owner sees: **"✓ Inventory Updated Successfully — N vehicles are now live."**

## 4. Backup / rollback flow

- **Rollback ("Restore Previous Excel"):** one click + confirmation → backup and
  live **swap** (backup→live, old live→backup) → refresh. Nothing is lost.
- **Delete Backup:** removes only `IVR_Sheet_OWNER_BACKUP.xlsx` after
  confirmation. The live Excel **cannot** be deleted from this panel (no such
  endpoint exists).
- **Upload History:** shows exactly the two files (file name, upload time,
  vehicle count, LIVE/BACKUP status). No long history.

## 5. Validation results — 24/24 PASS

| Check | Result |
|---|---|
| Status shows live card (name/date/count/LIVE) | ✅ |
| Upload v2 (45 cars) → accepted, live = 45 | ✅ |
| Backup auto-created; status shows live 45 / backup 44 | ✅ |
| **Chatbot finds the new car instantly** (no restart) | ✅ |
| Second upload → old backup **deleted automatically** | ✅ |
| **Never more than two managed files on disk** | ✅ (`IVR_Sheet.xlsx` + `IVR_Sheet_OWNER_BACKUP.xlsx`) |
| Rollback → previous Excel live again (45), chatbot follows | ✅ |
| Rollback again → original live (44) | ✅ |
| Delete backup → only backup removed, live untouched | ✅ |
| Deleting when no backup → polite 404 | ✅ |
| Garbage file → rejected with clear message, inventory untouched, no backup created | ✅ |
| No/wrong key → 401 on every owner endpoint | ✅ |
| Final state: live Excel intact, 44 cars, chatbot normal | ✅ |

UI smoke test: page connects, cards render (file name, date, 44 vehicles,
LIVE tag), "no backup yet" note appears when there is none, history lists the
two slots.

**Regression:** `chat_api_tests` 19 OK · `faq_tests` 46 OK ·
`inventory_upload_tests` 8 OK (old upload path untouched) ·
`inventory_retrieval_tests` 39 OK · `router_tests` 15 OK.

## 6. Permissions

All `/admin/owner/*` endpoints sit behind the existing admin-key gate (fails
closed; verified 401 without a key). The page asks for the **Owner key**. Today
that is the same `CHAT_ADMIN_API_KEYS` mechanism; a dedicated owner-only key can
be introduced in the future phases without changing this code (the gate already
supports multiple keys).

## 7. Future integration points (deliberately left open)

- `owner_panel_meta.json` — add `users`, `roles`, `audit` keys later; readers
  ignore unknown keys.
- Handlers accept the `service` object — a future permission layer can wrap the
  routes without touching handler logic.
- Owner actions currently piggyback on the existing HTTP access log; a later
  phase can call the existing `inventory_edit._audit()` helper for per-action
  audit rows (one line per handler).
- The staff dashboard's "Advanced" whole-workbook upload can be retired once the
  owner fully adopts this panel — separate decision, not taken in this phase.

---

# ✅ Result: the owner uploads Excel → validated → backed up → live → chatbot updated. Two files, one button, no restarts, nothing technical.
