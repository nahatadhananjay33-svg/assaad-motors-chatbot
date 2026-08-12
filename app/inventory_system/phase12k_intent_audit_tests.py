# -*- coding: utf-8 -*-
"""
Phase 12K — rigorous Vehicle-Details INTENT AUDIT (regression lock).

Every vehicle-detail field must recognise natural buyer phrasings (Hinglish +
Devanagari, alternate word orders, synonyms) and route to the CORRECT field —
never to price, availability, or a neighbouring field. Bare ambiguous words
("engine?", "battery?", "safety?", "features?", "mileage?") must clarify, never
guess. This test encodes the audit that found and fixed finding F9 (engine ->
price) plus the label/collision gaps discovered alongside it.

Data-independent: asserts at the parser/detector level (no reliance on any
specific inventory row), plus the follow-up gating that made F9 leak to price.
"""
import unittest

from query_parser import parse, _norm
import field_intents as fi
from chat_service import _is_price_followup, _is_attr_followup


# (phrase, expected_attr) — expected field must appear in detect()'s
# attr_fields or feature_filters for the phrase.
FIELD_CASES = [
    # engine family (bare "engine" is a clarify, tested separately)
    ("engine cc kitna hai?", "engine_cc"),
    ("engine capacity kya hai?", "engine_cc"),
    ("kitne cc ka engine hai?", "engine_cc"),
    ("kitne cc ki hai?", "engine_cc"),
    ("power kitni hai?", "power_bhp"),
    ("bhp kitna hai?", "power_bhp"),
    ("horsepower kitna hai?", "power_bhp"),
    ("torque kitna hai?", "torque_nm"),
    ("turbo hai kya?", "aspiration"),
    ("kitne gears hai?", "gears"),
    ("gear kitne hai?", "gears"),
    ("gearbox type kya hai?", "transmission_subtype"),
    ("cvt hai kya?", "transmission_subtype"),
    ("4wd hai kya?", "drivetrain"),
    # fuel economy / capacity
    ("mileage kitna hai?", "mileage_arai_kmpl"),
    ("average kitna deti hai?", "mileage_arai_kmpl"),
    ("arai mileage kya hai?", "mileage_arai_kmpl"),
    ("fuel tank kitna bada hai?", "fuel_tank_l"),
    ("petrol tank kitna bada hai?", "fuel_tank_l"),
    ("tank capacity kya hai?", "fuel_tank_l"),
    # dimensions
    ("boot space kitna hai?", "boot_litres"),
    ("dicky kitni badi hai?", "boot_litres"),
    ("ground clearance kitna hai?", "ground_clearance_mm"),
    ("gc kitna hai?", "ground_clearance_mm"),
    ("wheelbase kitna hai?", "wheelbase_mm"),
    ("gaadi kitni lambi hai?", "length_mm"),
    ("kitni chaudi hai?", "width_mm"),
    ("height kitni hai?", "height_mm"),
    ("kitni unchi hai gaadi?", "height_mm"),
    # exterior & lights
    ("sunroof hai kya?", "sunroof_type"),
    ("chhat khulti hai kya?", "sunroof_type"),
    ("panoramic sunroof hai kya?", "sunroof_type"),
    ("moonroof hai kya?", "sunroof_type"),
    ("led headlights hai?", "headlamp_type"),
    ("projector lamps hai kya?", "headlamp_type"),
    ("projector headlamps hai kya?", "headlamp_type"),
    ("drl hai kya?", "drl"),
    ("fog lamps hai kya?", "fog_lamps"),
    ("alloy wheels hai kya?", "wheel_type"),
    ("steel rim hai ya alloy?", "wheel_type"),
    ("wheel size kya hai?", "wheel_size_inch"),
    ("roof rails hai kya?", "roof_rails"),
    ("spoiler hai kya?", "spoiler"),
    # interior & comfort
    ("leather seats hai kya?", "upholstery"),
    ("fabric seats hai ya leather?", "upholstery"),
    ("seat material kya hai?", "upholstery"),
    ("climate control hai kya?", "ac_type"),
    ("auto ac hai kya?", "ac_type"),
    ("rear ac hai kya?", "rear_ac_vents"),
    ("peeche ac vents hai?", "rear_ac_vents"),
    ("power window hai kya?", "power_windows"),
    ("power windows hai kya?", "power_windows"),
    ("seat height adjust hoti hai kya?", "adjustable_seat"),
    ("power seat hai kya?", "adjustable_seat"),
    ("ventilated seats hai kya?", "ventilated_seats"),
    ("cooled seats hai kya?", "ventilated_seats"),
    ("cruise control hai kya?", "cruise_control"),
    ("keyless entry hai kya?", "keyless_entry"),
    ("push button start hai kya?", "push_button_start"),
    ("auto folding mirror hai kya?", "auto_folding_orvm"),
    ("electric mirror fold hote hai?", "auto_folding_orvm"),
    ("rear defogger working hai?", "rear_defogger"),
    ("rear wiper hai kya?", "rear_wiper"),
    ("back wiper hai kya?", "rear_wiper"),
    ("wireless charging hai kya?", "wireless_charging"),
    ("connected car features hai kya?", "connected_car"),
    # infotainment
    ("touchscreen kitne inch ka hai?", "touchscreen_inches"),
    ("android auto hai kya?", "android_auto_carplay"),
    ("apple carplay hai?", "android_auto_carplay"),
    ("kitne speakers hai?", "speakers"),
    ("music system hai kya?", "speakers"),
    ("reverse camera hai kya?", "camera_type"),
    ("back camera hai kya?", "camera_type"),
    ("360 camera hai kya?", "camera_type"),
    ("camera hai kya?", "camera_type"),
    ("steering controls hai kya?", "steering_controls"),
    # safety
    ("kitne airbags hai?", "airbags"),
    ("airbag kitne hai?", "airbags"),
    ("abs hai kya?", "abs_ebd"),
    ("esp hai kya?", "esp"),
    ("hill hold hai kya?", "hill_hold"),
    ("parking sensors hai kya?", "parking_sensors"),
    ("isofix hai kya?", "isofix"),
    ("ncap rating kya hai?", "ncap_rating"),
    ("safety rating kitni hai?", "ncap_rating"),
    # keys & accessories
    ("kitni chabi hai?", "keys_count"),
    ("kitni keys milengi?", "keys_count"),
    ("spare key hai kya?", "spare_key"),
    ("duplicate chabi hai kya?", "spare_key"),
    ("spare tyre hai kya?", "spare_tyre"),
    ("stepney hai kya?", "spare_tyre"),
    ("extra tyre hai kya?", "spare_tyre"),
    ("toolkit hai kya?", "toolkit"),
    ("floor mats hai kya?", "floor_mats"),
    ("kya accessories added hai?", "accessories_added"),
    # documents (extra)
    ("puc valid hai kya?", "puc_valid_till"),
    ("road tax paid hai kya?", "road_tax_status"),
    ("fitness certificate valid hai?", "fitness_valid_till"),
    ("duplicate rc hai kya?", "duplicate_rc"),
    ("private use thi ya taxi?", "usage_type"),
    ("tyre life kitni bachi hai?", "tyre_life_pct"),
    # EV
    ("battery health kitni hai?", "battery_health_pct"),
    ("battery ki health kitni hai?", "battery_health_pct"),
    ("ev range kitna hai?", "real_range_km"),
    ("ek charge mein kitna chalti hai?", "real_range_km"),
    ("battery warranty kitni hai?", "battery_warranty_till"),
    ("charger type kya hai?", "charger_type"),
    ("fast charging support karti hai?", "charger_type"),
    ("charging time kitna hai?", "charging_time"),
    ("charge hone mein kitni der?", "charging_time"),
    ("battery owned hai ya lease?", "battery_owned"),
    ("battery leased hai kya?", "battery_owned"),
    # Devanagari
    ("कितने एयरबैग है?", "airbags"),
    ("सनरूफ है क्या?", "sunroof_type"),
    ("कैमरा है क्या?", "camera_type"),
    ("माइलेज कितना है?", "mileage_arai_kmpl"),
    ("ग्राउंड क्लिअरन्स कितना है?", "ground_clearance_mm"),
]

