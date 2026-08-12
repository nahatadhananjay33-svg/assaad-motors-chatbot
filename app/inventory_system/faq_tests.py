"""
faq_tests.py
============

Tests for the Phase-3B deterministic FAQ layer:
  * language detection (english / hindi / hinglish / marathi)
  * FAQ intent detection across all 10 supported intents
  * business rules (fixed price, finance 2014+, exchange-no-valuation)
  * FAQ router (faq / inventory / unknown)
  * routing metrics + coverage
  * the explicit Phase-3B success-criteria queries

Run:  python faq_tests.py
"""

import os
import unittest

from language_detector import detect_language, ENGLISH, HINDI, HINGLISH, MARATHI
import faq_engine
import faq_templates as T
from faq_router import FAQRouter, RouteKind
from routing_metrics import RoutingMetrics

XLSX = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Language detection (all four languages)
# ─────────────────────────────────────────────────────────────────────────────
class TestLanguageDetection(unittest.TestCase):
    def test_english(self):
        for m in ["Finance available?", "Last price?", "Discount?",
                  "What is your address?", "Can I visit?"]:
            self.assertEqual(detect_language(m), ENGLISH, m)

    def test_hinglish(self):
        for m in ["Loan milega?", "Address bhejo", "Location send karo",
                  "Exchange karoge?", "kitne ki hai", "discount dedo"]:
            self.assertEqual(detect_language(m), HINGLISH, m)

    def test_hindi(self):
        for m in ["गाड़ी का दाम क्या है?", "क्या फाइनेंस मिलेगा?",
                  "पता भेजो", "कितने की है?"]:
            self.assertEqual(detect_language(m), HINDI, m)

    def test_marathi(self):
        for m in ["आज ओपन आहे का?", "फायनान्स मिळेल का?",
                  "गाडी कुठे आहे?", "किती किंमत आहे?"]:
            self.assertEqual(detect_language(m), MARATHI, m)

    def test_empty_defaults_english(self):
        self.assertEqual(detect_language(""), ENGLISH)
        self.assertEqual(detect_language("   "), ENGLISH)


# ─────────────────────────────────────────────────────────────────────────────
# 2. FAQ intent detection — all 10 intents
# ─────────────────────────────────────────────────────────────────────────────
class TestIntentDetection(unittest.TestCase):
    def test_address(self):
        self.assertEqual(faq_engine.detect_intent("What is your address?"), "address")
        self.assertEqual(faq_engine.detect_intent("address bhejo"), "address")

    def test_location(self):
        self.assertEqual(faq_engine.detect_intent("location send karo"), "location")
        self.assertEqual(faq_engine.detect_intent("share your google maps"), "location")

    def test_visit(self):
        self.assertEqual(faq_engine.detect_intent("can I visit the showroom?"), "visit")
        self.assertEqual(faq_engine.detect_intent("main aa sakta hu?"), "visit")

    def test_timing(self):
        self.assertEqual(faq_engine.detect_intent("what are your timings?"), "timing")
        self.assertEqual(faq_engine.detect_intent("aaj open hai?"), "timing")

    def test_finance(self):
        self.assertEqual(faq_engine.detect_intent("finance available?"), "finance")

    def test_loan(self):
        self.assertEqual(faq_engine.detect_intent("loan milega?"), "loan")

    def test_exchange(self):
        self.assertEqual(faq_engine.detect_intent("exchange karoge?"), "exchange")
        self.assertEqual(faq_engine.detect_intent("old car exchange?"), "exchange")

    def test_discount(self):
        self.assertEqual(faq_engine.detect_intent("any discount?"), "discount")

    def test_negotiation(self):
        for m in ["last price?", "best price?", "final rate?", "negotiable?",
                  "thoda kam karo"]:
            self.assertEqual(faq_engine.detect_intent(m), "negotiation", m)

    def test_booking(self):
        self.assertEqual(faq_engine.detect_intent("I want to book a car"), "booking")

    def test_non_faq_returns_none(self):
        for m in ["Creta available?", "Fortuner price?", "diesel SUV under 8 lakh",
                  "white automatic Honda"]:
            self.assertIsNone(faq_engine.detect_intent(m), m)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Business rules
