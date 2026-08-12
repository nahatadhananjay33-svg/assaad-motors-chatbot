"""
phase12i_tests.py
=================

Phase 12I — deterministic conversational hardening. Focused tests for the
weaknesses found in the 12H manual/automated validation:

  * KM     — "km kitna hai?" answers the odometer, never the price.
  * FUEL   — "petrol hai?"/"डीजल है?" answer the pinned car's fuel; "petrol wali
             dikhao" still searches.
  * BARE   — "boot?" -> boot space; "engine?"/"battery?"/"safety features?" ->
             one deterministic clarify (never a dead-end / guess).
  * DEVANAGARI — Hindi spellings एयरबैग / डीजल / कैमरा / मालिक now recognised.
  * BOOKING — "booking?"/"booking amount?"/"token amount?" -> booking, not EMI.
  * MULTI  — "price aur insurance?", "km aur owners?", "RC aur insurance",
             "price aur km" answer BOTH intents (no dropped secondary).
  * NEGOTIATION — indirect objections (mehenga / expensive / kyun / itne mein
             nahi / dusri jagah sasti / last kya karoge) -> fixed-price policy.

Plus anti-regression: search-vs-attribute preserved; single intents intact;
finance/EMI still finance; no fabrication. Runs on a COPY of the workbook. No LLM.
"""
from __future__ import annotations

import os, shutil, tempfile, unittest

from query_parser import parse
import faq_engine
import conversation_policy as CP
from inventory_models import FuelType

LIVE = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")


# ─────────────────────────────────────────────────────────────────────────────
# Unit — parser reclassification (attribute vs search) and new vocabulary
# ─────────────────────────────────────────────────────────────────────────────
class TestParser(unittest.TestCase):
    # FUEL — attribute question -> fuel_query; a filter/browse keeps fuel value
    def test_fuel_attribute_questions(self):
        for m in ["petrol hai?", "diesel hai?", "ye petrol hai?", "ye diesel hai?",
                  "पेट्रोल है?", "डीजल है?"]:
            q = parse(m)
            self.assertTrue(q.fuel_query, m)
            self.assertIsNone(q.fuel, m)

    def test_fuel_searches_preserved(self):
        for m in ["petrol wali dikhao", "diesel wali dikhao", "petrol chahiye",
                  "diesel wali under 8 lakh", "petrol wali gaadi"]:
            q = parse(m)
            self.assertFalse(q.fuel_query, m)
            self.assertIsNotNone(q.fuel, m)

    def test_fuel_conflict_still_clarifies(self):
        # "petrol diesel" (two values, no disjunction) is a conflict, not fuel_query
        self.assertFalse(parse("petrol diesel").fuel_query)

    # BARE boot -> boot space attribute, never a Sedan search
    def test_boot_is_attribute(self):
        q = parse("boot?")
        self.assertEqual(q.attr_fields, ["boot_litres"])
        self.assertIsNone(q.category)

    def test_boot_space_phrases_still_work(self):
        self.assertIn("boot_litres", parse("boot space kitna hai?").attr_fields)

    # AMBIGUOUS bare words -> a clarify flag, only when nothing else resolves
    def test_ambiguous_bare_fields(self):
        self.assertEqual(parse("engine?").ambiguous_field, "engine")
        self.assertEqual(parse("battery?").ambiguous_field, "battery")
        self.assertEqual(parse("safety features?").ambiguous_field, "safety features")
        self.assertEqual(parse("engine kya hai?").ambiguous_field, "engine")

    def test_specific_forms_not_ambiguous(self):
        # a fuller form resolves a real field and is NOT flagged ambiguous
        self.assertIsNone(parse("engine capacity kitna hai?").ambiguous_field)
        self.assertIsNone(parse("engine condition kaisi hai?").ambiguous_field)
        self.assertIsNone(parse("battery health kitni hai?").ambiguous_field)
        self.assertIn("engine_cc", parse("engine capacity kitna hai?").attr_fields)

    # DEVANAGARI (Hindi spellings) — airbags / fuel / camera / owners
    def test_devanagari_hindi_fields(self):
        self.assertIn("airbags", parse("कितने एयरबैग हैं?").attr_fields)
        self.assertIn("airbags", parse("एयरबैग कितने हैं?").attr_fields)
        self.assertIn("camera_type", parse("कैमरा है?").attr_fields)
        self.assertTrue(parse("डीजल है?").fuel_query)        # RULE D on Hindi diesel
        self.assertTrue(parse("कितने मालिक हैं?").ownership_query)

    # KM — the one broken phrase and its neighbours
    def test_km_reading_flags(self):
        for m in ["km kitna hai?", "kitna km hai?", "kitne km chali hai?",
                  "running kitni hai?", "odometer?"]:
            self.assertTrue(parse(m).km_reading_query, m)

    def test_km_search_preserved(self):
        for m in ["kam km wali dikhao", "sabse kam km wali car", "lowest km"]:
            q = parse(m)
            self.assertTrue(q.sort_low_km, m)
            self.assertFalse(q.km_reading_query, m)


