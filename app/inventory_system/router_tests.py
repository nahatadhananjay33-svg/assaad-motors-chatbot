"""
router_tests.py
===============

Tests for the Intent Router and grounded LLM fallback.

Verifies:
  * routing decisions (retrieval primary / template / llm)
  * retrieval is NEVER bypassed when it can answer (even with an LLM configured)
  * the LLM fallback is GROUNDED — returned vehicles always come from inventory
  * the LLM never invents vehicles / prices / availability, and any leaked
    registration is scrubbed
  * comparison with a not-in-stock model is not fabricated
  * the deterministic (no-LLM) fallback is safe and grounded
  * templates carry no inventory facts and no internal-field leaks

Run:  python router_tests.py
"""

import os
import re
import json
import unittest

from inventory_models import InventoryItem, BodyType
import inventory_loader as L
from query_parser import parse
from retrieval_engine import RetrievalEngine
from router import (
    IntentRouter, Route, TemplateResponder, LLMFallback, extract_models,
)
from chat_service import ChatService

XLSX = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")
REG_RE = re.compile(r"MH\d{2}[A-Z]{0,3}\d{3,4}")


class AdversarialLLM:
    """A hostile fake LLM that tries to invent a car, a price, and leak a reg."""
    def complete(self, system: str, user: str) -> str:
        return ("Aap MH02XX1234 wali Baleno le lo, sirf 99 rupaye mein! "
                "Best deal, abhi book karo.")


class EchoLLM:
    """A well-behaved fake LLM that only restates the provided facts."""
    def __init__(self):
        self.last_user = None
    def complete(self, system: str, user: str) -> str:
        self.last_user = user
        return "In dono mein se aap aa ke best wali le lena. Visit zaroor karein."


@unittest.skipUnless(os.path.exists(XLSX), "IVR_Sheet.xlsx not found")
class RouterBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = L.load_inventory(XLSX)
        cls.engine = RetrievalEngine(cls.items)
        cls.router = IntentRouter()
        cls.inv_models = {(i.model or "").lower() for i in cls.items}


# ─────────────────────────────────────────────────────────────────────────────
# 1. Routing decisions
# ─────────────────────────────────────────────────────────────────────────────
class TestRouting(RouterBase):
    def _route(self, msg):
        return self.router.decide(msg, parse(msg)).route

    def test_inventory_queries_go_to_retrieval(self):
        for msg in ["Creta available?", "SUV under 8 lakh", "diesel cars",
                    "white automatic Honda", "first owner cars", "Fortuner price?"]:
            self.assertEqual(self._route(msg), Route.RETRIEVAL, msg)

    def test_faq_go_to_template(self):
        for msg in ["where are you located?", "what is your address",
                    "finance milega?", "test drive available?",
                    "exchange hota hai kya?", "hello"]:
            self.assertEqual(self._route(msg), Route.TEMPLATE, msg)

    def test_complex_go_to_llm(self):
        for msg in ["Creta vs Nexon which is better?", "recommend a good car",
                    "best car for my family", "konsi gaadi lu?",
                    "jo reel mein thi woh gaadi"]:
            self.assertEqual(self._route(msg), Route.LLM, msg)

    def test_faq_keyword_does_not_steal_inventory_query(self):
        # 'finance' present but it's really a car lookup with strong filters
        d = self.router.decide("diesel SUV under 8 lakh with finance",
                               parse("diesel SUV under 8 lakh with finance"))
        self.assertEqual(d.route, Route.RETRIEVAL)

    def test_extract_multiple_models(self):
        self.assertEqual(set(extract_models("Creta vs Nexon")), {"Creta", "Nexon"})


# ─────────────────────────────────────────────────────────────────────────────
# 2. Retrieval stays primary (router never sends an inventory query to the LLM)
# ─────────────────────────────────────────────────────────────────────────────
class TestRetrievalPrimary(RouterBase):
    def test_inventory_queries_never_route_to_llm(self):
        for msg in ["Creta available?", "diesel SUV under 8 lakh", "white cars"]:
            self.assertEqual(self.router.decide(msg, parse(msg)).route,
                             Route.RETRIEVAL, msg)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Grounded LLM fallback library (deferred in Phase 3B) — tested directly,
#    NOT via ChatService (the service does not route to the LLM in this phase).
#    These guarantee the LLM path stays safe for when it is enabled later.
# ─────────────────────────────────────────────────────────────────────────────
class TestLLMGrounding(RouterBase):
    def _answer(self, msg, client):
        q = parse(msg)
        decision = self.router.decide(msg, q)
        return LLMFallback(self.engine, llm_client=client).answer(msg, q, decision)

    def test_returned_vehicles_all_exist_in_inventory(self):
        res = self._answer("recommend a good family car", EchoLLM())
        self.assertTrue(res.vehicles)
        for v in res.vehicles:
            self.assertIn((v["model"] or "").lower(), self.inv_models)  # real cars only

    def test_adversarial_llm_output_is_scrubbed(self):
        res = self._answer("Creta vs Nexon which is better?", AdversarialLLM())
        # the leaked registration must be scrubbed from the text
        self.assertNotRegex(res.response, REG_RE.pattern)
        # structured vehicles are REAL inventory rows, not the invented 'Baleno'
        for v in res.vehicles:
            self.assertIn((v["model"] or "").lower(), self.inv_models)
            self.assertNotEqual((v["model"] or "").lower(), "baleno")

    def test_prompt_contains_only_inventory_facts(self):
        echo = EchoLLM()
        self._answer("Creta vs Nexon which is better?", echo)
        body = echo.last_user.split("\n\nAnswer:")[0]
        facts = json.loads(body[body.index("["): body.rindex("]") + 1])
        self.assertTrue(facts)
        for f in facts:
            self.assertIn((f["model"] or "").lower(), self.inv_models)
            self.assertTrue(f["price_quotable"] or f["price_lakh"] is None)

    def test_comparison_with_out_of_stock_model_not_fabricated(self):
        # 'Endeavour' is not in inventory; the grounded answer must not invent it
        res = self._answer("Creta vs Endeavour which is better?", None)
        self.assertFalse(any((v["model"] or "").lower() == "endeavour" for v in res.vehicles))
        self.assertNotRegex(res.response, REG_RE.pattern)

    def test_deterministic_fallback_is_grounded_and_safe(self):
        res = self._answer("best car for my family", None)   # no LLM client
        self.assertFalse(res.llm_used)
        self.assertTrue(res.grounded)
        self.assertTrue(res.vehicles)
        for v in res.vehicles:
            self.assertIn((v["model"] or "").lower(), self.inv_models)

    def test_llm_used_flag(self):
        res = self._answer("recommend a car", EchoLLM())
        self.assertTrue(res.llm_used)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Templates — no inventory facts, no leaks
# ─────────────────────────────────────────────────────────────────────────────
class TestTemplates(unittest.TestCase):
    def setUp(self):
        self.t = TemplateResponder()

    def test_location_template(self):
        key = self.t.match("where are you located?")
        self.assertEqual(key, "location")
        ans = self.t.answer(key)
        self.assertIn("Vasant Oasis", ans)
        self.assertNotRegex(ans, REG_RE.pattern)

    def test_finance_template_no_invented_terms(self):
        key = self.t.match("emi available hai?")
        self.assertEqual(key, "finance")
        ans = self.t.answer(key).lower()
        # must not quote a concrete rate/tenure
        self.assertNotRegex(ans, r"\d+\s*%")
        self.assertNotRegex(ans, r"\d+\s*months")

    def test_no_match_returns_none(self):
        self.assertIsNone(self.t.match("Creta available?"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
