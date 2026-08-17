"""
inventory_loader_tests.py
=========================

Unit tests for the inventory loader's normalization, derivation, dirty-data
handling, and sold reconciliation.

Covers the required categories:
  * duplicate vehicles
  * dirty spellings
  * sold vehicles
  * missing values
  * malformed years
  * fuel normalization
  * color normalization

Run:  python inventory_loader_tests.py
"""

import os
import unittest

from inventory_models import (
    FuelType, Transmission, BodyType, ListingStatus, LocationType, ColorConfidence,
)
import inventory_loader as L


# ── helper: build a 17-wide sheet row from keyword column values ──────────────
def make_row(**kw):
    row = [None] * 17
    for key, val in kw.items():
        row[L.COL[key]] = val
    return tuple(row)


AS_OF = "2026-06-10T00:00:00+00:00"


def build(**kw):
    return L.build_item(make_row(**kw), source_sheet="DNJ", as_of=AS_OF)


XLSX = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")


# ─────────────────────────────────────────────────────────────────────────────
class TestFuelNormalization(unittest.TestCase):
    def test_basic_codes(self):
        self.assertEqual(L.normalize_fuel("P"), FuelType.PETROL)
        self.assertEqual(L.normalize_fuel("D"), FuelType.DIESEL)

    def test_cng_family_folds(self):
        self.assertEqual(L.normalize_fuel("C"), FuelType.CNG)
        self.assertEqual(L.normalize_fuel("CR"), FuelType.CNG)        # kit
        self.assertEqual(L.normalize_fuel("PC"), FuelType.PETROL_CNG)
        self.assertEqual(L.normalize_fuel("CP"), FuelType.PETROL_CNG)  # swapped

    def test_special_codes(self):
        self.assertEqual(L.normalize_fuel("SP"), FuelType.PETROL)     # dirty petrol
        self.assertEqual(L.normalize_fuel("PH"), FuelType.HYBRID)
        self.assertEqual(L.normalize_fuel("E"), FuelType.ELECTRIC)

    def test_dirty_and_unknown(self):
        self.assertEqual(L.normalize_fuel(" p "), FuelType.PETROL)    # trim+case
        self.assertEqual(L.normalize_fuel("ZZ"), FuelType.UNKNOWN)
        self.assertEqual(L.normalize_fuel(None), FuelType.UNKNOWN)


class TestColorNormalization(unittest.TestCase):
    def test_white_variants(self):
        for code in ("WHI", "WHIT", "WHITE", " white "):
            c, conf = L.normalize_color(code)
            self.assertEqual(c, "White")
            self.assertEqual(conf, ColorConfidence.HIGH)

    def test_silver_grey_black(self):
        self.assertEqual(L.normalize_color("SIL")[0], "Silver")
        self.assertEqual(L.normalize_color("GRY")[0], "Grey")
        self.assertEqual(L.normalize_color("BLA")[0], "Black")
        self.assertEqual(L.normalize_color("PLAT")[0], "Platinum")

    def test_grey_green_ambiguity(self):
        gre, conf = L.normalize_color("GRE")
        self.assertEqual(gre, "Grey")
        self.assertEqual(conf, ColorConfidence.LOW)        # ambiguous
        gree, conf2 = L.normalize_color("GREE")
        self.assertEqual(gree, "Green")
        self.assertEqual(conf2, ColorConfidence.LOW)

    def test_rep_is_not_a_color(self):
        c, _ = L.normalize_color("REP")
        self.assertIsNone(c)

    def test_blank(self):
        self.assertEqual(L.normalize_color(None), (None, ColorConfidence.HIGH))


class TestMalformedYears(unittest.TestCase):
    def test_plain_year(self):
        self.assertEqual(L.parse_year(2016), 2016)
        self.assertEqual(L.parse_year("2018"), 2018)

    def test_slash_suffix_kept_as_year(self):
        self.assertEqual(L.parse_year("2012/12"), 2012)   # /12 = Dec, year stays
        self.assertEqual(L.parse_year("2010/30"), 2010)   # /30 noise, not a month
        self.assertEqual(L.parse_year("2007/27"), 2007)

    def test_zero_blank_and_garbage(self):
        self.assertIsNone(L.parse_year(0))
        self.assertIsNone(L.parse_year(""))
        self.assertIsNone(L.parse_year(None))
        self.assertIsNone(L.parse_year("abcd"))
        self.assertIsNone(L.parse_year("99"))             # < 4 digits


