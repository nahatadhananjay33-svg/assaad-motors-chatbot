"""
phase12e_conversation_tests.py
==============================

Phase 12E — focused deterministic tests for conversation BEHAVIOUR + the 7-mode
classifier. Realistic buyer conversations, not thousands of synthetic ones.
Runs on a COPY of the workbook (no live pollution). NO LLM.
"""

from __future__ import annotations

import os, shutil, tempfile, unittest

import conversation_policy as CP

LIVE = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")


# ── unit: the classifier maps signals to the 7 modes ─────────────────────────
class TestModeClassifier(unittest.TestCase):
    CTX = {"reg": "MH01AB1234", "model": "Ertiga"}

    def _m(self, msg, ctx=None, rr="inventory"):
        return CP.classify(msg, ctx, rr_kind=rr)

    def test_current_car(self):
        for m in ["RC?", "insurance?", "owners?", "km?", "boot space kitna?",
                  "sunroof hai?", "music system hai?", "airbags kitne?"]:
            self.assertEqual(self._m(m, self.CTX), CP.MODE_CURRENT_CAR, m)

    def test_current_car_needs_pin_else_clarify(self):
        for m in ["RC?", "sunroof?", "price?", "boot space?"]:
            self.assertEqual(self._m(m, None), CP.MODE_CLARIFY, m)

    def test_same_model_variant(self):
        for m in ["automatic wali?", "petrol wali?", "kam km wali?",
                  "first owner wali?", "white wali?"]:
            self.assertEqual(self._m(m, self.CTX), CP.MODE_SAME_MODEL_VARIANT, m)

    def test_new_search(self):
        # a different CLASS of car (model / category / seats / budget / feature
        # filter) is a fresh browse — even with a car pinned
        for m in ["7 seater chahiye", "SUV under 8 lakh", "Creta dikhao",
                  "sunroof wali car", "cars under 5 lakh"]:
            self.assertEqual(self._m(m, self.CTX), CP.MODE_NEW_SEARCH, m)

    def test_variant_refinement_stays_same_model(self):
        # a pure variant refinement (fuel / transmission / colour / owner /
        # low-km) over a pinned model stays within the model (existing engine)
        for m in ["diesel automatic", "lowest km car"]:
            self.assertEqual(self._m(m, self.CTX), CP.MODE_SAME_MODEL_VARIANT, m)

    def test_multi_intent(self):
        for m in ["sunroof aur airbags hain?", "boot space aur ground clearance?",
                  "sunroof aur alloy wheels hain?", "airbags kitne aur camera hai?"]:
            self.assertEqual(self._m(m, self.CTX), CP.MODE_MULTI_INTENT, m)

    def test_conflict_is_clarify(self):
        for m in ["petrol diesel", "automatic manual", "white black"]:
            self.assertEqual(self._m(m, self.CTX), CP.MODE_CLARIFY, m)

    def test_disjunction_not_conflict(self):
        # "petrol ya diesel?" is a QUESTION, not a conflict
        self.assertNotEqual(self._m("petrol ya diesel?", self.CTX), CP.MODE_CLARIFY)

    def test_faq_and_offsheet(self):
        self.assertEqual(self._m("finance milega?", None, rr="faq"), CP.MODE_FAQ)
        self.assertEqual(self._m("exchange karoge?", None, rr="faq"), CP.MODE_FAQ)
        self.assertEqual(self._m("random gibberish xyz", None, rr="unknown"),
                         CP.MODE_OFFSHEET_UNKNOWN)

    def test_languages(self):
        # Devanagari attribute question with a pin -> current car
        self.assertEqual(self._m("बूट स्पेस किती?", self.CTX), CP.MODE_CURRENT_CAR)
        self.assertEqual(self._m("किती एअरबॅग?", self.CTX), CP.MODE_CURRENT_CAR)