# ─────────────────────────────────────────────────────────────────────────────
# Unit — FAQ intent detection (booking precedence + negotiation objections)
# ─────────────────────────────────────────────────────────────────────────────
class TestFAQIntents(unittest.TestCase):
    def test_booking_routes_to_booking(self):
        for m in ["booking?", "booking kaise karni hai?", "booking amount?",
                  "token amount?", "car book kar sakte hain?",
                  "reserve kar sakte hain?"]:
            self.assertEqual(faq_engine.detect_intent(m), "booking", m)

    def test_finance_still_finance(self):
        self.assertEqual(faq_engine.detect_intent("EMI?"), "finance_details")
        self.assertEqual(faq_engine.detect_intent("down payment?"), "finance_details")
        self.assertEqual(faq_engine.detect_intent("interest rate kya hai?"),
                         "finance_details")
        self.assertEqual(faq_engine.detect_intent("loan?"), "loan")
        self.assertEqual(faq_engine.detect_intent("finance?"), "finance")

    def test_indirect_negotiation(self):
        for m in ["bhai mehengi hai", "bahut expensive hai", "itna mehenga kyun?",
                  "why so expensive?", "itne mein nahi lunga", "last kya karoge?",
                  "dusri jagah sasti mil rahi hai", "महंगी है", "खूप महाग आहे"]:
            self.assertEqual(faq_engine.detect_intent(m), "negotiation", m)

    def test_explicit_negotiation_preserved(self):
        self.assertEqual(faq_engine.detect_intent("final price?"), "negotiation")
        self.assertEqual(faq_engine.detect_intent("discount?"), "discount")
        self.assertEqual(faq_engine.detect_intent("kuch kam karo"), "negotiation")

    def test_cheapest_search_not_negotiation(self):
        # a genuine cheapest-car browse must NOT be captured by negotiation
        self.assertIsNone(faq_engine.detect_intent("sasti gaadi dikhao"))
        self.assertIsNone(faq_engine.detect_intent("sabse sasti car"))


