"""
phase12c_tests.py
=================

Phase 12C validation — Vehicle Details data-entry persistence + schema exposure.
Runs on a COPY of the workbook (never the live sheet). Deterministic.
"""

from __future__ import annotations

import json, os, shutil, tempfile, unittest

import inventory_edit as E
import inventory_loader as L
from chat_service import ChatService

LIVE = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")


class Phase12CBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.copy = os.path.join(cls.tmp, "IVR_copy.xlsx")
        shutil.copy2(LIVE, cls.copy)
        cls.svc = ChatService(xlsx_path=cls.copy,
                              leads_db=os.path.join(cls.tmp, "l.db"),
                              analytics_db=os.path.join(cls.tmp, "a.db"),
                              unknown_db=os.path.join(cls.tmp, "u.db"))
        _, sd = E.handle_schema(cls.svc)
        allf = ([f for g in sd["groups"] for f in g["fields"]]
                if "groups" in sd else sd["fields"])
        cls.H = {f.get("header"): f["key"] for f in allf if f.get("header")}
        cls.reg = next(i.registration_no for i in cls.svc.engine.all_facing
                       if i.registration_no)

    @classmethod
    def tearDownClass(cls):
        try: cls.svc.close()
        except Exception: pass

    def _get(self, reg):
        _, d = E.handle_get_car(self.svc, json.dumps({"car_number": reg}).encode())
        return d.get("values", {})

    def _upd(self, reg, vals):
        _, d = E.handle_update_car(
            self.svc, json.dumps({"car_number": reg, "values": vals}).encode())
        return d


class TestSchemaExposesNewFields(Phase12CBase):
    def test_new_headers_present(self):
        for h in ("Engine CC", "Airbags", "Sunroof Type", "Keys Count", "RC Status"):
            self.assertIn(h, self.H, f"schema missing header {h}")

    def test_migration_added_columns(self):
        # every new grouped field must now be a discoverable column
        for _f, header, _k in L._NEW_EXT_FIELDS:
            self.assertIn(header, self.H, f"column not migrated: {header}")


class TestPersistence(Phase12CBase):
    def test_partial_save_and_reload(self):
        self._upd(self.reg, {self.H["Airbags"]: "6", self.H["ABS EBD"]: "Yes"})
        v = self._get(self.reg)
        self.assertEqual(str(v.get(self.H["Airbags"])), "6")
        self.assertEqual(str(v.get(self.H["ABS EBD"])), "Yes")

    def test_incremental_partial_save(self):
        self._upd(self.reg, {self.H["Airbags"]: "6"})
        self._upd(self.reg, {self.H["Upholstery"]: "Leather"})
        v = self._get(self.reg)
        self.assertEqual(str(v.get(self.H["Airbags"])), "6")     # earlier save kept
        self.assertEqual(v.get(self.H["Upholstery"]), "Leather")

    def test_persists_across_refresh(self):
        self._upd(self.reg, {self.H["Sunroof Type"]: "Single"})
        self.svc.refresh_inventory()
        self.assertEqual(self._get(self.reg).get(self.H["Sunroof Type"]), "Single")

    def test_add_car_with_new_fields(self):
        newreg = "MH01ZZ7788"
        _, d = E.handle_add_car(self.svc, json.dumps({"values": {
            "c14": newreg, self.H["Engine CC"]: "1200",
            self.H["RC Status"]: "Clear"}}).encode())
        self.assertEqual(d.get("status"), "ok")
        v = self._get(newreg)
        self.assertEqual(str(v.get(self.H["Engine CC"])), "1200")
        self.assertEqual(v.get(self.H["RC Status"]), "Clear")


if __name__ == "__main__":
    unittest.main(verbosity=2)
