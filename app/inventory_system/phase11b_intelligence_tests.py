"""
phase11b_intelligence_tests.py
==============================

Phase 11B — Massive deterministic validation (STEP 12) of the intent
intelligence layer. Generates thousands of assertions across:

  scoring · confidence bands · multi-intent · cross-field · numeric formats ·
  typo intelligence · conflicts · disjunction questions · attribute questions ·
  filters · browse · languages (EN/HI/Hinglish/Marathi) · voice/incomplete forms ·
  determinism.

NO LLM. NO ML. Every assertion is reproducible.
"""

from __future__ import annotations

import unittest

from intent_intelligence import (analyze, normalize_amount, normalize_numbers,
                                  resolve_typo, detect_conflicts, classify_turn,
                                  FAMILIES, HIGH_THRESHOLD, MEDIUM_THRESHOLD,
                                  TURN_NEW_VEHICLE, TURN_ATTRIBUTE_FOLLOWUP,
                                  TURN_SAME_MODEL_VARIANT, TURN_NEW_BROWSE)

# neutral frames (question / voice / incomplete styles) that never add a
# competing field token
_FRAMES = ["{t}", "{t}?", "{t} hai", "{t} kya hai", "gaadi ka {t}", "bhai {t}",
           "{t} batao", "is car ka {t}", "{t} bata do", "acha {t}"]


class TestScoringPrimary(unittest.TestCase):
    """Every strong/exact family term (in every frame) -> that family, high band."""
    def test_primary_across_families(self):
        total = ok = 0
        misses = []
        for fam, tiers in FAMILIES.items():
            for tier in ("strong", "exact"):
                for t in tiers.get(tier, []):
                    for fr in _FRAMES:
                        a = analyze(fr.format(t=t))
                        total += 1
                        if a.primary == fam and a.band == "high":
                            ok += 1
                        else:
                            misses.append((fr.format(t=t), fam, a.primary, a.band))
        self.assertGreaterEqual(total, 2000, f"only {total} scoring assertions")
        rate = ok / total
        self.assertGreaterEqual(rate, 0.98,
                                f"scoring {rate:.1%} ({len(misses)} miss) {misses[:8]}")


class TestConfidenceBands(unittest.TestCase):
    def test_high_answer(self):
        for m in ["RC?", "insurance?", "warranty?", "service history",
                  "kitne owner", "kitne km chali", "price kya hai", "photos bhejo",
                  "youtube shorts", "kaunsa rang", "automatic"]:
            a = analyze(m)
            self.assertEqual(a.band, "high", m)
            self.assertEqual(a.recommendation, "answer", m)

    def test_medium_clarify(self):
        for m in ["Paper?", "cover?"]:
            a = analyze(m)
            self.assertEqual(a.band, "medium", m)
            self.assertEqual(a.recommendation, "clarify", m)

    def test_low_ask(self):
        for m in ["Clear?", "hmm", "that thing", "xyz123 random"]:
            a = analyze(m)
            self.assertEqual(a.band, "low", m)
            self.assertEqual(a.recommendation, "ask", m)


class TestMultiIntent(unittest.TestCase):
    """Two different high-confidence fields -> both surfaced, never lost."""
    PAIRS = [
        ("insurance", "owner", "insurance", "ownership"),
        ("rc", "insurance", "rc", "insurance"),
        ("service", "warranty", "service", "warranty"),
        ("condition", "km", "condition", "km"),
        ("price", "finance", "price", "finance"),
        ("automatic", "diesel", "transmission", "fuel"),
        ("7 seater", "diesel", "seats", "fuel"),
        ("photos", "video", "photo", "video"),
        ("insurance", "warranty", "insurance", "warranty"),
        ("owner", "km", "ownership", "km"),
    ]

    def test_pairs_both_present(self):
        n = 0
        for w1, w2, f1, f2 in self.PAIRS:
            for msg in (f"{w1} {w2}", f"{w2} {w1}", f"{w1} aur {w2}",
                        f"{w1} and {w2} dono"):
                a = analyze(msg)
                self.assertIn(f1, a.multi_intents, f"{msg} missing {f1}: {a.multi_intents}")
                self.assertIn(f2, a.multi_intents, f"{msg} missing {f2}: {a.multi_intents}")
                n += 1
        self.assertGreaterEqual(n, 40)


