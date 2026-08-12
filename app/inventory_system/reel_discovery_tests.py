"""
reel_discovery_tests.py
=======================

The dealership has a large Instagram following, so most customers reference a reel
to IDENTIFY a car and ask if it is available ("ye reel wali gaadi hai kya?"). That
is a vehicle-identification / availability question — NOT a request to be SENT
reel/photo/video media. These tests lock in:

  * bare reel query (no car)      -> reel-aware clarify (ask car number/model/link)
  * reel + model / reg / partial  -> AVAILABILITY answer (not "reel unavailable")
  * reel + multi-car model        -> list the matches, ask which
  * follow-up (number/model)      -> resolves to the car
  * explicit media SEND request   -> unchanged media behaviour (reel bhejo / send)

Runs on a COPY of the workbook. No LLM.
"""
from __future__ import annotations

import os, shutil, tempfile, unittest

import chat_service as CS
from chat_service import _is_reel_source_query


# ── unit: the reel-source discriminator ──────────────────────────────────────
class TestReelDiscriminator(unittest.TestCase):
    def test_reel_reference_is_source(self):
        for m in ["ye reel wali gaadi hai kya?", "jo reel me thi wo gaadi",
                  "reel wali Fortuner available hai?", "insta pe dekhi thi wo car",
                  "is this car available which is in the reel", "reel",
                  "instagram wali car available hai?"]:
            self.assertTrue(_is_reel_source_query(m), m)

    def test_send_request_is_not_source(self):
        # explicit "send me the reel/photo/video" stays a media request
        for m in ["reel bhejo", "Send Nexon reel", "Fortuner ki reel bhejo",
                  "instagram link do", "reel ki photo bhejo", "reel ka link chahiye",
                  "Innova ka reel bhejo"]:
            self.assertFalse(_is_reel_source_query(m), m)

    def test_non_reel_media_not_source(self):
        for m in ["Fortuner photos", "Nexon ka video", "youtube video"]:
            self.assertFalse(_is_reel_source_query(m), m)


