"""
model_specs.py
==============

Phase 12B — deterministic Model Specifications Library.

Maps  make → model → (optional variant) → (optional year-range)  to the
STANDARD factory specifications & features of a vehicle, so the same facts do not
have to be re-typed for every car of the same model. NO LLM, NO network, NO
guessing — pure reference data.

Two hard rules keep it honest:

  1. **Owner data always wins.** `apply_specs()` fills a field ONLY when the car's
     own value is still `None` (i.e. the dealership hasn't entered it). Anything
     the owner typed in Excel / the panel is never overwritten.

  2. **No fabrication.** Only KNOWN models return specs. An unknown make/model
     returns `{}` → the field stays `None` → the chatbot says "Data not available".
     Nothing is ever invented from a segment default.

Only *factory-standard* fields are auto-filled (`SPEC_FIELDS`). Dealership-specific
facts (price, km, owners, insurance, RC, condition, service, accident, media,
remarks, keys, EV battery health, road tax…) are NEVER touched here — they are
entered per car.

The seed data below is generation-typical and intended to be extended/verified by
the dealership over time. Adding a model is a one-line dict entry.
"""

from __future__ import annotations

import unicodedata
from typing import Any, Dict, List, Optional

# ── Fields this library is allowed to auto-fill (factory-standard only) ──
SPEC_FIELDS: List[str] = [
    # engine
    "engine_cc", "power_bhp", "torque_nm", "aspiration",
    # transmission detail
    "transmission_subtype", "gears", "drivetrain",
    # fuel & economy
    "mileage_arai_kmpl", "fuel_tank_l",
    # dimensions
    "length_mm", "width_mm", "height_mm", "wheelbase_mm", "boot_litres",
    "ground_clearance_mm",
    # exterior & lights
    "headlamp_type", "drl", "fog_lamps", "wheel_type", "wheel_size_inch",
    "sunroof_type", "roof_rails", "spoiler",
    # interior & comfort
    "upholstery", "ac_type", "rear_ac_vents", "power_windows", "adjustable_seat",
    # convenience
    "push_button_start", "keyless_entry", "cruise_control", "auto_folding_orvm",
    "rear_defogger", "rear_wiper", "wireless_charging", "ventilated_seats",
    "connected_car",
    # infotainment
    "touchscreen_inches", "android_auto_carplay", "speakers", "camera_type",
    "steering_controls",
    # safety
    "airbags", "abs_ebd", "esp", "hill_hold", "parking_sensors", "isofix",
    "ncap_rating",
]

# Fields the library must NEVER fill (dealership-entered per car) — documented for
# clarity / used by the migration audit.
DEALERSHIP_FIELDS: List[str] = [
    "price_inr", "price_lakh", "price_quotable", "km_driven", "ownership_count",
    "insurance_type", "insurance_expiry", "zero_dep", "insurance_claim_history",
    "rc_status", "hypothecation_bank", "loan_closed", "noc_available",
    "finance_eligible", "accident_free", "flood_damage", "repainted",
    "body_condition", "engine_condition", "interior_condition", "tyre_condition",
    "brake_condition", "clutch_condition", "battery_condition",
    "service_history_available", "last_service_date", "service_center_type",
    "warranty_available", "warranty_expiry", "warranty_provider",
    "reason_for_sale", "best_features", "known_issues",
    "puc_valid_till", "road_tax_status", "fitness_valid_till", "duplicate_rc",
    "keys_count", "usage_type", "tyre_life_pct", "battery_replaced_on",
    "spare_key", "spare_tyre", "toolkit", "floor_mats", "accessories_added",
    "battery_health_pct", "real_range_km", "battery_warranty_till",
    "charger_type", "charging_time", "battery_owned",
]


def _norm_key(s: Optional[str]) -> str:
    """Lowercase + fold diacritics so 'Škoda' matches the 'skoda' key. Deterministic."""
    t = (s or "").strip().lower()
    return "".join(c for c in unicodedata.normalize("NFKD", t)
                   if not unicodedata.combining(c))