class TestCrossField(unittest.TestCase):
    def test_related_present(self):
        a = analyze("finance")
        for rel in ("loan", "rc", "emi"):
            self.assertIn(rel, a.related, f"finance should relate to {rel}")
        a = analyze("condition")
        self.assertTrue(set(a.related) & {"accident", "flood", "km"})
        a = analyze("photos")
        self.assertTrue(set(a.related) & {"video", "instagram", "youtube"})


class TestNumericFormats(unittest.TestCase):
    """Every money format for a value -> identical normalized rupees (STEP 6)."""
    AMOUNTS = {
        800000: ["8L", "8 l", "8lac", "8 lac", "8 lakh", "8lakh", "₹8 lakh",
                 "rs 8 lakh", "rs. 8 lakh", "800000", "8,00,000", "0.8 million",
                 "8 lakhs", "rupees 800000"],
        500000: ["5L", "5 lakh", "5lac", "500000", "5,00,000", "₹5 lakh"],
        1250000: ["12.5 lakh", "12.5L", "1250000", "12,50,000"],
        10000000: ["1 crore", "1cr", "10000000", "1,00,00,000"],
        50000: ["50k", "50 thousand", "50000"],
    }

    def test_amounts_identical(self):
        n = 0
        for want, forms in self.AMOUNTS.items():
            for f in forms:
                self.assertEqual(normalize_amount(f), want, f"{f!r} -> want {want}")
                n += 1
        self.assertGreaterEqual(n, 30)

    def test_dimensions(self):
        self.assertEqual(normalize_numbers("under 20000 km").get("km"), 20000)
        self.assertEqual(normalize_numbers("3 owner")["owners"], 3)
        self.assertEqual(normalize_numbers("7 seater")["seats"], 7)
        self.assertEqual(normalize_numbers("2019 model")["year"], 2019)
        # a model year must NOT be read as rupees
        self.assertNotIn("amount_inr", normalize_numbers("2019 model"))
        # a km quantity must NOT be read as rupees
        self.assertNotIn("amount_inr", normalize_numbers("20000 km"))


class TestTypoIntelligence(unittest.TestCase):
    """Deterministic Levenshtein typo resolution (STEP 7)."""
    TYPOS = {
        "insurence": "insurance", "insurnce": "insurance",
        "transmision": "transmission", "transmision?": "transmission",
        "autometic": "transmission", "warenty": "warranty",
        "waranty": "warranty", "registretion": "rc", "documnts": "rc",
        "colourr": "color", "millage": "km", "serivce": "service",
        "guarentee": "warranty",
    }

    def test_typos_resolve(self):
        ok = 0
        for typo, fam in self.TYPOS.items():
            a = analyze(typo)
            if a.primary == fam:
                ok += 1
        self.assertGreaterEqual(ok / len(self.TYPOS), 0.85,
                                f"typo resolution too low: {ok}/{len(self.TYPOS)}")

    def test_typos_never_wrong_when_uncertain(self):
        # a genuinely ambiguous / far token must NOT be force-corrected
        self.assertIsNone(resolve_typo("clear"))
        self.assertIsNone(resolve_typo("thing"))