# ── behaviour: real ChatService end-to-end ───────────────────────────────────
class TestReelBehaviour(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        LIVE = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")
        cls.tmp = tempfile.mkdtemp(prefix="reel_")
        copy = os.path.join(cls.tmp, "c.xlsx")
        shutil.copy2(LIVE, copy)
        cls.svc = CS.ChatService(xlsx_path=copy,
                                 leads_db=os.path.join(cls.tmp, "l.db"),
                                 analytics_db=os.path.join(cls.tmp, "a.db"),
                                 unknown_db=os.path.join(cls.tmp, "u.db"))
        fort = next(i for i in cls.svc.engine.all_facing if i.model == "Fortuner")
        cls.reg = fort.registration_no
        cls.reg_last4 = fort.registration_no[-4:]     # a real partial plate
        # a single-instance model, so "reel wali <model>" resolves to exactly one car
        from collections import Counter
        _cnt = Counter(i.model for i in cls.svc.engine.all_facing)
        cls.single_model = "Astor" if _cnt.get("Astor") == 1 else next(
            m for m, n in _cnt.items() if n == 1)

    @classmethod
    def tearDownClass(cls):
        try: cls.svc.close()
        except Exception: pass
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _h(self, m, sid):
        return self.svc.handle(m, session_id=sid)

    # ---- bare reel query -> ask for the car number/model/link ----
    def test_bare_reel_asks_for_car(self):
        for i, m in enumerate(["ye reel wali gaadi hai kya?", "reel wali gaadi",
                               "jo reel me thi wo gaadi available hai?",
                               "is this car available which is in the reel",
                               "instagram wali car available hai?"]):
            r = self._h(m, f"b{i}")
            self.assertEqual(r.intent, "reel_clarify", m)
            self.assertEqual(r.status, "clarify", m)
            self.assertIn("number", r.response.lower(), m)
            self.assertIn("G-REEL-CLARIFY", r.guardrails, m)
            # never a random inventory dump / price
            self.assertEqual(r.count, 0, m)

    # ---- reel + identified car -> AVAILABILITY (not "reel unavailable") ----
    def test_reel_with_model_answers_availability(self):
        r = self._h(f"reel wali {self.single_model} available hai?", "rm1")
        self.assertEqual(r.intent, "availability")
        self.assertEqual(r.count, 1)
        self.assertIn("available hai", r.response)
        self.assertNotIn("Instagram", r.response)

    def test_reel_with_registration_answers_availability(self):
        r = self._h(f"{self.reg} reel wali hai kya?", "rr1")
        self.assertEqual(r.count, 1)
        self.assertIn("available hai", r.response)
        self.assertNotIn("Instagram", r.response)

    def test_reel_with_partial_plate_answers_availability(self):
        # a partial plate (last 4 of a real reg) still identifies the car
        r = self._h(f"{self.reg_last4} wali reel gaadi", "rp1")
        self.assertNotEqual(r.intent, "reel_clarify")
        self.assertGreaterEqual(r.count, 1)
        self.assertNotIn("Instagram", r.response)

    def test_reel_with_multi_car_model_lists(self):
        # Nexon = 2 cars -> list them and ask which, never "reel unavailable"
        r = self._h("reel me jo nexon thi", "rn1")
        self.assertIn("Nexon", r.response)
        self.assertNotIn("Instagram", r.response)
        self.assertGreaterEqual(r.count, 2)

    # ---- workflow: clarify then the customer replies ----
    def test_followup_model_after_reel_clarify(self):
        sid = "fu1"
        r0 = self._h("ye reel wali gaadi hai kya?", sid)
        self.assertEqual(r0.intent, "reel_clarify")
        r = self._h(self.single_model, sid)
        self.assertEqual(r.count, 1)
        self.assertIn("available hai", r.response)

    def test_followup_number_after_reel_clarify(self):
        sid = "fu2"
        self._h("reel wali gaadi", sid)
        r = self._h(self.reg, sid)
        self.assertEqual(r.count, 1)
        self.assertIn("available hai", r.response)

    # ---- a PASTED reel LINK must never resolve a random car ----
    def test_pasted_reel_link_asks_for_car(self):
        for i, m in enumerate([
                "https://www.instagram.com/reel/C5xYz1AbCdE/",
                "https://www.instagram.com/reel/C5xYz1AbCdE/ ye gaadi hai kya?",
                "https://instagram.com/reel/DG9444kLm/",        # digits in shortcode
                "https://www.instagram.com/reel/Reel8000xy/",   # digits in shortcode
                "instagram.com/p/Cabc123def/ is this available?"]):
            r = self._h(m, f"lk{i}")
            self.assertEqual(r.intent, "reel_clarify", m)
            self.assertEqual(r.count, 0, m)                     # NO wrong car
            self.assertEqual(r.vehicles, [], m)                # no vehicle named

    def test_link_plus_named_model_still_resolves(self):
        # the URL is stripped, but a real model named alongside it still resolves
        r = self._h(f"https://www.instagram.com/reel/C5xYz1AbCdE/ {self.single_model} hai kya?",
                    "lm1")
        self.assertEqual(r.count, 1)
        self.assertIn(self.single_model, r.response)

    # ---- car SOLD / not in stock -> honest 'not available', never fabricate ----
    def test_absent_car_not_fabricated(self):
        for i, m in enumerate(["MH99XX0000 hai kya?", "XUV700 hai kya?",
                               "0001 wali gaadi hai kya?"]):
            r = self._h(m, f"na{i}")
            self.assertEqual(r.count, 0, m)
            self.assertIn("nahi", r.response.lower(), m)

    # ---- explicit media SEND request is unchanged ----
    def test_explicit_reel_send_still_media(self):
        r = self._h("Fortuner ki reel bhejo", "s1")
        self.assertNotEqual(r.intent, "reel_clarify")
        self.assertNotEqual(r.intent, "availability")   # it's a media request

    # ---- multilingual reel discovery ----
    def test_hindi_reel_reference(self):
        r = self._h("रील वाली गाड़ी है क्या?", "hi1")
        self.assertEqual(r.intent, "reel_clarify")
        r2 = self._h(f"रील वाली {self.single_model} available hai?", "hi2")
        self.assertEqual(r2.count, 1)
        self.assertIn("available hai", r2.response)


if __name__ == "__main__":
    unittest.main(verbosity=2)