# ═════════════════════════════════════════════════════════════════════════════
# SEED DATA — make → model → base specs (+ optional variant / year overrides)
#   {"base": {...}, "variants": {"<variant lower>": {...}}, "years": [(lo,hi,{...})]}
# Values are generation-typical. Extend/verify per dealership records.
# Booleans use True/False; unknown fields are simply omitted (never guessed).
# ═════════════════════════════════════════════════════════════════════════════
SPECS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "hyundai": {
        "creta": {"base": {
            "engine_cc": 1497, "fuel_tank_l": 50, "mileage_arai_kmpl": 16.8,
            "length_mm": 4300, "width_mm": 1790, "height_mm": 1635,
            "wheelbase_mm": 2610, "boot_litres": 433, "ground_clearance_mm": 190,
            "headlamp_type": "Projector", "wheel_type": "Alloy",
            "ac_type": "Auto-climate", "rear_ac_vents": True, "power_windows": "All 4",
            "abs_ebd": True, "airbags": 6, "isofix": True, "drivetrain": "FWD"}},
        "grand i10": {"base": {
            "engine_cc": 1197, "fuel_tank_l": 43, "mileage_arai_kmpl": 18.9,
            "length_mm": 3805, "width_mm": 1660, "height_mm": 1520,
            "wheelbase_mm": 2450, "boot_litres": 256, "ground_clearance_mm": 165,
            "wheel_type": "Alloy", "power_windows": "All 4", "abs_ebd": True,
            "airbags": 2, "drivetrain": "FWD"}},
        "xcent": {"base": {
            "engine_cc": 1197, "fuel_tank_l": 43, "mileage_arai_kmpl": 19.1,
            "length_mm": 3995, "width_mm": 1660, "height_mm": 1520,
            "wheelbase_mm": 2450, "boot_litres": 407, "ground_clearance_mm": 165,
            "abs_ebd": True, "airbags": 2, "drivetrain": "FWD"}},
    },
    "maruti suzuki": {
        "swift": {"base": {
            "engine_cc": 1197, "fuel_tank_l": 37, "mileage_arai_kmpl": 22.0,
            "length_mm": 3845, "width_mm": 1735, "height_mm": 1530,
            "wheelbase_mm": 2450, "boot_litres": 268, "ground_clearance_mm": 163,
            "power_windows": "All 4", "abs_ebd": True, "airbags": 2, "drivetrain": "FWD"}},
        "dzire": {"base": {
            "engine_cc": 1197, "fuel_tank_l": 37, "mileage_arai_kmpl": 23.2,
            "length_mm": 3995, "width_mm": 1735, "height_mm": 1515,
            "wheelbase_mm": 2450, "boot_litres": 378, "ground_clearance_mm": 163,
            "abs_ebd": True, "airbags": 2, "drivetrain": "FWD"}},
        "wagonr": {"base": {
            "engine_cc": 1197, "fuel_tank_l": 32, "mileage_arai_kmpl": 21.8,
            "length_mm": 3655, "width_mm": 1620, "height_mm": 1675,
            "wheelbase_mm": 2435, "boot_litres": 341, "ground_clearance_mm": 165,
            "abs_ebd": True, "airbags": 2, "drivetrain": "FWD"}},
        "alto": {"base": {
            "engine_cc": 796, "fuel_tank_l": 35, "mileage_arai_kmpl": 22.05,
            "length_mm": 3445, "width_mm": 1490, "height_mm": 1475,
            "wheelbase_mm": 2360, "boot_litres": 177, "ground_clearance_mm": 160,
            "airbags": 2, "drivetrain": "FWD"}},
        "ertiga": {"base": {
            "engine_cc": 1462, "fuel_tank_l": 45, "mileage_arai_kmpl": 20.5,
            "length_mm": 4395, "width_mm": 1735, "height_mm": 1690,
            "wheelbase_mm": 2740, "boot_litres": 209, "ground_clearance_mm": 185,
            "rear_ac_vents": True, "abs_ebd": True, "airbags": 2, "drivetrain": "FWD"}},
        "ciaz": {"base": {
            "engine_cc": 1462, "fuel_tank_l": 43, "mileage_arai_kmpl": 20.6,
            "length_mm": 4490, "width_mm": 1730, "height_mm": 1485,
            "wheelbase_mm": 2650, "boot_litres": 510, "ground_clearance_mm": 170,
            "ac_type": "Auto-climate", "abs_ebd": True, "airbags": 2, "drivetrain": "FWD"}},
        "sx4": {"base": {
            "engine_cc": 1586, "fuel_tank_l": 50, "length_mm": 4490, "width_mm": 1735,
            "height_mm": 1595, "wheelbase_mm": 2500, "boot_litres": 515,
            "abs_ebd": True, "airbags": 2, "drivetrain": "FWD"}},
        "eeco": {"base": {
            "engine_cc": 1196, "fuel_tank_l": 40, "length_mm": 3675, "width_mm": 1475,
            "height_mm": 1825, "wheelbase_mm": 2350, "drivetrain": "RWD"}},
    },
    "honda": {
        "city": {"base": {
            "engine_cc": 1497, "fuel_tank_l": 40, "mileage_arai_kmpl": 17.8,
            "length_mm": 4549, "width_mm": 1748, "height_mm": 1489,
            "wheelbase_mm": 2600, "boot_litres": 506, "ground_clearance_mm": 165,
            "headlamp_type": "LED", "wheel_type": "Alloy", "ac_type": "Auto-climate",
            "abs_ebd": True, "airbags": 6, "drivetrain": "FWD"}},
        "mobilio": {"base": {
            "engine_cc": 1498, "fuel_tank_l": 42, "mileage_arai_kmpl": 24.2,
            "length_mm": 4386, "width_mm": 1683, "height_mm": 1603,
            "wheelbase_mm": 2652, "ground_clearance_mm": 189, "rear_ac_vents": True,
            "abs_ebd": True, "airbags": 2, "drivetrain": "FWD"}},
        "wrv": {"base": {
            "engine_cc": 1199, "fuel_tank_l": 40, "mileage_arai_kmpl": 17.5,
            "length_mm": 3999, "width_mm": 1734, "height_mm": 1601,
            "wheelbase_mm": 2555, "boot_litres": 363, "ground_clearance_mm": 188,
            "sunroof_type": "Single", "abs_ebd": True, "airbags": 2, "drivetrain": "FWD"}},
    },
    "tata": {
        "nexon": {"base": {
            "engine_cc": 1199, "fuel_tank_l": 44, "mileage_arai_kmpl": 17.0,
            "length_mm": 3993, "width_mm": 1811, "height_mm": 1606,
            "wheelbase_mm": 2498, "boot_litres": 350, "ground_clearance_mm": 209,
            "headlamp_type": "Projector", "wheel_type": "Alloy", "abs_ebd": True,
            "airbags": 2, "ncap_rating": 5, "drivetrain": "FWD"}},
        "tigor": {"base": {
            "engine_cc": 1199, "fuel_tank_l": 35, "mileage_arai_kmpl": 20.3,
            "length_mm": 3993, "width_mm": 1677, "height_mm": 1532,
            "wheelbase_mm": 2450, "boot_litres": 419, "ground_clearance_mm": 170,
            "abs_ebd": True, "airbags": 2, "drivetrain": "FWD"}},
    },
    "volkswagen": {
        "polo": {"base": {
            "engine_cc": 999, "fuel_tank_l": 45, "mileage_arai_kmpl": 18.2,
            "length_mm": 3971, "width_mm": 1682, "height_mm": 1469,
            "wheelbase_mm": 2469, "boot_litres": 280, "ground_clearance_mm": 168,
            "abs_ebd": True, "airbags": 2, "drivetrain": "FWD"}},
        "vento": {"base": {
            "engine_cc": 999, "fuel_tank_l": 55, "mileage_arai_kmpl": 18.1,
            "length_mm": 4390, "width_mm": 1699, "height_mm": 1467,
            "wheelbase_mm": 2552, "boot_litres": 494, "ground_clearance_mm": 168,
            "ac_type": "Auto-climate", "abs_ebd": True, "airbags": 2, "drivetrain": "FWD"}},
    },
    "skoda": {
        "rapid": {"base": {
            "engine_cc": 999, "fuel_tank_l": 55, "mileage_arai_kmpl": 18.9,
            "length_mm": 4413, "width_mm": 1699, "height_mm": 1466,
            "wheelbase_mm": 2552, "boot_litres": 460, "ground_clearance_mm": 168,
            "abs_ebd": True, "airbags": 2, "drivetrain": "FWD"}},
    },
    "toyota": {
        "corolla altis": {"base": {
            "engine_cc": 1798, "fuel_tank_l": 55, "mileage_arai_kmpl": 15.0,
            "length_mm": 4620, "width_mm": 1775, "height_mm": 1460,
            "wheelbase_mm": 2700, "boot_litres": 470, "ground_clearance_mm": 165,
            "headlamp_type": "LED", "ac_type": "Auto-climate", "abs_ebd": True,
            "airbags": 7, "drivetrain": "FWD"}},
        "fortuner": {"base": {
            "engine_cc": 2755, "fuel_tank_l": 80, "mileage_arai_kmpl": 14.2,
            "length_mm": 4795, "width_mm": 1855, "height_mm": 1835,
            "wheelbase_mm": 2745, "ground_clearance_mm": 279, "headlamp_type": "LED",
            "wheel_type": "Alloy", "ac_type": "Auto-climate", "rear_ac_vents": True,
            "abs_ebd": True, "airbags": 7, "drivetrain": "RWD"}},
        "innova": {"base": {
            "engine_cc": 2393, "fuel_tank_l": 55, "mileage_arai_kmpl": 13.7,
            "length_mm": 4735, "width_mm": 1830, "height_mm": 1795,
            "wheelbase_mm": 2750, "ground_clearance_mm": 178, "rear_ac_vents": True,
            "abs_ebd": True, "airbags": 3, "drivetrain": "RWD"}},
    },
    "mahindra": {
        "kuv100": {"base": {
            "engine_cc": 1198, "fuel_tank_l": 35, "mileage_arai_kmpl": 18.2,
            "length_mm": 3675, "width_mm": 1735, "height_mm": 1655,
            "wheelbase_mm": 2385, "boot_litres": 243, "ground_clearance_mm": 170,
            "abs_ebd": True, "airbags": 2, "drivetrain": "FWD"}},
        "tuv300": {"base": {
            "engine_cc": 1493, "fuel_tank_l": 60, "mileage_arai_kmpl": 18.5,
            "length_mm": 3995, "width_mm": 1835, "height_mm": 1839,
            "wheelbase_mm": 2680, "boot_litres": 384, "ground_clearance_mm": 184,
            "abs_ebd": True, "airbags": 2, "drivetrain": "RWD"}},
        "marazzo": {"base": {
            "engine_cc": 1497, "fuel_tank_l": 45, "mileage_arai_kmpl": 17.6,
            "length_mm": 4585, "width_mm": 1866, "height_mm": 1774,
            "wheelbase_mm": 2760, "ground_clearance_mm": 200, "rear_ac_vents": True,
            "abs_ebd": True, "airbags": 2, "drivetrain": "FWD"}},
    },
    "kia": {
        "sonet": {"base": {
            "engine_cc": 1197, "fuel_tank_l": 45, "mileage_arai_kmpl": 18.4,
            "length_mm": 3995, "width_mm": 1790, "height_mm": 1610,
            "wheelbase_mm": 2500, "boot_litres": 392, "ground_clearance_mm": 205,
            "headlamp_type": "LED", "wheel_type": "Alloy", "sunroof_type": "Single",
            "ac_type": "Auto-climate", "abs_ebd": True, "airbags": 6, "drivetrain": "FWD"}},
    },
    "ford": {
        "ecosport": {"base": {
            "engine_cc": 1497, "fuel_tank_l": 52, "mileage_arai_kmpl": 17.0,
            "length_mm": 3998, "width_mm": 1765, "height_mm": 1647,
            "wheelbase_mm": 2519, "boot_litres": 352, "ground_clearance_mm": 200,
            "abs_ebd": True, "airbags": 6, "drivetrain": "FWD"}},
        "fiesta": {"base": {
            "engine_cc": 1499, "fuel_tank_l": 45, "length_mm": 4234, "width_mm": 1722,
            "height_mm": 1481, "wheelbase_mm": 2489, "boot_litres": 430,
            "abs_ebd": True, "airbags": 2, "drivetrain": "FWD"}},
    },
    "mg motor": {
        "astor": {"base": {
            "engine_cc": 1349, "fuel_tank_l": 45, "mileage_arai_kmpl": 15.4,
            "length_mm": 4323, "width_mm": 1809, "height_mm": 1650,
            "wheelbase_mm": 2585, "boot_litres": 488, "ground_clearance_mm": 180,
            "headlamp_type": "LED", "wheel_type": "Alloy", "sunroof_type": "Single",
            "ac_type": "Auto-climate", "abs_ebd": True, "airbags": 6,
            "connected_car": True, "drivetrain": "FWD"}},
    },
    "chevrolet": {
        "spark": {"base": {
            "engine_cc": 995, "fuel_tank_l": 35, "length_mm": 3640, "width_mm": 1597,
            "height_mm": 1522, "wheelbase_mm": 2375, "boot_litres": 170,
            "airbags": 1, "drivetrain": "FWD"}},
    },
}


