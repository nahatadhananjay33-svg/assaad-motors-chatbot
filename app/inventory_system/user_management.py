"""
user_management.py
==================

Phase 10B — simple staff user management for the Owner Panel.

Scope (deliberately small): create / edit / disable / enable / reset-password /
delete users, stored in a clean JSON structure that Phase 10C (login) can use
as-is. NO permissions, NO authentication, NO audit logs in this phase.

Storage: data/users.json
    {"users": [{"id", "full_name", "username", "password_hash",
                "role", "active", "created_at"}, ...]}

Passwords are salted PBKDF2-SHA256 (stdlib only), stored as
"pbkdf2_sha256$<iterations>$<salt-hex>$<hash-hex>". `verify_password()` is
exported for Phase 10C — login needs nothing else from this file.

Rules enforced here:
  * usernames are unique (case-insensitive)
  * the Owner account can never be deleted or disabled (role "Owner")
  * an Owner account is seeded on first run (username "owner",
    password "owner123" — reset it from the panel)

Endpoints (all behind the existing /admin key gate):
    GET  /admin/users/list
    POST /admin/users/create          {full_name, username, password, role}
    POST /admin/users/update          {username, full_name?, role?}
    POST /admin/users/set_active      {username, active}
    POST /admin/users/reset_password  {username, new_password}
    POST /admin/users/delete          {username}
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

_MS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "media_sync")
if _MS_DIR not in sys.path:
    sys.path.insert(0, _MS_DIR)
from _util import FileLock  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
USERS_PATH = os.path.join(DATA_DIR, "users.json")
_LOCK = USERS_PATH + ".lock"

ROLES = ["Owner", "Inventory Staff", "Photo Staff", "Video Staff",
         "Social Media Staff", "Finance Staff", "Document Staff",
         "Read-Only Manager"]

_PBKDF2_ITERATIONS = 200_000


# ─────────────────────────────────────────────────────────────────────────────
# password hashing (stdlib only) — verify_password() is Phase 10C's hook
# ─────────────────────────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 bytes.fromhex(salt), _PBKDF2_ITERATIONS)
    return "pbkdf2_sha256$%d$%s$%s" % (_PBKDF2_ITERATIONS, salt, digest.hex())


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt, expect = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                     bytes.fromhex(salt), int(iters))
        return secrets.compare_digest(digest.hex(), expect)
    except (ValueError, AttributeError):
        return False


# ─────────────────────────────────────────────────────────────────────────────
# storage
# ─────────────────────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load() -> Dict[str, Any]:
    try:
        with open(USERS_PATH, encoding="utf-8") as f:
            d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get("users"), list):
                return d
    except (OSError, ValueError):
        pass
    return {"users": []}


def _save(data: Dict[str, Any]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = USERS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, USERS_PATH)


def _seed_owner(data: Dict[str, Any]) -> bool:
    """Ensure one Owner account exists (first run). Returns True if seeded."""
    if any(u.get("role") == "Owner" for u in data["users"]):
        return False
    data["users"].insert(0, {
        "id": secrets.token_hex(8),
        "full_name": "Dealership Owner",
        "username": "owner",
        "password_hash": hash_password("owner123"),
        "role": "Owner",
        "active": True,
        "created_at": _now(),
    })
    return True


def _find(data: Dict[str, Any], username: str) -> Optional[Dict[str, Any]]:
    uname = (username or "").strip().lower()
    for u in data["users"]:
        if u.get("username", "").lower() == uname:
            return u
    return None


def _public(u: Dict[str, Any]) -> Dict[str, Any]:
    return {k: u.get(k) for k in ("id", "full_name", "username", "role",
                                  "active", "created_at")}


def _parse(body: bytes) -> Optional[Dict[str, Any]]:
    try:
        p = json.loads(body.decode("utf-8") or "{}")
        return p if isinstance(p, dict) else None
    except ValueError:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# handlers
# ─────────────────────────────────────────────────────────────────────────────
def handle_list() -> Tuple[int, Dict[str, Any]]:
    with FileLock(_LOCK):
        data = _load()
        if _seed_owner(data):
            _save(data)
    return 200, {"users": [_public(u) for u in data["users"]], "roles": ROLES}


def handle_create(body: bytes) -> Tuple[int, Dict[str, Any]]:
    p = _parse(body)
    if p is None:
        return 400, {"status": "error", "detail": "Body must be a JSON object."}
    full_name = (p.get("full_name") or "").strip()
    username = (p.get("username") or "").strip()
    password = p.get("password") or ""
    role = (p.get("role") or "").strip()
    if not full_name or not username:
        return 400, {"status": "error", "detail": "Full name and username are required."}
    if not username.replace("_", "").replace(".", "").isalnum():
        return 400, {"status": "error",
                     "detail": "Username: letters, numbers, dot or underscore only."}
    if len(password) < 6:
        return 400, {"status": "error", "detail": "Password must be at least 6 characters."}
    if role not in ROLES:
        return 400, {"status": "error", "detail": "Unknown role."}
    if role == "Owner":
        return 400, {"status": "error",
                     "detail": "There is only one Owner account — it already exists."}
    with FileLock(_LOCK):
        data = _load()
        _seed_owner(data)
        if _find(data, username):
            return 409, {"status": "error", "detail": "This username already exists."}
        user = {"id": secrets.token_hex(8), "full_name": full_name,
                "username": username, "password_hash": hash_password(password),
                "role": role, "active": True, "created_at": _now()}
        data["users"].append(user)
        _save(data)
    return 200, {"status": "ok", "message": "User created.", "user": _public(user)}


def handle_update(body: bytes) -> Tuple[int, Dict[str, Any]]:
    p = _parse(body)
    if p is None:
        return 400, {"status": "error", "detail": "Body must be a JSON object."}
    username = (p.get("username") or "").strip()
    if not username:
        return 400, {"status": "error", "detail": "Missing 'username'."}
    with FileLock(_LOCK):
        data = _load()
        u = _find(data, username)
        if u is None:
            return 404, {"status": "error", "detail": "User not found."}
        if "full_name" in p and (p["full_name"] or "").strip():
            u["full_name"] = p["full_name"].strip()
        if "role" in p and p["role"]:
            if u.get("role") == "Owner":
                return 400, {"status": "error",
                             "detail": "The Owner account's role cannot be changed."}
            if p["role"] not in ROLES or p["role"] == "Owner":
                return 400, {"status": "error", "detail": "Unknown role."}
            u["role"] = p["role"]
        _save(data)
    return 200, {"status": "ok", "message": "User updated.", "user": _public(u)}


def handle_set_active(body: bytes) -> Tuple[int, Dict[str, Any]]:
    p = _parse(body)
    if p is None:
        return 400, {"status": "error", "detail": "Body must be a JSON object."}
    username = (p.get("username") or "").strip()
    active = bool(p.get("active"))
    with FileLock(_LOCK):
        data = _load()
        u = _find(data, username)
        if u is None:
            return 404, {"status": "error", "detail": "User not found."}
        if u.get("role") == "Owner" and not active:
            return 400, {"status": "error",
                         "detail": "The Owner account cannot be disabled."}
        u["active"] = active
        _save(data)
    verb = "enabled" if active else "disabled"
    return 200, {"status": "ok", "message": f"User {verb}.", "user": _public(u)}


def handle_reset_password(body: bytes) -> Tuple[int, Dict[str, Any]]:
    p = _parse(body)
    if p is None:
        return 400, {"status": "error", "detail": "Body must be a JSON object."}
    username = (p.get("username") or "").strip()
    new_password = p.get("new_password") or ""
    if len(new_password) < 6:
        return 400, {"status": "error", "detail": "Password must be at least 6 characters."}
    with FileLock(_LOCK):
        data = _load()
        u = _find(data, username)
        if u is None:
            return 404, {"status": "error", "detail": "User not found."}
        u["password_hash"] = hash_password(new_password)
        _save(data)
    return 200, {"status": "ok", "message": "Password reset.", "user": _public(u)}


def handle_delete(body: bytes) -> Tuple[int, Dict[str, Any]]:
    p = _parse(body)
    if p is None:
        return 400, {"status": "error", "detail": "Body must be a JSON object."}
    username = (p.get("username") or "").strip()
    with FileLock(_LOCK):
        data = _load()
        u = _find(data, username)
        if u is None:
            return 404, {"status": "error", "detail": "User not found."}
        if u.get("role") == "Owner":
            return 400, {"status": "error",
                         "detail": "The Owner account cannot be deleted."}
        data["users"] = [x for x in data["users"] if x is not u]
        _save(data)
    return 200, {"status": "ok", "message": "User deleted."}
