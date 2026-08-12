"""
field_audit_tests.py — permanent, data-driven Excel-column -> intent -> retrieval
regression. Runs the `field_audit` framework against the CURRENT inventory
(a temp copy of the live sheet) and asserts the whole chain is correct for every
customer-facing field:

    0 column-mapping failures   (intent -> correct Excel column, all phrasings)
    0 wrong-column answers      (never answers price/km/another field by mistake)
    0 positive-retrieval fails  (fields with data return the right value)
    0 missing-data fabrications (blank fields say "data not available")
    0 filter failures           (returned cars actually satisfy the field)
    0 collision failures        (engine/km/owner/... never collapse to price)

Schema-driven + inventory-driven: it discovers the field registry and derives
targets from the loaded inventory, so it keeps passing when the Excel changes
(no hard-coded models / registrations / counts).
"""
import os
import shutil
import tempfile
import unittest

import field_audit as FA

XLSX = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")


@unittest.skipUnless(os.path.exists(XLSX), "IVR_Sheet.xlsx not found")
class TestFieldAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from chat_service import ChatService
        cls.tmp = tempfile.mkdtemp(prefix="fieldaudit_")
        copy = os.path.join(cls.tmp, "c.xlsx")
        shutil.copy2(XLSX, copy)
        cls.svc = ChatService(xlsx_path=copy,
                              leads_db=os.path.join(cls.tmp, "l.db"),
                              analytics_db=os.path.join(cls.tmp, "a.db"),
                              unknown_db=os.path.join(cls.tmp, "u.db"))
        cls.rows = FA.run_audit(cls.svc)
        cls.summary = FA.summarize(cls.rows)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.svc.close()
        except Exception:
            pass
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_every_field_intent_maps_to_its_own_column(self):
        bad = [(r["field"], r["map_fail"]) for r in self.summary["col_fail"]]
        self.assertEqual(bad, [], f"phrasings that map to the wrong column: {bad}")

    def test_no_wrong_column_price_answers(self):
        bad = [r["field"] for r in self.summary["wrongp"]]
        self.assertEqual(bad, [], f"fields answered as price by mistake: {bad}")

    def test_fields_with_data_retrieve_correct_value(self):
        bad = [r["field"] for r in self.summary["pos_fail"]]
        self.assertEqual(bad, [], f"positive-retrieval failures: {bad}")

    def test_missing_data_never_fabricated(self):
        bad = [r["field"] for r in self.summary["mis_fail"]]
        self.assertEqual(bad, [], f"missing-data fabrication failures: {bad}")

    def test_filters_return_only_matching_cars(self):
        bad = [r["field"] for r in self.summary["flt_fail"]]
        self.assertEqual(bad, [], f"filter failures: {bad}")

    def test_field_collisions_map_to_intended_column(self):
        fails = FA.collision_check(self.svc)
        self.assertEqual(fails, [], f"collision failures: {fails}")

    def test_at_least_the_core_fields_have_data_and_pass(self):
        # sanity: the registry discovered a meaningful field universe
        self.assertGreaterEqual(len(self.rows), 60)
        with_data = [r for r in self.rows if r["data_in_inv"]]
        self.assertGreaterEqual(len(with_data), 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
