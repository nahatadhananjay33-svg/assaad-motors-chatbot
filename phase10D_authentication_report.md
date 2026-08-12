# Phase 10D — Authentication & Login

**Goal:** Replace the temporary `X-Acting-User` header (Phase 10C) with a real
login. Keep it simple, modular, and production-ready. Do **not** touch the
chatbot, inventory, media, Excel, Supabase, logging, `refresh_inventory()`,
existing APIs, or the user/permission model.

**Status:** ✅ Complete. Implemented, self-validated (unit + integration + live
browser), and regression-checked. No audit logs / MFA / OAuth (out of scope by
design — this phase is the *foundation* for audit logs).

---

## 1. Architecture

### Before (Phase 10C)
The admin dashboards asked the user to type a **server address**, an **admin API
key**, and their **username** on every page. The username rode along in the
`X-Acting-User` header; `permissions.py` mapped it to a role and enforced access.

### After (Phase 10D)
```
                 ┌────────────┐   POST /auth/login {username, password}
   login.html ──▶│  chat_api  │──▶ auth.handle_login()
                 │   route()  │        │  verify against users.json (Phase 10B hash)
                 └────────────┘        ▼
                                  SessionStore.create()  ──▶  opaque token
                                        │
   token stored in localStorage ◀───────┘  (returned in JSON)

   Every later request:
   dashboard ──[X-Session-Token: <token>]──▶ chat_api._dispatch
        │                                        │ auth.resolve_user(token) → username
        │                                        ▼
        │                       SecurityGate.authorize(session_user=…)   ← session authorises /admin
        │                                        ▼
        │                       permissions.enforce(acting_user=username) ← UNCHANGED Phase 10C engine
        ▼
   AUTH.logout() ──[POST /auth/logout]──▶ SessionStore.destroy()  → redirect to login
```

**Key design decisions**

1. **Token in a header, not a cookie.** The dashboards are static HTML files
   pointed at a configurable API origin (they store the server address in
   `localStorage`). A cross-origin cookie would be fragile there; an opaque
   session **token** carried in the `X-Session-Token` header slots straight into
   how those pages already work and avoids all CORS-cookie issues.

2. **The session is a first-class admin credential.** A valid session authorises
   the `/admin/*` surface in place of the shared admin API key — per-user
   identity is stronger than a shared secret. When **no** session is present, the
   gate behaves *exactly* as Phase 10C did (admin still fails closed on the admin
   key), so nothing about the legacy path changed. The admin key still works for
   machine-to-machine callers.

3. **Identity feeds the existing permission engine, untouched.** `_dispatch`
   resolves the token to a username and passes it as `acting_user` to the same
   `permissions.enforce()` choke point. The permission matrix, field-scoping, and
   403 behaviour from Phase 10C are reused verbatim — the *only* change is where
   the username comes from (session first, `X-Acting-User` kept as a fallback for
   un-migrated tooling).

4. **Sessions are server-side and expire.** `SessionStore` is in-memory,
   thread-safe, and TTL-based (`CHAT_SESSION_TTL`, default **8 hours**). Expiry is
   checked on every access and evicted lazily; a `purge_expired()` sweep is
   available. The clock is injectable, so creation/expiry are unit-testable
   without real waiting.

5. **Modular by design (foundation for audit logs).** All auth logic lives in one
   new file, `auth.py`, exposing `resolve_user(token)` and typed
   `handle_login/logout/me`. A future audit-log phase can log
   `resolve_user()` results at the same single choke point without touching the
   permission or session internals.

