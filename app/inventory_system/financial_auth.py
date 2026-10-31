"""
financial_auth.py
==================

Authorization gate for the **Assad Motors Financial** console (``/financial/*``).

The financial console exposes sensitive internal data (purchase cost, profit/
loss, investor names, yields). It MUST NOT be reachable by customers. This is the
single choke point for every ``/financial/api/*`` endpoint.

Reuses the EXISTING auth stack (``auth.py`` session tokens in the
``X-Session-Token`` header, ``users.json`` store) — nothing parallel. Only the
**Owner** and **Finance Staff** roles are allowed in; every other role (and an
anonymous visitor) is rejected. Read-only: nothing here mutates anything.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import auth
import user_management

# Roles permitted on the Financial console.
ALLOWED_ROLES = {"Owner", "Finance Staff"}


def current_user(session_token: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return the live user record IFF the token is a valid session for an
    ACTIVE account whose role is allowed; otherwise None. Re-reads users.json so
    a role change / disabled account takes effect immediately."""
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
    if u.get("role") not in ALLOWED_ROLES:
        return None
    return u


def authorize(session_token: Optional[str]
              ) -> Optional[Tuple[int, Dict[str, Any]]]:
    """None when the caller may use the Financial console, else the rejection.
      * no/invalid/expired session -> 401
      * valid session, wrong role  -> 403
    """
    if not session_token:
        return 401, {"error": "unauthorized",
                     "detail": "Financial console login required."}
    if not auth.resolve_user(session_token):
        return 401, {"error": "unauthorized",
                     "detail": "Not logged in or session expired."}
    if current_user(session_token) is None:
        return 403, {"error": "forbidden",
                     "detail": "Financial console is for the Owner / Finance team only."}
    return None
