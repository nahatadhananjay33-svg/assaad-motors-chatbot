# -*- coding: utf-8 -*-
"""
Phase 12K — conversational INTENT AUDIT for groups H..O (regression lock).

Companion to phase12k_intent_audit_tests.py (per-field routing). This locks the
behaviour verified across the H..O audit and the three bugs it found + fixed:

  * M-1: negotiation asks that contain "price" ("last price?", "best price?",
         "final rate?") route to the FAQ negotiation script, not a price quote.
  * I-1: an explicit BROWSE ("automatic wali dikhao") after pinning a single car
         starts a FRESH inventory search — never relaxes back to the pinned car.
  * OWN: "kitne owner the?" is an owner-COUNT question, not a "<=2 owners" filter
         (which had silently dropped 3+ owner cars from a multi-car model).

Unit-level assertions are data-independent; the few end-to-end checks use the
Fortuner (stable single-car model) and any live multi-car model.
"""
import unittest

from query_parser import parse
import faq_engine
from chat_service import (ChatService, _is_price_followup, _is_attr_followup,
                          _has_browse_cue)

FORT = "MH04EX5958"

NEGOTIATION_PHRASES = ["last price?", "final price kya hai?", "best price bata do",
                       "lowest price?", "final rate?"]
DISCOUNT_PHRASES = ["discount milega?", "thoda kam karo", "bahut mehenga hai"]


class TestNegotiationRouting(unittest.TestCase):
    """M-1: price-word negotiation asks must not be shortcut to a price quote."""
    def test_faq_layer_sees_them_as_negotiation(self):
        for m in NEGOTIATION_PHRASES:
            self.assertEqual(faq_engine.detect_intent(m), "negotiation", m)
        for m in DISCOUNT_PHRASES:
            self.assertIn(faq_engine.detect_intent(m), ("negotiation", "discount"), m)

    def test_not_treated_as_price_or_attr_followup(self):
        for m in NEGOTIATION_PHRASES + DISCOUNT_PHRASES:
            q = parse(m)
            self.assertFalse(_is_price_followup(m, q), f"{m!r} price-followup")
            self.assertFalse(_is_attr_followup(m, q), f"{m!r} attr-followup")

    def test_plain_price_still_a_followup(self):
        # a genuine price question is NOT negotiation and keeps the fast path
        for m in ["price?", "kitne ka hai?", "final?"]:
            self.assertNotIn(faq_engine.detect_intent(m) or "", ("negotiation", "discount"), m)
            self.assertTrue(_is_price_followup(m, parse(m)), f"{m!r} should be price-followup")


class TestBrowseCue(unittest.TestCase):
    """I-1: explicit browse verbs force a fresh search; bare 'wali' does not."""
    def test_browse_verbs_detected(self):
        for m in ["automatic wali dikhao", "petrol cars dikhao", "diesel gaadiyan dikhao",
                  "show me automatic", "suv options dikhao"]:
            self.assertTrue(_has_browse_cue(m), m)

    def test_same_model_variant_not_a_browse(self):
        # bare variant asks ("automatic wali?") stay same-model-variant (12E)
        for m in ["automatic wali?", "petrol wali?", "first owner wali?", "white wali?"]:
            self.assertFalse(_has_browse_cue(m), m)


class TestOwnershipQuestionNotFilter(unittest.TestCase):
    """OWN: owner-count questions must not set a '<=2 owners' filter."""
    def test_owner_count_question_is_query_only(self):
        for m in ["kitne owner the?", "how many owners?", "kitne maalik the?",
                  "owner kitne hai?", "kiti malik hote?"]:
            q = parse(m)
            self.assertTrue(getattr(q, "ownership_query", False), f"{m!r} query")
            self.assertIsNone(q.ownership_max, f"{m!r} must NOT set ownership_max")
            self.assertIsNone(q.ownership_exact, f"{m!r} must NOT set ownership_exact")

    def test_few_owner_filter_preserved(self):
        for m in ["kam owner wali dikhao", "kam maalik wali"]:
            self.assertEqual(parse(m).ownership_max, 2, m)


class TestEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svc = ChatService()

    def _pin(self):
        sid = "conv-audit"
        self.svc.handle(FORT, session_id=sid)
        return sid

    def test_H_ambiguity_clarifies(self):
        for m in ["petrol diesel gaadi", "automatic manual chahiye", "engine?",
                  "battery?", "safety?", "automatic aur petrol?"]:
            r = self.svc.handle(m, session_id="amb")
            self.assertEqual(r.status, "clarify", f"{m!r} -> {r.response[:60]}")
            self.assertNotIn("lakh", r.response.lower(), m)

    def test_M_negotiation_end_to_end(self):
        sid = self._pin()
        for m in NEGOTIATION_PHRASES + DISCOUNT_PHRASES:
            r = self.svc.handle(m, session_id=sid)
            self.assertIn(r.intent, ("negotiation", "discount"),
                          f"{m!r} -> {r.intent}: {r.response[:60]}")

    def test_I_browse_after_pin_is_fresh_search(self):
        sid = self._pin()
        r = self.svc.handle("automatic wali dikhao", session_id=sid)
        self.assertTrue(r.vehicles, "browse returned no cars")
        # never the pinned manual Fortuner; every result actually automatic
        for v in r.vehicles:
            self.assertEqual(v.get("transmission"), "Automatic",
                             f"non-automatic leaked: {v.get('model')}")

    def test_J_multi_car_owner_question_never_silent_pick(self):
        # find a live multi-car model whose cars differ in ownership
        from collections import defaultdict
        by_model = defaultdict(list)
        for it in self.svc.engine.all_facing:
            if it.model:
                by_model[it.model].append(it)
        target = next((m for m, its in by_model.items()
                       if len(its) > 1 and len({i.ownership_count for i in its}) > 1), None)
        if not target:
            self.skipTest("no multi-car model with differing ownership in inventory")
        sid = "jmulti"
        self.svc.handle(f"{target} dikhao", session_id=sid)
        r = self.svc.handle("kitne owner the?", session_id=sid)
        # must clarify which car, not answer one silently
        self.assertEqual(r.status, "clarify",
                         f"{target} owner q -> {r.response[:80]}")


if __name__ == "__main__":
    unittest.main()
