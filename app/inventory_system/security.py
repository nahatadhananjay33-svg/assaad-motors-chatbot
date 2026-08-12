"""
security.py
==========

Edge security + privacy utilities for the API: API-key auth, rate limiting,
configurable CORS, and PII masking for logs. Deterministic, dependency-free.

  * `RateLimiter`   — fixed-window per-key limiter (thread-safe).
  * `SecurityGate`  — authorizes a request (api key + rate limit) and builds CORS.
  * `mask_pii`      — redacts phone numbers and names from log strings.

Auth model:
  * /chat   — OPT-IN: when no CHAT_API_KEYS are configured, requests are allowed
              (so local/dev and the test-suite keep working). Configure in prod.
  * /admin/* — FAILS CLOSED: with no admin key configured the admin surface is
              DISABLED (403), never silently open. Set CHAT_ADMIN_API_KEYS to enable.
"""

from __future__ import annotations

import re
import time
import threading
from collections import defaultdict, deque
from typing import Any, Dict, Iterable, Optional, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# PII masking (for logs — never log a raw phone number)
# ─────────────────────────────────────────────────────────────────────────────
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[\-\s]?|0)?[6-9]\d{9}(?!\d)")
_NAME_RE = re.compile(
    r"\b(my name is|i am|i'?m|myself|mera naam|naam)\s+([a-z]+(?:\s+[a-z]+)?)",
    re.I)
_NAME_FILLERS = {"hai", "hu", "hoon", "looking", "interested", "calling", "from"}


def mask_phone(text: str) -> str:
    return _PHONE_RE.sub("[PHONE]", text or "")


def _mask_name(match: "re.Match") -> str:
    cue = match.group(1)
    tokens = [t for t in match.group(2).split() if t.lower() not in _NAME_FILLERS]
    if not tokens:
        return match.group(0)
    return f"{cue} [NAME]"


def mask_pii(text: Optional[str]) -> Optional[str]:
    """Redact phone numbers and explicit names from a log string."""
    if not text:
        return text
    t = _PHONE_RE.sub("[PHONE]", text)
    t = _NAME_RE.sub(_mask_name, t)
    return t


# ─────────────────────────────────────────────────────────────────────────────
# Rate limiting (fixed window per key)
# ─────────────────────────────────────────────────────────────────────────────
class RateLimiter:
    def __init__(self, max_requests: int, window_sec: int, clock=time.time):
        self.max = max_requests
        self.window = window_sec
        self.clock = clock
        self._hits: Dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        if self.max <= 0:                      # disabled
            return True
        now = self.clock()
        with self._lock:
            dq = self._hits[key]
            cutoff = now - self.window
            while dq and dq[0] <= cutoff:
                dq.popleft()
            if len(dq) >= self.max:
                return False
            dq.append(now)
            return True


# ─────────────────────────────────────────────────────────────────────────────
# API-key helpers
# ─────────────────────────────────────────────────────────────────────────────
def extract_api_key(headers: Dict[str, str]) -> Optional[str]:
    """Read the key from X-API-Key or 'Authorization: Bearer <key>'."""
    def _get(name: str) -> Optional[str]:
        return headers.get(name) or headers.get(name.lower()) or headers.get(name.title())
    k = _get("X-API-Key")
    if k:
        return k.strip()
    auth = _get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def key_ok(provided: Optional[str], allowed: Iterable[str]) -> bool:
    allowed = set(allowed)
    if not allowed:                            # auth disabled
        return True
    return provided in allowed


# ─────────────────────────────────────────────────────────────────────────────
# CORS
# ─────────────────────────────────────────────────────────────────────────────
def cors_headers(origin: Optional[str], allowed_origins: Iterable[str]) -> Dict[str, str]:
    allowed = list(allowed_origins)
    if "*" in allowed:
        allow = "*"
    elif origin and origin in allowed:
        allow = origin
    else:
        return {}
    return {
        "Access-Control-Allow-Origin": allow,
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, X-API-Key, Authorization, X-Acting-User, X-Session-Token",
        "Access-Control-Max-Age": "600",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Security gate
# ─────────────────────────────────────────────────────────────────────────────
class SecurityGate:
    def __init__(self, *, api_keys: Iterable[str] = (), admin_keys: Iterable[str] = (),
                 limiter: Optional[RateLimiter] = None,
                 allowed_origins: Iterable[str] = ("*",)):
        self.api_keys = set(api_keys)
        self.admin_keys = set(admin_keys)
        self.limiter = limiter
        self.allowed_origins = list(allowed_origins)

    def authorize(self, method: str, path: str, headers: Dict[str, str],
                  client_id: str, session_user: Optional[str] = None
                  ) -> Optional[Tuple[int, Dict[str, Any]]]:
        """Return None if allowed, else (status, body) to reject with.

        ``session_user`` (Phase 10D) is the username resolved from a valid
        ``X-Session-Token`` — a logged-in staff member. When present it is a
        first-class admin credential: it authorizes the /admin surface in place
        of the shared admin API key. When absent, behaviour is exactly as before
        (admin fails closed on the admin key), so nothing about the legacy path
        changes."""
        path_n = path.split("?", 1)[0].rstrip("/") or "/"
        provided = extract_api_key(headers)

        if path_n in ("/", "/health") or path_n.startswith("/auth"):
            pass                                   # health + login are public
        elif path_n.startswith("/admin"):
            # Phase 10D: a valid session authorizes admin (per-user identity is
            # stronger than a shared key). Fall back to the legacy admin-key
            # gate — which still FAILS CLOSED — when there is no session.
            if session_user:
                pass
            elif not self.admin_keys:
                return 403, {"error": "admin_disabled",
                             "detail": "Admin endpoints are disabled: no admin API "
                                       "key configured (set CHAT_ADMIN_API_KEYS)."}
            elif not key_ok(provided, self.admin_keys):
                return 401, {"error": "unauthorized", "detail": "admin API key required"}
        else:
            if not key_ok(provided, self.api_keys):
                return 401, {"error": "unauthorized", "detail": "API key required"}

        rl_key = provided or client_id or "anon"
        if self.limiter and not self.limiter.allow(rl_key):
            return 429, {"error": "rate_limited", "detail": "too many requests"}
        return None

    def cors(self, origin: Optional[str]) -> Dict[str, str]:
        return cors_headers(origin, self.allowed_origins)