# ── behaviour: real ChatService conversation flows ───────────────────────────
class TestConversationFlows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from chat_service import ChatService
        cls.tmp = tempfile.mkdtemp()
        copy = os.path.join(cls.tmp, "c.xlsx")
        shutil.copy2(LIVE, copy)
        cls.svc = ChatService(xlsx_path=copy,
                              leads_db=os.path.join(cls.tmp, "l.db"),
                              analytics_db=os.path.join(cls.tmp, "a.db"),
                              unknown_db=os.path.join(cls.tmp, "u.db"))

    @classmethod
    def tearDownClass(cls):
        try: cls.svc.close()
        except Exception: pass

    def _h(self, msg, sid):
        return self.svc.handle(msg, session_id=sid)

    def test_bare_filter_after_browse_is_fresh(self):
        """Filter-audit regression: a bare primary-dimension filter after a filter
        browse is a FRESH browse (Excel-filter behaviour), not a narrowing of the
        previous browse. 'cng cars' then 'automatic' must show ALL automatics, not
        the 3 cng-automatics. Explicit 'sirf/only' still narrows."""
        sid = "fresh1"
        self._h("cng cars dikhao", sid)
        r = self._h("automatic", sid)          # bare -> fresh
        self.assertEqual(r.filters.get("transmission"), "Automatic")
        self.assertIsNone(r.filters.get("fuel"))         # CNG did NOT carry over
        std = self._h("automatic cars", "fresh_std")     # standalone reference
        self.assertEqual(r.count, std.count)

        sid2 = "narrow1"
        self._h("automatic cars", sid2)
        r2 = self._h("sirf petrol", sid2)      # explicit narrow -> merge
        self.assertEqual(r2.filters.get("transmission"), "Automatic")
        self.assertEqual(r2.filters.get("fuel"), "Petrol")

    def test_bare_price_after_browse_is_fresh(self):
        """A bare price/owner browse after a colour browse is ALSO fresh: 'gold
        cars' then '5 lakh ke andar' shows ALL cars under 5 lakh, not gold ones."""
        sid = "pfresh"
        self._h("gold cars", sid)
        r = self._h("5 lakh ke andar", sid)
        self.assertEqual(r.filters.get("price_max"), 500000)
        self.assertIsNone(r.filters.get("color"))        # gold did NOT carry over
        std = self._h("5 lakh ke andar", "pfresh_std")
        self.assertEqual(r.count, std.count)
        # explicit narrow keeps the class
        sid2 = "pnarrow"
        self._h("suv dikhao", sid2)
        r2 = self._h("sirf 5 lakh ke andar", sid2)
        self.assertEqual(r2.filters.get("category"), "SUV")
        self.assertEqual(r2.filters.get("price_max"), 500000)

    def test_step9_sequence(self):
        sid = "s9"
        r = self._h("Show me Ertiga", sid)
        self.assertIn(r.status, ("multi", "found"))
        self.assertEqual(r.meta["conversation_mode"], CP.MODE_NEW_SEARCH)
        r = self._h("automatic wali?", sid)
        self.assertEqual(r.meta["conversation_mode"], CP.MODE_SAME_MODEL_VARIANT)
        # every shown car is still an Ertiga (stayed within the model)
        self.assertTrue(all(v.get("model") == "Ertiga" for v in r.vehicles) or r.count == 0)
        r = self._h("RC?", sid)
        self.assertEqual(r.meta["conversation_mode"], CP.MODE_CURRENT_CAR)
        self.assertEqual(r.status, "found")
        r = self._h("7 seater chahiye", sid)
        self.assertEqual(r.meta["conversation_mode"], CP.MODE_NEW_SEARCH)

    def test_pinned_answers_pinned_car(self):
        sid = "pin"
        reg = next(i.registration_no for i in self.svc.engine.all_facing
                   if i.model == "Creta")
        self._h(reg + " available hai?", sid)
        r = self._h("boot space kitna?", sid)
        self.assertEqual(r.meta["conversation_mode"], CP.MODE_CURRENT_CAR)
        self.assertEqual(r.status, "found")
        self.assertIn("433", r.response)

    def test_cold_attribute_clarifies(self):
        r = self._h("sunroof hai?", "cold1")
        self.assertEqual(r.status, "clarify")
        self.assertEqual(r.meta["conversation_mode"], CP.MODE_CLARIFY)

    def test_conflict_clarifies(self):
        r = self._h("petrol diesel", "cf")
        self.assertEqual(r.status, "clarify")
        self.assertEqual(r.meta["conversation_mode"], CP.MODE_CLARIFY)

    def test_multi_intent_answers_all(self):
        sid = "mi"
        reg = next(i.registration_no for i in self.svc.engine.all_facing
                   if i.model == "Creta")
        self._h(reg + " available hai?", sid)
        r = self._h("airbags kitne aur boot space?", sid)
        self.assertEqual(r.meta["conversation_mode"], CP.MODE_MULTI_INTENT)
        self.assertIn("6", r.response)          # airbags
        self.assertIn("433", r.response)        # boot

    def test_missing_data_not_fabricated(self):
        sid = "md"
        reg = next(i.registration_no for i in self.svc.engine.all_facing
                   if i.model == "Creta")
        self._h(reg + " available hai?", sid)
        r = self._h("spare key hai?", sid)
        self.assertIn("Data not available", r.response)

    def test_fresh_search_not_stuck_on_previous(self):
        sid = "fs"
        reg = next(i.registration_no for i in self.svc.engine.all_facing
                   if i.model == "Creta")
        self._h(reg + " available hai?", sid)
        r = self._h("7 seater chahiye", sid)     # different requirement
        self.assertEqual(r.meta["conversation_mode"], CP.MODE_NEW_SEARCH)
        self.assertNotEqual(r.status, "found")   # a browse, not the pinned Creta


if __name__ == "__main__":
    unittest.main(verbosity=2)
