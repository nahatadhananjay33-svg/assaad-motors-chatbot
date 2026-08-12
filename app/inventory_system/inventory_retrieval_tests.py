"""
inventory_retrieval_tests.py
============================

End-to-end tests for the Phase-2B retrieval layer (parser -> engine -> formatter)
running entirely on inventory records — NO LLM / vector DB / embeddings / RAG.

Coverage maps to the requested query types and to the absolute-zero safety bars
in retrieval_acceptance_criteria.md (§2):

  Query types : availability, price, budget, fuel, transmission, ownership,
                colour, combination filters
  Safety      : no SOLD offered, no fake price, no phantom, no internal-field
                leak (G-EXPOSE), never a silent pick on >1 (G-MULTI), no
                hallucinated km/year, off-sheet routed not invented

Run:  python inventory_retrieval_tests.py
"""

import os
import unittest

from inventory_models import (
    InventoryItem, ListingStatus, FuelType, Transmission, BodyType,
)
import inventory_loader as L
from query_parser import parse, Query
from retrieval_engine import RetrievalEngine, CATEGORY_BODY_TYPES
from response_formatter import format_response, PUBLIC_LOCATION

XLSX = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")
AS_OF = "2026-06-10T00:00:00+00:00"


def load_engine():
    return RetrievalEngine(L.load_inventory(XLSX, as_of=AS_OF))


def answer(engine, utterance):
    return format_response(engine.search(parse(utterance)))


@unittest.skipUnless(os.path.exists(XLSX), "IVR_Sheet.xlsx not found")
class RetrievalTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = load_engine()


# ─────────────────────────────────────────────────────────────────────────────
# 1. PARSER — filter extraction (M1)
# ─────────────────────────────────────────────────────────────────────────────
class TestQueryParser(unittest.TestCase):
    def test_availability_intent(self):
        q = parse("Creta available hai?")
        self.assertEqual(q.model, "Creta")
        self.assertIn("availability", q.intents)

    def test_price_intent(self):
        q = parse("Fortuner kitne ki hai?")
        self.assertEqual(q.model, "Fortuner")
        self.assertIn("price", q.intents)

    def test_budget_ceiling(self):
        q = parse("SUV under 10 lakh")
        self.assertEqual(q.category, "SUV")
        self.assertEqual(q.price_max, 1000000)

    def test_budget_hinglish(self):
        q = parse("sedan 5 lakh tak")
        self.assertEqual(q.category, "Sedan")
        self.assertEqual(q.price_max, 500000)

    def test_fuel_folding(self):
        self.assertEqual(parse("diesel cars").fuel, FuelType.DIESEL)
        self.assertEqual(parse("CNG wali koi hai?").fuel, FuelType.CNG)
        self.assertEqual(parse("petrol gaadi").fuel, FuelType.PETROL)

    def test_transmission(self):
        self.assertEqual(parse("automatic cars").transmission, Transmission.AUTOMATIC)
        self.assertEqual(parse("manual gaadi").transmission, Transmission.MANUAL)

    def test_ownership(self):
        self.assertEqual(parse("first owner cars").ownership_exact, 1)
        self.assertEqual(parse("second owner").ownership_exact, 2)
        self.assertEqual(parse("kam owner wali").ownership_max, 2)

    def test_color(self):
        self.assertEqual(parse("white cars").color, "White")
        self.assertEqual(parse("kaali Creta").color, "Black")

    def test_combination(self):
        q = parse("white automatic Honda")
        self.assertEqual(q.color, "White")
        self.assertEqual(q.transmission, Transmission.AUTOMATIC)
        self.assertEqual(q.make, "HOND")

    def test_dirty_spelling_alias(self):
        self.assertEqual(parse("Seltos hai kya?").model, "Seltos")
        self.assertEqual(parse("breeza available?").model, "Brezza")

    def test_reel_words_stripped(self):
        q = parse("reel wali Fortuner hai kya?")
        self.assertEqual(q.model, "Fortuner")
        self.assertIn("reel wali", q.reel_stripped)

    def test_vague_reel_needs_clarify(self):
        q = parse("jo reel mein thi woh gaadi")
        self.assertTrue(q.clarify_needed)

    def test_offsheet_detection(self):
        # Phase 12D: sunroof is now an answerable field, not off_sheet.
        _q = parse("Creta mein sunroof hai?")
        self.assertFalse(_q.off_sheet)
        self.assertIn("sunroof_type", _q.attr_fields)
        # genuine off-sheet topics still route off-sheet
        self.assertTrue(parse("finance ho jayega?").off_sheet)
        self.assertTrue(parse("exchange karoge?").off_sheet)