class TestMissingValues(unittest.TestCase):
    def test_blank_km_is_none_not_zero(self):
        self.assertIsNone(L.parse_km(None))
        self.assertIsNone(L.parse_km(""))
        self.assertIsNone(L.parse_km("SCRAP"))            # note, not mileage
        self.assertIsNone(L.parse_km("SN 1.75"))
        self.assertIsNone(L.parse_km(4))                  # implausibly low -> unknown

    def test_real_km(self):
        self.assertEqual(L.parse_km(45065), 45065)
        self.assertEqual(L.parse_km("161000"), 161000)

    def test_blank_insurance_is_none(self):
        self.assertIsNone(L.normalize_insurance(None))
        self.assertEqual(L.normalize_insurance("DEC"), "DEC")

    def test_item_with_missing_fields(self):
        it = build(make="HYUN", model="CRETA", car_numb="MH01AB1234")
        self.assertEqual(it.fuel_norm, FuelType.UNKNOWN)
        self.assertEqual(it.transmission_norm, Transmission.UNKNOWN)
        self.assertIsNone(it.year_int)
        self.assertIsNone(it.km_driven)
        self.assertFalse(it.price_quotable)


class TestRateAndPriceCodes(unittest.TestCase):
    def test_real_prices(self):
        self.assertEqual(L.parse_rate(689000), (689000, 6.89, True))
        self.assertEqual(L.parse_rate("540000"), (540000, 5.4, True))

    def test_status_codes_never_money(self):
        for code in (4, 33, 44, "DDD", "DDDD"):
            inr, lakh, quot = L.parse_rate(code)
            self.assertIsNone(inr)
            self.assertFalse(quot)

    def test_below_floor_is_not_money(self):
        self.assertEqual(L.parse_rate(4)[2], False)
        self.assertEqual(L.parse_rate(9999)[2], False)

    def test_ivr_eligibility(self):
        it = build(make="TOYO", model="FORTUNER", rate=875000, car_numb="MH04EX5958")
        self.assertTrue(it.is_ivr_eligible)
        cheap = build(make="MARU", model="ALTO", rate=69000, car_numb="MH06AB2640")
        self.assertFalse(cheap.is_ivr_eligible)


class TestDirtySpellings(unittest.TestCase):
    def test_make_trailing_space(self):
        code, full = L.normalize_make("FORD ")
        self.assertEqual(code, "FORD")
        self.assertEqual(full, "Ford")
        self.assertEqual(L.normalize_make("MARU ")[1], "Maruti Suzuki")

    def test_make_misspell(self):
        self.assertEqual(L.normalize_make("HUYN")[1], "Hyundai")
        self.assertEqual(L.normalize_make("HMFC")[1], "Mitsubishi")

    def test_model_aliases(self):
        self.assertEqual(L.normalize_model("BREEZA"), "Brezza")
        self.assertEqual(L.normalize_model("SALTOS"), "Seltos")
        self.assertEqual(L.normalize_model("RARID"), "Rapid")
        self.assertEqual(L.normalize_model("MARAZOO"), "Marazzo")
        self.assertEqual(L.normalize_model("MOBILO"), "Mobilio")
        self.assertEqual(L.normalize_model("FIESTS"), "Fiesta")

    def test_model_spacing(self):
        self.assertEqual(L.normalize_model("I 20"), "i20")
        self.assertEqual(L.normalize_model("I20"), "i20")
        self.assertEqual(L.normalize_model("WAGON R"), "WagonR")
        self.assertEqual(L.normalize_model("I 20 ELITE"), "i20 Elite")  # stays distinct

    def test_model_fuzzy_fallback(self):
        # a near-miss not in the alias table folds to the closest known model
        self.assertEqual(L.normalize_model("CRETAA"), "Creta")


class TestLocationClassification(unittest.TestCase):
    def test_slot(self):
        code, typ, viewable = L.classify_location("Y5")
        self.assertEqual(typ, LocationType.SLOT)
        self.assertTrue(viewable)

    def test_custody_not_viewable(self):
        for c in ("POLI", "ILL", "NGP", "REP"):
            _, typ, viewable = L.classify_location(c)
            self.assertEqual(typ, LocationType.CUSTODY)
            self.assertFalse(viewable)

    def test_custody_viewable_partner(self):
        _, typ, viewable = L.classify_location("IMM")
        self.assertEqual(typ, LocationType.CUSTODY)
        self.assertTrue(viewable)


class TestPlaceholderRows(unittest.TestCase):
    def test_blank_model_is_placeholder(self):
        it = build(make="MARU", car_numb="MH01ZZ0000", color="REP", rate=44)
        self.assertTrue(it.is_placeholder)

    def test_cust_make_is_placeholder(self):
        it = build(make="CUST", model="", car_numb="MH14EB2745")
        self.assertTrue(it.is_placeholder)

    def test_missing_registration_is_placeholder(self):
        it = build(make="MARU", model="ALTO", rate=200000)  # no car_numb
        self.assertTrue(it.is_placeholder)
        self.assertTrue(it.registration_no.startswith("NOREG-"))


