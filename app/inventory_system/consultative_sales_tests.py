"""
consultative_sales_tests.py  —  Phase 7P.1
==========================================

Unit + integration tests for the consultative selling layer. They lock in:
  * the recommendation/question text for the documented entry intents,
  * that recommendations come ONLY from current inventory,
  * that the vehicle cards are never altered (additive wording only),
  * that the protected flows (Astor fix, low-KM, price follow-up, media,
    specific-model queries) are NOT hijacked by the consultative layer.
"""
from __future__ import annotations

import os
import tempfile
import unittest

import chat_service as CS
from chat_service import ChatService
import consultative_sales as CSL
from query_parser import parse


def _svc() -> ChatService:
    d = tempfile.mkdtemp(prefix="consult_test_")
    return ChatService(analytics_db=os.path.join(d, "a.db"),
                       leads_db=os.path.join(d, "l.db"),
                       unknown_db=os.path.join(d, "u.db"))


class TestDetectIntent(unittest.TestCase):
    def test_broad_intents_detected(self):
        cases = {
            "family car batao": "family", "MUV chahiye": "family",
            "SUV chahiye": "suv", "sedan dikhao": "sedan",
            "hatchback": "hatchback", "CNG car": "cng",
            "automatic car chahiye": "automatic", "budget car": "budget",
            "first car please": "first_car",
        }
        for msg, exp in cases.items():
            self.assertEqual(CSL.detect_intent(msg, parse(msg)), exp, msg)

    def test_specific_model_is_not_an_entry_intent(self):
        for msg in ["Swift available hai", "Ertiga details", "Creta price",
                    "Fortuner dikhao"]:
            self.assertIsNone(CSL.detect_intent(msg, parse(msg)), msg)

    def test_low_km_is_never_consultative(self):
        self.assertIsNone(CSL.detect_intent("low km car", parse("low km car")))


class TestRecommendations(unittest.TestCase):
    def test_picks_preferred_models_first(self):
        recs = CSL.pick_recommendations("family", ["Mobilio", "Ertiga", "Marazzo"])
        self.assertEqual(recs, ["Ertiga", "Marazzo"])

    def test_max_two_recommendations(self):
        recs = CSL.pick_recommendations("suv", ["Nexon", "Sonet", "Creta", "Astor"])
        self.assertLessEqual(len(recs), 2)

    def test_fills_from_matches_when_no_preferred(self):
        recs = CSL.pick_recommendations("family", ["Innova"])
        self.assertEqual(recs, ["Innova"])

    def test_empty_matches_yields_no_recommendation(self):
        self.assertEqual(CSL.pick_recommendations("family", []), [])
        self.assertIsNone(CSL.build_intro("family", []))

    def test_intro_has_one_question_and_under_three_lines(self):
        intro = CSL.consultative_intro("family", ["Ertiga", "Marazzo"])
        self.assertIn("Ertiga", intro)
        self.assertIn("Marazzo", intro)
        self.assertEqual(intro.count("?"), 1)
        self.assertLessEqual(len(intro.splitlines()), 3)


class TestIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svc = _svc()

    @classmethod
    def tearDownClass(cls):
        cls.svc.close()

    def test_family_is_consultative_and_keeps_cards(self):
        r = self.svc.handle("family car batao", session_id="s1")
        self.assertEqual(r.meta.get("consultative"), "family")
        self.assertIn("?", r.response)
        self.assertEqual(r.response.count("?"), 1)
        self.assertTrue(r.vehicles)                     # cards preserved
        self.assertIn("G-CONSULT", r.guardrails)

    def test_recommended_models_are_in_inventory(self):
        inv_models = {i.model for i in self.svc.engine.all_facing if i.model}
        for msg in ["family car batao", "SUV chahiye", "CNG car",
                    "automatic car chahiye", "car under 5 lakh"]:
            r = self.svc.handle(msg, session_id="s_inv")
            intent = r.meta.get("consultative")
            self.assertIsNotNone(intent, msg)
            recs = CSL.pick_recommendations(intent, r.meta.get("match_models", []))
            for m in recs:
                self.assertIn(m, inv_models, f"{msg}: {m} not in inventory")

    def test_vehicles_unchanged_vs_layer_off(self):
        # Same query, layer off vs on → identical vehicle set (additive wording).
        CS.CONSULTATIVE_LAYER = False
        off = self.svc.handle("SUV chahiye", session_id="off")
        CS.CONSULTATIVE_LAYER = True
        on = self.svc.handle("SUV chahiye", session_id="on")
        self.assertEqual([v["registration_no"] for v in off.vehicles],
                         [v["registration_no"] for v in on.vehicles])

    def test_specific_model_not_hijacked(self):
        r = self.svc.handle("Swift available hai", session_id="s2")
        self.assertIsNone(r.meta.get("consultative"))

    def test_astor_attr_guard_untouched(self):
        r = self.svc.handle("insurance kya hai", session_id="s3")
        self.assertIsNone(r.meta.get("consultative"))
        self.assertIn("G-ATTR-CLARIFY", r.guardrails)

    def test_low_km_untouched(self):
        r = self.svc.handle("low km car", session_id="s4")
        self.assertIsNone(r.meta.get("consultative"))

    def test_price_followup_untouched(self):
        # Phase 12J: use a SINGLE-car model so the price follow-up pins one car —
        # this test's purpose is that a price follow-up gets no consultative intro.
        # (On a MULTI-car model, "price kya hai" now correctly CLARIFIES which car
        # instead of silently picking one — covered by phase12j_tests.)
        self.svc.handle("Astor", session_id="s5")   # single-car model -> pins one car
        r = self.svc.handle("price kya hai", session_id="s5")
        self.assertIsNone(r.meta.get("consultative"))
        self.assertEqual(r.intent, "price")
        self.assertEqual(r.count, 1)

    def test_media_after_entry_untouched(self):
        self.svc.handle("family car batao", session_id="s6")
        r = self.svc.handle("photo bhejo", session_id="s6")
        self.assertIsNone(r.meta.get("consultative"))


if __name__ == "__main__":
    unittest.main()
