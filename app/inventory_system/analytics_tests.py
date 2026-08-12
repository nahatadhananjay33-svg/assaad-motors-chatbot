"""
analytics_tests.py
=================

Tests for Phase-3E analytics & unknown-query capture:
  * unknown query store (append-only, searchable, top queries)
  * analytics event store (record, by-day, counts)
  * conversation metrics (route %, distributions, rankings, funnel)
  * analytics engine reports (daily / weekly / summary)
  * chat_service integration (records route/intent/language/lead/vehicle)
  * the seven success-criteria questions over a synthetic 100-conversation set

Run:  python analytics_tests.py
"""

import os
import unittest

from unknown_query_store import UnknownQueryStore
from analytics import AnalyticsEngine, AnalyticsStore, AnalyticsEvent
import conversation_metrics as cm

XLSX = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")
T = "2026-06-10T10:00:00+00:00"
T2 = "2026-06-11T10:00:00+00:00"


def ev(session, route, **kw):
    return AnalyticsEvent(session_id=session, query=kw.get("query", "q"),
                          route=route, intent=kw.get("intent"),
                          language=kw.get("language", "english"),
                          lead_level=kw.get("lead_level"),
                          visit_ready=kw.get("visit_ready", False),
                          is_media=kw.get("is_media", False),
                          vehicle=kw.get("vehicle"),
                          timestamp=kw.get("timestamp", T))


# ─────────────────────────────────────────────────────────────────────────────
# 1. Unknown query store
# ─────────────────────────────────────────────────────────────────────────────
class TestUnknownQueryStore(unittest.TestCase):
    def setUp(self):
        self.s = UnknownQueryStore(":memory:")

    def test_record_and_count(self):
        self.s.record("which car is best for family?", session_id="s1",
                      language="english", timestamp=T, route="unknown",
                      detected_intent="unknown")
        self.assertEqual(self.s.count(), 1)

    def test_append_only_keeps_duplicates(self):
        self.s.record("compare creta vs nexon", session_id="s1")
        self.s.record("compare creta vs nexon", session_id="s2")
        self.assertEqual(self.s.count(), 2)            # not deduped on write

    def test_captures_all_fields(self):
        self.s.record("family car?", session_id="s9", language="hinglish",
                      timestamp=T, lead_score="Medium", route="unknown",
                      detected_intent="unknown")
        row = self.s.all()[0]
        self.assertEqual(row["session_id"], "s9")
        self.assertEqual(row["language"], "hinglish")
        self.assertEqual(row["lead_score"], "Medium")
        self.assertEqual(row["route"], "unknown")

    def test_search(self):
        self.s.record("insurance details?")
        self.s.record("family car recommendation")
        self.assertEqual(len(self.s.search("insurance")), 1)
        self.assertEqual(len(self.s.search("family")), 1)

    def test_top_queries_grouped_case_insensitive(self):
        self.s.record("Family car?")
        self.s.record("family car?")
        self.s.record("compare cars")
        top = self.s.top_queries(10)
        self.assertEqual(top[0]["query"], "family car?")
        self.assertEqual(top[0]["count"], 2)

    def test_by_language(self):
        self.s.record("a", language="english")
        self.s.record("b", language="marathi")
        self.assertEqual(self.s.by_language(), {"english": 1, "marathi": 1})

    def test_recent_order(self):
        for i in range(5):
            self.s.record(f"q{i}")
        recent = self.s.recent(3)
        self.assertEqual(recent[0]["query"], "q4")     # newest first


