"""
phase12g_context_tests.py
=========================

Phase 12G — deterministic CONTEXTUAL attribute hardening. Focused tests that a
SINGLE pinned vehicle answers year / odometer / transmission attribute questions,
while explicit search/variant language still browses/filters, unpinned questions
never fabricate, and multi-intent / follow-up memory / fresh browse stay intact.

Runs on a COPY of the workbook. NO LLM.
"""
from __future__ import annotations

import os, shutil, tempfile, unittest

from query_parser import parse
import conversation_policy as CP

LIVE = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")


# ── unit: parser reclassification (lexical attribute vs search discriminator) ──
class TestParserReclassification(unittest.TestCase):
    # YEAR — attribute questions -> year_query; searches -> year_exact filter
    def test_year_attribute_questions(self):
        for m in ["2019 model hai?", "ye 2019 model hai?", "model 2019 hai?",
                  "iska model year kya hai?", "kaunsa year hai?",
                  "ye kis year ki hai?", "model year kya hai?"]:
            q = parse(m)
            self.assertTrue(q.year_query, m)
            self.assertIsNone(q.year_exact, m)

    def test_year_searches_preserved(self):
        for m in ["2019 model chahiye", "2019 model wali car chahiye",
                  "2019 ki car dikhao", "2019 nexon"]:
            q = parse(m)
            self.assertFalse(q.year_query, m)
            self.assertEqual(q.year_exact, 2019, m)

    # KM — odometer question -> km_reading_query; low-km search -> sort_low_km
    def test_km_attribute_questions(self):
        for m in ["kam km chali hai?", "kam kilometer chali hai?",
                  "kitni km chali hai?", "running kitni hai?", "odometer kya hai?"]:
            q = parse(m)
            self.assertTrue(q.km_reading_query, m)
            self.assertFalse(q.sort_low_km, m)

    def test_km_searches_preserved(self):
        for m in ["kam km wali car chahiye", "sabse kam km wali car",
                  "low km wali car dikhao", "kam km"]:
            q = parse(m)
            self.assertTrue(q.sort_low_km, m)
            self.assertFalse(q.km_reading_query, m)

    # TRANSMISSION — attribute question -> transmission_query; else filter value
    def test_transmission_attribute_questions(self):
        for m in ["automatic hai?", "ye automatic hai?", "manual hai?",
                  "transmission automatic hai?", "gearbox automatic hai?"]:
            q = parse(m)
            self.assertTrue(q.transmission_query, m)
            self.assertIsNone(q.transmission, m)

    def test_transmission_searches_preserved(self):
        # explicit variant / browse language keeps the transmission FILTER
        for m in ["automatic wali dikhao", "automatic wali chahiye",
                  "automatic cars", "automatic cars dikhao",
                  "automatic mein koi hai?", "automatic wali?",
                  "automatic Ertiga hai?", "automatic wali Ertiga chahiye"]:
            q = parse(m)
            self.assertFalse(q.transmission_query, m)
            self.assertIsNotNone(q.transmission, m)

    def test_no_other_model_hijack(self):
        # naming a model/make/category = a search, never a pinned attribute
        self.assertFalse(parse("automatic Ertiga hai?").transmission_query)
        self.assertIsNone(parse("2019 Ertiga hai?").year_query or None)


# ── conversation-policy modes for the reclassified flags ─────────────────────
class TestModes(unittest.TestCase):
    CTX = {"reg": "MH01AB1234", "model": "Fortuner"}

    def _m(self, m, ctx=None, rr="inventory"):
        return CP.classify(m, ctx, rr_kind=rr)

    def test_pinned_attribute_is_current_car(self):
        for m in ["2019 model hai?", "kam km chali hai?", "automatic hai?",
                  "manual hai?", "kaunsa year hai?"]:
            self.assertEqual(self._m(m, self.CTX), CP.MODE_CURRENT_CAR, m)

    def test_unpinned_attribute_clarifies(self):
        for m in ["2019 model hai?", "kam km chali hai?", "automatic hai?"]:
            self.assertEqual(self._m(m, None), CP.MODE_CLARIFY, m)

    def test_search_language_not_current_car(self):
        for m in ["automatic wali dikhao", "2019 model chahiye",
                  "kam km wali car chahiye", "sabse kam km wali car"]:
            self.assertNotEqual(self._m(m, self.CTX), CP.MODE_CURRENT_CAR, m)


