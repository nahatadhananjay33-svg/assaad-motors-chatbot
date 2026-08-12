# Phase 10C — Role-Based Permissions — Report

**Date:** 2026-08-06
**Goal:** every role sees and uses only its own features. **No login, no
sessions, no JWT, no audit logs** (later phases) — permissions only.

**How identity works in this phase:** the admin pages send the staff member's
username in an **`X-Acting-User`** header. The backend maps username → role
(Phase 10B `users.json`) → permission set and enforces it on **every /admin
endpoint** (single choke point), returning **403 Forbidden** on violations.
Requests **without** the header keep the legacy admin-key-only behaviour, so
nothing existing breaks; Phase 10D (login) will make identity verified and
mandatory using the same choke point.

---

## 1. Roles → permissions

| Role | Can | Cannot (enforced 403 + hidden in UI) |
|---|---|---|
| **Owner** | Everything (`*`) | — |
| **Inventory Staff** | View dashboard, search, add car, edit car, refresh | Excel upload, backup restore/delete, users, media, owner panel |
| **Photo Staff** | View inventory, media panel, upload photos | Edit inventory, videos, links, users, Excel |
| **Video Staff** | Media panel, upload videos | Photos, inventory, users, Excel |
| **Social Media Staff** | Media panel, Instagram/YouTube links | Photos, videos, inventory, Excel, users |
| **Finance Staff** | View inventory; edit **only** finance fields | Everything else — field-level enforced |
| **Document Staff** | View inventory; edit **only** document fields | Everything else — field-level enforced |
| **Read-Only Manager** | **View** inventory, media, users, owner panel | Every write — all Save/Upload/Delete buttons hidden |

**Field-level scoping** (Finance/Document Staff) is computed from the live
Excel schema by keyword — so future columns follow the rules automatically:
- Finance → rate, price range, negotiable, EMI/loan/finance/hypothecation
  (resolved live to `c13, c54, c55, c56, c77, c78, c80`)
- Document → RC, insurance, warranty, ownership, service, NOC
  (resolved live to `c6, c10, c58, c59, c61, c73–c76, c79, …`)
An update_car posting any other column returns 403 naming the blocked fields.

## 2. Files changed

| File | Status | Purpose |
|---|---|---|
| `app/inventory_system/permissions.py` | **NEW** | Role→permission map, endpoint→permission map, field-scope rules, `enforce()` + `describe()` (drives UI hiding). |
| `app/inventory_system/chat_api.py` | **MODIFIED** | `route()` takes `acting_user`; one permission gate before all /admin handlers; new `GET /admin/users/my_permissions`. No handler logic touched. |
| `app/inventory_system/security.py` | **MODIFIED (1 word)** | `X-Acting-User` added to CORS `Allow-Headers` (required for browsers to send the header; no security weakening). |
| `inventory_admin.html` / `media_admin.html` / `owner_panel.html` | **MODIFIED (additive)** | "Your username" field; header attached to every call; buttons **hidden** (not disabled) per role; field-scoped roles see non-editable fields greyed; Owner Panel shows **Access Denied** to non-owners (Read-Only Manager gets view-only). |

## 3. Validation — 50/50 backend matrix + UI checks, all PASS

**Backend matrix** (one real user per role, every endpoint class):
- Legacy no-header requests: full access preserved (3/3).
- Owner: everything allowed (4/4).
- Inventory Staff: view/edit/refresh allowed; Excel, owner panel, backups, users, media all 403 (9/9).
- Photo Staff: inventory view + media list + photo upload allowed; videos/links/inventory-edit/users/Excel 403 (8/8).
- Video Staff / Social Media Staff: exactly their media verb allowed; all else 403 (8/8).
- Finance Staff: editing price **allowed**, editing model **403**, add car **403**; `allowed_cols` correct (4/4).
- Document Staff: editing insurance **allowed**, editing price **403** (3/3).
- Read-Only Manager: all four views allowed; every write 403 (9/9).
- Unknown username → 403; **disabled account → 403** (2/2).

**Frontend hiding (live browser, real pages):**
- Photo Staff on Media panel → **only "Upload Photos" visible**; videos, Instagram, YouTube, Mark Sold gone.
- Read-Only Manager on Inventory Dashboard → rows show **View + Media only**; Add Car, Refresh, Mark Sold, Edit, and the Excel upload section all hidden; status shows "Working as ui_view (Read-Only Manager)".
- Photo Staff on Owner Panel → **🚫 Access Denied**, every card hidden.
- Owner on Owner Panel → full panel (upload visible, 44 vehicles).

**Data integrity after tests:** Marazzo rate/colour unchanged; all test users removed.

**Regression:** `chat_api_tests` 19 OK · `faq_tests` 46 OK ·
`inventory_upload_tests` 8 OK · `router_tests` 15 OK.
`hardening_tests` 37/38 — the 1 failure is **pre-existing stale test data**
(asserts `inventory_count == 40` from when the stock had 40 cars; it is 44),
unrelated to permissions.

## 4. Future integration

- **Phase 10D login:** after verifying credentials (`user_management.verify_password`),
  set the session's username where `X-Acting-User` is read today — `enforce()`
  is already the single choke point; nothing else changes. Until then the header
  is client-supplied (documented limitation of a no-auth phase).
- **New endpoints:** add one line to `PATH_PERMISSIONS`; unmapped /admin paths
  are **closed by default** for non-owners.
- **New roles / permission tweaks:** edit `ROLE_PERMISSIONS` only.
- **Audit phase:** every denial already logs a `permission_denied` event with
  path + username to the persistent access log.

---

# ✅ Result: each of the 8 roles sees only its own buttons, and the backend independently rejects everything else with 403 — verified role-by-role, endpoint-by-endpoint, page-by-page.
