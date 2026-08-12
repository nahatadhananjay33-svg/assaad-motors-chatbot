"""
inventory_sync_tests.py
=======================

Unit tests for the inventory sync engine:
  * upsert by registration_no
  * idempotency (repeated uploads produce no changes)
  * update existing records when business fields change
  * soft-deactivate records missing from the source
  * sold vehicles are stored but never customer-facing
  * placeholders quarantined

Run:  python inventory_sync_tests.py
"""

import os
import unittest

from inventory_models import InventoryItem, ListingStatus, FuelType
from inventory_sync import (
    InMemoryInventoryStore, InventorySync, sync_inventory,
)
import inventory_loader as L

AS_OF1 = "2026-06-10T00:00:00+00:00"
AS_OF2 = "2026-06-10T01:00:00+00:00"
AS_OF3 = "2026-06-10T02:00:00+00:00"

XLSX = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")


def item(reg, **kw):
    return InventoryItem(registration_no=reg, **kw)


# ─────────────────────────────────────────────────────────────────────────────
class TestUpsertAndIdempotency(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryInventoryStore()
        self.items = [
            item("MH01AB1234", model="Creta", price_inr=540000, price_quotable=True),
            item("MH02CD5678", model="Swift", price_inr=300000, price_quotable=True),
        ]

    def test_first_sync_inserts(self):
        r = sync_inventory(self.items, self.store, when=AS_OF1)
        self.assertEqual(r.inserted, 2)
        self.assertEqual(r.updated, 0)
        self.assertEqual(len(self.store), 2)

    def test_second_sync_is_idempotent(self):
        sync_inventory(self.items, self.store, when=AS_OF1)
        r2 = sync_inventory(self.items, self.store, when=AS_OF2)
        self.assertEqual(r2.inserted, 0)
        self.assertEqual(r2.updated, 0)
        self.assertEqual(r2.unchanged, 2)

    def test_upsert_keyed_on_registration(self):
        sync_inventory(self.items, self.store, when=AS_OF1)
        # same reg, re-synced -> still one row (no duplicate key)
        sync_inventory([item("MH01AB1234", model="Creta", price_inr=540000,
                             price_quotable=True)], self.store, when=AS_OF2)
        self.assertIsNotNone(self.store.get("MH01AB1234"))
        self.assertEqual(len([r for r in self.store.fetch_all()
                              if r["registration_no"] == "MH01AB1234"]), 1)

    def test_created_at_preserved_on_update(self):
        sync_inventory(self.items, self.store, when=AS_OF1)
        changed = [item("MH01AB1234", model="Creta", price_inr=560000, price_quotable=True),
                   item("MH02CD5678", model="Swift", price_inr=300000, price_quotable=True)]
        sync_inventory(changed, self.store, when=AS_OF2)
        rec = self.store.get("MH01AB1234")
        self.assertEqual(rec["created_at"], AS_OF1)   # creation pinned
        self.assertEqual(rec["updated_at"], AS_OF2)   # update bumped


class TestUpdates(unittest.TestCase):
    def test_price_change_triggers_update(self):
        store = InMemoryInventoryStore()
        sync_inventory([item("MH01AB1234", model="Creta", price_inr=540000,
                            price_quotable=True)], store, when=AS_OF1)
        r = sync_inventory([item("MH01AB1234", model="Creta", price_inr=525000,
                                price_quotable=True)], store, when=AS_OF2)
        self.assertEqual(r.updated, 1)
        self.assertEqual(store.get("MH01AB1234")["price_inr"], 525000)

    def test_no_change_no_update(self):
        store = InMemoryInventoryStore()
        items = [item("MH01AB1234", model="Creta", price_inr=540000, price_quotable=True)]
        sync_inventory(items, store, when=AS_OF1)
        r = sync_inventory(items, store, when=AS_OF2)
        self.assertEqual(r.updated, 0)
        self.assertEqual(r.unchanged, 1)


class TestSoftDeactivate(unittest.TestCase):
    def test_missing_record_is_deactivated_not_deleted(self):
        store = InMemoryInventoryStore()
        first = [
            item("MH01AB1234", model="Creta", price_inr=540000, price_quotable=True),
            item("MH02CD5678", model="Swift", price_inr=300000, price_quotable=True),
        ]
        sync_inventory(first, store, when=AS_OF1)
        # second upload drops MH02CD5678
        second = [item("MH01AB1234", model="Creta", price_inr=540000, price_quotable=True)]
        r = sync_inventory(second, store, when=AS_OF2)
        self.assertEqual(r.deactivated, 1)
        rec = self.store_get(store, "MH02CD5678")
        self.assertIsNotNone(rec)                                  # not deleted
        self.assertEqual(rec["listing_status"], ListingStatus.INACTIVE)

    def test_reappearing_record_is_reactivated(self):
        store = InMemoryInventoryStore()
        sync_inventory([item("MH02CD5678", model="Swift", price_inr=300000,
                            price_quotable=True)], store, when=AS_OF1)
        sync_inventory([], store, when=AS_OF2)                      # drops it
        self.assertEqual(store.get("MH02CD5678")["listing_status"], ListingStatus.INACTIVE)
        sync_inventory([item("MH02CD5678", model="Swift", price_inr=300000,
                            price_quotable=True)], store, when=AS_OF3)  # back
        self.assertEqual(store.get("MH02CD5678")["listing_status"], ListingStatus.AVAILABLE)

    @staticmethod
    def store_get(store, reg):
        return store.get(reg)


class TestSoldHandling(unittest.TestCase):
    def test_sold_item_stored_but_not_customer_facing(self):
        store = InMemoryInventoryStore()
        sold = item("MH12KE0019", model="Innova", listing_status=ListingStatus.SOLD,
                    customer_viewable=False)
        r = sync_inventory([sold], store, when=AS_OF1)
        self.assertEqual(r.sold, 1)
        rec = store.get("MH12KE0019")
        self.assertEqual(rec["listing_status"], ListingStatus.SOLD)  # stored
        self.assertFalse(sold.is_customer_facing)                    # but hidden

    def test_sold_present_in_source_is_not_deactivated(self):
        store = InMemoryInventoryStore()
        avail = item("MH01AB1234", model="Creta", price_inr=540000, price_quotable=True)
        sold = item("MH12KE0019", model="Innova", listing_status=ListingStatus.SOLD)
        sync_inventory([avail, sold], store, when=AS_OF1)
        r = sync_inventory([avail, sold], store, when=AS_OF2)
        self.assertEqual(r.deactivated, 0)                           # stays 'sold'
        self.assertEqual(store.get("MH12KE0019")["listing_status"], ListingStatus.SOLD)


class TestPlaceholderQuarantine(unittest.TestCase):
    def test_placeholder_not_written(self):
        store = InMemoryInventoryStore()
        ph = item("NOREG-DNJ-X", model=None, is_placeholder=True)
        good = item("MH01AB1234", model="Creta", price_inr=540000, price_quotable=True)
        r = sync_inventory([ph, good], store, when=AS_OF1)
        self.assertEqual(r.placeholders_quarantined, 1)
        self.assertEqual(r.inserted, 1)
        self.assertIsNone(store.get("NOREG-DNJ-X"))


class TestRepeatedUploads(unittest.TestCase):
    """A realistic multi-day sequence: add, change price, sell one, drop one."""

    def test_lifecycle(self):
        store = InMemoryInventoryStore()
        day1 = [
            item("MH01AB1234", model="Creta", price_inr=540000, price_quotable=True),
            item("MH02CD5678", model="Swift", price_inr=300000, price_quotable=True),
            item("MH03EF9012", model="Innova", price_inr=795000, price_quotable=True),
        ]
        r1 = sync_inventory(day1, store, when=AS_OF1)
        self.assertEqual((r1.inserted, r1.updated, r1.deactivated), (3, 0, 0))

        day2 = [
            item("MH01AB1234", model="Creta", price_inr=525000, price_quotable=True),  # price drop
            item("MH02CD5678", model="Swift", price_inr=300000, price_quotable=True),  # same
            item("MH03EF9012", model="Innova", listing_status=ListingStatus.SOLD),     # sold
        ]
        r2 = sync_inventory(day2, store, when=AS_OF2)
        self.assertEqual(r2.updated, 2)        # creta price + innova->sold
        self.assertEqual(r2.unchanged, 1)
        self.assertEqual(r2.sold, 1)
        self.assertEqual(r2.deactivated, 0)

        day3 = [  # swift removed from sheet entirely
            item("MH01AB1234", model="Creta", price_inr=525000, price_quotable=True),
            item("MH03EF9012", model="Innova", listing_status=ListingStatus.SOLD),
        ]
        r3 = sync_inventory(day3, store, when=AS_OF3)
        self.assertEqual(r3.deactivated, 1)
        self.assertEqual(store.get("MH02CD5678")["listing_status"], ListingStatus.INACTIVE)


# ── integration over the real workbook ───────────────────────────────────────
@unittest.skipUnless(os.path.exists(XLSX), "IVR_Sheet.xlsx not found")
class TestRealWorkbookSync(unittest.TestCase):
    def test_load_then_sync_idempotent(self):
        items = L.load_inventory(XLSX, as_of=AS_OF1)
        store = InMemoryInventoryStore()
        r1 = sync_inventory(items, store, when=AS_OF1)
        r2 = sync_inventory(items, store, when=AS_OF2)
        self.assertEqual(r1.inserted, len(items) - r1.placeholders_quarantined)
        self.assertEqual(r2.inserted, 0)
        self.assertEqual(r2.updated, 0)
        self.assertEqual(r2.unchanged, r1.inserted)

    def test_no_sold_in_customer_facing_after_sync(self):
        items = L.load_inventory(XLSX, as_of=AS_OF1)
        store = InMemoryInventoryStore()
        sync_inventory(items, store, when=AS_OF1)
        for rec in store.fetch_all():
            if rec["listing_status"] == ListingStatus.SOLD:
                self.assertFalse(rec["customer_viewable"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