# ── behaviour: real ChatService end-to-end ───────────────────────────────────
class TestBehaviour(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from chat_service import ChatService
        cls.tmp = tempfile.mkdtemp(prefix="p12g_")
        copy = os.path.join(cls.tmp, "c.xlsx")
        shutil.copy2(LIVE, copy)
        cls.svc = ChatService(xlsx_path=copy,
                              leads_db=os.path.join(cls.tmp, "l.db"),
                              analytics_db=os.path.join(cls.tmp, "a.db"),
                              unknown_db=os.path.join(cls.tmp, "u.db"))
        # a genuinely single-car model, with its true attributes (data-driven)
        it = next(i for i in cls.svc.engine.all_facing if i.model == "Fortuner")
        cls.reg = it.registration_no
        cls.year = it.year_int
        cls.trans = it.transmission_norm
        # KM tests pin a car that actually HAS an odometer reading (+ its year),
        # since the live sheet leaves KM blank on many cars.
        kmcar = next(i for i in cls.svc.engine.all_facing
                     if i.km_driven and i.year_int)
        cls.kmreg = kmcar.registration_no
        cls.km = kmcar.km_driven
        cls.kmyear = kmcar.year_int

    @classmethod
    def tearDownClass(cls):
        try: cls.svc.close()
        except Exception: pass
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _pin(self, sid):
        """Pin the single Fortuner by registration and return its result."""
        return self.svc.handle(self.reg + " available hai?", session_id=sid)

    def _pin_km(self, sid):
        """Pin a car that has a real odometer reading (for KM assertions)."""
        return self.svc.handle(self.kmreg + " available hai?", session_id=sid)

    def _h(self, m, sid):
        return self.svc.handle(m, session_id=sid)

    # ---- YEAR ----
    def test_pinned_year_answers_car(self):
        for i, m in enumerate(["2019 model hai?", "ye 2019 model hai?",
                               "model year kya hai?", "kaunsa year hai?"]):
            sid = f"y{i}"; self._pin(sid)
            r = self._h(m, sid)
            self.assertEqual(r.status, "found", m)
            self.assertEqual(r.meta["conversation_mode"], CP.MODE_CURRENT_CAR, m)
            self.assertIn(str(self.year), r.response, m)

    def test_pinned_year_not_a_2019_search(self):
        sid = "yns"; self._pin(sid)
        r = self._h("2019 model hai?", sid)
        # the pinned car (2011) is named, not a list of 2019 cars
        self.assertEqual(r.count, 1)
        self.assertIn(str(self.year), r.response)

    def test_unpinned_year_no_fabrication(self):
        r = self._h("2019 model hai?", "cold_y")
        self.assertEqual(r.count, 0)
        self.assertNotEqual(r.status, "found")

    def test_year_search_still_searches(self):
        for sid, m in [("s_a", "2019 model chahiye"),
                       ("s_b", "2019 model wali car chahiye")]:
            r = self._h(m, sid)
            self.assertEqual(r.meta["conversation_mode"], CP.MODE_NEW_SEARCH, m)
            self.assertIn(r.status, ("multi", "found", "not_found"))

    def test_pinned_year_search_language_still_searches(self):
        # pinned, but explicit search language -> a fresh 2019 browse, not the car
        sid = "pys"; self._pin(sid)
        r = self._h("2019 model chahiye", sid)
        self.assertEqual(r.meta["conversation_mode"], CP.MODE_NEW_SEARCH)

    # ---- KM ----
    def test_pinned_km_answers_car(self):
        for i, m in enumerate(["kam km chali hai?", "kitni km chali hai?",
                               "running kitni hai?", "odometer kya hai?"]):
            sid = f"k{i}"; self._pin_km(sid)
            r = self._h(m, sid)
            self.assertEqual(r.status, "found", m)
            self.assertEqual(r.meta["conversation_mode"], CP.MODE_CURRENT_CAR, m)
            self.assertIn(f"{self.km:,}", r.response, m)

    def test_unpinned_km_no_fabrication(self):
        r = self._h("kam km chali hai?", "cold_k")
        self.assertEqual(r.count, 0)
        self.assertEqual(r.status, "clarify")

    def test_km_search_still_searches(self):
        for sid, m in [("ks_a", "kam km wali car chahiye"),
                       ("ks_b", "sabse kam km wali car")]:
            r = self._h(m, sid)
            self.assertEqual(r.meta["conversation_mode"], CP.MODE_NEW_SEARCH, m)
            self.assertGreater(r.count, 1, m)   # a real multi-car sort, not 1 pinned car

    # ---- TRANSMISSION ----
    def test_pinned_transmission_answers_car(self):
        for i, m in enumerate(["automatic hai?", "ye automatic hai?", "manual hai?",
                               "transmission automatic hai?"]):
            sid = f"t{i}"; self._pin(sid)
            r = self._h(m, sid)
            self.assertEqual(r.status, "found", m)
            self.assertEqual(r.meta["conversation_mode"], CP.MODE_CURRENT_CAR, m)
            self.assertIn(self.trans, r.response, m)   # the CAR's real transmission

    def test_unpinned_transmission_no_fabrication(self):
        r = self._h("automatic hai?", "cold_t")
        self.assertEqual(r.count, 0)
        self.assertEqual(r.status, "clarify")

    def test_transmission_search_still_searches(self):
        r = self._h("automatic cars dikhao", "ts_a")
        self.assertEqual(r.meta["conversation_mode"], CP.MODE_NEW_SEARCH)
        self.assertGreater(r.count, 1)
        r = self._h("automatic mein koi hai?", "ts_b")
        self.assertGreater(r.count, 1)

    def test_pinned_transmission_variant_language_searches(self):
        # pinned single car, but "automatic wali dikhao" = variant search language
        sid = "tv"; self._pin(sid)
        r = self._h("automatic wali dikhao", sid)
        self.assertNotEqual(r.meta["conversation_mode"], CP.MODE_CURRENT_CAR)

    # ---- CONVERSATION FLOWS ----
    def test_flow_single_pin_then_attrs(self):
        sid = "flow"
        self._h("Show me Ertiga", sid)
        r = self._h("automatic wali?", sid)       # narrows to the ONE automatic Ertiga
        self.assertEqual(r.count, 1)
        pinned = r.vehicles[0]
        r = self._h("automatic hai?", sid)
        self.assertEqual(r.meta["conversation_mode"], CP.MODE_CURRENT_CAR)
        self.assertEqual(r.vehicles[0]["registration_no"],
                         pinned["registration_no"])
        r = self._h("2019 model hai?", sid)
        self.assertEqual(r.meta["conversation_mode"], CP.MODE_CURRENT_CAR)
        self.assertIn(str(pinned["year"]), r.response)
        r = self._h("kam km chali hai?", sid)
        self.assertEqual(r.meta["conversation_mode"], CP.MODE_CURRENT_CAR)

    def test_flow_rc_then_year_km(self):
        sid = "flow2"; self._pin_km(sid)
        self._h("RC?", sid)
        r = self._h("2019 model hai?", sid)
        self.assertIn(str(self.kmyear), r.response)
        r = self._h("kam km chali hai?", sid)
        self.assertIn(f"{self.km:,}", r.response)

    def test_flow_fresh_browse_still_works(self):
        sid = "flow3"; self._pin(sid)
        r = self._h("7 seater chahiye", sid)
        self.assertEqual(r.meta["conversation_mode"], CP.MODE_NEW_SEARCH)
        self.assertGreater(r.count, 1)

    # ---- MULTI-INTENT (must answer the pinned car, never convert to a search) ----
    def test_multi_intent_answers_pinned(self):
        for i, m in enumerate(["automatic hai aur kitne owners hain?",
                               "2019 model hai aur kitne owners hain?",
                               "kitni km chali hai aur insurance?",
                               "automatic hai aur sunroof hai?"]):
            sid = f"mi{i}"; self._pin(sid)
            r = self._h(m, sid)
            self.assertEqual(r.status, "found", m)
            self.assertEqual(r.count, 1, m)
            self.assertEqual(r.vehicles[0]["registration_no"], self.reg, m)

    # ---- LANGUAGE (Devanagari attribute questions on the pinned car) ----
    def test_language_variants(self):
        sid = "lang"; self._pin(sid)
        r = self._h("कोणते वर्ष आहे?", sid)      # Marathi: which year?
        self.assertEqual(r.meta["conversation_mode"], CP.MODE_CURRENT_CAR)
        self.assertIn(str(self.year), r.response)


if __name__ == "__main__":
    unittest.main(verbosity=2)
