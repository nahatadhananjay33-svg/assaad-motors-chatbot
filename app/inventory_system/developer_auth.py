"""
developer_auth.py
=================

Developer Dashboard — the separate developer-level authorization layer.

The Developer Dashboard exposes sensitive operational data (chat logs, admin
activity, errors, system internals). It MUST NOT be reachable by customers,
staff, or even the Owner. This module is the single authorization choke point
for every ``/developer/*`` endpoint.

Design (reuses the existing auth stack, adds nothing parallel):
  * Identity still comes from the EXISTING login (``auth.py`` session tokens in
    the ``X-Session-Token`` header) against the EXISTING ``users.json`` store.
  * A dedicated **"Developer"** role is the only role allowed in. It is granted
    NO business permissions (see ``permissions.ROLE_PERMISSIONS``), so a
    Developer session is *confined* to the read-only ``/developer`` surface and
    is rejected by the existing ``/admin/*`` permission engine.
  * The Developer account is created by **env-required seeding only** — it is
    minted on startup ONLY when BOTH ``DEV_DASHBOARD_USER`` and
    ``DEV_DASHBOARD_PASSWORD`` are set. There is deliberately no default
    account and no fallback password, so an un-configured deployment simply has
    no developer login (fail-closed).

Nothing here touches the chatbot, inventory, media, Excel, Supabase, or any
existing API behaviour. It only reads users/sessions and decides yes/no.
"""

from __future__ import annotations

import os
import secrets
from typing import Any, Dict, Optional, Tuple

import auth
import user_management

# The one role permitted on the Developer Dashboard.
DEV_ROLE = "Developer"


# ─────────────────────────────────────────────────────────────────────────────
# env-required seeding
# ─────────────────────────────────────────────────────────────────────────────
def _env(name: str) -> str:
    v = os.getenv(name)
    return v.strip() if v else ""


def developer_credentials_configured() -> bool:
    """True when both env vars needed to seed a developer account are present."""
    return bool(_env("DEV_DASHBOARD_USER") and _env("DEV_DASHBOARD_PASSWORD"))


def seed_developer() -> bool:
    """Ensure the Developer account exists — but ONLY when both
    ``DEV_DASHBOARD_USER`` and ``DEV_DASHBOARD_PASSWORD`` are configured.

    Idempotent and safe to call on every startup:
      * missing env vars           -> does nothing, returns False (fail-closed);
      * account already present     -> repairs role/active if drifted, but never
                                       overwrites a password the developer may
                                       have changed via the panel;
      * account missing             -> creates it with the env password.

    Returns True only when a brand-new account was created.
    """
    username = _env("DEV_DASHBOARD_USER")
    password = _env("DEV_DASHBOARD_PASSWORD")
    if not username or not password:
        return False

    with user_management.FileLock(user_management._LOCK):
        data = user_management._load()
        user_management._seed_owner(data)                 # keep owner invariant
        existing = user_management._find(data, username)
        if existing is not None:
            changed = False
            if existing.get("role") != DEV_ROLE:
                existing["role"] = DEV_ROLE
                changed = True
            if not existing.get("active", True):
                existing["active"] = True
                changed = True
            if changed:
                user_management._save(data)
            return False
        user = {
            "id": secrets.token_hex(8),
            "full_name": "System Developer",
            "username": username,
            "password_hash": user_management.hash_password(password),
            "role": DEV_ROLE,
            "active": True,
            "created_at": user_management._now(),
        }
        data["users"].append(user)
        user_management._save(data)
    return True


# ─────────────────────────────────────────────────────────────────────────────
# authorization — the single gate for every /developer/* endpoint
# ─────────────────────────────────────────────────────────────────────────────
def current_developer(session_token: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return the live user record IFF the token is a valid session for an
    ACTIVE account whose role is Developer; otherwise None.

    Re-reads users.json (like ``auth.handle_me``) so a role change or a disabled
    account takes effect immediately, even mid-session."""
    username = auth.resolve_user(session_token)
    if not username:
        return None
    try:
        data = user_management._load()
        user_management._seed_owner(data)
        u = user_management._find(data, username)
    except Exception:
        return None
    if u is None or not u.get("active", True):
        return None
    if u.get("role") != DEV_ROLE:
        return None
    return u


def is_developer(session_token: Optional[str]) -> bool:
    return current_developer(session_token) is not None


def authorize(session_token: Optional[str]
              ) -> Optional[Tuple[int, Dict[str, Any]]]:
    """Return None when the caller is an authorized Developer, else the
    (status, payload) rejection to send back.

      * no/invalid/expired session      -> 401
      * valid session, wrong role       -> 403

    A generic message is used so the endpoint never reveals whether a real
    non-developer account exists behind the token."""
    if not session_token:
        return 401, {"error": "unauthorized",
                     "detail": "Developer login required."}
    if not auth.resolve_user(session_token):
        return 401, {"error": "unauthorized",
                     "detail": "Not logged in or session expired."}
    if current_developer(session_token) is None:
        return 403, {"error": "forbidden",
                     "detail": "Developer access only."}
    return None