# ─────────────────────────────────────────────────────────────────────────────
# Behaviour — real ChatService end-to-end (pinned by registration)
# ─────────────────────────────────────────────────────────────────────────────
class TestBehaviour(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from chat_service import ChatService
        cls.tmp = tempfile.mkdtemp(prefix="p12i_")
        copy = os.path.join(cls.tmp, "c.xlsx")
        shutil.copy2(LIVE, copy)
        cls.svc = ChatService(xlsx_path=copy,
                              leads_db=os.path.join(cls.tmp, "l.db"),
                              analytics_db=os.path.join(cls.tmp, "a.db"),
                              unknown_db=os.path.join(cls.tmp, "u.db"))
        it = next(i for i in cls.svc.engine.all_facing if i.model == "Fortuner")
        cls.reg = it.registration_no
        cls.year = it.year_int
        cls.fuel = it.fuel_norm
        cls.owners = it.ownership_count
        cls.airbags = getattr(it, "airbags", None)
        # KM/price tests pin a car that actually HAS an odometer reading + a
        # quotable price (the live sheet legitimately leaves KM blank on many cars).
        kmcar = next(i for i in cls.svc.engine.all_facing
                     if i.km_driven and i.price_quotable and i.price_lakh)
        cls.kmreg = kmcar.registration_no
        cls.km = kmcar.km_driven
        cls.price_lakh = kmcar.price_lakh

    @classmethod
    def tearDownClass(cls):
        try: cls.svc.close()
        except Exception: pass
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _pin(self, sid):
        return self.svc.handle(self.reg + " available hai?", session_id=sid)

    def _pin_km(self, sid):
        return self.svc.handle(self.kmreg + " available hai?", session_id=sid)

    def _h(self, m, sid):
        return self.svc.handle(m, session_id=sid)

    # ---- KM: the headline bug ----
    def test_km_kitna_hai_is_odometer_not_price(self):
        sid = "km1"; self._pin_km(sid)
        r = self._h("km kitna hai?", sid)
        self.assertEqual(r.status, "found")
        self.assertIn(f"{self.km:,}", r.response)
        self.assertNotIn("lakh", r.response.lower())   # NOT the price

    def test_km_variants_answer_odometer(self):
        for i, m in enumerate(["kitna km hai?", "kitne km chali hai?",
                               "running kitni hai?", "odometer reading?"]):
            sid = f"kmv{i}"; self._pin_km(sid)
            r = self._h(m, sid)
            self.assertIn(f"{self.km:,}", r.response, m)

    # ---- FUEL attribute vs search ----
    def test_pinned_fuel_answers_car(self):
        for i, m in enumerate(["petrol hai?", "diesel hai?", "ye petrol hai?",
                               "पेट्रोल है?", "डीजल है?"]):
            sid = f"f{i}"; self._pin(sid)
            r = self._h(m, sid)
            self.assertEqual(r.status, "found", m)
            self.assertEqual(r.count, 1, m)
            self.assertIn(self.fuel, r.response, m)

    def test_fuel_search_still_searches(self):
        for sid, m in [("fs_a", "petrol wali dikhao"), ("fs_b", "diesel wali dikhao")]:
            r = self._h(m, sid)
            self.assertGreater(r.count, 1, m)          # a real multi-car browse

    # ---- BARE fields ----
    def test_bare_boot_answers_pinned(self):
        sid = "boot"; self._pin(sid)
        r = self._h("boot?", sid)
        self.assertEqual(r.status, "found")
        self.assertEqual(r.count, 1)
        self.assertIn("Boot", r.response)

    def test_ambiguous_bare_clarifies(self):
        for i, m in enumerate(["engine?", "battery?", "safety features?"]):
            sid = f"amb{i}"; self._pin(sid)
            r = self._h(m, sid)
            self.assertEqual(r.status, "clarify", m)
            self.assertEqual(r.intent, "clarify", m)
            self.assertIn("G-AMBIGUOUS-FIELD", r.guardrails, m)

    # ---- DEVANAGARI ----
    def test_devanagari_pinned_answers(self):
        sid = "dv1"; self._pin(sid)
        r = self._h("कितने एयरबैग हैं?", sid)
        self.assertIn(str(self.airbags), r.response)
        sid = "dv2"; self._pin(sid)
        r = self._h("कितने मालिक हैं?", sid)
        self.assertIn(str(self.owners), r.response)
        sid = "dv3"; self._pin(sid)
        r = self._h("डीजल है?", sid)
        self.assertIn(self.fuel, r.response)

    # ---- BOOKING ----
    def test_booking_end_to_end(self):
        for i, m in enumerate(["booking?", "booking amount?", "token amount?"]):
            r = self._h(m, f"bk{i}")
            self.assertEqual(r.intent, "booking", m)
            self.assertEqual(r.status, "faq", m)
            self.assertIn("book", r.response.lower(), m)

    def test_finance_end_to_end_preserved(self):
        self.assertEqual(self._h("EMI?", "fin1").intent, "finance_details")
        self.assertEqual(self._h("down payment?", "fin2").intent, "finance_details")

    # ---- MULTI-INTENT: both intents answered ----
    def test_multi_price_and_insurance(self):
        sid = "mi1"; self._pin_km(sid)
        r = self._h("price aur insurance?", sid)
        self.assertEqual(r.count, 1)
        self.assertIn(f"{self.price_lakh:.2f}", r.response)   # price
        self.assertIn("Insurance", r.response)        # secondary not dropped

    def test_multi_km_and_owners(self):
        sid = "mi2"; self._pin_km(sid)
        r = self._h("km aur owners?", sid)
        self.assertIn(f"{self.km:,}", r.response)
        self.assertIn("owner", r.response.lower())

    def test_multi_rc_and_insurance(self):
        sid = "mi3"; self._pin(sid)
        r = self._h("RC aur insurance batao", sid)
        self.assertIn("RC", r.response)
        self.assertIn("Insurance", r.response)

    def test_multi_price_and_km(self):
        sid = "mi4"; self._pin_km(sid)
        r = self._h("price aur km batao", sid)
        self.assertIn(f"{self.price_lakh:.2f}", r.response)
        self.assertIn(f"{self.km:,}", r.response)

    def test_multi_new_fields_still_both(self):
        # anti-regression: 12D pure attr_fields multi keeps answering both
        sid = "mi5"; self._pin(sid)
        r = self._h("sunroof aur airbags?", sid)
        self.assertIn("Sunroof", r.response)
        self.assertIn("Airbags", r.response)

    # ---- NEGOTIATION ----
    def test_indirect_negotiation_end_to_end(self):
        for i, m in enumerate(["bhai mehengi hai", "bahut expensive hai",
                               "itna mehenga kyun?", "itne mein nahi lunga",
                               "dusri jagah sasti mil rahi hai",
                               "last kya karoge?"]):
            r = self._h(m, f"neg{i}")
            self.assertEqual(r.status, "faq", m)
            self.assertIn(r.intent, ("negotiation", "discount"), m)
            self.assertNotEqual(r.status, "multi", m)   # never a budget dump

    def test_cheapest_search_still_searches(self):
        r = self._h("sasti gaadi dikhao", "cheap1")
        self.assertNotEqual(r.status, "faq")            # a real inventory browse

    # ---- SINGLE-INTENT anti-regression (unchanged behaviour) ----
    def test_single_intents_intact(self):
        sid = "si"; self._pin(sid)
        self.assertIn(self.fuel, self._h("fuel kya hai?", sid).response)
        self._pin(sid)
        self.assertIn(str(self.owners), self._h("owners?", sid).response)
        self._pin(sid)
        self.assertIn(str(self.airbags), self._h("airbags?", sid).response)


if __name__ == "__main__":
    unittest.main(verbosity=2)
