"""
config.py
=========

Single source of configuration for the backend. All paths, keys, ports, and
runtime settings are read here from environment variables (with safe defaults),
so nothing operational is hard-coded across the codebase.

Persistence lives under `data/` so it survives restarts:
    data/leads.db · data/analytics.db · data/unknown_queries.db

Env vars (all optional):
    CHAT_DATA_DIR          directory for the SQLite files (default ./data)
    CHAT_XLSX              inventory workbook path
    CHAT_HOST / CHAT_API_PORT
    CHAT_API_KEYS          comma-separated keys allowed on /chat (empty = open)
    CHAT_ADMIN_API_KEYS    comma-separated keys allowed on /admin/* (empty = open)
    CHAT_RATE_LIMIT        max requests per window (<=0 disables; default 120)
    CHAT_RATE_WINDOW       window seconds (default 60)
    CHAT_CORS_ORIGINS      comma-separated allowed origins (default *)
    CHAT_LOG_PII_MASKING   mask PII in logs (default true)
    CHAT_TOP_N             max vehicles returned per answer (default 5)
"""

from __future__ import annotations

import os
from typing import List, Set

_HERE = os.path.dirname(os.path.abspath(__file__))


def _env(name: str, default: str) -> str:
    v = os.getenv(name)
    return v if v not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, ""))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _env_list(name: str, default: List[str]) -> List[str]:
    v = os.getenv(name)
    if not v:
        return list(default)
    return [x.strip() for x in v.split(",") if x.strip()]


# ── paths ──
DATA_DIR: str = _env("CHAT_DATA_DIR", os.path.join(_HERE, "data"))
LEADS_DB: str = os.path.join(DATA_DIR, "leads.db")
ANALYTICS_DB: str = os.path.join(DATA_DIR, "analytics.db")
UNKNOWN_DB: str = os.path.join(DATA_DIR, "unknown_queries.db")
XLSX_PATH: str = _env("CHAT_XLSX", os.path.join(_HERE, "..", "IVR_Sheet.xlsx"))

# ── server ──
HOST: str = _env("CHAT_HOST", "0.0.0.0")
PORT: int = _env_int("CHAT_API_PORT", 8000)

# ── environment / deployment mode ──
# CHAT_ENV=production turns the security warnings below into hard startup
# blockers (see production_blockers()).
ENV: str = _env("CHAT_ENV", "development").strip().lower()
IS_PRODUCTION: bool = ENV in ("production", "prod")

# ── security ──
API_KEYS: Set[str] = set(_env_list("CHAT_API_KEYS", []))
ADMIN_API_KEYS: Set[str] = set(_env_list("CHAT_ADMIN_API_KEYS", []))
RATE_LIMIT_MAX: int = _env_int("CHAT_RATE_LIMIT", 120)
RATE_LIMIT_WINDOW: int = _env_int("CHAT_RATE_WINDOW", 60)
# CORS origins: prefer ALLOWED_ORIGINS (Phase 8B), fall back to the legacy
# CHAT_CORS_ORIGINS for back-compat, else wildcard (dev-only; warned at startup).
CORS_ALLOWED_ORIGINS: List[str] = _env_list(
    "ALLOWED_ORIGINS", _env_list("CHAT_CORS_ORIGINS", ["*"]))

# ── behaviour ──
LOG_PII_MASKING: bool = _env_bool("CHAT_LOG_PII_MASKING", True)
# Phase 11C: raised 5 -> 50 (≈ unlimited for this stock) so Excel-style
# filter queries ("5 seater", "MH01", "insurance wali") list EVERY match.
TOP_N: int = _env_int("CHAT_TOP_N", 50)


def ensure_data_dir(path: str = None) -> str:
    """Create the data directory if missing. Returns the directory path."""
    d = path or DATA_DIR
    os.makedirs(d, exist_ok=True)
    return d


def snapshot() -> dict:
    """Non-secret config view (safe to expose in /health). Never returns keys."""
    return {
        "data_dir": DATA_DIR,
        "xlsx_path": os.path.basename(XLSX_PATH),
        "host": HOST,
        "port": PORT,
        "env": ENV,
        "auth_required": bool(API_KEYS),
        "admin_enabled": bool(ADMIN_API_KEYS),     # admin fails closed when no key
        "admin_auth_required": bool(ADMIN_API_KEYS),
        "rate_limit_max": RATE_LIMIT_MAX,
        "rate_limit_window": RATE_LIMIT_WINDOW,
        "cors_origins": CORS_ALLOWED_ORIGINS,
        "log_pii_masking": LOG_PII_MASKING,
    }


def security_warnings() -> List[str]:
    """Human-readable warnings about insecure-for-production settings.
    Emitted loudly at startup (see chat_api.run); never raises."""
    w: List[str] = []
    if not API_KEYS:
        w.append("CHAT_API_KEYS not set — /chat accepts UNAUTHENTICATED requests "
                 "(protected only by rate limiting; front with a reverse proxy / "
                 "backend key injection in production).")
    if not ADMIN_API_KEYS:
        w.append("CHAT_ADMIN_API_KEYS not set — admin endpoints (/admin/*) are "
                 "DISABLED (fail-closed). Set CHAT_ADMIN_API_KEYS to enable inventory refresh.")
    if "*" in CORS_ALLOWED_ORIGINS:
        w.append("CORS allows ALL origins ('*') — set ALLOWED_ORIGINS to your exact "
                 "site origin(s) for production.")
    if RATE_LIMIT_MAX <= 0:
        w.append(f"Rate limiting is DISABLED (CHAT_RATE_LIMIT={RATE_LIMIT_MAX}) — "
                 "set a positive per-key requests/window for production.")
    return w


def production_blockers() -> List[str]:
    """Subset of security_warnings that MUST be fixed before serving in
    production (CHAT_ENV=production). Returns [] when safe to start."""
    b: List[str] = []
    if not ADMIN_API_KEYS:
        b.append("CHAT_ADMIN_API_KEYS must be set in production "
                 "(otherwise admin endpoints are disabled).")
    if "*" in CORS_ALLOWED_ORIGINS:
        b.append("ALLOWED_ORIGINS must be an explicit allow-list in production "
                 "(wildcard '*' is not allowed).")
    if RATE_LIMIT_MAX <= 0:
        b.append("CHAT_RATE_LIMIT must be > 0 in production.")
    return b
