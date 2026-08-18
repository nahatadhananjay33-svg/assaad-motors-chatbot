"""
filter_accuracy_tests.py
========================

"Filters must behave exactly like an Excel filter" — the dealership reported that
searches were returning far fewer cars than the sheet contains ("petrol cars
under 5 lakh" showed a handful when ~15-20 were expected).

Every assertion here computes the EXPECTED set directly from the current Excel
and requires the chatbot to return the same number, so the tests stay honest when
the inventory is swapped. Four defects were behind the under-counting:

1. POOL RESTRICTION (the big one). Any search without a price ceiling was run
   against only the ">= 2 lakh IVR" slice, silently hiding the 47 cheapest cars:
   "petrol cars" returned 56 of 89, "cng cars" 6 of 23, "manual cars" 93 of 131.
   An explicit filter now searches the whole book.

2. SUNROOF NEVER FILTERED. "sunroof cars" parsed as an attribute *question*
   (what sunroof does this car have?) rather than a search, so it matched nothing
   at all — 0 of 2. A plural browse noun ("cars") now marks it as a filter, while
   "is car me sunroof hai?" stays a question about one car.

3. BI-FUEL INVISIBLE. Bi-fuel cars are stored "Petrol+CNG"; exact equality meant
   "cng cars" found 9 of 23. A CNG request now matches combined values. Asking
   for petrol/diesel stays an exact column match, so a CNG-kitted car is not
   handed to someone who asked for a plain petrol one.

4. YEAR-LIKE PLATE SWALLOWED. A plate ending 1938 was suppressed as "a year" by
   a looser pattern than the year parser actually accepts, so it matched neither
   path and the car was unreachable by its number.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

import inventory_loader as L
import query_parser as qp

XLSX = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")


def _lc(v):
    return str(v or "").lower()


def _fuel_is(item, fuel):
    """Ground truth mirroring the product rule: CNG/LPG match bi-fuel values,
    petrol/diesel are exact."""
    v = _lc(item.fuel_norm)
    if fuel in ("cng", "lpg"):
        return fuel in {p.strip() for p in v.replace("/", "+").split("+")}
    return v == fuel


def _has_sunroof(item):
    return bool(item.sunroof_type) and _lc(item.sunroof_type) not in ("none", "nan", "")


@unittest.skipUnless(os.path.exists(XLSX), "IVR_Sheet.xlsx not found")
class TestFilterCountsMatchExcel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from chat_service import ChatService
        cls.tmp = tempfile.mkdtemp(prefix="filtacc_")
        cls.items = [i for i in L.load_inventory(XLSX) if i.is_customer_facing]
        cls.svc = ChatService(XLSX, leads_db=os.path.join(cls.tmp, "l.db"),
                              analytics_db=os.path.join(cls.tmp, "a.db"),
                              unknown_db=os.path.join(cls.tmp, "u.db"))

    @classmethod
    def tearDownClass(cls):
        try:
            cls.svc.close()
        except Exception:
            pass
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _assert_count(self, query, predicate):
        expected = sum(1 for i in self.items if predicate(i))
        self.assertGreater(expected, 0,
                           f"test is vacuous — no car in stock matches {query!r}")
        r = self.svc.handle(query, session_id=None)
        self.assertEqual(r.count or 0, expected,
                         f"{query!r}: bot returned {r.count}, Excel has {expected}")

    # ── single column ──
    def test_fuel(self):
        for q, f in [("petrol cars", "petrol"), ("diesel cars", "diesel"),
                     ("cng cars", "cng")]:
            self._assert_count(q, lambda i, f=f: _fuel_is(i, f))

    def test_transmission(self):
        for q, t in [("automatic cars", "automatic"), ("manual cars", "manual")]:
            self._assert_count(q, lambda i, t=t: _lc(i.transmission_norm) == t)

    def test_sunroof(self):
        self._assert_count("sunroof cars", _has_sunroof)

    def test_seats(self):
        self._assert_count("7 seater cars", lambda i: i.seats == 7)
        self._assert_count("5 seater cars", lambda i: i.seats == 5)

    def test_owners(self):
        self._assert_count("first owner cars", lambda i: i.ownership_count == 1)
        self._assert_count("second owner cars", lambda i: i.ownership_count == 2)

    def test_price_ceiling(self):
        for q, cap in [("cars under 3 lakh", 3.0), ("cars under 10 lakh", 10.0),
                       ("cars under 500000", 5.0)]:
            self._assert_count(q, lambda i, c=cap: i.price_lakh and i.price_lakh <= c)

    # ── chained columns: each filter must narrow the previous set ──
    def test_two_column_chains(self):
        self._assert_count("petrol automatic cars",
                           lambda i: _fuel_is(i, "petrol")
                           and _lc(i.transmission_norm) == "automatic")
        self._assert_count("cng cars under 5 lakh",
                           lambda i: _fuel_is(i, "cng")
                           and i.price_lakh and i.price_lakh <= 5.0)
        self._assert_count("7 seater diesel cars",
                           lambda i: i.seats == 7 and _fuel_is(i, "diesel"))

    def test_three_column_chains(self):
        self._assert_count(
            "petrol automatic cars under 5 lakh",
            lambda i: _fuel_is(i, "petrol")
            and _lc(i.transmission_norm) == "automatic"
            and i.price_lakh and i.price_lakh <= 5.0)
        self._assert_count(
            "diesel manual cars under 5 lakh",
            lambda i: _fuel_is(i, "diesel")
            and _lc(i.transmission_norm) == "manual"
            and i.price_lakh and i.price_lakh <= 5.0)

    # ── no CARD may violate a stated constraint ──
    def test_every_card_satisfies_every_filter(self):
        r = self.svc.handle("petrol automatic cars under 5 lakh", session_id="c1")
        bad = [c.get("registration_no") for c in (r.vehicles or [])
               if _lc(c.get("fuel")) != "petrol"
               or _lc(c.get("transmission")) != "automatic"
               or (c.get("price_lakh") or 0) > 5.0]
        self.assertEqual(bad, [], f"cards violating the filters: {bad}")

    # ── the opening suggestion chips must all return cars ──
    def test_suggestion_chips_all_return_results(self):
        for chip in ["Manual", "Automatic", "Petrol", "Cng cars",
                     "Luxury cars", "Sunroof cars", "7 seater"]:
            r = self.svc.handle(chip, session_id=f"chip-{chip}")
            self.assertGreater(r.count or 0, 0, f"chip {chip!r} returned nothing")


class TestSunroofStaysAQuestionForOneCar(unittest.TestCase):
    def test_singular_phrasing_is_not_a_filter(self):
        import field_intents
        from query_parser import _norm
        attr, filt = field_intents.detect(_norm("is car me sunroof hai"))
        self.assertIn("sunroof_type", attr,
                      "asking about ONE car must stay an attribute question")
        self.assertEqual(filt, {})

    def test_plural_phrasing_is_a_filter(self):
        import field_intents
        from query_parser import _norm
        attr, filt = field_intents.detect(_norm("sunroof cars"))
        self.assertIn("sunroof_type", filt, "'sunroof cars' must be a filter")


class TestYearLikePlateReachable(unittest.TestCase):
    def test_plate_ending_in_a_non_year_number(self):
        # 1938 is not in the year parser's range, so it must stay a plate lookup
        self.assertEqual(qp.parse("1938").reg_partial, "1938")
        self.assertIsNone(qp.parse("1938").year_exact)

    def test_real_years_still_years(self):
        for y in ("2015", "2019", "2012"):
            q = qp.parse(f"{y} model dikhao")
            self.assertEqual(q.year_exact, int(y))
            self.assertIsNone(q.reg_partial)


class TestRareColourVocabulary(unittest.TestCase):
    """Filter-audit regression: rare Excel colours must be recognised and the
    colour loop must match the longest phrase first (so 'red black' -> Red+Black,
    not Red). 'platinum' and 'red+black' (R+B) were previously unrecognised."""

    def test_platinum_recognised(self):
        self.assertEqual(qp.parse("platinum cars").color, "Platinum")

    def test_red_black_beats_bare_red(self):
        self.assertEqual(qp.parse("red black cars").color, "Red+Black")
        self.assertEqual(qp.parse("red and black car").color, "Red+Black")

    def test_plain_colours_unchanged(self):
        self.assertEqual(qp.parse("red cars").color, "Red")
        self.assertEqual(qp.parse("black cars").color, "Black")
        self.assertEqual(qp.parse("navy blue car").color, "Blue")


class TestYearFloorCombinesWithPrice(unittest.TestCase):
    """Filter-audit regression: an explicit year FLOOR must survive alongside a
    price filter. 'under 5 lakh 2018 se upar' used to drop the year silently."""

    def test_year_floor_plus_price(self):
        q = qp.parse("under 5 lakh 2018 se upar cars")
        self.assertEqual(q.price_max, 500000)
        self.assertEqual(q.year_min, 2018)
        q2 = qp.parse("2018 ke baad ki gaadi 4 lakh ke andar")
        self.assertEqual(q2.year_min, 2018)
        self.assertEqual(q2.price_max, 400000)

    def test_bare_exact_year_still_gated_under_price(self):
        # a bare exact year under a price stays unset (price digits never a year)
        q = qp.parse("5 lakh ke andar cars")
        self.assertIsNone(q.year_exact)
        self.assertIsNone(q.year_min)


class TestKmChaliAndPriceBand(unittest.TestCase):
    """Filter-audit regression: 'chali' (driven) km cue, and price BANDS."""

    def test_chali_is_km_not_price(self):
        q = qp.parse("50000 se kam chali")
        self.assertEqual(q.km_max, 50000)
        self.assertIsNone(q.price_max)      # NOT read as ₹50,000
        self.assertIsNone(q.price_min)

    def test_price_band_sets_both_bounds(self):
        for text in ("between 4 and 6 lakh", "4 se 6 lakh", "4 to 6 lakh", "4-6 lakh"):
            q = qp.parse(text)
            self.assertEqual((q.price_min, q.price_max), (400000, 600000), text)

    def test_single_price_still_ceiling(self):
        q = qp.parse("under 5 lakh")
        self.assertEqual(q.price_max, 500000)
        self.assertIsNone(q.price_min)

    def test_k_multiplier_chali(self):
        q = qp.parse("40k se kam chali hui petrol")
        self.assertEqual(q.km_max, 40000)
        self.assertEqual(q.fuel, "Petrol")


class TestDevanagariFilters(unittest.TestCase):
    """Filter-audit regression: Hindi Devanagari filter words."""

    def test_devanagari_transmission(self):
        self.assertEqual(qp.parse("ऑटोमैटिक गाड़ियां").transmission, "Automatic")
        self.assertEqual(qp.parse("मैनुअल गाड़ी").transmission, "Manual")

    def test_devanagari_colours(self):
        self.assertEqual(qp.parse("सफेद गाड़ी").color, "White")
        self.assertEqual(qp.parse("काली गाड़ी").color, "Black")
        self.assertEqual(qp.parse("लाल कार").color, "Red")

    def test_automatic_typo(self):
        self.assertEqual(qp.parse("automatc cars").transmission, "Automatic")


if __name__ == "__main__":
    unittest.main(verbosity=2)
