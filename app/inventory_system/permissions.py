"""
permissions.py
==============

Phase 10C — role-based permissions (NO login / sessions / JWT / audit — those
are later phases).

How identity reaches the backend in this phase: the admin pages send the acting
staff member's username in the **X-Acting-User** header. This module maps
username -> role (from Phase 10B's users.json) -> permission set and enforces
it on every /admin endpoint, returning **403 Forbidden** on violations.

Back-compat: a request WITHOUT X-Acting-User keeps the legacy admin-key-only
behaviour (full access). Phase 10D (login) will make identity mandatory and
verified; this module's `enforce()` is already the single choke point for that.

Permission vocabulary (strings):
    inventory.view    inventory.edit    inventory.refresh
    excel.upload      excel.rollback    excel.delete_backup
    owner.view
    users.view        users.manage
    media.view        media.photos      media.videos
    media.links       media.sold

Field-scoped editing: Finance Staff / Document Staff carry
`inventory.edit_fields` — they may call update_car but ONLY for their
columns (matched by header keywords against the live Excel schema).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

import user_management
import inventory_edit

# ─────────────────────────────────────────────────────────────────────────────
# role -> permissions
# ─────────────────────────────────────────────────────────────────────────────
ALL = "*"

ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    "Owner": {ALL},
    # Developer Dashboard role: NO business permissions. A Developer session is
    # confined to the read-only /developer surface (see developer_auth.py) and is
    # intentionally rejected by every /admin/* endpoint below (unmapped/needed
    # perms are absent from this empty set).
    "Developer": set(),
    "Inventory Staff": {"inventory.view", "inventory.edit", "inventory.refresh"},
    "Photo Staff": {"inventory.view", "media.view", "media.photos"},
    "Video Staff": {"media.view", "media.videos"},
    "Social Media Staff": {"media.view", "media.links"},
    "Finance Staff": {"inventory.view", "inventory.edit_fields"},
    "Document Staff": {"inventory.view", "inventory.edit_fields"},
    "Read-Only Manager": {"inventory.view", "media.view", "users.view",
                          "owner.view"},
}

# field-scope keyword rules (matched against the dynamic schema labels)
_FIELD_SCOPE_RE = {
    "Finance Staff": re.compile(
        r"rate|price|negotiable|emi|loan|finance|hypothecation", re.I),
    "Document Staff": re.compile(
        r"\brc\b|rc status|insurance|warranty|owner|ownership|service|noc", re.I),
}

# endpoint -> required permission
PATH_PERMISSIONS: Dict[str, str] = {
    "/admin/refresh_inventory": "inventory.refresh",
    "/admin/inventory_status": "inventory.view",
    "/admin/upload_inventory": "excel.upload",
    "/admin/inventory/dashboard": "inventory.view",
    "/admin/inventory/schema": "inventory.view",
    "/admin/inventory/vehicles": "inventory.view",
    "/admin/inventory/get_car": "inventory.view",
    "/admin/inventory/update_car": "inventory.edit",     # or edit_fields (scoped)
    "/admin/inventory/add_car": "inventory.edit",
    "/admin/inventory/restore_car": "inventory.edit",
    "/admin/inventory/duplicate_audit": "inventory.view",
    "/admin/owner/status": "owner.view",
    "/admin/owner/validate": "inventory.view",       # read-only integrity check
    "/admin/owner/upload": "excel.upload",
    "/admin/owner/rollback": "excel.rollback",
    "/admin/owner/restore_latest": "excel.rollback",   # undo last edit (owner-only)
    "/admin/owner/delete_backup": "excel.delete_backup",
    "/admin/owner/download": "excel.download",       # owner-only (has "*")
    # Customer conversation log — read-only view + export. Owner-only: no role
    # below lists "chatlogs.view", so only the Owner (ALL) is admitted; every
    # other staff role and the Developer get 403.
    "/admin/owner/chat_logs": "chatlogs.view",
    "/admin/owner/chat_logs/detail": "chatlogs.view",
    "/admin/owner/chat_logs/export": "chatlogs.view",
    "/admin/users/list": "users.view",
    "/admin/users/create": "users.manage",
    "/admin/users/update": "users.manage",
    "/admin/users/set_active": "users.manage",
    "/admin/users/reset_password": "users.manage",
    "/admin/users/delete": "users.manage",
    "/admin/users/my_permissions": None,                 # open to any known user
    "/admin/media/vehicles": "media.view",
    "/admin/media/upload_photos": "media.photos",
    "/admin/media/upload_videos": "media.videos",
    "/admin/media/add_link": "media.links",
    "/admin/media/mark_sold": "media.sold",
}

_scope_cache: Dict[str, List[str]] = {}


def _lookup_user(username: str) -> Optional[Dict[str, Any]]:
    data = user_management._load()
    user_management._seed_owner(data)
    return user_management._find(data, username)


def _allowed_col_keys(role: str, service: Any) -> List[str]:
    """Column keys ("c<n>") this field-scoped role may edit — from the live
    Excel schema, so new columns follow the same keyword rules automatically."""
    if role in _scope_cache:
        return _scope_cache[role]
    rx = _FIELD_SCOPE_RE.get(role)
    if rx is None:
        return []
    _c, schema = inventory_edit.handle_schema(service)
    keys = [f["key"] for g in schema["groups"] for f in g["fields"]
            if f["editable"] and rx.search(f["label"])]
    _scope_cache[role] = keys
    return keys


def permissions_of(role: str) -> Set[str]:
    return set(ROLE_PERMISSIONS.get(role, set()))


def _has(perms: Set[str], needed: str) -> bool:
    return ALL in perms or needed in perms


def describe(username: str, service: Any) -> Tuple[int, Dict[str, Any]]:
    """GET /admin/users/my_permissions — drives the frontend hiding."""
    if not username:
        return 200, {"username": None, "role": None, "permissions": [ALL],
                     "allowed_cols": None,
                     "note": "No acting user set — legacy full access."}
    u = _lookup_user(username)
    if u is None:
        return 403, {"error": "forbidden", "detail": "Unknown user."}
    if not u.get("active", True):
        return 403, {"error": "forbidden", "detail": "This account is disabled."}
    role = u.get("role", "")
    perms = sorted(permissions_of(role))
    cols = _allowed_col_keys(role, service) if "inventory.edit_fields" in perms else None
    return 200, {"username": u["username"], "role": role,
                 "permissions": perms, "allowed_cols": cols}


def enforce(method: str, path: str, acting_user: Optional[str],
            service: Any, body: bytes) -> Optional[Tuple[int, Dict[str, Any]]]:
    """Return None when allowed, else a (403, payload) to send back."""
    if not path.startswith("/admin"):
        return None
    if not acting_user:                      # legacy admin-key-only requests
        return None
    u = _lookup_user(acting_user)
    if u is None:
        return 403, {"error": "forbidden", "detail": "Access Denied — unknown user."}
    if not u.get("active", True):
        return 403, {"error": "forbidden", "detail": "Access Denied — account disabled."}
    role = u.get("role", "")
    perms = permissions_of(role)
    if ALL in perms:
        return None

    needed = PATH_PERMISSIONS.get(path)
    if needed is None and path in PATH_PERMISSIONS:
        return None                          # explicitly open (my_permissions)
    if needed is None:
        # unmapped admin endpoint: closed to everyone except Owner
        return 403, {"error": "forbidden",
                     "detail": "Access Denied — not allowed for your role."}

    if _has(perms, needed):
        return None

    # field-scoped editors: update_car only, restricted to their columns
    if (needed == "inventory.edit" and path == "/admin/inventory/update_car"
            and "inventory.edit_fields" in perms):
        import json as _json
        try:
            payload = _json.loads(body.decode("utf-8") or "{}")
            values = payload.get("values") or payload.get("fields") or {}
        except Exception:
            values = {}
        allowed = set(_allowed_col_keys(role, service))
        posted = {k for k in values if isinstance(k, str) and k.startswith("c")}
        blocked = sorted(posted - allowed)
        if not posted:
            return 403, {"error": "forbidden",
                         "detail": "Access Denied — nothing you may edit."}
        if blocked:
            return 403, {"error": "forbidden",
                         "detail": "Access Denied — your role cannot edit these "
                                   "fields: " + ", ".join(blocked)}
        return None

    return 403, {"error": "forbidden",
                 "detail": "Access Denied — not allowed for your role."}
