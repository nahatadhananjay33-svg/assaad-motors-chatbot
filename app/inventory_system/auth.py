"""
auth.py
=======

Phase 10D — simple, production-ready authentication & sessions.

This replaces the temporary ``X-Acting-User`` header (Phase 10C) with a real
login. It is intentionally small and self-contained:

  * validate a username/password against the SAME ``users.json`` and password
    hashes created in Phase 10B (``user_management.verify_password``);
  * on success mint an opaque, cryptographically-random **session token** and
    keep the session server-side (in-memory, thread-safe, with an expiry);
  * expose ``resolve_user(token)`` so the API can turn a token back into the
    acting username and feed the EXISTING Phase 10C permission engine unchanged.

Transport: the token travels in the ``X-Session-Token`` request header (not a
cookie). The admin dashboards are static HTML files pointed at a configurable
API origin, so a header + localStorage token is more robust than a cross-origin
cookie — and it slots straight into how those pages already store settings.

Deliberately NOT in this phase (later phases build on this foundation):
  * audit logs  * MFA  * OAuth  * password-reset self-service

Nothing here touches the chatbot, inventory, media, Excel, Supabase, logging, or
``refresh_inventory()``. ``SessionStore`` takes an injectable clock so session
creation and **expiry** are unit-testable without real waiting.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from typing import Any, Dict, Optional, Tuple

import user_management

# Session lifetime (seconds). Override with CHAT_SESSION_TTL. Default 8 hours —
# a normal dealership working day; the user logs in once each morning.
try:
    DEFAULT_TTL = int(os.getenv("CHAT_SESSION_TTL", "") or 8 * 3600)
except ValueError:
    DEFAULT_TTL = 8 * 3600


# ─────────────────────────────────────────────────────────────────────────────
# Session store (in-memory, thread-safe, TTL). Injectable clock for testing.
# ─────────────────────────────────────────────────────────────────────────────
class SessionStore:
    def __init__(self, ttl: int = DEFAULT_TTL, clock=time.time):
        self.ttl = int(ttl)
        self.clock = clock
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create(self, username: str, role: str) -> str:
        """Mint a new session for ``username`` and return its token."""
        token = secrets.token_urlsafe(32)
        now = self.clock()
        with self._lock:
            self._sessions[token] = {
                "username": username,
                "role": role,
                "created_at": now,
                "expires_at": now + self.ttl,
            }
        return token

    def get(self, token: Optional[str]) -> Optional[Dict[str, Any]]:
        """Return a copy of the live session, or None if missing/expired.
        Expired sessions are evicted lazily on access."""
        if not token:
            return None
        now = self.clock()
        with self._lock:
            s = self._sessions.get(token)
            if s is None:
                return None
            if s["expires_at"] <= now:
                del self._sessions[token]
                return None
            return dict(s)

    def username_for(self, token: Optional[str]) -> Optional[str]:
        s = self.get(token)
        return s["username"] if s else None

    def destroy(self, token: Optional[str]) -> bool:
        """Log out: drop the session. Returns True if one was removed."""
        if not token:
            return False
        with self._lock:
            return self._sessions.pop(token, None) is not None

    def purge_expired(self) -> int:
        """Evict all expired sessions. Returns how many were removed."""
        now = self.clock()
        with self._lock:
            dead = [t for t, s in self._sessions.items() if s["expires_at"] <= now]
            for t in dead:
                del self._sessions[t]
        return len(dead)

    def active_count(self) -> int:
        self.purge_expired()
        with self._lock:
            return len(self._sessions)


# Module-level singleton the API uses in production. Tests can inject their own.
SESSIONS = SessionStore()


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────
def _parse(body: bytes) -> Optional[Dict[str, Any]]:
    try:
        p = json.loads((body or b"").decode("utf-8") or "{}")
        return p if isinstance(p, dict) else None
    except (ValueError, UnicodeDecodeError):
        return None


def _authenticate(username: str, password: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Return (user, None) on success, else (None, reason_detail).

    Reuses Phase 10B storage + hashing verbatim; never reveals whether it was
    the username or the password that was wrong (single generic message)."""
    data = user_management._load()
    user_management._seed_owner(data)          # first-run owner is always present
    u = user_management._find(data, username)
    generic = "Invalid username or password."
    if u is None:
        return None, generic
    if not user_management.verify_password(password, u.get("password_hash", "")):
        return None, generic
    if not u.get("active", True):
        return None, "This account is disabled. Contact the owner."
    return u, None


def _public_user(u: Dict[str, Any]) -> Dict[str, Any]:
    return {"username": u.get("username"), "full_name": u.get("full_name"),
            "role": u.get("role")}


# ─────────────────────────────────────────────────────────────────────────────
# request handlers — each returns (http_status, json_payload)
# ─────────────────────────────────────────────────────────────────────────────
def handle_login(body: bytes, store: Optional[SessionStore] = None
                 ) -> Tuple[int, Dict[str, Any]]:
    """POST /auth/login  {username, password} -> {token, user}."""
    store = store or SESSIONS
    p = _parse(body)
    if p is None:
        return 400, {"status": "error", "detail": "Body must be a JSON object."}
    username = (p.get("username") or "").strip()
    password = p.get("password") or ""
    if not username or not password:
        return 400, {"status": "error",
                     "detail": "Username and password are required."}
    user, reason = _authenticate(username, password)
    if user is None:
        return 401, {"status": "error", "detail": reason}
    token = store.create(user["username"], user.get("role", ""))
    return 200, {"status": "ok", "token": token, "user": _public_user(user)}


def handle_logout(token: Optional[str], store: Optional[SessionStore] = None
                  ) -> Tuple[int, Dict[str, Any]]:
    """POST /auth/logout (X-Session-Token) -> destroys the session."""
    store = store or SESSIONS
    store.destroy(token)                       # idempotent — always report success
    return 200, {"status": "ok", "message": "Logged out."}


def handle_me(token: Optional[str], store: Optional[SessionStore] = None
              ) -> Tuple[int, Dict[str, Any]]:
    """GET /auth/me (X-Session-Token) -> the logged-in user, or 401."""
    store = store or SESSIONS
    s = store.get(token)
    if s is None:
        return 401, {"status": "error", "detail": "Not logged in or session expired."}
    data = user_management._load()
    user_management._seed_owner(data)
    u = user_management._find(data, s["username"])
    if u is None:
        store.destroy(token)                   # user was deleted mid-session
        return 401, {"status": "error", "detail": "Account no longer exists."}
    if not u.get("active", True):
        store.destroy(token)                   # user was disabled mid-session
        return 401, {"status": "error", "detail": "This account is disabled."}
    return 200, {"status": "ok", "user": _public_user(u)}


def resolve_user(token: Optional[str], store: Optional[SessionStore] = None
                 ) -> Optional[str]:
    """Turn a session token into the acting username (or None). This is the
    single hook the API uses to feed the Phase 10C permission engine."""
    store = store or SESSIONS
    return store.username_for(token)
