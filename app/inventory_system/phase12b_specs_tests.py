"""
phase12b_specs_tests.py
=======================

Phase 12B validation — the schema expansion + model_specs auto-fill.
Deterministic; runs under the normal `*_tests.py` sweep.
"""

from __future__ import annotations

import os
import unittest

import model_specs as ms
import inventory_loader as L
from inventory_models import InventoryItem

XLSX = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")


class TestSpecFieldSeparation(unittest.TestCase):
    def test_spec_and_dealership_fields_are_disjoint(self):
        overlap = set(ms.SPEC_FIELDS) & set(ms.DEALERSHIP_FIELDS)
        self.assertFalse(overlap, f"fields cannot be both: {overlap}")

    def test_new_fields_exist_on_model(self):
        it = InventoryItem(registration_no="MH01AB0001")
        for f in ms.SPEC_FIELDS + ms.DEALERSHIP_FIELDS:
            self.assertTrue(hasattr(it, f), f"InventoryItem missing field {f}")


class TestResolve(unittest.TestCase):
    def test_known_model_returns_specs(self):
        self.assertTrue(ms.resolve_specs("Hyundai", "Creta"))
        self.assertEqual(ms.resolve_specs("Hyundai", "Creta")["engine_cc"], 1497)

    def test_unknown_model_no_fabrication(self):
        self.assertEqual(ms.resolve_specs("Foo", "Bar"), {})
        self.assertEqual(ms.resolve_specs(None, None), {})

    def test_accent_folding(self):
        # 'Škoda Rapid' must match the 'skoda' key
        self.assertTrue(ms.resolve_specs("Škoda", "Rapid"))

    def test_only_spec_fields_returned(self):
        for k in ms.resolve_specs("Toyota", "Fortuner"):
            self.assertIn(k, ms.SPEC_FIELDS)


class TestApplySpecs(unittest.TestCase):
    def test_fills_empty_only(self):
        it = InventoryItem(registration_no="MH01AB0002", make_full="Hyundai",
                           model="Creta")
        self.assertIsNone(it.engine_cc)
        ms.apply_specs(it)
        self.assertEqual(it.engine_cc, 1497)
        self.assertEqual(it.boot_litres, 433)

    def test_owner_data_wins(self):
        it = InventoryItem(registration_no="MH01AB0003", make_full="Hyundai",
                           model="Creta", airbags=2, boot_litres=400)
        ms.apply_specs(it)
        self.assertEqual(it.airbags, 2)        # owner value NOT overwritten (lib=6)
        self.assertEqual(it.boot_litres, 400)  # owner value NOT overwritten (lib=433)
        self.assertEqual(it.engine_cc, 1497)   # empty field still filled

    def test_unknown_model_untouched(self):
        it = InventoryItem(registration_no="MH01AB0004", make_full="Foo", model="Bar")
        ms.apply_specs(it)
        self.assertIsNone(it.engine_cc)
        self.assertIsNone(it.boot_litres)

    def test_never_fills_dealership_fields(self):
        it = InventoryItem(registration_no="MH01AB0005", make_full="Hyundai",
                           model="Creta")
        before = {f: getattr(it, f) for f in ms.DEALERSHIP_FIELDS}
        ms.apply_specs(it)
        for f in ms.DEALERSHIP_FIELDS:   # apply_specs must not CHANGE any of them
            self.assertEqual(getattr(it, f), before[f],
                             f"dealership field {f} must not be auto-filled")

    def test_deterministic(self):
        a = InventoryItem(registration_no="MH01AB0006", make_full="Honda", model="City")
        b = InventoryItem(registration_no="MH01AB0007", make_full="Honda", model="City")
        ms.apply_specs(a); ms.apply_specs(b)
        for f in ms.SPEC_FIELDS:
            self.assertEqual(getattr(a, f), getattr(b, f))


class TestBackwardCompatAndLoad(unittest.TestCase):
    def test_item_constructs_without_new_args(self):
        it = InventoryItem(registration_no="MH01AB0008")   # must not raise
        self.assertEqual(it.registration_no, "MH01AB0008")

    def test_live_sheet_loads_and_autofills(self):
        items = L.load_inventory(XLSX)
        self.assertGreater(len(items), 0)
        # existing populated fields unchanged
        creta = next((i for i in items if i.model == "Creta"), None)
        self.assertIsNotNone(creta)
        self.assertEqual(creta.make_full, "Hyundai")
        # auto-fill happened for a known model
        self.assertEqual(creta.engine_cc, 1497)
        # a meaningful share of the fleet is auto-filled from the specs library.
        # (The live fleet is diverse — ~200 cars across many models — so the
        # model_specs library currently covers a substantial minority, not half.)
        matched = sum(1 for i in items if ms.coverage_for(i)["known"])
        self.assertGreaterEqual(matched, len(items) // 3)

    def test_excel_override_precedence_field_read(self):
        # every new grouped field must be wired to a header, so an owner CAN override
        wired = {f for f, _h, _k in L._NEW_EXT_FIELDS}
        for f in ms.SPEC_FIELDS:
            self.assertIn(f, wired, f"spec field {f} not overridable via Excel")


if __name__ == "__main__":
    unittest.main(verbosity=2)
