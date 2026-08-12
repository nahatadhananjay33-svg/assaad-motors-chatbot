"""
inventory_sync.py
=================

Syncs normalized `InventoryItem`s into the Supabase `inventory` table following
the approved Option-C workflow (`final_inventory_architecture.md` §5.4–5.5):

  * UPSERT by `registration_no` (the natural key).
  * Idempotent — re-running with the same data produces zero changes.
  * Update existing records when business fields actually change.
  * Soft-deactivate registrations that vanish from the sheet
    (listing_status -> 'inactive'); never hard-delete.
  * Sold-car suppression — sold rows are written but never customer-facing.

The Supabase client is *pluggable* so this runs in tests / CI / dry-runs with no
network. Provide:
  * `InMemoryInventoryStore`  — fake store used by tests and offline runs, OR
  * `SupabaseInventoryStore`  — thin adapter over supabase-py (optional import).

Both satisfy the `InventoryStore` protocol below.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

from inventory_models import InventoryItem, ListingStatus, utcnow_iso

TABLE = "inventory"


# ─────────────────────────────────────────────────────────────────────────────
# Storage abstraction
# ─────────────────────────────────────────────────────────────────────────────
class InventoryStore(Protocol):
    def fetch_all(self) -> List[Dict[str, Any]]:
        """Return every existing inventory record as a dict."""
        ...

    def upsert(self, record: Dict[str, Any]) -> None:
        """Insert or update a record keyed on registration_no."""
        ...

    def deactivate(self, registration_no: str, when: str) -> None:
        """Soft-deactivate a record (listing_status -> inactive)."""
        ...


class InMemoryInventoryStore:
    """A dict-backed store keyed on registration_no — for tests / dry-runs."""

    def __init__(self) -> None:
        self._db: Dict[str, Dict[str, Any]] = {}

    def fetch_all(self) -> List[Dict[str, Any]]:
        return [dict(v) for v in self._db.values()]

    def upsert(self, record: Dict[str, Any]) -> None:
        reg = record["registration_no"]
        self._db[reg] = dict(record)

    def deactivate(self, registration_no: str, when: str) -> None:
        if registration_no in self._db:
            self._db[registration_no]["listing_status"] = ListingStatus.INACTIVE
            self._db[registration_no]["updated_at"] = when

    # convenience for assertions
    def get(self, registration_no: str) -> Optional[Dict[str, Any]]:
        rec = self._db.get(registration_no)
        return dict(rec) if rec else None

    def __len__(self) -> int:
        return len(self._db)


class SupabaseInventoryStore:
    """
    Thin adapter over supabase-py. Imported lazily so the rest of the system
    (and all tests) run without the dependency or credentials.
    """

    def __init__(self, url: str, key: str, table: str = TABLE) -> None:
        from supabase import create_client  # optional dependency
        self._client = create_client(url, key)
        self._table = table

    def fetch_all(self) -> List[Dict[str, Any]]:
        res = self._client.table(self._table).select("*").execute()
        return res.data or []

    def upsert(self, record: Dict[str, Any]) -> None:
        self._client.table(self._table).upsert(
            record, on_conflict="registration_no"
        ).execute()

    def deactivate(self, registration_no: str, when: str) -> None:
        self._client.table(self._table).update(
            {"listing_status": ListingStatus.INACTIVE, "updated_at": when}
        ).eq("registration_no", registration_no).execute()


# ─────────────────────────────────────────────────────────────────────────────
# Sync report
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class SyncReport:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    deactivated: int = 0
    sold: int = 0
    placeholders_quarantined: int = 0
    total_in_source: int = 0
    inserted_regs: List[str] = field(default_factory=list)
    updated_regs: List[str] = field(default_factory=list)
    deactivated_regs: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "inserted": self.inserted,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "deactivated": self.deactivated,
            "sold": self.sold,
            "placeholders_quarantined": self.placeholders_quarantined,
            "total_in_source": self.total_in_source,
        }

    def summary(self) -> str:
        return (
            f"inserted={self.inserted} updated={self.updated} "
            f"unchanged={self.unchanged} deactivated={self.deactivated} "
            f"sold={self.sold} quarantined={self.placeholders_quarantined} "
            f"source_total={self.total_in_source}"
        )


# fields compared to decide whether an existing row actually changed
_FINGERPRINT_SKIP = {"id", "created_at", "updated_at", "as_of", "raw", "media"}


def _changed(new_rec: Dict[str, Any], old_rec: Dict[str, Any]) -> bool:
    for k, v in new_rec.items():
        if k in _FINGERPRINT_SKIP:
            continue
        if old_rec.get(k) != v:
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Sync engine
# ─────────────────────────────────────────────────────────────────────────────
class InventorySync:
    def __init__(self, store: InventoryStore, *, quarantine_placeholders: bool = True):
        self.store = store
        self.quarantine_placeholders = quarantine_placeholders

    def sync(self, items: List[InventoryItem], *, when: Optional[str] = None) -> SyncReport:
        """
        Reconcile `items` into the store. Idempotent: a second identical call
        reports all-unchanged and writes nothing new.
        """
        when = when or utcnow_iso()
        report = SyncReport(total_in_source=len(items))

        # Optionally drop placeholder/non-car rows from what we write (risk R03).
        active_items = []
        for it in items:
            if self.quarantine_placeholders and it.is_placeholder:
                report.placeholders_quarantined += 1
                continue
            active_items.append(it)

        existing = {r["registration_no"]: r for r in self.store.fetch_all()}
        source_regs = set()

        for it in active_items:
            rec = it.to_record()
            reg = rec["registration_no"]
            source_regs.add(reg)

            if it.listing_status == ListingStatus.SOLD:
                report.sold += 1

            old = existing.get(reg)
            if old is None:
                rec["created_at"] = when
                rec["updated_at"] = when
                self.store.upsert(rec)
                report.inserted += 1
                report.inserted_regs.append(reg)
            elif _changed(rec, old):
                rec["created_at"] = old.get("created_at", when)
                rec["updated_at"] = when
                self.store.upsert(rec)
                report.updated += 1
                report.updated_regs.append(reg)
            else:
                report.unchanged += 1

        # Soft-deactivate previously-known regs that disappeared from the source.
        # (Sold rows that are still present in the source remain 'sold', not
        #  deactivated — they stay queryable for "just sold, here's similar".)
        for reg, old in existing.items():
            if reg not in source_regs and old.get("listing_status") not in (
                ListingStatus.INACTIVE,
            ):
                self.store.deactivate(reg, when)
                report.deactivated += 1
                report.deactivated_regs.append(reg)

        return report


def sync_inventory(
    items: List[InventoryItem],
    store: InventoryStore,
    *,
    when: Optional[str] = None,
    quarantine_placeholders: bool = True,
) -> SyncReport:
    """Convenience one-shot wrapper."""
    return InventorySync(
        store, quarantine_placeholders=quarantine_placeholders
    ).sync(items, when=when)


if __name__ == "__main__":
    import sys
    from inventory_loader import load_inventory

    path = sys.argv[1] if len(sys.argv) > 1 else "../IVR_Sheet.xlsx"
    items = load_inventory(path)
    store = InMemoryInventoryStore()
    r1 = sync_inventory(items, store, when="2026-06-10T00:00:00+00:00")
    print("first  :", r1.summary())
    r2 = sync_inventory(items, store, when="2026-06-10T01:00:00+00:00")
    print("second :", r2.summary(), "(should be all-unchanged => idempotent)")