# ─────────────────────────────────────────────────────────────────────────────
# 2. AVAILABILITY
# ─────────────────────────────────────────────────────────────────────────────
class TestAvailability(RetrievalTestBase):
    def test_creta_available(self):
        r = self.engine.search(parse("Creta available?"))
        self.assertTrue(r.found)
        self.assertTrue(all(m.model == "Creta" for m in r.matches))

    def test_swift_not_in_stock_offers_segment(self):
        """No Swift exists -> correct result is a hatchback alternative, never a fake Swift."""
        r = self.engine.search(parse("Swift available hai?"))
        self.assertFalse(any(m.model == "Swift" for m in r.matches))  # never fabricated
        self.assertTrue(r.alternative_segment)
        self.assertTrue(all(m.body_type == BodyType.HATCHBACK for m in r.matches))

    def test_named_model_searches_full_catalogue(self):
        # a sub-2L named model still resolves (G-SOURCE-FALLBACK), not filtered out
        r = self.engine.search(parse("Spark available?"))
        self.assertTrue(any(m.model == "Spark" for m in r.matches))


# ─────────────────────────────────────────────────────────────────────────────
# 3. PRICE
# ─────────────────────────────────────────────────────────────────────────────
class TestPrice(RetrievalTestBase):
    def test_named_price_quoted_in_lakh(self):
        # a single-instance, quotable-price model (named-model price -> lakh)
        a = answer(self.engine, "Astor price?")
        self.assertEqual(a.status, "found")
        self.assertIn("lakh", a.spoken)
        self.assertIn("G-PRICE-UNIT", a.guardrails_fired)

    def test_cars_under_8_lakh(self):
        r = self.engine.search(parse("cars under 8 lakh"))
        self.assertTrue(r.found)
        for m in r.matches:
            self.assertTrue(m.price_quotable)
            self.assertLessEqual(m.price_inr, 800000)


# ─────────────────────────────────────────────────────────────────────────────
# 4. BUDGET (category + ceiling)
# ─────────────────────────────────────────────────────────────────────────────
class TestBudget(RetrievalTestBase):
    def test_suv_under_10_lakh(self):
        r = self.engine.search(parse("SUV under 10 lakh"))
        for m in r.matches:
            self.assertIn(m.body_type, CATEGORY_BODY_TYPES["SUV"])
            self.assertLessEqual(m.price_inr, 1000000)

    def test_sedan_under_5_lakh(self):
        r = self.engine.search(parse("Sedan under 5 lakh"))
        for m in r.matches:
            self.assertEqual(m.body_type, BodyType.SEDAN)
            self.assertLessEqual(m.price_inr, 500000)


# ─────────────────────────────────────────────────────────────────────────────
# 5. FUEL
# ─────────────────────────────────────────────────────────────────────────────
class TestFuel(RetrievalTestBase):
    def test_diesel(self):
        r = self.engine.search(parse("diesel cars"))
        self.assertTrue(r.found)
        self.assertTrue(all(m.fuel_norm == FuelType.DIESEL for m in r.matches))

    def test_petrol(self):
        r = self.engine.search(parse("petrol cars"))
        self.assertTrue(all(m.fuel_norm == FuelType.PETROL for m in r.matches))

    def test_cng_family(self):
        r = self.engine.search(parse("CNG cars"))
        self.assertTrue(r.found)
        self.assertTrue(all(m.fuel_norm == FuelType.CNG for m in r.matches))


