"""
phase12d_field_tests.py
=======================

Phase 12D — deterministic recognition of the NEW vehicle-detail fields
(specs / features / EV / keys / extra documents). Runs under the normal
`*_tests.py` sweep. NO LLM.

Coverage: for every new field, TERMS (its aliases, EN/HI/Hinglish/Marathi) ×
neutral question FRAMES → assert the parser resolves the field. Plus pinned-car
answering, cold clarification, filters, multi-intent and missing-data behaviour.
"""

from __future__ import annotations

import os, shutil, tempfile, unittest

from query_parser import parse, _norm
import field_intents as FI

# neutral question frames (no filter cue → attribute questions)
FRAMES = ["{t}", "{t}?", "{t} hai", "{t} hai kya", "kya {t} hai", "isme {t} hai",
          "is car mein {t} hai", "gaadi mein {t} hai", "{t} milega", "{t} milta hai",
          "{t} ke baare mein batao", "bhai {t} hai", "{t} kaisa hai",
          "{t} kitna hai", "{t} आहे का"]


def _detect_attr(msg):
    a, f = FI.detect(_norm(msg))
    return a, f


class TestFieldRecognition(unittest.TestCase):
    def test_every_field_resolves_across_frames(self):
        total = ok = 0
        misses = []
        per_field = {}
        for attr, spec in FI.FIELD_SPECS.items():
            c = 0
            for lbl in spec["labels"]:
                for fr in FRAMES:
                    msg = fr.format(t=lbl)
                    a, _ = _detect_attr(msg)
                    total += 1
                    if attr in a:
                        ok += 1; c += 1
                    else:
                        misses.append((attr, msg, a))
            per_field[attr] = c
        rate = ok / total
        self.assertGreaterEqual(total, 3000, f"only {total} utterances")
        self.assertGreaterEqual(rate, 0.99, f"{rate:.1%} ({len(misses)} miss) {misses[:8]}")
        # each field must have >= 30 resolving utterances
        low = {k: v for k, v in per_field.items() if v < 30}
        self.assertFalse(low, f"fields under 30 utterances: {low}")


class TestFilterVsAttribute(unittest.TestCase):
    def test_filter_cue_makes_it_a_filter(self):
        for lbl, attr in [("sunroof", "sunroof_type"), ("alloy wheels", "wheel_type"),
                          ("reverse camera", "camera_type"), ("cruise control", "cruise_control"),
                          ("android auto", "android_auto_carplay")]:
            a, f = _detect_attr(f"{lbl} wali car")
            self.assertIn(attr, f, f"{lbl} wali -> should be filter: {a} {f}")
            self.assertNotIn(attr, a)

    def test_no_cue_is_attribute(self):
        for lbl, attr in [("sunroof", "sunroof_type"), ("boot space", "boot_litres"),
                          ("airbags", "airbags")]:
            a, f = _detect_attr(f"{lbl} kitna hai")
            self.assertIn(attr, a)

    def test_airbag_count_filter_value(self):
        _, f = _detect_attr("6 airbags wali car")
        self.assertEqual(f.get("airbags"), 6)

    def test_alloy_filter_value(self):
        _, f = _detect_attr("alloy wheels wali")
        self.assertEqual(f.get("wheel_type"), "Alloy")


class TestMultiIntent(unittest.TestCase):
    def test_two_fields_both_detected(self):
        for m, fs in [("airbags kitne aur camera hai", {"airbags", "camera_type"}),
                      ("boot space aur ground clearance", {"boot_litres", "ground_clearance_mm"}),
                      ("sunroof aur alloy wheels", {"sunroof_type", "wheel_type"}),
                      ("led headlights aur fog lamps", {"headlamp_type", "fog_lamps"})]:
            a, f = _detect_attr(m)
            got = set(a) | set(f)
            self.assertTrue(fs <= got, f"{m}: missing {fs - got}")


