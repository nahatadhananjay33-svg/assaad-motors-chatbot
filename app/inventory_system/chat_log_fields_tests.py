"""
chat_log_fields_tests.py
========================

Regression for the SIMPLIFIED chat log. The persistent conversation record is
deliberately minimal — the chatbot stores only the customer message and the
agent reply per turn:

    timestamp, conversation_id, session_id, user_query, bot_response

The chatbot still computes intent / filters / retrieval / result_count / etc.
internally to answer the customer, but those runtime values are NO LONGER
persisted. These tests lock that contract in: a real chat turn writes the
conversation and nothing else, and the never-deployed filters/result_count
columns are gone.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import unittest

XLSX = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")

# Internal/analytics columns that the production chatbot must NOT populate.
_METADATA_COLS = [
    "detected_language", "detected_intent", "route", "unknown_flag",
    "matched_inventory", "response_time_ms", "lead_level", "visit_ready",
    "vehicle_selected",
]


@unittest.skipUnless(os.path.exists(XLSX), "IVR_Sheet.xlsx not found")
class TestMinimalChatLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="clogf_")
        self.db = os.path.join(self.tmp, "pilot_query_log.db")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _svc(self):
        from instrumented_chat_service import InstrumentedChatService
        return InstrumentedChatService(
            XLSX, leads_db=os.path.join(self.tmp, "l.db"),
            analytics_db=os.path.join(self.tmp, "a.db"),
            unknown_db=os.path.join(self.tmp, "u.db"), pilot_log_db=self.db)

    def test_no_filters_or_result_count_columns(self):
        """The never-deployed filters/result_count columns are gone for good."""
        svc = self._svc()
        try:
            c = sqlite3.connect(self.db)
            cols = {r[1] for r in c.execute("PRAGMA table_info(query_log)")}
            c.close()
            self.assertNotIn("filters", cols)
            self.assertNotIn("result_count", cols)
        finally:
            svc.close()

    def test_chatbot_persists_only_message_and_response(self):
        svc = self._svc()
        try:
            svc.handle("petrol automatic cars under 5 lakh", session_id="s")
            svc.handle("Swift hai kya?", session_id="s")
            c = sqlite3.connect(self.db)
            c.row_factory = sqlite3.Row
            rows = c.execute("SELECT * FROM query_log WHERE session_id='s' ORDER BY id"
                             ).fetchall()
            c.close()
            self.assertEqual(len(rows), 2)
            for r in rows:
                d = dict(r)
                # the conversation IS recorded …
                self.assertTrue(d["user_query"])
                self.assertTrue(d["bot_response"])
                self.assertEqual(d["conversation_id"], "s")
                self.assertEqual(d["session_id"], "s")
                self.assertTrue(d["timestamp"])
                # … and NO internal metadata is persisted.
                for col in _METADATA_COLS:
                    val = d[col]
                    self.assertIn(val, (None, 0, ""),
                                  f"metadata column {col!r} was persisted: {val!r}")
        finally:
            svc.close()

    def test_unknown_log_not_grown_by_chatbot(self):
        """Unresolved/unknown analytics are no longer accumulated per turn."""
        svc = self._svc()
        try:
            svc.handle("zzxqwerty nonsense", session_id="g")
            c = sqlite3.connect(self.db)
            n = c.execute("SELECT COUNT(*) FROM unknown_log").fetchone()[0]
            c.close()
            self.assertEqual(n, 0)
        finally:
            svc.close()

    def test_dashboard_detail_is_conversation_only(self):
        """The Developer Dashboard conversation detail exposes only the
        customer/agent transcript — no intent/filters/latency/etc."""
        from developer_dashboard import handle_chat_detail
        svc = self._svc()
        try:
            svc.handle("diesel cars", session_id="d")
            _, detail = handle_chat_detail(svc, "d")
            turn = detail["turns"][0]
            self.assertEqual(set(turn.keys()), {"timestamp", "customer", "agent"})
            self.assertEqual(turn["customer"], "diesel cars")
            self.assertTrue(turn["agent"])
        finally:
            svc.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
