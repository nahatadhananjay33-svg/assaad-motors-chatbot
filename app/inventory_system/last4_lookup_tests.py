"""
last4_lookup_tests.py
=====================

Regression for two last-4 (partial registration) bugs reported from the live
pilot chatbot.

1. "6944 k price" answered with a BUDGET BROWSE instead of that car's price.
   The bare "k" was read as a thousands multiplier (6944 * 1000 = a Rs 69.44
   lakh ceiling), which set price_max and threw the plate lookup away. In
   Hinglish a spaced "k" is almost always "ka" typed short — "6944 ka price".
   Fix: query_parser only treats a SPACED "k" as thousands when it is not
   introducing an attribute question. Attached forms ("500k") are unchanged.

2. "6687 ki photos bhejo" replied "Kaunsi gaadi ke photos chahiye?" while the
   very same turn rendered the correct car's card — a self-contradicting answer.
   media_lookup._identifies_vehicle counted model/make/category/seats but not
   reg_partial, so the media path never resolved a car named by its last digits.
   Fix: reg_partial counts as identifying a vehicle. Matching still goes through
   retrieval_engine._matches, which requires the digits to be the plate's
   COMPLETE trailing group — so this cannot loosen into a wrong-car answer.

Data-driven off the CURRENT Excel: the cars are looked up by their real trailing
digit groups, so these keep working after an inventory swap.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import unittest

import inventory_loader as L
import query_parser as qp

XLSX = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")

ATTR_WORDS = ["price", "photo", "km", "fuel", "colour", "owner", "year"]


def _trailing(plate: str):
    m = re.search(r"(\d+)$", (plate or "").upper().replace(" ", ""))
    return m.group(1) if m else None


class TestSpacedKIsPossessiveNotBudget(unittest.TestCase):
    def test_spaced_k_before_attribute_is_not_a_budget(self):
        for w in ATTR_WORDS:
            q = qp.parse(f"6944 k {w}")
            self.assertIsNone(q.price_max, f"'6944 k {w}' wrongly parsed as a budget")
            self.assertEqual(q.reg_partial, "6944", f"'6944 k {w}' lost the plate lookup")

    def test_attached_k_is_still_a_budget(self):
        for phrase, want in [("500k", 500_000), ("500k budget", 500_000),
                             ("600k tak", 600_000), ("800k ke andar", 800_000),
                             ("budget 700k", 700_000)]:
            q = qp.parse(phrase)
            self.assertEqual(q.price_max, want, f"budget lost for {phrase!r}")
            self.assertIsNone(q.reg_partial, f"{phrase!r} wrongly became a plate")

    def test_spelled_thousand_still_a_budget(self):
        self.assertEqual(qp.parse("500 thousand").price_max, 500_000)

    def test_other_budget_forms_unaffected(self):
        for phrase in ["5 lakh ke andar", "2 lakh se kam", "10 lakh tak", "under 8"]:
            self.assertIsNotNone(qp.parse(phrase).price_max, f"budget lost for {phrase!r}")


class TestPartialRegIdentifiesVehicleForMedia(unittest.TestCase):
    def test_reg_partial_counts_as_identified(self):
        import media_lookup as ml
        mq = ml.parse_media_query("6687 ki photos bhejo")
        self.assertTrue(mq.identified_vehicle,
                        "last-4 must identify a vehicle for the media path")

    def test_model_and_make_still_identify(self):
        import media_lookup as ml
        for m in ["Innova ki photos bhejo", "Audi ki photos dikhao"]:
            self.assertTrue(ml.parse_media_query(m).identified_vehicle, m)

    def test_bare_media_request_still_unidentified(self):
        import media_lookup as ml
        mq = ml.parse_media_query("photos bhejo")
        self.assertFalse(mq.identified_vehicle,
                         "a bare photo request must still ask which car")


@unittest.skipUnless(os.path.exists(XLSX), "IVR_Sheet.xlsx not found")
class TestLast4EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from chat_service import ChatService
        cls.tmp = tempfile.mkdtemp(prefix="last4_")
        cls.items = [i for i in L.load_inventory(XLSX) if i.is_customer_facing]
        cls.svc = ChatService(XLSX, leads_db=os.path.join(cls.tmp, "l.db"),
                              analytics_db=os.path.join(cls.tmp, "a.db"),
                              unknown_db=os.path.join(cls.tmp, "u.db"))
        # a car whose trailing digit group is unique, so the answer is unambiguous
        seen = {}
        for i in cls.items:
            t = _trailing(i.registration_no)
            if t:
                seen.setdefault(t, []).append(i)
        cls.car = next(v[0] for k, v in sorted(seen.items())
                       if len(v) == 1 and v[0].price_lakh)
        cls.tail = _trailing(cls.car.registration_no)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.svc.close()
        except Exception:
            pass
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_k_price_returns_that_cars_price(self):
        want = [f"{self.car.price_lakh:g}", f"{self.car.price_lakh:.2f}"]
        for phrase in (f"{self.tail} k price", f"{self.tail} ka price",
                       f"{self.tail} ki price"):
            r = self.svc.handle(phrase, session_id=f"k-{phrase}")
            self.assertTrue(any(w in (r.response or "") for w in want),
                            f"{phrase!r} -> {r.response!r} (expected {want})")

    def test_last4_photo_request_names_the_car_not_a_clarify(self):
        r = self.svc.handle(f"{self.tail} ki photos bhejo", session_id="p1")
        self.assertEqual(r.intent, "photo_request", r.response)
        self.assertNotIn("kaunsi gaadi", (r.response or "").lower(),
                         "resolved car must not also be asked for")
        self.assertIn(str(self.car.year_int), r.response or "",
                      "reply should name the resolved car")


if __name__ == "__main__":
    unittest.main(verbosity=2)