class TestBodyTypeAndSeats(unittest.TestCase):
    # Body type is still derived from the model (needed for SUV / MUV / Hatchback
    # category filters). SEATS are NO LONGER inferred — they come only from the
    # "Seats" Excel column, so a row built without that column has seats == None.
    # The column-read + seat-filter path is covered end-to-end in
    # filter_accuracy_tests (7 seater == Seats 7 against the live sheet).
    def test_suv_body_type_seats_not_inferred(self):
        it = build(make="TOYO", model="FORTUNER", car_numb="MH04EX5958")
        self.assertEqual(it.body_type, BodyType.SUV)
        self.assertIsNone(it.seats)          # no inference — column is the source

    def test_muv_body_type_seats_not_inferred(self):
        it = build(make="TOYO", model="INNOVA", car_numb="MH04ET0678")
        self.assertEqual(it.body_type, BodyType.MUV)
        self.assertIsNone(it.seats)

    def test_hatchback_body_type_seats_not_inferred(self):
        it = build(make="MARU", model="SWIFT", car_numb="MH01PA7577")
        self.assertEqual(it.body_type, BodyType.HATCHBACK)
        self.assertIsNone(it.seats)


class TestDuplicateVehicles(unittest.TestCase):
    def test_same_model_multiple_units_kept_distinct(self):
        rows = [
            make_row(make="TOYO", model="INNOVA", year=2014, rate=370000, car_numb="MH04ET0678"),
            make_row(make="TOYO", model="INNOVA", year=2016, rate=795000, car_numb="MH03AF2646"),
        ]
        items = [L.build_item(r, source_sheet="DNJ", as_of=AS_OF) for r in rows]
        regs = {i.registration_no for i in items}
        self.assertEqual(len(regs), 2)  # distinct units, distinct keys

    def test_dedup_keeps_real_over_placeholder_on_key_collision(self):
        # two rows share a registration; the real one must win
        good = L.build_item(
            make_row(make="HYUN", model="CRETA", rate=540000, car_numb="MH05CV5732"),
            source_sheet="DNJ", as_of=AS_OF)
        placeholder = L.build_item(
            make_row(make="CUST", model="", car_numb="MH05CV5732"),
            source_sheet="DNJ", as_of=AS_OF)
        by_reg = {}
        for it in (placeholder, good):
            ex = by_reg.get(it.registration_no)
            if ex is None or (ex.is_placeholder and not it.is_placeholder):
                by_reg[it.registration_no] = it
        self.assertFalse(by_reg["MH05CV5732"].is_placeholder)


class TestSoldReconciliation(unittest.TestCase):
    def test_sold_via_registration_in_sold_set(self):
        it = build(make="TOYO", model="INNOVA", rate=370000, car_numb="MH12KE0019")
        self.assertEqual(it.listing_status, ListingStatus.AVAILABLE)
        n = L.reconcile_sold([it], {"MH12KE0019"})
        self.assertEqual(n, 1)
        self.assertEqual(it.listing_status, ListingStatus.SOLD)
        self.assertFalse(it.customer_viewable)
        self.assertFalse(it.is_customer_facing)

    def test_sold_via_ddd_rate(self):
        it = build(make="TOYO", model="INNOVA", rate="DDD", car_numb="MH12KE0019")
        L.reconcile_sold([it], set())
        self.assertEqual(it.listing_status, ListingStatus.SOLD)

    def test_available_when_not_sold(self):
        it = build(make="HYUN", model="CRETA", rate=540000, car_numb="MH05CV5732")
        L.reconcile_sold([it], {"MH99XX9999"})
        self.assertTrue(it.is_customer_facing)


# ── integration over the real workbook ───────────────────────────────────────
@unittest.skipUnless(os.path.exists(XLSX), "IVR_Sheet.xlsx not found")
class TestRealWorkbookIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = L.load_inventory(XLSX, as_of=AS_OF)

    def test_rows_loaded(self):
        self.assertGreater(len(self.items), 0)

    def test_keys_unique(self):
        regs = [i.registration_no for i in self.items]
        self.assertEqual(len(regs), len(set(regs)))  # no duplicate keys (R11)

    def test_no_status_code_quoted_as_price(self):
        for it in self.items:
            if not it.price_quotable:
                self.assertIsNone(it.price_inr)

    def test_no_zero_year(self):
        for it in self.items:
            self.assertTrue(it.year_int is None or it.year_int >= 1990)

    def test_sold_never_customer_facing(self):
        cf = L.customer_facing(self.items)
        for it in cf:
            self.assertNotEqual(it.listing_status, ListingStatus.SOLD)

    def test_all_fuel_values_canonical(self):
        for it in self.items:
            self.assertIn(it.fuel_norm, FuelType.ALL)


if __name__ == "__main__":
    unittest.main(verbosity=2)
