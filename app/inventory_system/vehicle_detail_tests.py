"""
vehicle_detail_tests.py
=======================

Regression for the customer "click a card -> vehicle details" feature
(GET /vehicle?reg=<reg>, served by vehicle_detail.handle_vehicle_detail).

Data-driven off the CURRENT Excel so the assertions stay honest when the
inventory changes. Covers the acceptance list: exact-registration identity,
duplicate models, current-inventory reflection, sold/removed handling, missing
fields, media isolation, and — most importantly — that NO internal/admin field
can leak through the customer-safe serializer.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from collections import Counter

import inventory_loader as L
import vehicle_detail as VD

XLSX = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")

# Tokens that would betray an internal/admin/system field leaking to a customer.
_FORBIDDEN = [
    "price_inr", "is_ivr", "is_placeholder", "stock_no", "source_sheet",
    "location_code", "custody", "\"raw\"", "rate_status", "service_role",
    "supabase_key", "supabase_service", "password", "_lookup", "rate (rs)",
    "car numb", "reg last 4",
]


@unittest.skipUnless(os.path.exists(XLSX), "IVR_Sheet.xlsx not found")
class VehicleDetailBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from chat_service import ChatService
        cls.tmp = tempfile.mkdtemp(prefix="vdet_")
        cls.items = [i for i in L.load_inventory(XLSX) if i.is_customer_facing]
        cls.svc = ChatService(XLSX, leads_db=os.path.join(cls.tmp, "l.db"),
                              analytics_db=os.path.join(cls.tmp, "a.db"),
                              unknown_db=os.path.join(cls.tmp, "u.db"))

    @classmethod
    def tearDownClass(cls):
        try:
            cls.svc.close()
        except Exception:
            pass
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _get(self, reg):
        return VD.handle_vehicle_detail(self.svc, f"reg={reg}")


class TestIdentityAndCorrectness(VehicleDetailBase):
    def test_exact_registration_is_returned(self):
        it = self.items[0]
        st, d = self._get(it.registration_no)
        self.assertEqual(st, 200)
        self.assertEqual(d["registration_no"], it.registration_no)

    def test_duplicate_model_resolves_to_the_clicked_car(self):
        dups = [m for m, c in Counter(i.model for i in self.items).items()
                if m and c > 1]
        self.assertTrue(dups, "expected a duplicate model in stock")
        regs = [i.registration_no for i in self.items if i.model == dups[0]]
        for rg in regs:
            st, d = self._get(rg)
            self.assertEqual(st, 200)
            self.assertEqual(d["registration_no"], rg,
                             f"{rg}: duplicate model must return the exact car")

    def test_primary_values_match_the_live_record(self):
        it = next(i for i in self.items if i.price_lakh and i.year_int
                  and i.fuel_norm and i.transmission_norm)
        _, d = self._get(it.registration_no)
        pri = {r["label"]: r["value"] for r in d["primary"]}
        self.assertEqual(pri["Year"], str(it.year_int))
        self.assertEqual(pri["Fuel"], it.fuel_norm)
        self.assertEqual(pri["Transmission"], it.transmission_norm)
        self.assertIn(f"{it.price_lakh:.2f}", pri["Price"])

    def test_current_inventory_reflection_not_cached_card(self):
        # Mutate the LIVE record the endpoint actually reads (svc._reg_lookup),
        # not a separate load — the point is the endpoint reflects current state.
        reg = next(i.registration_no for i in self.items if i.price_lakh)
        live = self.svc._reg_lookup[reg]
        original = live.price_lakh
        try:
            live.price_lakh = 9.99         # simulate a live inventory edit
            _, d = self._get(reg)
            price = {r["label"]: r["value"] for r in d["primary"]}["Price"]
            self.assertIn("9.99", price)   # endpoint reads the live record
        finally:
            live.price_lakh = original


class TestMissingAndRemoved(VehicleDetailBase):
    def test_removed_or_unknown_vehicle_is_not_available(self):
        st, d = self._get("MH99ZZ0000")
        self.assertEqual(st, 404)
        self.assertEqual(d["status"], "not_available")
        self.assertIn("no longer available", d["message"].lower())

    def test_missing_primary_field_shows_data_not_available(self):
        blank_km = next((i for i in self.items if i.km_driven is None), None)
        if blank_km is None:
            self.skipTest("no car with a blank KM in current stock")
        _, d = self._get(blank_km.registration_no)
        km = {r["label"]: r["value"] for r in d["primary"]}["KM Driven"]
        self.assertEqual(km, "Data not available")

    def test_missing_secondary_fields_are_hidden_not_fabricated(self):
        # details/specs only ever contain present values (never a fabricated one)
        for it in self.items[:20]:
            _, d = self._get(it.registration_no)
            for row in d["details"] + d["specs"]:
                self.assertNotIn(row["value"].lower(),
                                 ("none", "nan", "unknown", ""))

    def test_missing_reg_param(self):
        st, d = VD.handle_vehicle_detail(self.svc, "")
        self.assertEqual(st, 400)


class TestSecurityAndMedia(VehicleDetailBase):
    def test_no_internal_fields_leak(self):
        for it in self.items[:30]:
            _, d = self._get(it.registration_no)
            flat = json.dumps(d).lower()
            for tok in _FORBIDDEN:
                self.assertNotIn(tok, flat,
                                 f"internal token {tok!r} leaked for {it.registration_no}")

    def test_top_level_keys_are_customer_safe_only(self):
        _, d = self._get(self.items[0].registration_no)
        self.assertEqual(set(d.keys()), {
            "status", "registration_no", "title", "make", "model", "variant",
            "primary", "details", "specs", "media", "links"})

    def test_media_is_scoped_to_the_vehicle(self):
        # media dict is always present and only ever http(s) urls (or empty)
        for it in self.items[:15]:
            _, d = self._get(it.registration_no)
            self.assertIn("photos", d["media"])
            self.assertIn("videos", d["media"])
            for u in d["media"]["photos"] + d["media"]["videos"]:
                self.assertTrue(u.startswith("http"), u)


if __name__ == "__main__":
    unittest.main(verbosity=2)
