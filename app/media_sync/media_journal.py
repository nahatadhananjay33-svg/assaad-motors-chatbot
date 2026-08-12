"""
media_journal.py — the recovery journal.

The authoritative record of every media file: what was uploaded, where it lives
in Storage, its public URL, which Excel slot it occupies, and its lifecycle
state. This is what makes the Storage→Excel pipeline crash-safe and recoverable
(reconciliation re-applies anything that didn't reach Excel).

States:  pending_upload → uploaded → pending_excel → completed
                                   ↘ failed

Keyed on `supabase_path` (deterministic per content) → idempotent.
"""

from __future__ import annotations

import sqlite3
import threading
from typing import Any, Dict, List, Optional

from _util import utcnow_iso

# states
PENDING_UPLOAD = "pending_upload"
UPLOADED = "uploaded"
PENDING_EXCEL = "pending_excel"
COMPLETED = "completed"
FAILED = "failed"
STATES = {PENDING_UPLOAD, UPLOADED, PENDING_EXCEL, COMPLETED, FAILED}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS media_journal (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    registration_no TEXT NOT NULL,
    file_name       TEXT NOT NULL,
    media_type      TEXT NOT NULL,
    supabase_path   TEXT UNIQUE NOT NULL,
    public_url      TEXT,
    status          TEXT NOT NULL,
    slot            INTEGER,
    content_hash    TEXT,
    error           TEXT,
    created_at      TEXT,
    updated_at      TEXT
);
"""

_COLS = ["registration_no", "file_name", "media_type", "supabase_path",
         "public_url", "status", "slot", "content_hash", "error",
         "created_at", "updated_at"]


class MediaJournal:
    def __init__(self, path: str = ":memory:", clock=utcnow_iso):
        self.path = path
        self.clock = clock
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    # ── create / fetch ──
    def get_or_create(self, *, registration_no: str, file_name: str,
                      media_type: str, supabase_path: str,
                      content_hash: Optional[str] = None,
                      now: Optional[str] = None) -> Dict[str, Any]:
        now = now or self.clock()
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM media_journal WHERE supabase_path=?",
                (supabase_path,)).fetchone()
            if row:
                return dict(row)
            self._conn.execute(
                "INSERT INTO media_journal "
                "(registration_no,file_name,media_type,supabase_path,status,"
                " content_hash,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (registration_no, file_name, media_type, supabase_path,
                 PENDING_UPLOAD, content_hash, now, now))
            self._conn.commit()
            return dict(self._conn.execute(
                "SELECT * FROM media_journal WHERE supabase_path=?",
                (supabase_path,)).fetchone())

    def get(self, supabase_path: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM media_journal WHERE supabase_path=?",
                (supabase_path,)).fetchone()
            return dict(r) if r else None

    # ── update / transitions ──
    def update(self, supabase_path: str, *, now: Optional[str] = None,
               **fields: Any) -> None:
        now = now or self.clock()
        fields["updated_at"] = now
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self._conn.execute(
                f"UPDATE media_journal SET {sets} WHERE supabase_path=?",
                (*fields.values(), supabase_path))
            self._conn.commit()

    def mark_uploaded(self, supabase_path: str, public_url: str, now=None) -> None:
        self.update(supabase_path, status=UPLOADED, public_url=public_url,
                    error=None, now=now)

    def mark_pending_excel(self, supabase_path: str, now=None) -> None:
        self.update(supabase_path, status=PENDING_EXCEL, now=now)

    def mark_completed(self, supabase_path: str, slot: int, now=None) -> None:
        self.update(supabase_path, status=COMPLETED, slot=slot, error=None, now=now)

    def mark_failed(self, supabase_path: str, error: str, now=None) -> None:
        self.update(supabase_path, status=FAILED, error=error, now=now)

    # ── queries ──
    def by_status(self, *statuses: str) -> List[Dict[str, Any]]:
        marks = ",".join("?" * len(statuses))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM media_journal WHERE status IN ({marks}) ORDER BY id",
                statuses).fetchall()
            return [dict(r) for r in rows]

    def by_registration(self, registration_no: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM media_journal WHERE registration_no=? ORDER BY id",
                (registration_no,)).fetchall()
            return [dict(r) for r in rows]

    def all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(
                "SELECT * FROM media_journal ORDER BY id").fetchall()]

    def registrations(self) -> List[str]:
        with self._lock:
            return [r[0] for r in self._conn.execute(
                "SELECT DISTINCT registration_no FROM media_journal").fetchall()]

    def counts(self) -> Dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) FROM media_journal GROUP BY status").fetchall()
            return {s: n for s, n in rows}

    def delete(self, supabase_path: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM media_journal WHERE supabase_path=?",
                               (supabase_path,))
            self._conn.commit()

    def delete_registration(self, registration_no: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM media_journal WHERE registration_no=?",
                (registration_no,))
            self._conn.commit()
            return cur.rowcount

    def close(self) -> None:
        self._conn.close()