# Bare ambiguous field words -> must set ambiguous_field (clarify), never price.
AMBIGUOUS_CASES = [
    ("engine kitna hai?", "engine"),
    ("engine?", "engine"),
    ("engine kya hai?", "engine"),
    ("battery kitni hai?", "battery"),
    ("safety kaisi hai?", "safety"),
    ("features kya hai?", "features"),
    ("mileage?", "mileage"),
]

# Explicit price words must still route to price even next to a field word.
PRICE_CASES = [
    "engine price kya hai?", "engine ka daam?", "kitne ka hai?", "rate kya hai?",
]


class TestFieldIntentRouting(unittest.TestCase):
    def test_every_field_phrasing_routes_to_its_field(self):
        for phrase, attr in FIELD_CASES:
            a, f = fi.detect(_norm(phrase))
            hit = set(a) | set(f.keys())
            self.assertIn(attr, hit,
                          f"{phrase!r} -> {sorted(hit)} (expected {attr})")


class TestAmbiguousFields(unittest.TestCase):
    def test_bare_ambiguous_clarifies_not_price(self):
        for phrase, key in AMBIGUOUS_CASES:
            q = parse(phrase)
            self.assertEqual(getattr(q, "ambiguous_field", None), key,
                             f"{phrase!r} should set ambiguous_field={key}")
            self.assertNotIn("price", q.intents,
                             f"{phrase!r} must NOT be a price intent (F9)")

    def test_ambiguous_excluded_from_followup_shortcuts(self):
        # The loose "kitna hai" must not shortcut a bare ambiguous field into the
        # pinned-car price / attr follow-up (this was the end-to-end F9 leak).
        for phrase, _ in AMBIGUOUS_CASES:
            q = parse(phrase)
            self.assertFalse(_is_price_followup(phrase, q),
                             f"{phrase!r} wrongly treated as price follow-up")
            self.assertFalse(_is_attr_followup(phrase, q),
                             f"{phrase!r} wrongly treated as attr follow-up")


class TestExplicitPriceStillWorks(unittest.TestCase):
    def test_explicit_price_words_route_to_price(self):
        for phrase in PRICE_CASES:
            q = parse(phrase)
            self.assertIn("price", q.intents,
                          f"{phrase!r} should keep the price intent")
            self.assertIsNone(getattr(q, "ambiguous_field", None),
                              f"{phrase!r} should not clarify")


if __name__ == "__main__":
    unittest.main()