class TestDeconfliction(unittest.TestCase):
    def test_no_11a_collisions(self):
        q = parse("boot space kitna hai")
        self.assertIsNone(q.category)                 # not Sedan
        self.assertIn("boot_litres", q.attr_fields)
        q = parse("android auto hai")
        self.assertIsNone(q.transmission)             # not Automatic
        q = parse("fuel tank capacity kitni")
        self.assertFalse(q.fuel_query)
        self.assertIn("fuel_tank_l", q.attr_fields)
        q = parse("ev range kitna hai")
        self.assertIsNone(q.fuel)                     # not Electric browse
        self.assertIn("real_range_km", q.attr_fields)

    def test_gearbox_still_11a_transmission(self):
        # 'gearbox' remains a Phase-11A transmission question (unchanged)
        self.assertTrue(parse("gearbox kaisa hai").transmission_query)


class TestLanguages(unittest.TestCase):
    def test_devanagari(self):
        cases = [("सनरूफ आहे का", "sunroof_type"), ("बूट स्पेस किती", "boot_litres"),
                 ("किती एअरबॅग", "airbags"), ("रेंज किती", "real_range_km"),
                 ("टचस्क्रीन आहे का", "touchscreen_inches")]
        for m, attr in cases:
            a, _ = _detect_attr(m)
            self.assertIn(attr, a, f"{m} -> {a}")


class TestEndToEnd(unittest.TestCase):
    """Pinned answering, cold clarification, missing-data — on a workbook copy."""
    @classmethod
    def setUpClass(cls):
        from chat_service import ChatService
        cls.tmp = tempfile.mkdtemp()
        copy = os.path.join(cls.tmp, "c.xlsx")
        shutil.copy2(os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx"), copy)
        cls.svc = ChatService(xlsx_path=copy,
                              leads_db=os.path.join(cls.tmp, "l.db"),
                              analytics_db=os.path.join(cls.tmp, "a.db"),
                              unknown_db=os.path.join(cls.tmp, "u.db"))
        cls.reg = next(i.registration_no for i in cls.svc.engine.all_facing
                       if i.model == "Creta")

    @classmethod
    def tearDownClass(cls):
        try: cls.svc.close()
        except Exception: pass

    def test_cold_clarifies(self):
        for m in ["sunroof hai?", "boot space kitna?", "airbags kitne?"]:
            r = self.svc.handle(m, session_id="cold-" + m)
            self.assertEqual(r.status, "clarify", f"{m} -> {r.status}")

    def test_pinned_answers_from_spec(self):
        sid = "pin"
        self.svc.handle(self.reg + " available hai?", session_id=sid)
        r = self.svc.handle("boot space kitna?", session_id=sid)
        self.assertEqual(r.status, "found")
        self.assertIn("433", r.response)              # Creta boot from model_specs
        r = self.svc.handle("airbags kitne?", session_id=sid)
        self.assertIn("6", r.response)

    def test_pinned_missing_data_never_fabricated(self):
        sid = "pin2"
        self.svc.handle(self.reg + " available hai?", session_id=sid)
        r = self.svc.handle("spare key hai?", session_id=sid)   # dealership field, empty
        self.assertIn("Data not available", r.response)

    def test_filter_returns_cars(self):
        r = self.svc.handle("alloy wheels wali car", session_id="f")
        self.assertIn(r.status, ("multi", "found"))
        self.assertGreater(r.count, 0)


if __name__ == "__main__":
    total = ok = 0
    per = {}
    for attr, spec in FI.FIELD_SPECS.items():
        c = 0
        for lbl in spec["labels"]:
            for fr in FRAMES:
                a, _ = FI.detect(_norm(fr.format(t=lbl)))
                total += 1; ok += (attr in a); c += (attr in a)
        per[attr] = c
    print(f"fields: {len(FI.FIELD_SPECS)} | utterances: {total} | resolved: {ok} ({100*ok/total:.1f}%)")
    print("min per-field:", min(per.values()), "| fields <30:", {k: v for k, v in per.items() if v < 30})