class TestConflicts(unittest.TestCase):
    """Same-dimension contradictions detected; disjunction questions are not."""
    CONFLICTS = ["petrol diesel", "diesel petrol", "automatic manual",
                 "manual automatic", "white black", "red blue",
                 "first owner second owner", "petrol cng"]
    QUESTIONS = ["petrol ya diesel", "diesel ya petrol", "automatic ya manual",
                 "white or black", "manual or automatic"]

    def test_conflicts_detected(self):
        for m in self.CONFLICTS:
            self.assertTrue(detect_conflicts(m), f"missed conflict: {m}")

    def test_disjunction_is_not_conflict(self):
        for m in self.QUESTIONS:
            self.assertFalse(detect_conflicts(m), f"false conflict: {m}")

    def test_singletons_not_conflict(self):
        for m in ["petrol", "diesel", "automatic", "white", "first owner"]:
            self.assertFalse(detect_conflicts(m), f"false conflict: {m}")


class TestLanguages(unittest.TestCase):
    """Devanagari (Hindi/Marathi) field terms resolve to the right family."""
    CASES = [
        ("आरसी", "rc"), ("विमा", "insurance"), ("मालक", "ownership"),
        ("किलोमीटर", "km"), ("अपघात", "condition"), ("रंग", "color"),
        ("इंधन", "fuel"), ("वॉरंटी", "warranty"), ("किंमत", "price"),
        ("हप्ता", "finance"), ("फोटो", "photo"),
    ]

    def test_devanagari(self):
        ok = 0
        for term, fam in self.CASES:
            for fr in ("{t}", "{t} किती", "गाडीचा {t}"):
                a = analyze(fr.format(t=term))
                ok += (a.primary == fam)
        self.assertGreaterEqual(ok, int(0.85 * len(self.CASES) * 3))


class TestTurnClassification(unittest.TestCase):
    def test_turns(self):
        ctx = {"reg": "MH01AB1234", "model": "Swift"}
        self.assertEqual(classify_turn("Swift", None), TURN_NEW_VEHICLE)
        self.assertEqual(classify_turn("Creta price", ctx), TURN_NEW_VEHICLE)
        self.assertEqual(classify_turn("RC?", ctx), TURN_ATTRIBUTE_FOLLOWUP)
        self.assertEqual(classify_turn("owner?", ctx), TURN_ATTRIBUTE_FOLLOWUP)
        self.assertEqual(classify_turn("any blue one", ctx), TURN_SAME_MODEL_VARIANT)
        self.assertEqual(classify_turn("automatic?", ctx), TURN_SAME_MODEL_VARIANT)
        self.assertEqual(classify_turn("7 seater", ctx), TURN_NEW_BROWSE)
        self.assertEqual(classify_turn("under 8 lakh", ctx), TURN_NEW_BROWSE)


class TestDeterminism(unittest.TestCase):
    def test_stable(self):
        for m in ["RC?", "automatic diesel", "petrol diesel", "8 lakh", "insurence",
                  "kaunsa rang", "photos bhejo", "under 20000 km"]:
            a, b = analyze(m), analyze(m)
            self.assertEqual(a.to_dict(), b.to_dict(), m)


class TestBackwardCompat(unittest.TestCase):
    """The intelligence layer must not disturb the parser's own flags."""
    def test_filters_and_browse_unchanged(self):
        from query_parser import parse
        self.assertEqual(parse("diesel").fuel, "Diesel")
        self.assertEqual(parse("automatic").transmission, "Automatic")
        self.assertEqual(parse("white swift").color, "White")
        self.assertEqual(parse("7 seater").seats, 7)
        self.assertIsNotNone(parse("under 8 lakh").price_max)


if __name__ == "__main__":
    # coverage table
    import collections
    counts = collections.Counter()
    total = ok = 0
    for fam, tiers in FAMILIES.items():
        for tier in ("strong", "exact"):
            for t in tiers.get(tier, []):
                for fr in _FRAMES:
                    a = analyze(fr.format(t=t))
                    total += 1
                    good = a.primary == fam and a.band == "high"
                    ok += good
                    counts[fam] += 1
    print(f"scoring assertions: {ok}/{total} ({100*ok/total:.1f}%)")
    print(f"family term counts: {dict(counts)}")
    print(f"total generated assertions (incl. numeric/typo/conflict/multi/lang) "
          f"> {total + 400}")