# ─────────────────────────────────────────────────────────────────────────────
class TestBusinessRules(unittest.TestCase):
    def test_discount_says_fixed_price(self):
        r = faq_engine.resolve("any discount?")
        self.assertEqual(r.template_key, "price_fixed")
        self.assertIn("fixed", r.response.lower())

    def test_negotiation_says_fixed_price(self):
        r = faq_engine.resolve("last price?")
        self.assertEqual(r.template_key, "price_fixed")

    def test_finance_mentions_2014_and_no_guarantee(self):
        r = faq_engine.resolve("finance available?")
        self.assertEqual(r.template_key, "finance")
        self.assertIn("2014", r.response)

    def test_finance_pre_2014_is_ineligible(self):
        r = faq_engine.resolve("can I get finance on a 2010 car?")
        self.assertEqual(r.template_key, "finance_ineligible")

    def test_finance_2014_plus_eligible(self):
        r = faq_engine.resolve("finance on a 2018 model?")
        self.assertEqual(r.template_key, "finance")

    def test_loan_uses_finance_rule(self):
        r = faq_engine.resolve("loan milega?")
        self.assertEqual(r.intent, "loan")
        self.assertEqual(r.template_key, "finance")

    def test_exchange_no_valuation_quote(self):
        r = faq_engine.resolve("exchange karoge?")
        self.assertEqual(r.template_key, "exchange")
        self.assertNotRegex(r.response, r"\d+\s*(lakh|lac|rupee|rupaye|₹)")

    def test_every_faq_encourages_visit(self):
        # each FAQ response references the area/address (a gentle visit nudge)
        for intent_msg in ["address?", "location?", "can I visit?", "timing?",
                           "finance?", "loan?", "exchange?", "discount?",
                           "last price?", "book a car"]:
            r = faq_engine.resolve(intent_msg)
            self.assertIsNotNone(r, intent_msg)
            self.assertTrue(
                T.DEALERSHIP["area"] in r.response or T.DEALERSHIP["address"] in r.response,
                intent_msg)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Templates exist for every intent × language
# ─────────────────────────────────────────────────────────────────────────────
class TestTemplateCoverage(unittest.TestCase):
    def test_all_template_keys_have_all_languages(self):
        for key, bucket in T.FAQ_TEMPLATES.items():
            for lang in T.LANGUAGES:
                self.assertIn(lang, bucket, f"{key}/{lang}")
                self.assertTrue(bucket[lang].strip())

    def test_render_fills_placeholders(self):
        out = T.render("address", "english")
        self.assertNotIn("{address}", out)
        self.assertIn(T.DEALERSHIP["address"], out)

    def test_render_each_language(self):
        for lang in T.LANGUAGES:
            self.assertTrue(T.render("finance", lang).strip())


# ─────────────────────────────────────────────────────────────────────────────
# 5. Multi-language FAQ resolution
# ─────────────────────────────────────────────────────────────────────────────
class TestMultiLanguageFAQ(unittest.TestCase):
    def test_finance_in_each_language(self):
        cases = {
            "finance available?": ENGLISH,
            "finance milega kya?": HINGLISH,
            "क्या फाइनेंस मिलेगा?": HINDI,
            "फायनान्स मिळेल का?": MARATHI,
        }
        for msg, lang in cases.items():
            r = faq_engine.resolve(msg)
            self.assertIn(r.intent, ("finance", "loan"), msg)
            self.assertEqual(r.language, lang, msg)
            self.assertEqual(r.response, T.render(r.template_key, lang))

    def test_timing_marathi(self):
        r = faq_engine.resolve("आज ओपन आहे का?")
        self.assertEqual(r.intent, "timing")
        self.assertEqual(r.language, MARATHI)

    def test_discount_in_each_language(self):
        for msg in ["any discount?", "koi discount?", "कोई छूट?", "सवलत आहे का?"]:
            r = faq_engine.resolve(msg)
            self.assertIn(r.intent, ("discount", "negotiation"), msg)
            self.assertEqual(r.template_key, "price_fixed", msg)

    def test_hindi_finance_resolves(self):
        r = faq_engine.resolve("क्या फाइनेंस मिलेगा?")
        self.assertEqual(r.intent, "finance")
        self.assertEqual(r.language, HINDI)


# ─────────────────────────────────────────────────────────────────────────────
# 5b. Configurable dealership address (Rule 4)
# ─────────────────────────────────────────────────────────────────────────────
class TestConfigurableAddress(unittest.TestCase):
    def tearDown(self):
        # restore defaults so other tests are unaffected
        T.configure(address="Vasant Oasis Car Parking, Marol, Andheri East, Mumbai 400059",
                    area="Andheri East, Mumbai")

    def test_address_is_configurable(self):
        T.configure(address="New Lot, Powai, Mumbai", area="Powai")
        self.assertIn("Powai", T.render("address", "english"))

    def test_maps_and_whatsapp_support_present(self):
        self.assertTrue(T.maps_url().startswith("http"))
        wa = T.whatsapp_location()
        self.assertIn("address", wa)
        self.assertIn("latitude", wa)


