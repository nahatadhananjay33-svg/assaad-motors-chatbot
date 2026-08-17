"""
chat_log_fields_tests.py
========================

Regression for the two monitoring columns added to the chat log:
  * filters       — JSON of the active inventory filter dict per turn
  * result_count  — number of vehicles matched that turn

Covers: in-place migration of a pre-existing (old-schema) query_log DB, correct
recording on new turns (including 0-result searches), and that the Developer
Dashboard conversation detail surfaces both.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import unittest

XLSX = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")


@unittest.skipUnless(os.path.exists(XLSX), "IVR_Sheet.xlsx not found")
class TestChatLogFilterFields(unittest.TestCase):
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

    def test_migration_adds_columns_without_touching_old_rows(self):
        # a pre-existing DB on the OLD schema (no filters/result_count)
        c = sqlite3.connect(self.db)
        c.execute("CREATE TABLE query_log (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                  "timestamp TEXT, session_id TEXT, user_query TEXT, bot_response TEXT)")
        c.execute("INSERT INTO query_log (session_id,user_query,bot_response) "
                  "VALUES ('old','q','a')")
        c.commit(); c.close()

        svc = self._svc()      # opening migrates in place
        try:
            c = sqlite3.connect(self.db)
            cols = {r[1] for r in c.execute("PRAGMA table_info(query_log)")}
            self.assertIn("filters", cols)
            self.assertIn("result_count", cols)
            row = c.execute("SELECT user_query,filters,result_count FROM query_log "
                            "WHERE session_id='old'").fetchone()
            self.assertEqual(row[0], "q")      # old data intact
            self.assertIsNone(row[1])          # new columns NULL/default
            c.close()
        finally:
            svc.close()

    def test_filters_and_count_recorded(self):
        svc = self._svc()
        try:
            svc.handle("petrol automatic cars under 5 lakh", session_id="s")
            svc.handle("Swift hai kya?", session_id="s")     # 0 results, still a filter
            c = sqlite3.connect(self.db); c.row_factory = sqlite3.Row
            rows = c.execute("SELECT * FROM query_log WHERE session_id='s' ORDER BY id"
                             ).fetchall()
            c.close()
            f0 = json.loads(rows[0]["filters"])
            self.assertEqual(f0.get("fuel"), "Petrol")
            self.assertEqual(f0.get("transmission"), "Automatic")
            self.assertEqual(f0.get("price_max"), 500000)
            self.assertGreater(rows[0]["result_count"], 0)
            # a 0-result search still records the filter that failed
            self.assertEqual(json.loads(rows[1]["filters"]).get("model"), "Swift")
            self.assertEqual(rows[1]["result_count"], 0)
        finally:
            svc.close()

    def test_non_filter_turn_stores_null_filters(self):
        svc = self._svc()
        try:
            svc.handle("kaise ho?", session_id="g")
            c = sqlite3.connect(self.db)
            filt = c.execute("SELECT filters FROM query_log WHERE session_id='g'"
                             ).fetchone()[0]
            c.close()
            self.assertIsNone(filt)
        finally:
            svc.close()

    def test_dashboard_detail_surfaces_fields(self):
        from developer_dashboard import handle_chat_detail
        svc = self._svc()
        try:
            svc.handle("diesel cars", session_id="d")
            _, detail = handle_chat_detail(svc, "d")
            turn = detail["turns"][0]
            self.assertIn("filters", turn)
            self.assertIn("result_count", turn)
            self.assertEqual(turn["filters"].get("fuel"), "Diesel")
            self.assertGreater(turn["result_count"], 0)
        finally:
            svc.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