def resolve_specs(make: Optional[str], model: Optional[str],
                  variant: Optional[str] = None,
                  year: Optional[int] = None) -> Dict[str, Any]:
    """Return the merged standard spec dict for a vehicle, most-specific-wins.
    Unknown make/model -> {} (no fabrication)."""
    mk, md = _norm_key(make), _norm_key(model)
    model_entry = SPECS.get(mk, {}).get(md)
    if not model_entry:
        return {}
    out: Dict[str, Any] = dict(model_entry.get("base", {}))
    # year-range overrides
    for lo, hi, patch in model_entry.get("years", []):
        if year is not None and lo <= year <= hi:
            out.update(patch)
    # variant overrides (highest precedence)
    v = _norm_key(variant)
    if v:
        for vkey, patch in model_entry.get("variants", {}).items():
            if _norm_key(vkey) in v or v in _norm_key(vkey):
                out.update(patch)
    # only ever expose whitelisted spec fields
    return {k: val for k, val in out.items() if k in SPEC_FIELDS}


def apply_specs(item: Any) -> Any:
    """Fill an InventoryItem's STANDARD spec fields from the library, but ONLY
    where the dealership has not entered a value (item field is None). Owner data
    always wins. Never fabricates for unknown models. Returns the same item.
    Fully exception-safe: any error leaves the item unchanged."""
    try:
        specs = resolve_specs(getattr(item, "make_full", None),
                              getattr(item, "model", None),
                              getattr(item, "variant", None),
                              getattr(item, "year_int", None))
        if not specs:
            return item
        for field, value in specs.items():
            if getattr(item, field, None) is None:
                setattr(item, field, value)
    except Exception:
        pass
    return item


def known_models() -> List[str]:
    return sorted(f"{mk} {md}" for mk, mds in SPECS.items() for md in mds)


def coverage_for(item: Any) -> Dict[str, Any]:
    """How many spec fields the library can fill for one item (diagnostic)."""
    specs = resolve_specs(getattr(item, "make_full", None),
                          getattr(item, "model", None),
                          getattr(item, "variant", None),
                          getattr(item, "year_int", None))
    return {"known": bool(specs), "fillable": len(specs)}


if __name__ == "__main__":
    import json
    print("Known models:", len(known_models()))
    for mk, md in [("Hyundai", "Creta"), ("Maruti Suzuki", "Swift"),
                   ("Toyota", "Fortuner"), ("Unknown", "Ghost")]:
        print(f"\n{mk} {md}:")
        print(json.dumps(resolve_specs(mk, md), indent=2, default=str))
