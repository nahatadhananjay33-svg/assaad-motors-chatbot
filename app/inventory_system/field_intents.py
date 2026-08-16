"""
field_intents.py
================

Phase 12D — deterministic intent recognition for the NEW vehicle-detail fields
added in Phase 12B/12C (engine, dimensions, exterior, interior, comfort,
infotainment, safety, EV, keys, extra documents). NO LLM.

This module is a thin, data-driven extension of the existing Phase 11A/11B engine.
It does NOT re-handle fields already covered by 11A (km, owners, colour, fuel,
transmission, seats, price, insurance, rc, service, warranty, accident/flood
condition, year) — those keep working exactly as before. It only adds the fields
that previously had NO recognition.

Each field maps to an InventoryItem attribute, so answers come straight from the
inventory record (spec-auto-filled by model_specs, or dealership-entered) — never
fabricated. Unknown value → the caller renders "Data not available".

Public API:
    FIELD_SPECS                         ordered {attr: spec}
    detect(text) -> (attr_fields, feature_filters)
    display(attr), unit(attr), ftype(attr), role(attr)
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from query_parser import _norm, _has          # cached, fast (Phase 11A perf fix)

# role: "attr" = attribute question only · "both" = also a sensible inventory filter
# type: bool | int | float | enum | text
# Each entry: attr -> {display, unit, type, role, labels[...]}
FIELD_SPECS: Dict[str, Dict[str, Any]] = {
    # ── Engine ──
    "engine_cc": {"display": "Engine", "unit": " cc", "type": "int", "role": "attr",
        "labels": ["engine cc", "engine capacity", "cc kitna", "kitna cc", "kitne cc",
                   "engine size", "इंजिन सीसी", "इंजिन क्षमता", "how much cc"]},
    "power_bhp": {"display": "Power", "unit": " bhp", "type": "float", "role": "attr",
        "labels": ["power bhp", "bhp", "horsepower", "kitni power", "power kitni",
                   "power kitna", "engine power", "पॉवर", "अश्वशक्ती"]},
    "torque_nm": {"display": "Torque", "unit": " Nm", "type": "float", "role": "attr",
        "labels": ["torque", "nm torque", "kitna torque", "टॉर्क"]},
    "aspiration": {"display": "Aspiration", "unit": "", "type": "enum", "role": "attr",
        "labels": ["aspiration", "turbo hai", "turbo", "naturally aspirated", "टर्बो"]},
    # ── Transmission detail (gearbox itself → 11A transmission) ──
    "transmission_subtype": {"display": "Gearbox type", "unit": "", "type": "enum", "role": "both",
        "labels": ["amt", "cvt", "dct", "dsg", "imt", "torque converter",
                   "gearbox type", "transmission type", "kaunsa gearbox"]},
    "gears": {"display": "Gears", "unit": " gears", "type": "int", "role": "attr",
        "labels": ["number of gears", "kitne gears", "how many gears", "gear count",
                   "kitne gear", "gear kitne", "gears kitne", "kitni gear",
                   "गिअर संख्या"]},
    "drivetrain": {"display": "Drive type", "unit": "", "type": "enum", "role": "both",
        "labels": ["drivetrain", "drive type", "fwd", "rwd", "awd", "4wd", "four wheel drive",
                   "two wheel drive", "all wheel drive", "kaunsa drive"]},
    # ── Fuel economy / capacity ──
    "mileage_arai_kmpl": {"display": "Mileage (ARAI)", "unit": " kmpl", "type": "float", "role": "attr",
        "labels": ["mileage kitna", "mileage kitni", "kitna mileage", "average kitna",
                   "kitna average", "arai mileage", "mileage kya", "kmpl", "kitne ka average",
                   # "average kya/batao" — "average" unambiguously means km/l here.
                   # NOTE: bare "mileage" is deliberately NOT a label: on its own it
                   # could mean running (km chali) or km/l, so it must reach the 12J
                   # clarify instead of guessing. See AMBIGUOUS_FIELDS["mileage"].
                   "average kya", "kya average", "average batao",
                   "मायलेज किती", "किती मायलेज", "ऍव्हरेज किती", "milage kitna",
                   # Hindi Devanagari spelling "माइलेज" (Marathi "मायलेज" above)
                   "माइलेज", "माइलेज कितना", "कितना माइलेज"]},
    "fuel_tank_l": {"display": "Fuel tank", "unit": " litres", "type": "int", "role": "attr",
        "labels": ["fuel tank", "tank capacity", "fuel tank capacity", "tank kitna",
                   "petrol tank", "diesel tank", "इंधन टाकी", "टाकी क्षमता"]},
    # ── Dimensions ──
    "boot_litres": {"display": "Boot space", "unit": " litres", "type": "int", "role": "attr",
        "labels": ["boot space", "boot capacity", "boot litres", "dicky space", "dickey space",
                   "digi space", "boot kitna", "luggage space", "बूट स्पेस", "डिकी", "डिक्की",
                   "samaan kitna", "bootspace", "boot", "dicky", "dickey", "digi"]},
    "ground_clearance_mm": {"display": "Ground clearance", "unit": " mm", "type": "int", "role": "attr",
        "labels": ["ground clearance", "clearance kitna", "gc kitna", "high clearance kitna",
                   "जमिनीपासून उंची", "ग्राउंड क्लिअरन्स"]},
    "wheelbase_mm": {"display": "Wheelbase", "unit": " mm", "type": "int", "role": "attr",
        "labels": ["wheelbase", "wheel base", "व्हीलबेस"]},
    "length_mm": {"display": "Length", "unit": " mm", "type": "int", "role": "attr",
        "labels": ["length kitni", "car length", "kitni lambi", "lambai", "लांबी"]},
    "width_mm": {"display": "Width", "unit": " mm", "type": "int", "role": "attr",
        "labels": ["width kitni", "car width", "kitni chaudi", "chaudai", "रुंदी"]},
    "height_mm": {"display": "Height", "unit": " mm", "type": "int", "role": "attr",
        "labels": ["height kitni", "car height", "kitni unchi", "उंची किती"]},
    # ── Exterior & lights ──
    "sunroof_type": {"display": "Sunroof", "unit": "", "type": "enum", "role": "both",
        "labels": ["sunroof", "sun roof", "moonroof", "panoramic roof", "panoramic sunroof",
                   "roof khulta", "roof khulti", "chhat khulti", "chhat khulta", "chat khulti",
                   "सनरूफ", "छत खुलती", "छत खुलता", "sunroof hai", "sunroof aahe"]},
    "headlamp_type": {"display": "Headlamps", "unit": "", "type": "enum", "role": "both",
        "labels": ["led headlight", "led headlights", "led lights", "projector headlamp",
                   "projector headlamps", "projector lamp", "projector lamps",
                   "projector lights", "headlamp", "headlamps", "headlight", "headlights",
                   "headlamp type", "headlight type", "halogen",
                   "एलईडी हेडलाईट", "प्रोजेक्टर"]},
    "drl": {"display": "DRLs", "unit": "", "type": "bool", "role": "both",
        "labels": ["drl", "drls", "daytime running lamp", "daytime running lights", "day running lights"]},
    "fog_lamps": {"display": "Fog lamps", "unit": "", "type": "bool", "role": "both",
        "labels": ["fog lamp", "fog lamps", "fog light", "fog lights", "फॉग लाईट"]},
    "wheel_type": {"display": "Wheels", "unit": "", "type": "enum", "role": "both",
        "labels": ["alloy", "alloys", "alloy wheel", "alloy wheels", "steel wheel",
                   "steel rim", "अलॉय", "अलॉय व्हील"]},
    "wheel_size_inch": {"display": "Wheel size", "unit": " inch", "type": "int", "role": "attr",
        "labels": ["wheel size", "tyre size", "rim size", "kitne inch tyre", "व्हील साइझ"]},
    "roof_rails": {"display": "Roof rails", "unit": "", "type": "bool", "role": "attr",
        "labels": ["roof rail", "roof rails", "रूफ रेल"]},
    "spoiler": {"display": "Spoiler", "unit": "", "type": "bool", "role": "attr",
        "labels": ["spoiler", "स्पॉयलर"]},
    # ── Interior & comfort ──
    "upholstery": {"display": "Upholstery", "unit": "", "type": "enum", "role": "both",
        "labels": ["leather seats", "leather seat", "leather interior", "fabric seats",
                   "leatherette", "upholstery", "seat material", "leather hai", "चामडी सीट"]},
    "ac_type": {"display": "AC", "unit": "", "type": "enum", "role": "attr",
        "labels": ["climate control", "automatic climate control", "auto ac", "ac type",
                   "manual ac", "ac kaisa", "एसी", "क्लायमेट कंट्रोल", "ac hai"]},
    "rear_ac_vents": {"display": "Rear AC vents", "unit": "", "type": "bool", "role": "both",
        "labels": ["rear ac", "rear ac vents", "back ac", "rear vents", "peeche ac",
                   "मागे एसी", "rear blower"]},
    "power_windows": {"display": "Power windows", "unit": "", "type": "enum", "role": "attr",
        "labels": ["power window", "power windows", "auto windows", "पॉवर विंडो"]},
    "adjustable_seat": {"display": "Seat adjust", "unit": "", "type": "enum", "role": "attr",
        "labels": ["adjustable seat", "height adjust", "seat height", "power seat",
                   "electric seat", "memory seat", "सीट अ‍ॅडजस्ट"]},
    "ventilated_seats": {"display": "Ventilated seats", "unit": "", "type": "bool", "role": "both",
        "labels": ["ventilated seat", "ventilated seats", "cooled seats", "व्हेंटिलेटेड सीट"]},
    "cruise_control": {"display": "Cruise control", "unit": "", "type": "bool", "role": "both",
        "labels": ["cruise control", "cruise", "क्रूझ कंट्रोल"]},
    "keyless_entry": {"display": "Keyless entry", "unit": "", "type": "bool", "role": "both",
        "labels": ["keyless entry", "keyless", "smart key", "smart entry", "कीलेस"]},
    "push_button_start": {"display": "Push-button start", "unit": "", "type": "bool", "role": "both",
        "labels": ["push button", "push button start", "start stop button", "button start",
                   "पुश बटन"]},
    "auto_folding_orvm": {"display": "Auto-folding mirrors", "unit": "", "type": "bool", "role": "attr",
        "labels": ["auto folding mirror", "auto fold orvm", "electric mirror", "folding mirror",
                   "orvm"]},
    "rear_defogger": {"display": "Rear defogger", "unit": "", "type": "bool", "role": "attr",
        "labels": ["defogger", "rear defogger", "demister", "डिफॉगर"]},
    "rear_wiper": {"display": "Rear wiper", "unit": "", "type": "bool", "role": "attr",
        "labels": ["rear wiper", "back wiper", "मागचा वायपर"]},
    "wireless_charging": {"display": "Wireless charging", "unit": "", "type": "bool", "role": "attr",
        "labels": ["wireless charging", "wireless charger", "वायरलेस चार्जिंग"]},
    "connected_car": {"display": "Connected car", "unit": "", "type": "bool", "role": "attr",
        "labels": ["connected car", "connected tech", "car connectivity", "remote start app"]},
    # ── Infotainment ──
    "touchscreen_inches": {"display": "Touchscreen", "unit": " inch", "type": "float", "role": "attr",
        "labels": ["touchscreen", "touch screen", "infotainment", "display screen", "screen size",
                   "टचस्क्रीन", "स्क्रीन"]},
    "android_auto_carplay": {"display": "Android Auto / CarPlay", "unit": "", "type": "bool", "role": "both",
        "labels": ["android auto", "apple carplay", "carplay", "car play", "android auto carplay"]},
    "speakers": {"display": "Speakers", "unit": " speakers", "type": "int", "role": "attr",
        "labels": ["speakers", "music system", "stereo", "sound system", "kitne speaker",
                   "bluetooth", "usb", "aux", "स्पीकर", "म्युझिक सिस्टम"]},
    "camera_type": {"display": "Camera", "unit": "", "type": "enum", "role": "both",
        "labels": ["reverse camera", "rear camera", "back camera", "360 camera", "360 degree camera",
                   "parking camera", "camera hai", "camera laga", "rear cam",
                   "back cam", "camera", "कॅमेरा", "रिव्हर्स कॅमेरा", "कॅमेरा आहे",
                   # Phase 12I: Hindi Devanagari "कैमरा" (Marathi "कॅमेरा" above)
                   "कैमरा", "कैमरा है", "कैमेरा"]},
    "steering_controls": {"display": "Steering controls", "unit": "", "type": "bool", "role": "attr",
        "labels": ["steering control", "steering controls", "steering mounted",
                   "steering mounted controls", "steering buttons", "audio controls on steering"]},
    # ── Safety ──
    "airbags": {"display": "Airbags", "unit": " airbags", "type": "int", "role": "both",
        "labels": ["airbag", "airbags", "kitne airbag", "how many airbags", "airbag count",
                   "number of airbags", "एअरबॅग", "किती एअरबॅग",
                   # Phase 12I: Hindi Devanagari "एयरबैग" (Marathi "एअरबॅग" above)
                   "एयरबैग", "कितने एयरबैग", "एयरबैग कितने", "एयरबैग है", "एयर बैग"]},
    "abs_ebd": {"display": "ABS/EBD", "unit": "", "type": "bool", "role": "both",
        "labels": ["abs", "ebd", "anti lock brakes", "abs ebd", "abs hai", "एबीएस"]},
    "esp": {"display": "ESP", "unit": "", "type": "bool", "role": "both",
        "labels": ["esp", "esc", "stability control", "traction control", "ईएसपी"]},
    "hill_hold": {"display": "Hill-hold", "unit": "", "type": "bool", "role": "attr",
        "labels": ["hill hold", "hill assist", "hill start assist"]},
    "parking_sensors": {"display": "Parking sensors", "unit": "", "type": "enum", "role": "both",
        "labels": ["parking sensor", "parking sensors", "rear sensor", "reverse sensor",
                   "पार्किंग सेन्सर"]},
    "isofix": {"display": "ISOFIX", "unit": "", "type": "bool", "role": "attr",
        "labels": ["isofix", "child seat mount", "child seat anchor"]},
    "ncap_rating": {"display": "NCAP rating", "unit": " stars", "type": "int", "role": "attr",
        "labels": ["ncap", "ncap rating", "safety rating", "crash rating", "star rating",
                   "एनकॅप"]},
    # ── Keys & accessories ──
    "keys_count": {"display": "Keys", "unit": " keys", "type": "int", "role": "attr",
        "labels": ["number of keys", "how many keys", "kitni chabi", "kitni keys", "keys kitni",
                   "किती चाव्या", "how many key"]},
    "spare_key": {"display": "Spare key", "unit": "", "type": "bool", "role": "attr",
        "labels": ["spare key", "duplicate key", "duplicate chabi", "duplicate chaabi",
                   "extra key", "second key", "डुप्लिकेट चावी", "डुप्लिकेट चाबी"]},
    "spare_tyre": {"display": "Spare tyre", "unit": "", "type": "bool", "role": "attr",
        "labels": ["spare tyre", "spare wheel", "stepney", "extra tyre", "स्पेअर टायर"]},
    "toolkit": {"display": "Toolkit", "unit": "", "type": "bool", "role": "attr",
        "labels": ["toolkit", "tool kit", "jack", "tools", "टूलकिट"]},
    "floor_mats": {"display": "Floor mats", "unit": "", "type": "bool", "role": "attr",
        "labels": ["floor mat", "floor mats", "7d mats", "car mats", "फ्लोअर मॅट"]},
    "accessories_added": {"display": "Accessories", "unit": "", "type": "text", "role": "attr",
        "labels": ["accessories", "extra fitting", "after market", "accessories added",
                   "modifications", "अ‍ॅक्सेसरीज"]},
    # ── Documents (extra, beyond 11A rc/insurance) ──
    "puc_valid_till": {"display": "PUC", "unit": "", "type": "text", "role": "attr",
        "labels": ["puc", "puc valid", "pollution certificate", "pollution valid", "पीयूसी"]},
    "road_tax_status": {"display": "Road tax", "unit": "", "type": "enum", "role": "attr",
        "labels": ["road tax", "tax paid", "lifetime tax", "road tax status", "रोड टॅक्स"]},
    "fitness_valid_till": {"display": "Fitness", "unit": "", "type": "text", "role": "attr",
        "labels": ["fitness certificate", "fitness valid", "fc valid", "फिटनेस"]},
    "duplicate_rc": {"display": "Duplicate RC", "unit": "", "type": "bool", "role": "attr",
        "labels": ["duplicate rc", "duplicate registration"]},
    "usage_type": {"display": "Usage", "unit": "", "type": "enum", "role": "both",
        "labels": ["private use", "taxi use", "commercial use", "corporate car", "taxi car",
                   "private car", "personal use", "usage type", "टॅक्सी", "प्रायव्हेट"]},
    "tyre_life_pct": {"display": "Tyre life", "unit": "%", "type": "int", "role": "attr",
        "labels": ["tyre life", "tyre condition percent", "tyre percent", "tyres kitne percent",
                   "टायर लाईफ"]},
    # ── EV ──
    "battery_health_pct": {"display": "Battery health", "unit": "%", "type": "int", "role": "attr",
        "labels": ["battery health", "battery ki health", "battery condition percent",
                   "battery percent", "soh", "बॅटरी हेल्थ", "बैटरी हेल्थ", "battery life"]},
    "real_range_km": {"display": "Range", "unit": " km", "type": "int", "role": "attr",
        "labels": ["real range", "ev range", "driving range", "full charge range", "range kitna",
                   "kitna range", "kitni range", "range kitni", "ek charge", "ek charge mein",
                   "charge mein kitna", "charge mein kitni", "रेंज", "एका चार्जमध्ये"]},
    "battery_warranty_till": {"display": "Battery warranty", "unit": "", "type": "text", "role": "attr",
        "labels": ["battery warranty", "battery guarantee", "बॅटरी वॉरंटी"]},
    "charger_type": {"display": "Charger", "unit": "", "type": "text", "role": "attr",
        "labels": ["charger type", "charger included", "ac charger", "dc charger", "charging type",
                   "fast charging", "चार्जर"]},
    "charging_time": {"display": "Charging time", "unit": "", "type": "text", "role": "attr",
        "labels": ["charging time", "charge time", "kitni der charging", "charge hone mein",
                   "चार्जिंग वेळ"]},
    "battery_owned": {"display": "Battery owned", "unit": "", "type": "bool", "role": "attr",
        "labels": ["battery owned", "battery lease", "battery leased", "battery rented"]},
}

# phrases (longest first) so specific ones win; each maps to its attr
_PHRASE_TO_ATTR: List[Tuple[str, str]] = sorted(
    ((_norm(lbl), attr) for attr, spec in FIELD_SPECS.items() for lbl in spec["labels"]),
    key=lambda t: -len(t[0]))

# filter cues → treat a "both" field as an inventory FILTER, not an attribute Q
_FILTER_CUES = ("wali", "wale", "wala", "vali", "vala", "walon", "walo", "chahiye",
                "chaahiye", "chaiye", "dikhao", "dikha do", "show me", "with ",
                "cars with", "gaadi with", "वाली", "वाले", "पाहिजे", "हवी", "हव्या",
                "असलेली", "असलेल्या")


def _has_filter_cue(text: str) -> bool:
    return any(c in text for c in _FILTER_CUES)


def display(attr: str) -> str: return FIELD_SPECS[attr]["display"]
def unit(attr: str) -> str: return FIELD_SPECS[attr]["unit"]
def ftype(attr: str) -> str: return FIELD_SPECS[attr]["type"]
def role(attr: str) -> str: return FIELD_SPECS[attr]["role"]


import re as _re


def _filter_value(attr: str, text: str):
    """The required value for a feature filter, or None meaning 'present/truthy'."""
    if attr == "airbags":
        m = _re.search(r"\b([1-9]|1[0-2])\s*airbag", text)
        return int(m.group(1)) if m else None
    if attr == "wheel_type":
        return "Alloy" if "alloy" in text else ("Steel" if "steel" in text else None)
    if attr == "drivetrain":
        for k, v in (("4wd", "4WD"), ("awd", "AWD"), ("rwd", "RWD"), ("fwd", "FWD")):
            if k in text:
                return v
        return None
    if attr == "transmission_subtype":
        for k in ("amt", "cvt", "dct", "dsg", "imt"):
            if k in text:
                return k.upper()
        return None
    return None                                    # None => require present/truthy


def detect(text_norm: str) -> Tuple[List[str], Dict[str, Any]]:
    """Given already-normalized text, return (attr_fields, feature_filters).
    attr_fields = fields asked as attribute questions (answer from the car).
    feature_filters = {attr: value|None} for 'both'-role fields asked as a filter
    (None => require the feature present/truthy)."""
    matched: List[str] = []
    for phrase, attr in _PHRASE_TO_ATTR:
        if attr in matched:
            continue
        if _has(text_norm, phrase):
            matched.append(attr)
    if not matched:
        return [], {}
    is_filter = _has_filter_cue(text_norm)
    attr_fields: List[str] = []
    feature_filters: Dict[str, Any] = {}
    for attr in matched:
        if is_filter and FIELD_SPECS[attr]["role"] == "both":
            feature_filters[attr] = _filter_value(attr, text_norm)
        else:
            attr_fields.append(attr)
    return attr_fields, feature_filters


if __name__ == "__main__":
    for t in ["sunroof hai", "boot space kitna", "airbags kitne aur camera hai",
              "sunroof wali car", "6 airbags wali", "ev range kitna",
              "led headlights aur alloy wheels", "charging time kitna",
              "4wd wali", "cvt wali"]:
        a, f = detect(_norm(t))
        print(f"{t:34} attr={a} filter={f}")
