# Phase 10B — User Management — Report

**Date:** 2026-08-06
**Goal:** the Owner manages staff accounts from the Owner Panel. Users only —
**no permissions, no authentication, no audit logs** (later phases).

**Scope guardrail (honoured):** chatbot, inventory loader, Owner Panel Excel
features, dashboards, media, Supabase, logging, security, and all existing APIs
are unchanged (regression: 88 tests across 4 suites OK; Excel section verified
still working on the same page).

---

## 1. Architecture

```
owner_panel.html ("User Management" section)
        │  X-API-Key (existing /admin gate)
        ▼
/admin/users/list · create · update · set_active · reset_password · delete
        │            (user_management.py — pure stdlib)
        ▼
data/users.json           {"users": [ {id, full_name, username, password_hash,
 (+ .lock file)                        role, active, created_at} ]}
```

- **Storage:** one JSON file, written atomically under a `FileLock` (same helper
  the Excel/media panels use). Clean structure = Phase 10C reads it directly.
- **Passwords:** salted **PBKDF2-SHA256, 200k iterations**, stored as
  `pbkdf2_sha256$<iter>$<salt>$<hash>`. `verify_password()` is exported — the
  future login phase needs nothing else from this module.
- **Roles (8, no permissions attached):** Owner · Inventory Staff · Photo Staff ·
  Video Staff · Social Media Staff · Finance Staff · Document Staff ·
  Read-Only Manager.
- **Seeding:** first call creates the Owner account (`owner` / `owner123` —
  reset it from the panel). Exactly one Owner can exist.

## 2. Files changed

| File | Status | Purpose |
|---|---|---|
| `app/inventory_system/user_management.py` | **NEW** | Storage + hashing + all six handlers. |
| `app/inventory_system/owner_panel.html` | **MODIFIED (additive)** | New "User Management" card: table (Name/Username/Role/Status/Created/Actions), Create User form, per-row Edit / Reset Password / Disable-Enable / Delete. Excel sections untouched. |
| `app/inventory_system/chat_api.py` | **MODIFIED** | Registered the 6 `/admin/users/*` routes (+405 list). No existing route touched. |

## 3. Validation — 20/20 backend + UI smoke test PASS

| Check | Result |
|---|---|
| Owner auto-seeded on first list; 8 roles exposed; **no password hash in API output** | ✅ |
| Create user | ✅ |
| Duplicate username rejected — **case-insensitive** (`RAMESH` vs `ramesh`) | ✅ 409 |
| Short password (<6) rejected | ✅ |
| Creating a second Owner rejected | ✅ |
| Edit (name + role) | ✅ |
| Disable → Enable | ✅ |
| Reset password → new password verifies, old one fails (checked against the stored hash) | ✅ |
| **Owner cannot be disabled / deleted / role-changed** | ✅ 400 each |
| Delete staff user | ✅ |
| No admin key → 401 on every endpoint | ✅ |
| UI: table renders, create form works end-to-end, **owner row shows no Disable/Delete buttons**, role dropdown excludes Owner | ✅ |
| Excel management section on the same page still fully working | ✅ |

**Regression:** `chat_api_tests` 19 OK · `faq_tests` 46 OK ·
`inventory_upload_tests` 8 OK · `router_tests` 15 OK.

## 4. Future integration (Phase 10C+)

- **Login:** call `user_management.verify_password(pw, user["password_hash"])`
  after `_find()` — the module already exposes both. Check `active` to block
  disabled accounts.
- **Permissions:** attach a `permissions` list per role or per user inside
  `users.json` — readers ignore unknown keys; no schema migration needed.
- **Audit:** wrap the six handlers with the existing `inventory_edit._audit()`
  helper (one line each) when the audit phase arrives.
- **Owner key vs staff keys:** the `/admin` gate already supports multiple
  comma-separated keys; per-user API keys can map onto this later.

---

# ✅ Result: the Owner can create, edit, disable, enable, reset and delete staff accounts from the Owner Panel — with the Owner account itself untouchable — and the user store is login-ready for Phase 10C.
