# Phase 10E — Audit Logs & Activity Tracking

**Goal:** Give the Owner a clean, read-only activity history — *who did what,
when, on which vehicle* — without modifying any existing workflow. No analytics,
no charts, no dashboards. Just record every important action.

**Status:** ✅ Complete. Implemented, self-validated (unit + live HTTP + browser),
and regression-checked. **Zero** changes to any existing business module.

---

## 1. Architecture

### The one idea
Every request already funnels through a single HTTP choke point
(`chat_api._dispatch`). Phase 10E adds **one passive line** there: after the
request is answered, a fully-guarded `audit.observe(...)` looks at the
`(method, path)`, pulls the who / what / vehicle / result out of the request body
and the handler's **own response**, and writes **exactly one** append-only row.
It never changes a response, never slows the request (it runs *after*
`_respond`), and never raises.

```
  request ─▶ gate ─▶ route() ─▶ handler (UNCHANGED)         data
                         │            └────────────▶ Excel / Supabase / users.json
                         ▼
                  _respond(...)  ← client already has its answer
                         │
                         ▼   (Phase 10E — passive, post-response, guarded)
              audit.observe(method, path, actor, status, body, payload)
                         │  map (method,path) → action + category
                         │  extract vehicle / target / new_value / detail
                         ▼
                  audit.record()  ──▶  data/audit.db   (append-only)
                                             ▲
   Owner Panel  ──GET /admin/audit/list──────┘   (read-only; Owner-only)
```

**Why this shape**
- **Nothing existing is touched.** The chatbot, inventory loader, Excel
  management, owner panel backend, user management, login, permissions, Supabase,
  media logic, and every existing API run byte-for-byte as before. Auditing reads
  their inputs/outputs from the outside; it never reaches inside them.
- **Exactly one row per action.** `observe()` is called once per handled request
  and writes 0 rows (for non-actions like `/health`, `/chat`, reads,
  `my_permissions`, the audit view itself) or 1 row (for a mapped action).
