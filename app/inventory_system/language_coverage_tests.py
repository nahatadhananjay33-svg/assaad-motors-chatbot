"""
language_coverage_tests.py
==========================

Regression for three customer-language bugs found by the 750-question live
validation run. All three had the same shape: the customer's words were fine, but
the query never reached the right Excel column.

1. PRICE VOCABULARY (8 of the 10 live failures)
   Standard Hindi "कीमत" was not recognised as a price word anywhere, while the
   Marathi spelling "किंमत" was — because four separate call sites (parser
   intents, response_formatter's explicit-price check, chat_service's two
   follow-up gates) each carried their OWN price-synonym list and the spelling
   had been added to some and not others. A customer asking "MH.. की कीमत क्या
   है?" got an availability blurb instead of the price.
   Fix: fold the whole phonetic family to the canonical token "price" once, in
   the normalization pass every call site shares (query_parser.normalize_typos).

2. SECOND-MODEL DIGITS (the other 2 live failures)
   "3 Series aur 525 I me kaunsi behtar hai?" -> the '525' of the SECOND model
   leaked into reg_partial, so the search returned nothing and the bot said BOTH
   cars were unavailable — while both were standing on the lot. The earlier fix
   only protected the one model that won `q.model`.
   Fix: query_parser._digits_belong_to_a_model scans the whole model catalogue.

3. YEAR-LIKE NUMBER PLATES (found while auditing last-4 lookups)
   A plate whose trailing digits look like a year was claimed by the model-year
   parser, so cars ending 1938/1994/1996/2001/2005 were unreachable by their
   last-4 and reported "not available".
   Fix: query_parser._plate_cue_adjacent — an explicit plate word ("number",
   "plate") NEXT TO the digits makes them a registration, while "2015 model
   dikhao" still reads as a year.

Data-driven off the CURRENT Excel, so they keep protecting the whole class of bug
after the dealership swaps the inventory.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import unittest
from collections import defaultdict

import inventory_loader as L
import query_parser as qp

XLSX = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")

# Every realistic spelling of "what does it cost" the brief calls out, in all
# three scripts. These are ASSERTIONS about coverage, not a synonym table the
# product reads — the product folds them with a handful of family regexes.
PRICE_PHRASES_DEVANAGARI = [
    "कीमत", "कीमत क्या है", "कीमत कितनी है", "कीमत बताओ", "कीमत बता दो",
    "गाड़ी की कीमत", "इसकी कीमत", "इस गाड़ी की कीमत", "कितने की है",
    "कितने में है", "कितने में मिलेगी", "दाम क्या है", "दाम कितना है",
    "दाम बताओ", "मूल्य क्या है",
]
PRICE_PHRASES_ROMAN = [
    "keemat", "keemat kya hai", "keemat kitni hai", "keemat batao",
    "keemat bata do", "gaadi ki keemat", "iski keemat", "is gaadi ki keemat",
    "kitne ki hai", "kitne mein hai", "kitne mein milegi", "daam kya hai",
    "daam kitna hai", "daam batao", "mulya kya hai",
]
PRICE_PHRASES_PHONETIC = [
    "kimat", "kimmat", "keemaat", "keemattt", "keemat kya h", "keemat kitni h",
    "keemat btao", "keemat bta do", "kimmat kya hai", "kimmat kitni hai",
    "keemath",
]
ALL_PRICE_PHRASES = (PRICE_PHRASES_DEVANAGARI + PRICE_PHRASES_ROMAN
                     + PRICE_PHRASES_PHONETIC)

# The spellings the FOLD itself owns — the price noun in each script, plus the
# Devanagari "for how much" phrases. The Roman equivalents ("kitne ki hai") were
# already in the parser's phrase vocabulary and stay there; the contract that
# covers every phrasing regardless of which layer handles it is the price-intent
# and end-to-end tests below.
PRICE_NOUN_SPELLINGS = [
    "कीमत", "किंमत", "किमत", "कीमती", "दाम", "दामों", "भाव", "मूल्य", "रेट",
    "कितने की", "कितने में", "कितने का",
    "keemat", "kimat", "kimmat", "kemat", "kiimat", "keemaat", "keemattt",
    "keemath", "mulya", "moolya",
]


def _trailing_digits(plate: str):
    m = re.search(r"(\d+)$", (plate or "").upper().replace(" ", ""))
    return m.group(1) if m else None


class TestPriceVocabularyFolding(unittest.TestCase):
    """Unit level: every spelling collapses to the one canonical token."""

    def test_every_noun_spelling_folds_to_price(self):
        for p in PRICE_NOUN_SPELLINGS:
            self.assertIn("price", qp.normalize_price_vocab(p).lower(),
                          f"price vocabulary not folded: {p!r}")

    def test_parser_tags_price_intent(self):
        for p in ALL_PRICE_PHRASES:
            self.assertIn("price", qp.parse(f"MH01AB1234 {p}").intents,
                          f"no price intent for: {p!r}")

    def test_hindi_and_marathi_spellings_agree(self):
        """The exact bug: कीमत (Hindi) behaved differently from किंमत (Marathi)."""
        for a, b in [("कीमत", "किंमत"), ("कीमत", "किमत"), ("keemat", "kimmat")]:
            self.assertEqual("price" in qp.normalize_price_vocab(a).lower(),
                             "price" in qp.normalize_price_vocab(b).lower(),
                             f"{a!r} and {b!r} must fold alike")

    def test_does_not_swallow_unrelated_words(self):
        """The fold must not turn ordinary vocabulary into a price question."""
        for s in ["kitne km chali hai", "kismat", "kitne owner hain",
                  "kitne airbags hain", "kitne seater hai", "kaun si gaadi",
                  "कितने किलोमीटर चली है", "कितने मालिक"]:
            self.assertNotIn("price", qp.normalize_price_vocab(s).lower(),
                             f"price fold wrongly fired on: {s!r}")


class TestYearLikePlateDisambiguation(unittest.TestCase):
    def test_plate_cue_makes_year_like_digits_a_plate(self):
        for q in ["1994 number wali gaadi dikhao", "gaadi number 1994",
                  "1996 number ki gaadi ka price batao", "plate 2001"]:
            p = qp.parse(q)
            self.assertIsNotNone(p.reg_partial, f"plate not detected: {q}")
            self.assertIsNone(p.year_exact, f"wrongly read as a year: {q}")

    def test_year_queries_stay_year_queries(self):
        for q, yr in [("2015 model dikhao", 2015), ("2012 wali car batao", 2012),
                      ("2016 model ki cars", 2016), ("2015 ki gaadi dikhao", 2015),
                      ("2015 model ka number", 2015)]:
            p = qp.parse(q)
            self.assertEqual(p.year_exact, yr, f"year lost: {q}")
            self.assertIsNone(p.reg_partial, f"year wrongly read as plate: {q}")


@unittest.skipUnless(os.path.exists(XLSX), "IVR_Sheet.xlsx not found")
class TestLanguageCoverageEndToEnd(unittest.TestCase):
    """End-to-end against the CURRENT Excel: question -> right column -> right
    value. Isolated temp DBs; production inventory is only read."""

    @classmethod
    def setUpClass(cls):
        from chat_service import ChatService
        cls.tmp = tempfile.mkdtemp(prefix="langcov_")
        cls.items = [i for i in L.load_inventory(XLSX) if i.is_customer_facing]
        cls.svc = ChatService(XLSX, leads_db=os.path.join(cls.tmp, "l.db"),
                              analytics_db=os.path.join(cls.tmp, "a.db"),
                              unknown_db=os.path.join(cls.tmp, "u.db"))
        # a deterministic priced car to ask about
        cls.car = next(i for i in cls.items
                       if i.price_lakh and i.registration_no)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.svc.close()
        except Exception:
            pass
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _price_tokens(self, it):
        return [f"{it.price_lakh:g}", f"{it.price_lakh:.2f}"]

    def test_price_answered_for_every_language_variant(self):
        it = self.car
        want = self._price_tokens(it)
        for i, p in enumerate(ALL_PRICE_PHRASES):
            r = self.svc.handle(f"{it.registration_no} {p}", session_id=f"pv-{i}")
            self.assertTrue(any(w in (r.response or "") for w in want),
                            f"{p!r} -> no price {want} in: {r.response!r}")

    def test_price_answered_as_bare_followup_on_pinned_car(self):
        it = self.car
        want = self._price_tokens(it)
        for i, p in enumerate(ALL_PRICE_PHRASES):
            sid = f"pf-{i}"
            self.svc.handle(f"{it.registration_no} dikhao", session_id=sid)
            r = self.svc.handle(p, session_id=sid)
            self.assertTrue(any(w in (r.response or "") for w in want),
                            f"follow-up {p!r} -> no price {want} in: {r.response!r}")

    def test_every_car_reachable_by_its_last_digits(self):
        """Covers the year-like-plate class: no car in stock may be unreachable
        by the trailing digit group printed on its plate."""
        by_suffix = defaultdict(list)
        for i in self.items:
            t = _trailing_digits(i.registration_no)
            if t:
                by_suffix[t].append(i)
        self.assertTrue(by_suffix, "no registrations in current inventory")
        unreachable = []
        for tg, group in sorted(by_suffix.items()):
            r = self.svc.handle(f"{tg} number wali gaadi dikhao", session_id=f"sfx-{tg}")
            if (r.count or 0) == 0:
                unreachable.append((tg, [g.registration_no for g in group]))
        self.assertEqual(unreachable, [], f"cars unreachable by last digits: {unreachable}")

    def test_comparison_of_two_instock_models_never_claims_unavailable(self):
        """A second model's digits must not zero out the search. Data-driven:
        pair each in-stock digit-named model with another in-stock model."""
        models = sorted({i.model for i in self.items if i.model})
        digit_models = [m for m in models if any(c.isdigit() for c in m)]
        self.assertTrue(digit_models, "expected a digit-named model in stock")
        for m in digit_models:
            other = next(o for o in models if o != m)
            q = f"{m} aur {other} me kaunsi behtar hai?"
            r = self.svc.handle(q, session_id=f"cmp-{m}")
            self.assertNotIn(r.status, ("not_found", "unknown"),
                             f"{q!r} -> {r.status}: both cars are in stock")
            self.assertGreaterEqual(r.count or 0, 1, f"{q!r} returned 0 cars")


if __name__ == "__main__":
    unittest.main(verbosity=2)
