"""
media_reconciliation.py — repair drift between Storage, the Journal, and Excel.

Repairs:
  * Uploaded to Supabase but Excel update failed  → retry the Excel write.
  * Excel cell clobbered (URL the journal says is done is gone) → re-apply.
  * Journal/Excel says present but the Storage file is missing → flag.
  * Storage object with no journal entry → flag as orphan.

`reconciliation_report()` returns the current drift snapshot (read-only).
`reconcile()` performs the repairs and logs them to the audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import openpyxl

from _poc import read_layout, index_rows
from _util import utcnow_iso
import media_journal as J
import media_audit as A
from media_sync_service import apply_pending_to_excel


@dataclass
class ReconReport:
    excel_reapplied: int = 0
    clobbers_repaired: int = 0
    missing_file_flagged: int = 0
    orphan_storage: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "excel_reapplied": self.excel_reapplied,
            "clobbers_repaired": self.clobbers_repaired,
            "missing_file_flagged": self.missing_file_flagged,
            "orphan_storage": self.orphan_storage,
            "details": self.details,
        }


class ReconciliationEngine:
    def __init__(self, journal: J.MediaJournal, workbook_path: str, store,
                 audit: A.MediaAudit, *, bucket: str, lock_path: str,
                 backup_dir: Optional[str] = None, clock=utcnow_iso):
        self.journal = journal
        self.workbook_path = workbook_path
        self.store = store
        self.audit = audit
        self.bucket = bucket
        self.lock_path = lock_path
        self.backup_dir = backup_dir
        self.clock = clock

    # ── read-only drift snapshot ──
    def reconciliation_report(self) -> Dict[str, Any]:
        counts = self.journal.counts()
        missing = [e["supabase_path"] for e in self.journal.all()
                   if e["status"] in (J.UPLOADED, J.PENDING_EXCEL, J.COMPLETED)
                   and not self.store.exists(self.bucket, e["supabase_path"])]
        journal_paths = {e["supabase_path"] for e in self.journal.all()}
        orphans = [p for p in self.store.list_paths(self.bucket) if p not in journal_paths]
        clobbered = [e["supabase_path"] for e in self._detect_clobbers()]
        return {
            "journal_counts": counts,
            "pending_excel": len(self.journal.by_status(J.UPLOADED))
                             + len(self.journal.by_status(J.PENDING_EXCEL)),
            "missing_storage_files": missing,
            "orphan_storage_files": orphans,
            "clobbered_excel": clobbered,
        }

    # ── detect completed entries whose URL is no longer in Excel ──
    def _detect_clobbers(self) -> List[Dict[str, Any]]:
        completed = self.journal.by_status(J.COMPLETED)
        if not completed:
            return []
        wb = openpyxl.load_workbook(self.workbook_path)
        ws = wb.active
        layout = read_layout(ws)
        rows = index_rows(ws, layout.car_col) if layout.car_col else {}
        clobbered = []
        for e in completed:
            reg, mtype, url = e["registration_no"], e["media_type"], e["public_url"]
            if reg not in rows:
                continue
            slot_cols = layout.slots.get(mtype, [])
            present = [ws.cell(rows[reg], c).value for c in slot_cols]
            if url not in [v for v in present if v]:
                clobbered.append(e)
        wb.close()
        return clobbered

    # ── perform repairs ──
    def reconcile(self, *, user: str = "system", now: Optional[str] = None) -> ReconReport:
        now = now or self.clock()
        report = ReconReport()

        # (1) clobber repair: completed-but-missing-in-Excel → back to pending_excel
        for e in self._detect_clobbers():
            self.journal.mark_pending_excel(e["supabase_path"], now=now)
            report.clobbers_repaired += 1

        # (2) re-apply all pending (covers "uploaded but Excel failed" + clobbers)
        res = apply_pending_to_excel(
            self.journal, self.workbook_path, self.audit, bucket=self.bucket,
            lock_path=self.lock_path, backup_dir=self.backup_dir, user=user, now=now)
        report.excel_reapplied = res.get("written", 0)
        report.details["excel"] = res

        # (3) storage file missing → flag (mark failed, audit)
        for e in self.journal.all():
            if e["status"] in (J.UPLOADED, J.PENDING_EXCEL, J.COMPLETED) \
                    and not self.store.exists(self.bucket, e["supabase_path"]):
                self.journal.mark_failed(e["supabase_path"], "storage_object_missing", now=now)
                self.audit.log(A.RECONCILIATION, registration=e["registration_no"],
                               result="failure", user=user,
                               detail=f"storage file missing: {e['supabase_path']}", now=now)
                report.missing_file_flagged += 1

        # (4) orphan storage object (no journal entry) → flag
        journal_paths = {e["supabase_path"] for e in self.journal.all()}
        for p in self.store.list_paths(self.bucket):
            if p not in journal_paths:
                report.orphan_storage.append(p)
                self.audit.log(A.RECONCILIATION, result="flagged", user=user,
                               detail=f"orphan storage object: {p}", now=now)

        self.audit.log(A.RECONCILIATION, result="success", user=user,
                       detail=f"reapplied={report.excel_reapplied} "
                              f"clobbers={report.clobbers_repaired} "
                              f"missing={report.missing_file_flagged} "
                              f"orphans={len(report.orphan_storage)}", now=now)
        return report