### Endpoints added
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/auth/login` | public | `{username,password}` → `{token, user}` |
| POST | `/auth/logout` | `X-Session-Token` | destroy the session (idempotent) |
| GET  | `/auth/me` | `X-Session-Token` | current user, or 401 (also revokes if the account was deleted/disabled mid-session) |

### Page protection
| Page | Not logged in | Logged in, wrong role |
|---|---|---|
| `login.html` | — (this is the login page) | — |
| `inventory_admin.html` | → redirect to `login.html?next=…` | server enforces per-endpoint (buttons hidden by role) |
| `media_admin.html` | → redirect to `login.html?next=…` | server enforces per-endpoint (buttons hidden by role) |
| `owner_panel.html` | → redirect to `login.html?next=…` | **Access Denied** (Owner-only page gate) + server enforcement |

Client-side gating is UX only; the server enforces every permission independently
(defence in depth — verified below).

---

## 2. Files Changed

### New files
| File | What it is |
|---|---|
| `app/inventory_system/auth.py` | `SessionStore` (in-memory, TTL, thread-safe, injectable clock) + `handle_login/logout/me` + `resolve_user`. Reuses `user_management.verify_password` and `users.json` verbatim. |
| `app/inventory_system/login.html` | Simple white login page (username, password, optional server address). Stores the session token in `localStorage`, honours `?next=`, redirects Owner → Owner Panel, others → Inventory Dashboard. |
| `app/inventory_system/auth_guard.js` | Shared front-end guard included by the three dashboards: redirects to login when there's no session, exposes `AUTH.headers()/jheaders()` (send `X-Session-Token`), renders the “Signed in as … · Logout” bar, and `AUTH.requireOwner()` for the Owner-only page gate. |
| `app/inventory_system/auth_tests.py` | 29 tests — session lifecycle/expiry, login/logout/me, route integration, gate regression, session-driven permissions. |

### Modified files (additive / backward-compatible)
| File | Change |
|---|---|
| `chat_api.py` | Import `auth`; add `/auth/login|logout|me` routes; `route()` gains a `session_token=None` param; `_dispatch` resolves the token → `session_user`, derives `acting_user` (session wins, header fallback), and passes `session_user` to the gate. |
| `security.py` | `SecurityGate.authorize()` gains `session_user=None`: a valid session authorises `/admin`; `/auth/*` is public. Added `X-Session-Token` to the CORS allow-headers. **No change when `session_user` is absent.** |
| `owner_panel.html` | Include `auth_guard.js`; drop the manual server/key/username inputs (kept as hidden fields for compatibility); Owner-only gate; auto-load on session; Logout via the shared bar. |
| `inventory_admin.html` | Same guard wiring; identity from the session; auto-load; Logout. |
| `media_admin.html` | Same guard wiring; identity from the session; auto-load; Logout. |

**Not touched:** `chat_service.py`, `inventory_*`, `media_*`, `owner_panel.py`,
`user_management.py`, `permissions.py`, Excel, Supabase, logging,
`refresh_inventory()`, and every existing API contract.

---

## 3. Validation Results (self-run — no manual testing required)

### 3a. New auth unit + integration tests
`python -m pytest -q auth_tests.py` → **29 passed.**

Coverage:
- **SessionStore:** create/resolve, unknown token, **expiry at the TTL boundary**,
  destroy + idempotency, `purge_expired`, token uniqueness.
- **Login:** success (seeded owner), wrong password, unknown user, **identical
  message for bad-user vs bad-password** (no user enumeration), disabled account,
  missing fields, malformed body, case-insensitive username.
- **Logout / me:** valid, no token, logout-then-me, idempotent logout,
  **me after expiry**, **live revocation when an account is disabled mid-session**.
- **route():** `/auth/login → /auth/me → /auth/logout` end to end; bad creds → 401;
  wrong method → 405.
- **SecurityGate:** `/auth/*` public; session authorises `/admin`; **legacy
  admin-key path byte-for-byte unchanged**; health still public.
- **Session→permissions end to end:** a logged-in Photo Staff is 403 on an
  Owner-only endpoint and allowed on media; Owner passes everything.

### 3b. Live server verification (real HTTP, clean server on :8000)
| Check | Result |
|---|---|
| `GET /health` | `200` |
| `POST /auth/login` (owner) | `200`, 43-char token + user object |
| `GET /admin/users/list` **without** session | `403` (fails closed — no admin key set) |
| `GET /admin/users/list` **with** session | `200` |
| `POST /auth/login` wrong password | `401` |
| `GET /auth/me` | `200` |
| logout → `GET /auth/me` | `401` |
| Photo-Staff session → `owner/status`, `owner/rollback`, `users/create` | `403`, `403`, `403` |
| Photo-Staff session → `media/vehicles` | `200` |
| `my_permissions` (Photo-Staff session) | correct role + permissions, resolved from the session |

### 3c. Live browser verification (login.html + dashboards)
- Visiting `inventory_admin.html` with no session → **redirected** to
  `login.html?next=inventory_admin.html`.
- UI login as `owner` → redirected to the `next` page; Inventory Dashboard loaded
  **44 cars via the session** (no key/username typed); signed-in bar +
  Logout rendered; **zero console errors**.
- Owner → `owner_panel.html` opens and loads the live Excel.
- **Logout** button → token cleared, redirected to `login.html`.
- UI login as a **Photo Staff** user → lands on the Inventory Dashboard;
  navigating to `owner_panel.html` shows **“🚫 Access Denied — the Owner Panel is
  for the Owner account only.”** and the panel controls are removed.

---

## 4. Regression Results

Full suite (all `*_tests.py`, including the new `auth_tests.py`):

```
python -m pytest -q *_tests.py
=> 445 passed, 1 failed
```

- **Baseline before Phase 10D:** the same 1 test already failed —
  `hardening_tests.py::TestInventoryRefresh::test_refresh_returns_ok_and_count`
  asserts `inventory_count == 40`, but the current live `IVR_Sheet.xlsx` holds
  **44** vehicles. This is a **stale data-count expectation, unrelated to
  authentication**, and pre-exists this phase.
- **Phase 10D introduced 0 regressions.** Every previously-passing test still
  passes; the 29 new auth tests are additive.

> Note: the test files use the `*_tests.py` naming, so run them explicitly
> (`pytest *_tests.py`) — bare `pytest` uses the default `test_*.py` glob and
> discovers nothing.

---

## 5. Future Integration Points

This phase is deliberately the **foundation** for what comes next:

1. **Audit logs (next phase).** `_dispatch` already resolves every request to a
   real username at one choke point. An audit layer can record
   `(timestamp, username, method, path, status)` there — plus login/logout events
   inside `auth.handle_login/handle_logout` — with no change to sessions or
   permissions. `SessionStore` carries `created_at` per session for
   session-lifetime auditing.
2. **Session persistence.** Sessions are in-memory (they clear on restart — an
   acceptable, secure default). A future store can back `SessionStore` with SQLite
   (next to `leads.db`/`analytics.db`) behind the same interface.
3. **Idle timeout / sliding expiry.** Currently absolute TTL from creation.
   Sliding expiry (extend on activity) is a localized change in `SessionStore.get`.
4. **MFA / OAuth / SSO.** `handle_login` is the single authentication entry point;
   an additional factor or an external identity provider can wrap it without
   touching the dashboards or the gate.
5. **Password self-service & rotation.** `user_management` already owns hashing;
   a “change my password” endpoint can reuse `verify_password` + `hash_password`.
6. **Production hardening.** `CHAT_SESSION_TTL` tunes session length. In
   production, keep serving the dashboards and the API from the same origin (or a
   tight `ALLOWED_ORIGINS`) and set a strong Owner password on first login — the
   seeded `owner/owner123` is a first-run convenience only.

---

## 6. How to run (operator quick reference)

```bash
# 1. Start the API (serves /auth/* and /admin/* ; sessions authorise admin)
cd app/inventory_system
python chat_api.py                       # http://localhost:8000

# 2. Serve the dashboards (any static host / same origin in prod)
python -m http.server 8080               # http://localhost:8080/login.html
```

Open `login.html`, sign in (first run: `owner` / `owner123`), and every dashboard
then knows who you are — no keys or usernames to type. Use **Logout** in the top
bar to end the session.
