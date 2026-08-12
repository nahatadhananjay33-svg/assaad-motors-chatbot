"""
lead_tests.py
============

Tests for Phase-3C lead capture & visit conversion:
  * field extraction (phone, name, vehicle, budget, language, timestamp)
  * interest flags (finance, exchange, visit intent)
  * lead scoring (High / Medium / Low)
  * visit signals (address, location, hours, inspection)
  * persistent storage (upsert idempotency, counts)
  * multi-turn accumulation

Run:  python lead_tests.py
"""

import unittest

from query_parser import parse
import visit_conversion as vc
from lead_capture import (
    extract_phone, extract_name, extract_vehicle, Lead, LeadCaptureEngine,
)
from lead_storage import LeadStore

NOW = "2026-06-10T10:00:00+00:00"
LATER = "2026-06-10T10:05:00+00:00"


# ─────────────────────────────────────────────────────────────────────────────
# 1. Field extraction
# ─────────────────────────────────────────────────────────────────────────────
class TestPhoneExtraction(unittest.TestCase):
    def test_plain_10_digit(self):
        self.assertEqual(extract_phone("call me on 9876543210"), "9876543210")

    def test_with_country_code(self):
        self.assertEqual(extract_phone("+91 98765 43210"), "9876543210")
        self.assertEqual(extract_phone("0 98765 43210"), "9876543210")

    def test_invalid_start_digit(self):
        self.assertIsNone(extract_phone("number 5876543210"))   # mobiles are 6-9

    def test_no_phone(self):
        self.assertIsNone(extract_phone("Creta under 8 lakh"))
        self.assertIsNone(extract_phone("price 800000"))


class TestNameExtraction(unittest.TestCase):
    def test_my_name_is(self):
        self.assertEqual(extract_name("my name is Rahul"), "Rahul")
        self.assertEqual(extract_name("My name is Priya Sharma"), "Priya Sharma")

    def test_i_am(self):
        self.assertEqual(extract_name("I am Amit"), "Amit")

    def test_hinglish(self):
        self.assertEqual(extract_name("mera naam Sunil hai"), "Sunil")

    def test_rejects_stopword(self):
        self.assertIsNone(extract_name("I'm looking for a Creta"))
        self.assertIsNone(extract_name("I am interested in finance"))

    def test_no_name(self):
        self.assertIsNone(extract_name("Creta available?"))


class TestVehicleExtraction(unittest.TestCase):
    def test_model_with_colour(self):
        self.assertEqual(extract_vehicle(parse("white Creta")), "White Creta")

    def test_category_with_fuel(self):
        self.assertEqual(extract_vehicle(parse("diesel SUV")), "Diesel SUV")

    def test_make_only(self):
        self.assertEqual(extract_vehicle(parse("show me a Honda")), "Honda")

    def test_nothing(self):
        self.assertIsNone(extract_vehicle(parse("hello there")))


# ─────────────────────────────────────────────────────────────────────────────
# 2. Visit-conversion signals & scoring
# ─────────────────────────────────────────────────────────────────────────────
class TestSignals(unittest.TestCase):
    def _sig(self, msg):
        return vc.extract_message_signals(msg)[0]

    def test_high_signals(self):
        self.assertIn(vc.WANTS_ADDRESS, self._sig("what is your address?"))
        self.assertIn(vc.WANTS_LOCATION, self._sig("send location"))
        self.assertIn(vc.ASKS_HOURS, self._sig("what are your timings?"))
        self.assertIn(vc.ASKS_AVAILABILITY, self._sig("is the Creta available?"))
        self.assertIn(vc.ASKS_INSPECTION, self._sig("I want to inspect the car"))

    def test_medium_signals(self):
        self.assertIn(vc.ASKS_FINANCE, self._sig("can I get finance?"))
        self.assertIn(vc.ASKS_EXCHANGE, self._sig("exchange karoge?"))
        self.assertIn(vc.ASKS_BUDGET, self._sig("budget 8 lakh"))

    def test_browsing_signal(self):
        self.assertEqual(self._sig("just browsing"), {vc.BROWSING})

    def test_finance_available_not_counted_as_availability(self):
        sig = self._sig("finance available?")
        self.assertIn(vc.ASKS_FINANCE, sig)
        self.assertNotIn(vc.ASKS_AVAILABILITY, sig)


class TestScoring(unittest.TestCase):
    def test_high(self):
        self.assertEqual(vc.score({vc.WANTS_LOCATION}).level, "High")
        self.assertEqual(vc.score({vc.ASKS_AVAILABILITY}).level, "High")
        self.assertEqual(vc.score({vc.ASKS_HOURS}).level, "High")

    def test_medium(self):
        self.assertEqual(vc.score({vc.ASKS_FINANCE}).level, "Medium")
        self.assertEqual(vc.score({vc.ASKS_EXCHANGE}).level, "Medium")
        self.assertEqual(vc.score({vc.ASKS_BUDGET}).level, "Medium")

    def test_low(self):
        self.assertEqual(vc.score({vc.BROWSING}).level, "Low")
        self.assertEqual(vc.score(set()).level, "Low")

    def test_high_beats_medium(self):
        s = vc.score({vc.ASKS_FINANCE, vc.WANTS_ADDRESS})
        self.assertEqual(s.level, "High")
        self.assertEqual(s.points, 15)           # 10 high + 5 medium

    def test_visit_signals_map(self):
        s = vc.score({vc.WANTS_ADDRESS, vc.ASKS_INSPECTION})
        self.assertTrue(s.visit_signals[vc.WANTS_ADDRESS])
        self.assertTrue(s.visit_signals[vc.ASKS_INSPECTION])
        self.assertFalse(s.visit_signals[vc.WANTS_LOCATION])
        self.assertTrue(s.visit_ready)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Storage
