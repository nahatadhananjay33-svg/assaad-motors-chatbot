"""
model_recognition_tests.py
==========================

Regression for the digit-name model-recognition fix.

Bug (found in the 750-question live validation): a model name containing digits
(XUV500, KUV100, TUV300, "Xuv 700", "525 I") was not findable by name — the
standalone-digit partial-plate heuristic grabbed the "500" out of "XUV500" as a
reg_partial and returned "not available", even though those cars were in stock.

Two-part fix:
  * query_parser: a digit-run immediately preceded by a letter, or that is part
    of the recognized model name, is NOT treated as a partial plate;
  * retrieval_engine: model comparison is space/hyphen-insensitive so an inventory
    spelling ("Xuv 700") folds together with its market alias ("XUV700").

These tests are data-driven off the CURRENT inventory, so they keep protecting
the whole *class* of bug (any in-stock model whose name contains a digit) even if
the Excel changes.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from collections import Counter

import inventory_loader as L
import query_parser as qp
from retrieval_engine import _model_key

XLSX = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")

# Simulate these digit-named models being in stock (they are, in the live Excel),
# so the parser recognizes them exactly as it does in production after
# refresh_inventory(). Additive + idempotent; harmless to other tests.
qp.register_inventory_models(["XUV500", "KUV100", "TUV300", "Xuv 700", "525 I"])


def _has_digit(s: str) -> bool:
    return any(c.isdigit() for c in (s or ""))


class TestModelKey(unittest.TestCase):
    def test_space_hyphen_insensitive(self):
        self.assertEqual(_model_key("Xuv 700"), _model_key("XUV700"))
        self.assertEqual(_model_key("xuv-700"), _model_key("XUV 700"))
        self.assertEqual(_model_key("C Class"), _model_key("cclass"))
        self.assertNotEqual(_model_key("XUV500"), _model_key("XUV300"))


class TestDigitModelParse(unittest.TestCase):
    def test_model_digits_not_hijacked_as_plate(self):
        for q in ["XUV500 ka price kya hai?", "KUV100 hai kya?", "TUV300 dikhao",
                  "xuv500 automatic hai kya?", "Xuv 700 ka price", "525 I ka price"]:
            self.assertIsNone(qp.parse(q).reg_partial,
                              f"digit-in-model wrongly taken as plate: {q}")

    def test_partial_plate_still_works(self):
        self.assertEqual(qp.parse("6922 ka price").reg_partial, "6922")
        self.assertEqual(qp.parse("price of 9999").reg_partial, "9999")
        self.assertEqual(qp.parse("insurance of 6922").reg_partial, "6922")

    def test_year_budget_km_not_hijacked(self):
        self.assertIsNone(qp.parse("2015 ki gaadi").reg_partial)
        self.assertIsNone(qp.parse("under 500000").reg_partial)
        self.assertIsNone(qp.parse("20000 km se kam").reg_partial)


@unittest.skipUnless(os.path.exists(XLSX), "IVR_Sheet.xlsx not found")
class TestDigitModelEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from chat_service import ChatService
        cls.tmp = tempfile.mkdtemp(prefix="modelrec_")
        items = [i for i in L.load_inventory(XLSX) if i.is_customer_facing]
        cls.counts = Counter(i.model for i in items if i.model)
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

    def test_every_instock_digit_model_findable_by_name(self):
        digit_models = [m for m in self.counts if _has_digit(m)]
        self.assertTrue(digit_models,
                        "expected at least one digit-named model in current stock")
        for m in digit_models:
            r = self.svc.handle(f"{m} ka price kya hai?", session_id=f"mr-{m}")
            self.assertNotIn(r.status, ("not_found", "unknown"),
                             f"{m} ({self.counts[m]} in stock) -> {r.status} (not findable by name)")
            self.assertGreaterEqual(r.count, 1, f"{m} returned 0 cars")


if __name__ == "__main__":
    unittest.main(verbosity=2)