# ─────────────────────────────────────────────────────────────────────────────
# 6. TRANSMISSION
# ─────────────────────────────────────────────────────────────────────────────
class TestTransmission(RetrievalTestBase):
    def test_automatic(self):
        r = self.engine.search(parse("automatic cars"))
        self.assertTrue(all(m.transmission_norm == Transmission.AUTOMATIC for m in r.matches))

    def test_manual(self):
        r = self.engine.search(parse("manual cars"))
        self.assertTrue(all(m.transmission_norm == Transmission.MANUAL for m in r.matches))


# ─────────────────────────────────────────────────────────────────────────────
# 7. OWNERSHIP
# ─────────────────────────────────────────────────────────────────────────────
class TestOwnership(RetrievalTestBase):
    def test_first_owner(self):
        r = self.engine.search(parse("first owner cars"))
        self.assertTrue(r.found)
        self.assertTrue(all(m.ownership_count == 1 for m in r.matches))

    def test_second_owner(self):
        r = self.engine.search(parse("second owner cars"))
        self.assertTrue(all(m.ownership_count == 2 for m in r.matches))


# ─────────────────────────────────────────────────────────────────────────────
# 8. COLOUR
# ─────────────────────────────────────────────────────────────────────────────
class TestColor(RetrievalTestBase):
    def test_white(self):
        r = self.engine.search(parse("white cars"))
        self.assertTrue(r.found)
        self.assertTrue(all(m.color_norm == "White" for m in r.matches))

    def test_black(self):
        r = self.engine.search(parse("black cars"))
        self.assertTrue(all(m.color_norm == "Black" for m in r.matches))


# ─────────────────────────────────────────────────────────────────────────────
# 9. COMBINATION FILTERS
# ─────────────────────────────────────────────────────────────────────────────
class TestCombination(RetrievalTestBase):
    def test_diesel_suv_under_8_lakh(self):
        r = self.engine.search(parse("Diesel SUV under 8 lakh"))
        self.assertTrue(r.found)
        for m in r.matches:
            self.assertEqual(m.fuel_norm, FuelType.DIESEL)
            self.assertIn(m.body_type, CATEGORY_BODY_TYPES["SUV"])
            self.assertLessEqual(m.price_inr, 800000)
        # every match already verified above as a diesel SUV within budget
        # (which cars qualify is data-driven, so no per-model exclusion here)

    def test_white_automatic_honda_relaxes_not_fabricates(self):
        # no white automatic Honda exists -> engine relaxes & announces, no fake row
        r = self.engine.search(parse("white automatic Honda"))
        self.assertTrue(r.found)
        self.assertTrue(all(m.make == "HOND" for m in r.matches))   # hard filter kept
        self.assertTrue(len(r.relaxed) > 0)                          # something relaxed


# ─────────────────────────────────────────────────────────────────────────────
# 10. SAFETY / GUARDRAILS (acceptance criteria §2 — absolute zero)
# ─────────────────────────────────────────────────────────────────────────────
SWEEP = [
    "Creta available?", "Swift available hai?", "Fortuner price?",
    "cars under 8 lakh", "SUV under 10 lakh", "Sedan under 5 lakh",
    "diesel cars", "petrol cars", "CNG cars", "automatic cars", "manual cars",
    "first owner cars", "second owner cars", "white cars", "black cars",
    "white automatic Honda", "Diesel SUV under 8 lakh",
    "Creta mein sunroof hai?", "finance milega?", "jo reel mein thi woh gaadi",
]


