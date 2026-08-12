"""
supabase_keepalive.py
=====================

Keeps the Supabase free-tier project ACTIVE so it never auto-pauses
(free projects pause after ~1 week of no activity, which kills all
car photo/video links and silently breaks uploads).

Run daily (Windows Task Scheduler locally; cron on the VPS):
    python supabase_keepalive.py

What it does: loads SUPABASE_URL / SUPABASE_KEY from the repo-root .env,
makes one tiny authenticated Storage API request (counts as activity),
and appends the outcome to data/supabase_keepalive.log so you can always
check when the last successful ping happened.

Exit codes: 0 = ping ok · 1 = ping failed (paused / no network / bad creds)
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, "..", "..", ".env")
LOG_PATH = os.path.join(HERE, "data", "supabase_keepalive.log")


def load_env() -> dict:
    creds = {}
    try:
        with open(ENV_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                creds[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return creds


def log(status: str, detail: str) -> None:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": stamp, "status": status, "detail": detail}) + "\n")


def main() -> int:
    creds = load_env()
    url = creds.get("SUPABASE_URL", "").rstrip("/")
    key = creds.get("SUPABASE_KEY", "")
    if not url or not key:
        log("error", "SUPABASE_URL/SUPABASE_KEY missing in .env")
        print("keepalive: missing credentials")
        return 1
    req = urllib.request.Request(
        url + "/storage/v1/bucket",
        headers={"apikey": key, "Authorization": "Bearer " + key},
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            body = r.read(200)
            log("ok", "HTTP %d, %d bytes" % (r.getcode(), len(body)))
            print("keepalive: ok (HTTP %d)" % r.getcode())
            return 0
    except Exception as e:
        log("fail", str(e)[:200])
        print("keepalive: FAILED —", str(e)[:120])
        print("If this keeps failing, the project may be paused: resume it at "
              "https://supabase.com/dashboard")
        return 1


if __name__ == "__main__":
    sys.exit(main())