# ─────────────────────────────────────────────────────────────────────────────
class TestStorage(unittest.TestCase):
    def setUp(self):
        self.store = LeadStore(":memory:")

    def test_upsert_and_get(self):
        lead = Lead(session_id="s1", phone="9876543210", score_level="High",
                    created_at=NOW, updated_at=NOW, observed_signals=["wants_address"],
                    visit_signals={"wants_address": True})
        self.store.upsert(lead.to_record())
        got = self.store.get("s1")
        self.assertEqual(got["phone"], "9876543210")
        self.assertEqual(got["observed_signals"], ["wants_address"])
        self.assertTrue(got["visit_signals"]["wants_address"])

    def test_idempotent_upsert_same_session(self):
        lead = Lead(session_id="s1", created_at=NOW, updated_at=NOW)
        self.store.upsert(lead.to_record())
        self.store.upsert(lead.to_record())            # same session again
        self.assertEqual(self.store.count(), 1)        # no duplicate row

    def test_created_at_preserved_on_update(self):
        self.store.upsert(Lead(session_id="s1", created_at=NOW, updated_at=NOW).to_record())
        self.store.upsert(Lead(session_id="s1", created_at=LATER, updated_at=LATER,
                               score_level="High").to_record())
        got = self.store.get("s1")
        self.assertEqual(got["created_at"], NOW)       # creation pinned
        self.assertEqual(got["score_level"], "High")

    def test_counts(self):
        self.store.upsert(Lead(session_id="a", score_level="High", visit_ready=True).to_record())
        self.store.upsert(Lead(session_id="b", score_level="Medium").to_record())
        self.store.upsert(Lead(session_id="c", score_level="Low").to_record())
        self.assertEqual(self.store.count(), 3)
        self.assertEqual(self.store.count_by_level(),
                         {"High": 1, "Medium": 1, "Low": 1})
        self.assertEqual(self.store.count_visit_ready(), 1)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Capture engine (end to end)
# ─────────────────────────────────────────────────────────────────────────────
class TestCaptureEngine(unittest.TestCase):
    def setUp(self):
        self.eng = LeadCaptureEngine(LeadStore(":memory:"))

    def test_captures_all_fields(self):
        lead = self.eng.capture("s1", "I'm Rahul, white Creta under 8 lakh, "
                                      "my number is 9876543210", now=NOW)
        self.assertEqual(lead.name, "Rahul")
        self.assertEqual(lead.phone, "9876543210")
        self.assertEqual(lead.interested_vehicle, "White Creta")
        self.assertEqual(lead.budget_max, 800000)
        self.assertEqual(lead.language, "english")
        self.assertEqual(lead.created_at, NOW)
        self.assertEqual(lead.updated_at, NOW)
        self.assertTrue(lead.lead_id.startswith("LD-"))

    def test_finance_and_exchange_flags(self):
        lead = self.eng.capture("s1", "can I get finance and exchange my old car?", now=NOW)
        self.assertTrue(lead.finance_interest)
        self.assertTrue(lead.exchange_interest)

    def test_visit_intent_flag(self):
        lead = self.eng.capture("s1", "what is your address?", now=NOW)
        self.assertTrue(lead.visit_intent)
        self.assertTrue(lead.visit_ready)
        self.assertEqual(lead.score_level, "High")

    def test_browsing_is_low(self):
        lead = self.eng.capture("s1", "just looking around", now=NOW)
        self.assertEqual(lead.score_level, "Low")
        self.assertFalse(lead.visit_ready)

    def test_multi_turn_accumulates_and_is_sticky(self):
        self.eng.capture("s1", "I'm Priya, looking at a Nexon", now=NOW)
        self.eng.capture("s1", "is finance possible?", now=NOW)        # Medium
        lead = self.eng.capture("s1", "great, what's your address?", now=LATER)  # High
        self.assertEqual(lead.name, "Priya")                           # sticky name
        self.assertTrue(lead.finance_interest)                         # sticky flag
        self.assertEqual(lead.interested_vehicle, "Nexon")
        self.assertEqual(lead.score_level, "High")
        self.assertIn(vc.ASKS_FINANCE, lead.observed_signals)
        self.assertIn(vc.WANTS_ADDRESS, lead.observed_signals)
        self.assertEqual(self.eng.store.count(), 1)                    # one lead/session

    def test_separate_sessions_separate_leads(self):
        self.eng.capture("s1", "address?", now=NOW)
        self.eng.capture("s2", "finance?", now=NOW)
        self.assertEqual(self.eng.store.count(), 2)
        self.assertEqual(self.eng.store.count_by_level().get("High"), 1)
        self.assertEqual(self.eng.store.count_by_level().get("Medium"), 1)

    def test_language_captured_multilingual(self):
        self.assertEqual(self.eng.capture("a", "address bhejo", now=NOW).language, "hinglish")
        self.assertEqual(self.eng.capture("b", "फायनान्स मिळेल का?", now=NOW).language, "marathi")


if __name__ == "__main__":
    unittest.main(verbosity=2)