class TestSafety(RetrievalTestBase):
    def test_no_internal_field_ever_leaked(self):
        for utt in SWEEP:
            a = answer(self.engine, utt)
            self.assertFalse(a.contains_forbidden, f"leak in: {utt} -> {a.spoken}")

    def test_positive_answers_carry_visit_pivot_and_public_location(self):
        for utt in SWEEP:
            a = answer(self.engine, utt)
            if a.status in ("found", "multi", "segment"):
                self.assertTrue(a.visit_pivot, utt)
                self.assertIn(PUBLIC_LOCATION, a.spoken, utt)

    def test_never_silent_single_pick_when_multiple(self):
        # G-MULTI: a multi result must be flagged multi (count+clarifier), not 1 silent pick
        a = answer(self.engine, "first owner cars")
        self.assertEqual(a.status, "multi")
        self.assertIn("G-MULTI", a.guardrails_fired)

    def test_offsheet_never_fabricates(self):
        # Phase 12D: sunroof moved to answerable fields; use a genuine off-sheet
        # topic (finance) to assert off-sheet still never fabricates.
        a = answer(self.engine, "finance milega?")
        self.assertEqual(a.status, "off_sheet")
        self.assertIn("G-OFFSHEET", a.guardrails_fired)

    def test_sold_car_never_offered(self):
        # inject a SOLD Creta alongside the real inventory; it must never surface
        items = L.load_inventory(XLSX, as_of=AS_OF)
        sold = InventoryItem(registration_no="MH00SOLD0001", model="Creta",
                             make="HYUN", make_full="Hyundai", year_int=2020,
                             price_inr=900000, price_lakh=9.0, price_quotable=True,
                             body_type=BodyType.COMPACT_SUV, is_ivr_eligible=True,
                             listing_status=ListingStatus.SOLD, customer_viewable=False)
        eng = RetrievalEngine(items + [sold])
        r = eng.search(parse("Creta available?"))
        self.assertFalse(any(m.registration_no == "MH00SOLD0001" for m in r.matches))
        for m in r.matches:
            self.assertNotEqual(m.listing_status, ListingStatus.SOLD)

    def test_price_code_row_never_quoted_as_money(self):
        # inject a price-coded (non-quotable) car and ask its price
        items = L.load_inventory(XLSX, as_of=AS_OF)
        coded = InventoryItem(registration_no="MH00CODE0002", model="Endeavour",
                              make="FORD", make_full="Ford", year_int=2018,
                              price_inr=None, price_lakh=None, price_quotable=False,
                              body_type=BodyType.SUV, is_ivr_eligible=True)
        eng = RetrievalEngine(items + [coded])
        a = format_response(eng.search(parse("Endeavour price?")))
        self.assertEqual(a.status, "found")
        self.assertIn("G-PRICE", a.guardrails_fired)
        # no rupee/lakh number emitted for a coded price
        self.assertNotIn("lakh", a.spoken.split("confirm")[0])  # no number before the hedge

    def test_blank_year_and_km_not_stated(self):
        items = L.load_inventory(XLSX, as_of=AS_OF)
        # use a model NOT otherwise in stock so the search resolves to just this
        # blank-year/blank-km car (isolating the G-YEAR / G-KM withholding).
        blank = InventoryItem(registration_no="MH00BLNK0003", model="Endeavour",
                              make="FORD", make_full="Ford", year_int=None,
                              km_driven=None, price_inr=700000, price_lakh=7.0,
                              price_quotable=True, body_type=BodyType.SUV,
                              is_ivr_eligible=True)
        eng = RetrievalEngine(items + [blank])
        a = format_response(eng.search(parse("Endeavour available?")))
        self.assertIn("G-YEAR", a.guardrails_fired)
        self.assertIn("G-KM", a.guardrails_fired)


# ─────────────────────────────────────────────────────────────────────────────
# 11. TARGET — "Swift available hai?" returns the correct inventory result
# ─────────────────────────────────────────────────────────────────────────────
class TestPrimaryTarget(RetrievalTestBase):
    def test_swift_available_hai(self):
        a = answer(self.engine, "Swift available hai?")
        # correct, guardrail-safe result: no fabricated Swift, hatchback alternative,
        # visit pivot present, no internal leak
        self.assertEqual(a.status, "segment")
        self.assertFalse(a.contains_forbidden)
        self.assertTrue(a.visit_pivot)
        self.assertIn(PUBLIC_LOCATION, a.spoken)
        self.assertNotIn("Swift", [v["model"] for v in a.shown])


if __name__ == "__main__":
    unittest.main(verbosity=2)
