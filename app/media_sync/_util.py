"""
_util.py — production utilities for the media sync layer.

Cross-process file locking, atomic workbook writes, Excel open-lock detection,
content hashing, and deterministic-friendly time helpers (injectable clock).
"""

from __future__ import annotations

import os
import time
import errno
import shutil
import hashlib
import tempfile
from datetime import datetime, timezone, timedelta
from typing import Optional


# ── time ──
def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_days(iso_ts: str, days: int) -> str:
    return (datetime.fromisoformat(iso_ts) + timedelta(days=days)).isoformat()


def is_past(deadline_iso: str, now_iso: str) -> bool:
    return datetime.fromisoformat(now_iso) >= datetime.fromisoformat(deadline_iso)


# ── content hashing (idempotent storage paths) ──
def sha1_file(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Excel "open by a human" detection (Office lock file ~$name.xlsx) ──
def excel_open_by_user(workbook_path: str) -> bool:
    d = os.path.dirname(os.path.abspath(workbook_path))
    n = os.path.basename(workbook_path)
    return os.path.exists(os.path.join(d, "~$" + n))


# ── cross-process advisory file lock ──
class FileLock:
    """Lockfile-based mutual exclusion (atomic O_EXCL create). Safe across
    processes on one host. Used to serialize workbook writes among staff syncs."""

    def __init__(self, lock_path: str, timeout: float = 15.0, poll: float = 0.05,
                 stale_after: float = 120.0):
        self.lock_path = lock_path
        self.timeout = timeout
        self.poll = poll
        self.stale_after = stale_after
        self._fd: Optional[int] = None

    def acquire(self) -> "FileLock":
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self._fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self._fd, str(os.getpid()).encode())
                return self
            except FileExistsError:
                # break a stale lock if its holder is long gone
                try:
                    age = time.time() - os.path.getmtime(self.lock_path)
                    if age > self.stale_after:
                        os.remove(self.lock_path)
                        continue
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"could not acquire lock: {self.lock_path}")
                time.sleep(self.poll)
            except OSError as e:
                if e.errno == errno.EEXIST:
                    time.sleep(self.poll)
                    continue
                raise

    def release(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        try:
            os.remove(self.lock_path)
        except OSError:
            pass

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()


# ── atomic workbook save (temp + os.replace) with optional backup ──
def atomic_save_workbook(wb, path: str, backup_dir: Optional[str] = None,
                         now_iso: Optional[str] = None) -> Optional[str]:
    """Write to a temp file in the same dir, optionally back up the current file,
    then atomically replace. A crash mid-write never corrupts the master."""
    d = os.path.dirname(os.path.abspath(path)) or "."
    backup_path = None
    if backup_dir and os.path.exists(path):
        os.makedirs(backup_dir, exist_ok=True)
        stamp = (now_iso or utcnow_iso()).replace(":", "").replace("-", "").replace(".", "")
        backup_path = os.path.join(backup_dir, f"{os.path.basename(path)}.{stamp}.bak")
        shutil.copy2(path, backup_path)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".xlsx")
    os.close(fd)
    try:
        wb.save(tmp)
        os.replace(tmp, path)          # atomic on the same volume
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return backup_path
