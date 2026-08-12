"""
media_audit.py — append-only audit trail for every media action.

Actions: upload · excel_update · cleanup · reconciliation · failure.
Each entry records timestamp, registration, action, result, and the staff user.
"""

from __future__ import annotations

import sqlite3
import threading
from typing import Any, Dict, List, Optional

from _util import utcnow_iso

# actions
UPLOAD = "upload"
EXCEL_UPDATE = "excel_update"
CLEANUP = "cleanup"
RECONCILIATION = "reconciliation"
FAILURE = "failure"
ACTIONS = {UPLOAD, EXCEL_UPDATE, CLEANUP, RECONCILIATION, FAILURE}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS media_audit (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT,
    registration TEXT,
    action       TEXT,
    result       TEXT,
    user         TEXT,
    file_name    TEXT,
    media_type   TEXT,
    detail       TEXT
);
"""


class MediaAudit:
    def __init__(self, path: str = ":memory:", clock=utcnow_iso):
        self.path = path
        self.clock = clock
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def log(self, action: str, *, registration: Optional[str] = None,
            result: str = "success", user: str = "system",
            file_name: Optional[str] = None, media_type: Optional[str] = None,
            detail: Optional[str] = None, now: Optional[str] = None) -> int:
        now = now or self.clock()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO media_audit "
                "(timestamp,registration,action,result,user,file_name,media_type,detail) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (now, registration, action, result, user, file_name, media_type, detail))
            self._conn.commit()
            return cur.lastrowid

    # convenience
    def failure(self, *, registration=None, user="system", detail=None,
                file_name=None, media_type=None, now=None) -> int:
        return self.log(FAILURE, registration=registration, result="failure",
                        user=user, detail=detail, file_name=file_name,
                        media_type=media_type, now=now)

    # queries
    def all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(
                "SELECT * FROM media_audit ORDER BY id").fetchall()]

    def by_action(self, action: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(
                "SELECT * FROM media_audit WHERE action=? ORDER BY id",
                (action,)).fetchall()]

    def by_registration(self, registration: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(
                "SELECT * FROM media_audit WHERE registration=? ORDER BY id",
                (registration,)).fetchall()]

    def count(self, action: Optional[str] = None) -> int:
        with self._lock:
            if action:
                return self._conn.execute(
                    "SELECT COUNT(*) FROM media_audit WHERE action=?",
                    (action,)).fetchone()[0]
            return self._conn.execute("SELECT COUNT(*) FROM media_audit").fetchone()[0]

    def summary(self) -> Dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT action, COUNT(*) FROM media_audit GROUP BY action").fetchall()
            return {a: n for a, n in rows}

    def close(self) -> None:
        self._conn.close()