# ─────────────────────────────────────────────────────────────────────────────
# 2. Analytics store
# ─────────────────────────────────────────────────────────────────────────────
class TestAnalyticsStore(unittest.TestCase):
    def setUp(self):
        self.s = AnalyticsStore(":memory:")

    def test_record_and_all(self):
        self.s.record(ev("s1", "inventory", vehicle="Creta"))
        rows = self.s.all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["vehicle"], "Creta")
        self.assertFalse(rows[0]["visit_ready"])

    def test_by_day(self):
        self.s.record(ev("s1", "faq", timestamp=T))
        self.s.record(ev("s2", "faq", timestamp=T2))
        self.assertEqual(len(self.s.by_day("2026-06-10")), 1)
        self.assertEqual(len(self.s.by_day("2026-06-11")), 1)

    def test_by_days(self):
        self.s.record(ev("s1", "faq", timestamp=T))
        self.s.record(ev("s2", "faq", timestamp=T2))
        self.assertEqual(len(self.s.by_days(["2026-06-10", "2026-06-11"])), 2)

    def test_count(self):
        for _ in range(3):
            self.s.record(ev("s", "unknown"))
        self.assertEqual(self.s.count(), 3)

    def test_bool_round_trip(self):
        self.s.record(ev("s1", "inventory", visit_ready=True, is_media=True))
        row = self.s.all()[0]
        self.assertTrue(row["visit_ready"])
        self.assertTrue(row["is_media"])


# ─────────────────────────────────────────────────────────────────────────────
# 3. Conversation metrics
# ─────────────────────────────────────────────────────────────────────────────
class TestConversationMetrics(unittest.TestCase):
    def _events(self):
        return [
            ev("s1", "inventory", vehicle="Creta", lead_level="High", visit_ready=True).to_event(),
            ev("s1", "faq", intent="finance", lead_level="Medium").to_event(),
            ev("s2", "inventory", vehicle="Fortuner", lead_level="Low").to_event(),
            ev("s3", "unknown", query="family car?", intent="unknown").to_event(),
            ev("s4", "faq", intent="address", language="hinglish").to_event(),
            ev("s5", "inventory", vehicle="Creta", is_media=True).to_event(),
        ]

    def test_route_percentages(self):
        m = cm.compute(self._events())
        self.assertEqual(m["total_queries"], 6)
        self.assertEqual(m["inventory_percentage"], 50.0)
        self.assertEqual(m["faq_percentage"], round(200/6, 1))
        self.assertEqual(m["unknown_percentage"], round(100/6, 1))

    def test_media_percentage(self):
        m = cm.compute(self._events())
        self.assertEqual(m["media_percentage"], round(100/6, 1))

    def test_top_requested_models(self):
        m = cm.compute(self._events())
        top = m["top_requested_models"]
        self.assertEqual(top[0]["model"], "Creta")
        self.assertEqual(top[0]["count"], 2)

    def test_language_distribution(self):
        m = cm.compute(self._events())
        langs = {d["language"]: d["count"] for d in m["language_distribution"]}
        self.assertEqual(langs["english"], 5)
        self.assertEqual(langs["hinglish"], 1)

    def test_top_unknown_queries(self):
        m = cm.compute(self._events())
        self.assertEqual(m["top_unknown_queries"][0]["query"], "family car?")

    def test_top_requested_intents(self):
        m = cm.compute(self._events())
        intents = {d["intent"] for d in m["top_requested_intents"]}
        self.assertIn("finance", intents)
        self.assertIn("address", intents)

    def test_empty_events(self):
        m = cm.compute([])
        self.assertEqual(m["total_queries"], 0)
        self.assertEqual(m["inventory_percentage"], 0.0)

    def test_route_counts_present(self):
        m = cm.compute(self._events())
        self.assertEqual(m["route_counts"].get("inventory"), 3)
        self.assertEqual(m["route_counts"].get("faq"), 2)
        self.assertEqual(m["route_counts"].get("unknown"), 1)

    def test_model_percentage_of_mentions(self):
        m = cm.compute(self._events())   # 3 vehicle mentions: Creta x2, Fortuner x1
        creta = next(d for d in m["top_requested_models"] if d["model"] == "Creta")
        self.assertEqual(creta["percentage"], round(200/3, 1))


