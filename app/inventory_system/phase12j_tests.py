"""
phase12j_tests.py
=================

Phase 12J — context & data completeness hardening. Focused tests for the four
items:

  * MILEAGE  — "mileage?" (bare) clarifies (running vs km/l); "mileage kitna/kya"
               = kmpl; "kitne km chali"/"running" = odometer. Never price / search.
  * AUTO+PETROL — "automatic aur petrol hai?" answers both (pinned); "...wali
               dikhao"/"...chahiye" search; bare "automatic aur petrol?" clarifies.
  * MODEL-ONLY (multiple cars) — attribute follow-ups answer the COMMON value when
               provably identical across all matches, else CLARIFY which variant.
               Single-car pin and same-model variant search preserved.
  * DATA     — blank field -> "Data not available" (no fabrication); edit -> save ->
               refresh -> chatbot answers the saved value.

Runs on a COPY of the workbook. No LLM.
"""
from __future__ import annotations

import json
import os, shutil, tempfile, unittest

from query_parser import parse

LIVE = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")


# ─────────────────────────────────────────────────────────────────────────────
# Unit — parser flags
# ─────────────────────────────────────────────────────────────────────────────
class TestParser(unittest.TestCase):
    def test_bare_mileage_is_ambiguous(self):
        self.assertEqual(parse("mileage?").ambiguous_field, "mileage")
        self.assertEqual(parse("mileage").ambiguous_field, "mileage")

    def test_mileage_kmpl_forms_not_ambiguous(self):
        for m in ["mileage kitna hai?", "mileage kya hai?", "average kitna hai?",
                  "kitna average deti hai?"]:
            q = parse(m)
            self.assertIsNone(q.ambiguous_field, m)
            self.assertIn("mileage_arai_kmpl", q.attr_fields, m)

    def test_km_forms_are_odometer(self):
        for m in ["kitne km chali?", "running kitni hai?", "kitna chala hai?"]:
            self.assertTrue(parse(m).km_reading_query, m)
            self.assertIsNone(parse(m).ambiguous_field, m)

    def test_attr_pair_ambiguous(self):
        self.assertTrue(parse("automatic aur petrol?").attr_pair_ambiguous)
        self.assertTrue(parse("petrol aur automatic?").attr_pair_ambiguous)

    def test_attr_pair_not_flagged_when_question_or_search(self):
        # "hai?" -> both become attribute queries (answered), not the ambiguous pair
        q = parse("automatic aur petrol hai?")
        self.assertFalse(q.attr_pair_ambiguous)
        self.assertTrue(q.fuel_query and q.transmission_query)
        # search language stays a filter search
        for m in ["automatic petrol wali dikhao", "automatic petrol chahiye"]:
            self.assertFalse(parse(m).attr_pair_ambiguous, m)

    def test_seater_question_vocab(self):
        for m in ["kitne seater hai?", "seater kitna hai?", "कितने सीटर हैं?"]:
            self.assertTrue(parse(m).seats_query, m)
        # a real 7-seater search is still a filter, not a question
        self.assertIsNone(parse("7 seater chahiye").seats_query or None)