# ─────────────────────────────────────────────────────────────────────────────
# 6. FAQ router (faq / inventory / unknown)
# ─────────────────────────────────────────────────────────────────────────────
class TestFAQRouter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = FAQRouter()

    def test_faq_routes(self):
        for m in ["loan milega?", "finance available?", "last price?", "discount?",
                  "address bhejo", "location send karo", "exchange karoge?",
                  "can I visit?", "what are your timings?", "book a car"]:
            self.assertEqual(self.r.classify(m).kind, RouteKind.FAQ, m)

    def test_inventory_routes(self):
        for m in ["Creta available?", "SUV under 8 lakh", "Fortuner price?",
                  "diesel cars", "white automatic Honda"]:
            self.assertEqual(self.r.classify(m).kind, RouteKind.INVENTORY, m)

    def test_unknown_routes(self):
        # Phase 7H: "hello there" now resolves deterministically to a greeting,
        # so genuine-unknown coverage uses gibberish that matches no intent.
        for m in ["blah blah", "asdf qwerty zxcv"]:
            rr = self.r.classify(m)
            self.assertEqual(rr.kind, RouteKind.UNKNOWN, m)
            self.assertEqual(rr.intent, "unknown")
            self.assertTrue(rr.mark_for_future_llm)

    def test_greeting_routes(self):
        # Phase 7H: pure greetings resolve to a deterministic greeting FAQ.
        for m in ["hello there", "Hi", "Good morning", "namaste"]:
            rr = self.r.classify(m)
            self.assertEqual(rr.kind, RouteKind.FAQ, m)
            self.assertEqual(rr.intent, "greeting", m)

    def test_media_no_vehicle_routes_to_clarify(self):
        # Phase 4C.2: a media reference with no identifiable vehicle is now
        # resolved deterministically with a clarifying FAQ response instead
        # of falling through to "unknown".
        rr = self.r.classify("jo reel mein thi woh gaadi")
        self.assertEqual(rr.kind, RouteKind.FAQ)
        self.assertEqual(rr.intent, "media_clarify")

    def test_router_carries_language(self):
        self.assertEqual(self.r.classify("फायनान्स मिळेल का?").language, MARATHI)


# ─────────────────────────────────────────────────────────────────────────────
# 7. Routing metrics + coverage
# ─────────────────────────────────────────────────────────────────────────────
class TestRoutingMetrics(unittest.TestCase):
    def test_counts_and_coverage(self):
        m = RoutingMetrics()
        m.record("faq", intent="finance", language="english")
        m.record("inventory", language="english")
        m.record("inventory", language="hinglish")
        m.record("unknown", language="english")
        c = m.coverage()
        self.assertEqual(c["total"], 4)
        self.assertEqual(c["faq_count"], 1)
        self.assertEqual(c["inventory_count"], 2)
        self.assertEqual(c["unknown_count"], 1)
        self.assertEqual(c["handled_without_llm"], 3)
        self.assertEqual(c["coverage_pct"], 75.0)
        self.assertEqual(c["unknown_pct"], 25.0)

    def test_reset(self):
        m = RoutingMetrics()
        m.record("faq", intent="loan")
        m.reset()
        self.assertEqual(m.total, 0)


# ─────────────────────────────────────────────────────────────────────────────
# 8. Success criteria (must work WITHOUT any LLM)
# ─────────────────────────────────────────────────────────────────────────────
class TestSuccessCriteria(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = FAQRouter()

    def test_required_queries_resolve_deterministically(self):
        expected = {
            "Loan milega?": "loan",
            "Finance available?": "finance",
            "Last price?": "negotiation",
            "Discount?": "discount",
            "Address bhejo": "address",
            "Location send karo": "location",
            "Exchange karoge?": "exchange",
            "आज ओपन आहे का?": "timing",
            "फायनान्स मिळेल का?": "finance",
        }
        for msg, intent in expected.items():
            rr = self.r.classify(msg)
            self.assertEqual(rr.kind, RouteKind.FAQ, msg)        # no LLM needed
            self.assertEqual(rr.intent, intent, msg)
            self.assertTrue(rr.faq.response.strip(), msg)


# ─────────────────────────────────────────────────────────────────────────────
# 9. End-to-end through the chat service (optional — needs the workbook)
# ─────────────────────────────────────────────────────────────────────────────
@unittest.skipUnless(os.path.exists(XLSX), "IVR_Sheet.xlsx not found")
class TestServiceIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from chat_service import ChatService
        cls.svc = ChatService(XLSX)

    def test_faq_through_service(self):
        r = self.svc.handle("Loan milega?")
        self.assertEqual(r.intent, "loan")
        self.assertEqual(r.meta["route"], "faq")
        self.assertEqual(r.vehicles, [])

    def test_unknown_marks_future_llm(self):
        # Phase 7H: "hello there" is now a greeting; use gibberish for unknown.
        r = self.svc.handle("asdf qwerty zxcv")
        self.assertEqual(r.intent, "unknown")
        self.assertTrue(r.meta["mark_for_future_llm"])

    def test_media_clarify_through_service(self):
        # A photo/video reference with no vehicle -> media clarify FAQ response.
        r = self.svc.handle("photo bhejo")
        self.assertEqual(r.intent, "media_clarify")
        self.assertEqual(r.meta["route"], "faq")

    def test_reel_reference_asks_for_car(self):
        # A REEL reference with no vehicle is a discovery/identification question:
        # ask for the car number / model / reel link (not a media-send clarify).
        r = self.svc.handle("jo reel mein thi woh gaadi")
        self.assertEqual(r.intent, "reel_clarify")
        self.assertIn("number", r.response.lower())

    def test_coverage_tracks_routes(self):
        svc = self.svc
        svc.metrics.reset()
        for m in ["Loan milega?", "Creta available?", "blah blah"]:
            svc.handle(m)
        c = svc.coverage()
        self.assertEqual(c["total"], 3)
        self.assertEqual(c["faq_count"], 1)
        self.assertEqual(c["inventory_count"], 1)
        self.assertEqual(c["unknown_count"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