# ─────────────────────────────────────────────────────────────────────────────
# 4. Lead funnel
# ─────────────────────────────────────────────────────────────────────────────
class TestFunnel(unittest.TestCase):
    def test_funnel_counts(self):
        events = [
            ev("s1", "inventory", lead_level="High", visit_ready=True).to_event(),
            ev("s1", "faq", lead_level="Medium").to_event(),     # same session
            ev("s2", "faq", lead_level="Medium").to_event(),
            ev("s3", "inventory", lead_level="Low").to_event(),  # browsing only
            ev("s4", "unknown").to_event(),                      # no lead level
        ]
        f = cm.funnel(events)
        self.assertEqual(f["conversations"], 4)
        self.assertEqual(f["leads"], 2)                # s1(High), s2(Medium)
        self.assertEqual(f["visit_ready"], 1)          # s1
        self.assertEqual(f["high_priority_leads"], 1)  # s1

    def test_session_level_max_lead(self):
        events = [
            ev("s1", "inventory", lead_level="Low").to_event(),
            ev("s1", "faq", lead_level="High").to_event(),       # escalates s1
        ]
        f = cm.funnel(events)
        self.assertEqual(f["high_priority_leads"], 1)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Analytics engine + reports
# ─────────────────────────────────────────────────────────────────────────────
class TestAnalyticsEngine(unittest.TestCase):
    def setUp(self):
        self.eng = AnalyticsEngine()

    def test_unknown_forwarded_to_unknown_store(self):
        self.eng.record(ev("s1", "unknown", query="family car?", intent="unknown"))
        self.eng.record(ev("s2", "inventory", vehicle="Creta"))
        self.assertEqual(self.eng.unknown_store.count(), 1)     # only the unknown

    def test_summary_report(self):
        self.eng.record(ev("s1", "inventory", vehicle="Creta", lead_level="High", visit_ready=True))
        self.eng.record(ev("s2", "faq", intent="finance"))
        self.eng.record(ev("s3", "unknown", query="compare?"))
        r = self.eng.summary_report()
        self.assertEqual(r["report_type"], "summary")
        self.assertEqual(r["total_queries"], 3)
        self.assertIn("top_unknown_questions", r)
        self.assertEqual(r["total_events"], 3)

    def test_daily_report(self):
        self.eng.record(ev("s1", "faq", timestamp=T))
        self.eng.record(ev("s2", "faq", timestamp=T2))
        r = self.eng.daily_report("2026-06-10")
        self.assertEqual(r["report_type"], "daily")
        self.assertEqual(r["total_queries"], 1)

    def test_weekly_report(self):
        self.eng.record(ev("s1", "faq", timestamp="2026-06-05T10:00:00+00:00"))
        self.eng.record(ev("s2", "faq", timestamp="2026-06-10T10:00:00+00:00"))
        self.eng.record(ev("s3", "faq", timestamp="2026-06-01T10:00:00+00:00"))  # outside
        r = self.eng.weekly_report("2026-06-10")
        self.assertEqual(r["report_type"], "weekly")
        self.assertEqual(r["total_queries"], 2)        # 06-05 and 06-10 in window
        self.assertEqual(len(r["days"]), 7)

    def test_reports_are_json_compatible(self):
        import json
        self.eng.record(ev("s1", "inventory", vehicle="Creta", lead_level="High"))
        for r in (self.eng.summary_report(), self.eng.daily_report("2026-06-10"),
                  self.eng.weekly_report("2026-06-10")):
            json.dumps(r)        # must not raise

    def test_vehicle_ranking(self):
        for _ in range(3):
            self.eng.record(ev("s", "inventory", vehicle="Creta"))
        self.eng.record(ev("s", "inventory", vehicle="Fortuner"))
        ranking = self.eng.vehicle_ranking()
        self.assertEqual(ranking[0]["model"], "Creta")
        self.assertEqual(ranking[0]["count"], 3)

    def test_top_unknown_questions(self):
        self.eng.record(ev("s1", "unknown", query="family car?"))
        self.eng.record(ev("s2", "unknown", query="family car?"))
        top = self.eng.top_unknown_questions()
        self.assertEqual(top[0]["count"], 2)