# ─────────────────────────────────────────────────────────────────────────────
# Behaviour — real ChatService end-to-end
# ─────────────────────────────────────────────────────────────────────────────
class TestBehaviour(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from chat_service import ChatService
        cls.tmp = tempfile.mkdtemp(prefix="p12j_")
        copy = os.path.join(cls.tmp, "c.xlsx")
        shutil.copy2(LIVE, copy)
        cls.svc = ChatService(xlsx_path=copy,
                              leads_db=os.path.join(cls.tmp, "l.db"),
                              analytics_db=os.path.join(cls.tmp, "a.db"),
                              unknown_db=os.path.join(cls.tmp, "u.db"))
        fort = next(i for i in cls.svc.engine.all_facing if i.model == "Fortuner")
        cls.fort_reg = fort.registration_no
        cls.fort_km = fort.km_driven
        cls.fort_mileage = getattr(fort, "mileage_arai_kmpl", None)
        # KM tests pin a car that actually HAS an odometer reading.
        kmcar = next(i for i in cls.svc.engine.all_facing if i.km_driven)
        cls.km_reg = kmcar.registration_no
        cls.km_val = kmcar.km_driven
        # Ertiga = multiple cars sharing seats / airbags, differing fuel/trans/year
        ert = [i for i in cls.svc.engine.all_facing if i.model == "Ertiga"]
        cls.ertiga_n = len(ert)
        cls.ertiga_seats = ert[0].seats
        cls.ertiga_airbags = getattr(ert[0], "airbags", None)

    @classmethod
    def tearDownClass(cls):
        try: cls.svc.close()
        except Exception: pass
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _pin_fort(self, sid):
        return self.svc.handle(self.fort_reg + " available hai?", session_id=sid)

    def _pin_km(self, sid):
        return self.svc.handle(self.km_reg + " available hai?", session_id=sid)

    def _pin_ertiga(self, sid):
        return self.svc.handle("show me Ertiga", session_id=sid)

    def _h(self, m, sid):
        return self.svc.handle(m, session_id=sid)

    # ---- MILEAGE ----
    def test_bare_mileage_clarifies(self):
        sid = "m1"; self._pin_fort(sid)
        r = self._h("mileage?", sid)
        self.assertEqual(r.status, "clarify")
        self.assertIn("running", r.response.lower())
        self.assertIn("km/l", r.response.lower())
        self.assertNotIn("lakh", r.response.lower())      # never price

    def test_mileage_kmpl_answered(self):
        if self.fort_mileage is None:
            self.skipTest("mileage blank on test car")
        sid = "m2"; self._pin_fort(sid)
        r = self._h("mileage kitna hai?", sid)
        self.assertIn("kmpl", r.response.lower())

    def test_km_is_odometer(self):
        for i, m in enumerate(["kitne km chali?", "running kitni hai?"]):
            sid = f"m3{i}"; self._pin_km(sid)
            r = self._h(m, sid)
            self.assertIn(f"{self.km_val:,}", r.response, m)

    # ---- AUTO + PETROL ----
    def test_auto_petrol_pair_clarifies(self):
        sid = "ap1"; self._pin_fort(sid)
        r = self._h("automatic aur petrol?", sid)
        self.assertEqual(r.status, "clarify")
        self.assertIn("G-ATTR-PAIR-CLARIFY", r.guardrails)

    def test_auto_petrol_hai_answers_both(self):
        sid = "ap2"; self._pin_fort(sid)
        r = self._h("automatic aur petrol hai?", sid)
        self.assertEqual(r.status, "found")
        self.assertIn("Fuel", r.response)
        self.assertIn("gear", r.response.lower())

    def test_auto_petrol_search_still_searches(self):
        for sid, m in [("ap3", "automatic petrol wali dikhao"),
                       ("ap4", "automatic petrol chahiye")]:
            r = self._h(m, sid)
            self.assertNotEqual(r.status, "clarify", m)
            self.assertNotIn("G-ATTR-PAIR-CLARIFY", r.guardrails, m)

    # ---- MODEL-ONLY: MULTIPLE ----
    def test_model_multi_common_value(self):
        # all Ertigas share seats and airbags -> answer the COMMON value,
        # covering every car ("Dono" for 2, "Saari N" for more).
        sid = "mm1"; self._pin_ertiga(sid)
        r = self._h("kitne seater hai?", sid)
        self.assertEqual(r.intent, "model_common")
        self.assertIn(str(self.ertiga_seats), r.response)
        self.assertTrue("Dono" in r.response or "Saari" in r.response, r.response)
        sid = "mm2"; self._pin_ertiga(sid)
        r = self._h("airbags kitne?", sid)
        self.assertEqual(r.intent, "model_common")
        self.assertIn(str(self.ertiga_airbags), r.response)

    def test_model_multi_differ_clarifies(self):
        for i, m in enumerate(["automatic hai?", "petrol hai?", "price?",
                               "kaunsa year hai?", "kitne km chali?"]):
            sid = f"mm3{i}"; self._pin_ertiga(sid)
            r = self._h(m, sid)
            self.assertEqual(r.status, "clarify", m)
            self.assertIn("G-MODEL-CLARIFY", r.guardrails, m)
            self.assertIn("Ertiga", r.response, m)
            self.assertIn("kaunsi", r.response.lower(), m)

    def test_model_multi_no_silent_pick(self):
        # the failing 12H behaviour: never answer one Ertiga's price silently
        sid = "mm4"; self._pin_ertiga(sid)
        r = self._h("price?", sid)
        self.assertNotEqual(r.intent, "price")
        self.assertEqual(r.status, "clarify")

    def test_model_multi_variant_search_preserved(self):
        for i, m in enumerate(["automatic wali dikhao", "petrol wali dikhao",
                               "kam km wali dikhao"]):
            sid = f"mm5{i}"; self._pin_ertiga(sid)
            r = self._h(m, sid)
            self.assertNotEqual(r.status, "clarify", m)
            self.assertNotIn("G-MODEL-CLARIFY", r.guardrails, m)

    def test_single_car_model_still_pins(self):
        for i, m in enumerate(["automatic hai?", "price?", "kitne km chali?"]):
            sid = f"sc{i}"; self._pin_fort(sid)
            r = self._h(m, sid)
            self.assertEqual(r.status, "found", m)
            self.assertEqual(r.count, 1, m)

    # ---- LANGUAGE (Devanagari model-multi: common value + clarify) ----
    def test_language_model_multi_common(self):
        # Hindi Devanagari airbags question -> common value across both Ertigas
        sid = "lg1"; self._pin_ertiga(sid)
        r = self._h("कितने एयरबैग हैं?", sid)
        self.assertEqual(r.intent, "model_common")
        self.assertIn(str(self.ertiga_airbags), r.response)

    def test_language_model_multi_clarify(self):
        # Hindi Devanagari fuel question -> the two Ertigas differ -> clarify
        sid = "lg2"; self._pin_ertiga(sid)
        r = self._h("पेट्रोल है?", sid)
        self.assertEqual(r.status, "clarify")
        self.assertIn("Ertiga", r.response)


# ─────────────────────────────────────────────────────────────────────────────
# Data completeness — no fabrication; edit -> save -> refresh -> answer
# ─────────────────────────────────────────────────────────────────────────────
class TestDataCompleteness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from chat_service import ChatService
        cls.tmp = tempfile.mkdtemp(prefix="p12j_data_")
        cls.copy = os.path.join(cls.tmp, "c.xlsx")
        shutil.copy2(LIVE, cls.copy)
        cls.svc = ChatService(xlsx_path=cls.copy,
                              leads_db=os.path.join(cls.tmp, "l.db"),
                              analytics_db=os.path.join(cls.tmp, "a.db"),
                              unknown_db=os.path.join(cls.tmp, "u.db"))
        # a single-car model with a BLANK sunroof (owner-entered field)
        it = next(i for i in cls.svc.engine.all_facing
                  if i.model == "Fortuner")
        cls.reg = it.registration_no

    @classmethod
    def tearDownClass(cls):
        try: cls.svc.close()
        except Exception: pass
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _pin(self, sid):
        self.svc.handle(self.reg + " available hai?", session_id=sid)

    def test_blank_field_not_fabricated(self):
        sid = "d1"; self._pin(sid)
        r = self.svc.handle("sunroof hai?", session_id=sid)
        self.assertIn("Data not available", r.response)

    def test_edit_save_refresh_answer(self):
        import inventory_edit as IE
        # find the Sunroof Type column key deterministically
        _c, sch = IE.handle_schema(self.svc)
        key = None
        for g in sch["groups"]:
            for f in g["fields"]:
                if (f.get("header", "").upper() == "SUNROOF TYPE"
                        or f.get("label") == "Sunroof Type"):
                    key = f["key"]
        self.assertIsNotNone(key, "Sunroof Type column not found")
        body = json.dumps({"car_number": self.reg,
                           "values": {key: "Single"}}).encode("utf-8")
        code, resp = IE.handle_update_car(self.svc, body)
        self.assertEqual(code, 200, resp)
        # handle_update_car already called service.refresh_inventory()
        sid = "d2"; self._pin(sid)
        r = self.svc.handle("sunroof hai?", session_id=sid)
        self.assertIn("Single", r.response)              # the SAVED value
        self.assertNotIn("Data not available", r.response)


if __name__ == "__main__":
    unittest.main(verbosity=2)