- **Owner-only for free.** `/admin/audit/list` is an *unmapped* `/admin` path, so
  the existing Phase 10C rule ("unmapped admin path ⇒ Owner only, 403 for every
  other role") already restricts it. **`permissions.py` was not modified.**
- **Truly read-only / tamper-proof.** The store exposes `record()` and `query()`
  only — there is deliberately **no** update/delete/clear function anywhere, and
  the HTTP surface is a single `GET` (POST ⇒ 405). Logs cannot be edited or
  deleted from any screen or endpoint.
- **Safe by construction.** `observe()` is wrapped in `try/except` on both sides
  (inside `audit.py` and at the call site), so a logging fault can never affect a
  real request. Passwords are never read or stored.

### Storage — `data/audit.db` (SQLite, append-only)
One table, mirroring the required record fields:

| column | meaning |
|---|---|
| `id` | autoincrement (also the newest-first sort key) |
| `ts` | ISO-8601 UTC timestamp |
| `username` | who performed it |
| `role` | their role (resolved from `users.json`) |
| `action` | human action name (e.g. "Add New Car") |
| `category` | Inventory · Media · Users · Excel · Login (drives filters) |
| `vehicle` | registration, when applicable |
| `old_value` / `new_value` | optional before/after (e.g. "44 vehicles live", "role: Finance Staff") |
| `status` | `success` or `failed` |
| `detail` | optional context (e.g. "target user: raj", failure reason) |

### Actions recorded
| Category | Actions (endpoint → label) |
|---|---|
| **Login** | Login (`/auth/login`), Logout (`/auth/logout`) — including **failed** logins |
| **Excel** | Upload New Excel (`/admin/owner/upload`, `/admin/upload_inventory`), Restore Previous Excel (`/admin/owner/rollback`), Delete Backup Excel (`/admin/owner/delete_backup`) |
| **Inventory** | Add New Car (`/admin/inventory/add_car`), Edit Car (`/admin/inventory/update_car`), Restore Vehicle (`/admin/inventory/restore_car`) |
| **Media** | Upload Photos, Upload Videos, Add Instagram Link / Add YouTube Link (`/admin/media/add_link`, label by platform), Mark Vehicle Sold |
| **Users** | Create User, Edit User, Reset Password, Enable User / Disable User (`/admin/users/set_active`, label by state), Delete User |

> Note on the requirement's "Delete Photos / Delete Videos / Remove Instagram
> Link / Remove YouTube Link / Delete Car (if supported)": the current system has
> **no** endpoints for these operations — media removal happens only as a side
> effect of *Mark Vehicle Sold*, which **is** logged. No endpoints were invented
> (that would mean modifying media/inventory logic, which is out of scope). If
> those operations are ever added, wiring them is a one-line entry in
> `audit.ACTIONS`.

### Owner Panel — "Activity Logs" section
A new read-only card on the (Owner-only) Owner Panel:
- Columns: **Time · User · Role · Action · Vehicle · Status**, newest first.
- **Search** box → username, vehicle, or action (also matches the target user of
  user-management actions, so searching a username finds actions *about* that
  account too).
- **Filter** buttons: **All · Inventory · Media · Users · Excel · Login**.
- A Refresh button and a live result count. No charts, no editing, no delete.

---

## 2. Files Changed

### New files
| File | What it is |
|---|---|
| `app/inventory_system/audit.py` | The whole feature: SQLite append-only store (`record`/`query`/`count`), the `(method,path) → action` map with field extractors, the passive `observe()` interceptor, and the read-only `handle_list()` HTTP handler. No update/delete API. |
| `app/inventory_system/audit_tests.py` | 23 tests — store, exactly-one-per-action across all 20 action cases, non-actions ignored, timestamps, username, role, vehicle, filters, search, failure recording, password-never-stored, read-only, owner-only, read-only method. |

### Modified files (additive only)
| File | Change |
|---|---|
| `chat_api.py` | Import `audit`; add one read-only route `GET /admin/audit/list`; capture the query string; call `audit.observe(...)` once in `_dispatch` **after** the response is sent (guarded). No handler behaviour changed. |
| `owner_panel.html` | Add the read-only "Activity Logs" card (table + search + filters + refresh) and its JS; hook `loadAudit()` into the existing Owner load flow. |

**Not touched (verified):** `chat_service.py`, `inventory_loader.py`,
`inventory_edit.py`, `inventory_upload.py`, `owner_panel.py`, `user_management.py`,
`permissions.py`, `auth.py`, `security.py`, `media_*`, Supabase code, Excel
handling, `refresh_inventory()`, and every existing API contract.

---

## 3. Validation Results (self-run — no manual testing)

### 3a. Audit unit + integration tests
`python -m pytest -q audit_tests.py` → **23 passed.**

- **Exactly one entry per action:** all 20 action variants (login, logout, upload
  excel ×2, rollback, delete backup, add/edit/restore car, upload photos/videos,
  add Instagram/YouTube link, mark sold, create/edit/reset/enable/disable/delete
  user) each add **exactly +1** row with the right action, category, and vehicle.
- **Non-actions never logged:** `/health`, `/chat`, `/auth/me`,
  `/admin/users/my_permissions`, `/admin/audit/list`, `/admin/inventory/dashboard`,
  `/admin/media/vehicles` → 0 rows.
- **Timestamp:** ISO-8601 UTC, and rows come back strictly newest-first.
- **Username & role:** actor captured; role resolved from `users.json`
  (owner→Owner, Photo Staff→Photo Staff); login role taken from the response.
- **Vehicle:** extracted from the handler's own `car_number`/`vehicle` echo.
- **Filters:** each of Inventory/Media/Users/Excel/Login returns only its bucket; All = everything.
- **Search:** by vehicle, by username (incl. target user), by action; case-insensitive.
- **Failure recording:** a failed login is stored `status=failed` with the reason.
- **Security/robustness:** passwords never appear in any row; `observe()` never
  raises on garbage input; the module exposes **no** update/delete/clear/remove.
- **Owner-only & read-only method:** `permissions.enforce` allows Owner, 403s a
  non-owner; `POST /admin/audit/list` ⇒ 405.

### 3b. Live server verification (real HTTP, fresh `audit.db`)
Ran a real sequence through the running server:

| Step (real HTTP) | Result |
|---|---|
| login owner, **failed** login, create/disable/enable/reset/edit/delete user, logout (9 actions) | **9 rows written** |
| a read in the middle (`my_permissions`) | **0 rows** (not logged) |
| `GET /admin/audit/list` | newest-first, correct ts/user/role/action/status/detail |
| `?category=Users` | only the 6 user actions |
| `?category=Login` | Login/Logout incl. the failed login |
| `?search=testuser10e` | the 6 actions targeting that user |
| Photo-Staff session → `GET /admin/audit/list` | **403** (Owner-only) |
| `POST /admin/audit/list` | **405** (read-only) |
| no-session → `GET /admin/audit/list` | **403** |

### 3c. Live browser verification (Owner Panel → Activity Logs)
- Logged in as Owner → the **Activity Logs** table rendered (Time/User/Role/
  Action/Vehicle/Status), newest first, with all six filter buttons and a count.
- Clicking **Users** narrowed to the user actions; typing **`pstaff10e`** in
  search combined with the filter → "Showing 2 events · filter: Users · search:
  “pstaff10e”" (the Create + Delete of that account). **Zero console errors.**

*(Verification artifacts and the test-run `audit.db` were cleaned up afterwards so
the Owner starts with an empty, real activity log.)*

---

## 4. Regression Results

Full suite (all `*_tests.py`, including the new `audit_tests.py`):

```
python -m pytest -q *_tests.py
=> 468 passed, 1 failed
```

- **The 1 failure pre-exists this phase and is unrelated to auditing:**
  `hardening_tests.py::TestInventoryRefresh::test_refresh_returns_ok_and_count`
  asserts `inventory_count == 40`, but the live `IVR_Sheet.xlsx` now holds **44**
  vehicles — a stale data-count expectation. It failed identically before Phase
  10E (and before Phase 10D).
- **Phase 10E introduced 0 regressions.** The count went from 445 → **468**
  passing; the +23 are the new audit tests. Every previously-passing test still
  passes.

> Reminder: tests use the `*_tests.py` naming, so run `python -m pytest *_tests.py`
> (bare `pytest` uses the default `test_*.py` glob and finds nothing).

---

## 5. How it satisfies each requirement

| Requirement | How |
|---|---|
| Don't modify existing modules | Auditing is a passive observer at the HTTP choke point + a read-only endpoint. No business module changed. |
| Who / when / which vehicle | `username`, `role`, `ts`, `vehicle` columns, extracted from each request/response. |
| Log every listed action | `audit.ACTIONS` maps every supported endpoint; the unsupported "delete photo/link/car" have no endpoints and are noted. |
| Store fields (ts, user, role, action, vehicle, old, new, status) | Exactly those columns in `audit_events`. |
| Owner Panel "Activity Logs" table, newest first | New read-only card with the required columns, `ORDER BY id DESC`. |
| Search by username / vehicle / action | `query(search=…)` (plus detail, so target users are findable). |
| Filters All/Inventory/Media/Users/Excel/Login | Filter buttons → `?category=…`. |
| Read-only; nobody edits/deletes; Owner-only view | No update/delete anywhere; single `GET`; Owner-only via the unmapped-path rule. |
| Simple — no charts/graphs/dashboards/notifications | Just one table. |

---

## 6. Future integration points (not built now)
- **New actions** (if delete-photo/link/car endpoints are ever added): one entry
  each in `audit.ACTIONS` — no other change.
- **Retention / export**: a scheduled `query()`-to-CSV job could archive old rows;
  the append-only store makes this trivial and safe.
- **Old-value capture**: `old_value` is wired but mostly left blank (handlers
  don't return prior state); a future phase could snapshot before/after for edits.