# ─────────────────────────────────────────────────────────────────────────────
# 6. chat_service integration
# ─────────────────────────────────────────────────────────────────────────────
@unittest.skipUnless(os.path.exists(XLSX), "IVR_Sheet.xlsx not found")
class TestServiceIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from chat_service import ChatService
        cls.svc = ChatService(XLSX)

    def test_records_every_request(self):
        before = self.svc.analytics.store.count()
        self.svc.handle("Creta available?", session_id="i1")
        self.svc.handle("loan milega?", session_id="i1")
        self.svc.handle("blah blah xyz", session_id="i2")
        self.assertEqual(self.svc.analytics.store.count(), before + 3)

    def test_route_and_vehicle_recorded(self):
        self.svc.handle("Fortuner available?", session_id="i3")
        rows = [r for r in self.svc.analytics.store.all() if r["session_id"] == "i3"]
        self.assertEqual(rows[-1]["route"], "inventory")
        self.assertEqual(rows[-1]["vehicle"], "Fortuner")

    def test_unknown_captured(self):
        before = self.svc.analytics.unknown_store.count()
        self.svc.handle("zzz nonsense qqq", session_id="i4")
        self.assertEqual(self.svc.analytics.unknown_store.count(), before + 1)

    def test_lead_status_recorded_with_session(self):
        self.svc.handle("what is your address?", session_id="i5")
        rows = [r for r in self.svc.analytics.store.all() if r["session_id"] == "i5"]
        self.assertEqual(rows[-1]["lead_level"], "High")
        self.assertTrue(rows[-1]["visit_ready"])

    def test_response_unchanged_by_analytics(self):
        r = self.svc.handle("Creta available?", session_id="i6")
        # the public response still has exactly the documented keys
        d = r.to_dict()
        for k in ("intent", "response", "vehicles", "status", "count"):
            self.assertIn(k, d)


# ─────────────────────────────────────────────────────────────────────────────
# 7. Success criteria — 100-conversation synthetic pilot
# ─────────────────────────────────────────────────────────────────────────────
class TestSuccessCriteria100(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        eng = AnalyticsEngine()
        # 100 events across routes/vehicles/languages
        for i in range(50):                                   # 50 inventory
            veh = ["Creta", "Fortuner", "Polo", "Nexon"][i % 4]
            eng.record(ev(f"c{i}", "inventory", vehicle=veh,
                          lead_level="High" if i % 5 == 0 else "Low",
                          visit_ready=(i % 5 == 0)))
        for i in range(30):                                   # 30 faq
            eng.record(ev(f"c{i}", "faq", intent="finance",
                          language="hinglish" if i % 2 else "english",
                          lead_level="Medium"))
        for i in range(20):                                   # 20 unknown
            eng.record(ev(f"u{i}", "unknown",
                          query="which car is best for family?"))
        cls.report = eng.summary_report()
        cls.funnel = eng.funnel()

    def test_q1_inventory_percentage(self):
        self.assertEqual(self.report["inventory_percentage"], 50.0)

    def test_q2_faq_percentage(self):
        self.assertEqual(self.report["faq_percentage"], 30.0)

    def test_q3_unknown_percentage(self):
        self.assertEqual(self.report["unknown_percentage"], 20.0)

    def test_q4_most_interest_vehicle(self):
        self.assertTrue(self.report["top_requested_models"])
        self.assertEqual(self.report["top_requested_models"][0]["count"], 13)

    def test_q5_leads_captured(self):
        self.assertGreater(self.funnel["leads"], 0)

    def test_q6_visit_ready(self):
        self.assertGreater(self.funnel["visit_ready"], 0)

    def test_q7_unknown_to_become_faq(self):
        top = self.report["top_unknown_questions"]
        self.assertEqual(top[0]["query"], "which car is best for family?")
        self.assertEqual(top[0]["count"], 20)


if __name__ == "__main__":
    unittest.main(verbosity=2)
