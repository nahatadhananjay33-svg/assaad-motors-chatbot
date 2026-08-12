"""
query_parser.py
===============

Deterministic customer-utterance -> structured `Query` parser for the retrieval
engine. NO LLM, NO embeddings, NO vector DB — pure rules grounded in:

  * Information extraction/02_inventory/inventory_query_mapping.csv  (phrase->field)
  * Information extraction/02_inventory/retrieval_guardrails.md       (G-ALIAS, G-FUEL,
    G-COLOR, G-REEL, G-OFFSHEET-DETECT)
  * Information extraction/02_inventory/inventory_retrieval_rules.md  (§2,§3)

Handles English / Hindi / Hinglish surface forms. Reuses the normalization maps
already implemented in `inventory_loader.py` so codes/spellings fold identically
on the query side and the data side.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, List, Optional, Set

from inventory_models import FuelType, Transmission, BodyType
import inventory_loader as L
from model_aliases import EXTENDED_MODEL_ALIASES
from slang_aliases import (
    FUEL_SLANG, TRANSMISSION_AUTO_TERMS, TRANSMISSION_MANUAL_TERMS,
    AVAILABILITY_TERMS, PRICE_TERMS, OWNERSHIP_FIRST, OWNERSHIP_SECOND,
    OWNERSHIP_FEW, COLOR_ADDITIONS,
)


# ─────────────────────────────────────────────────────────────────────────────
# Query model
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Query:
    raw: str
    # filters
    make: Optional[str] = None            # make CODE (e.g. 'HOND')
    model: Optional[str] = None           # canonical model (e.g. 'Creta')
    fuel: Optional[str] = None            # FuelType value
    transmission: Optional[str] = None    # Transmission value
    color: Optional[str] = None           # canonical colour
    ownership_exact: Optional[int] = None
    ownership_max: Optional[int] = None
    price_max: Optional[int] = None
    price_min: Optional[int] = None
    category: Optional[str] = None        # 'SUV' | 'Sedan' | 'Hatchback' | 'MUV' | 'Luxury'
    seats: Optional[int] = None
    km_max: Optional[int] = None          # "under 20000 km" / "20k km se kam"
    reg_partial: Optional[str] = None     # partial registration: "MH01", "6922"
    has_insurance: Optional[bool] = None  # "insurance kis kis ka hai" -> insured cars
    year_min: Optional[int] = None
    year_exact: Optional[int] = None      # bare 4-digit year, e.g. "2019 nexon"
    sort_cheapest: bool = False
    sort_low_km: bool = False             # Phase 7L: "low km" / "less driven" -> km ascending
    # intent / flags
    intents: Set[str] = field(default_factory=set)   # availability/price/fuel/...
    off_sheet: bool = False
    off_sheet_topic: Optional[str] = None
    insurance_query: bool = False
    reel_stripped: List[str] = field(default_factory=list)
    clarify_needed: bool = False
    registration: Optional[str] = None    # normalized registration number, if any
    condition_query: bool = False         # TASK7: condition / accident history
    downpayment_query: bool = False       # TASK8: downpayment / EMI estimate
    service_query: bool = False           # Phase 7D: service history questions
    rc_query: bool = False                # Phase 7D: RC / loan / NOC questions
    flood_query: bool = False             # Phase 7D: flood / water damage questions
    warranty_detail_query: bool = False   # Phase 7D: warranty on a specific vehicle
    ownership_query: bool = False         # Phase 7H: owner count / history question
    km_reading_query: bool = False        # "kitne km chali" -> this car's odometer
    clarify_budget: Optional[int] = None  # bare number 1-20 w/o unit; ask confirmation
    # Phase 11A: attribute-question intents — "what is THIS car's <field>?" (no
    # value given). Distinct from the same-named FILTER fields above: a filter
    # carries a value ("white car" -> color=White, a browse); a query asks the
    # field of the pinned car ("kaunsa rang?" -> color_query, answer that car).
    color_query: bool = False
    fuel_query: bool = False
    transmission_query: bool = False
    seats_query: bool = False
    year_query: bool = False              # Phase 12G: "kaunsa year?" / "2019 model hai?" -> this car's model year
    # Phase 12D: new vehicle-detail fields (specs/features/EV/keys/extra docs).
    # attr_fields = InventoryItem attributes asked as attribute questions (answer
    # from the pinned car); feature_filters = {attr: value|None} inventory filters.
    attr_fields: List[str] = field(default_factory=list)
    feature_filters: Dict[str, object] = field(default_factory=dict)
    # Phase 12I: a genuinely ambiguous BARE field word ("engine?", "battery?",
    # "safety features?") that maps to no single answerable field. Set only when
    # nothing else resolved — the caller returns a deterministic clarify (never a
    # guess, never a fresh inventory dump). Holds the ambiguous key.
    ambiguous_field: Optional[str] = None
    # Phase 12J: a coordinated two-attribute FILTER form ("automatic aur petrol?")
    # with no question word (`hai`) and no search cue — genuinely ambiguous between
    # "is THIS car automatic AND petrol?" and "show automatic petrol cars". The
    # caller returns a deterministic clarify (add `hai?` to ask, `wali dikhao` to
    # search). Never silently picks one meaning.
    attr_pair_ambiguous: bool = False

    def active_filters(self) -> Dict[str, object]:
        keys = ("make", "model", "fuel", "transmission", "color",
                "ownership_exact", "ownership_max", "price_max", "price_min",
                "category", "seats", "km_max", "reg_partial", "has_insurance",
                "year_min", "year_exact")
        return {k: getattr(self, k) for k in keys if getattr(self, k) is not None}

    def has_any_filter(self) -> bool:
        return (bool(self.active_filters()) or self.sort_cheapest
                or self.sort_low_km or bool(self.registration)
                or bool(self.feature_filters))          # Phase 12D feature filters


# ─────────────────────────────────────────────────────────────────────────────
# Vocabulary (deterministic lookups)
# ─────────────────────────────────────────────────────────────────────────────
# make word -> make code
MAKE_WORDS: Dict[str, str] = {
    "maruti": "MARU", "suzuki": "MARU", "maruti suzuki": "MARU",
    "toyota": "TOYO",
    "hyundai": "HYUN",
    "honda": "HOND",
    "mahindra": "MAHI",
    "tata": "TATA",
    "mercedes": "MERC", "merc": "MERC", "benz": "MERC",
    "volkswagen": "VOX", "vw": "VOX",
    "skoda": "SKODA",
    "ford": "FORD",
    "bmw": "BMW",
    "audi": "AUDI",
    "jeep": "JEEP",
    "kia": "KIA",
    "renault": "RENA",
    "nissan": "NISS",
    "mg": "MG",
    "chevrolet": "SHEV", "chevy": "SHEV",
    "mitsubishi": "HMFC",
    "jaguar": "JAGUAR",
    "volvo": "VOLV",
    "isuzu": "ISUZU",
}

# model lookups (lowercased alias/canonical -> canonical). Longest match wins.
def _build_model_lookup() -> Dict[str, str]:
    lut: Dict[str, str] = {}
    for canon in L.KNOWN_MODELS:
        lut[canon.lower()] = canon
    for raw, canon in L.MODEL_ALIASES.items():
        lut[raw.lower()] = canon
    # common spacing/synonym surface forms
    lut.update({
        "i 20": "i20", "i20": "i20", "i-20": "i20",
        "i 10": "i10", "i10": "i10",
        "wagon r": "WagonR", "wagonr": "WagonR",
        "eco sport": "EcoSport", "ecosport": "EcoSport",
        "corolla altis": "Corolla Altis", "altis": "Corolla Altis",
        "innova crysta": "Innova Crysta", "crysta": "Innova Crysta",
        "grand i10": "Grand i10",
        "c class": "C Class", "c-class": "C Class",
        "e class": "E Class",
    })
    # Extended market-wide aliases (all of India's used-car market)
    for raw, canon in EXTENDED_MODEL_ALIASES.items():
        lut[raw.lower()] = canon
    return lut

MODEL_LOOKUP = _build_model_lookup()
# phrases sorted longest-first so 'corolla altis' beats 'corolla'
_MODEL_PHRASES = sorted(MODEL_LOOKUP.keys(), key=lambda s: -len(s))


def register_inventory_models(models) -> None:
    """Merge the LIVE inventory's model names into the recognizer so every car
    currently in stock is searchable by its own model name — including models
    outside the static market vocabulary (e.g. Camry, Evoque, Jaguar, Benz, 800).

    Inventory is the source of truth: call this on load and on every
    refresh_inventory(). Additive + idempotent — a model that later leaves stock
    simply yields 0 matches ("not available"), never a stale result, so there is
    no need to prune. Word-boundary matching (see `_has`) keeps short / numeric
    names safe (e.g. '800' never matches inside '800000')."""
    added = False
    for m in models:
        key = (str(m).strip().lower() if m else "")
        if len(key) >= 2 and key not in MODEL_LOOKUP:
            MODEL_LOOKUP[key] = str(m).strip()
            added = True
    if added:
        # mutate in place so the module-global reference used by parse() sees it
        _MODEL_PHRASES[:] = sorted(MODEL_LOOKUP.keys(), key=lambda s: -len(s))

FUEL_WORDS: Dict[str, str] = {
    "diesel": FuelType.DIESEL,
    "petrol": FuelType.PETROL,
    "cng": FuelType.CNG, "gas": FuelType.CNG,
    "hybrid": FuelType.HYBRID,
    "electric": FuelType.ELECTRIC, "ev": FuelType.ELECTRIC,
    "dual fuel": FuelType.PETROL_CNG,
    # slang / regional
    "dijal": FuelType.DIESEL,
    "peterol": FuelType.PETROL, "patrol": FuelType.PETROL,
    "battery wali": FuelType.ELECTRIC, "battery wala": FuelType.ELECTRIC,
    "charging wali": FuelType.ELECTRIC,
    "strong hybrid": FuelType.HYBRID, "self charging": FuelType.HYBRID,
    "cng kit": FuelType.CNG, "gas wali": FuelType.CNG,
    "petrol cng": FuelType.PETROL_CNG,
    # Phase 7H.2: Marathi (Devanagari)
    "डिझेल": FuelType.DIESEL, "पेट्रोल": FuelType.PETROL,
    "सीएनजी": FuelType.CNG, "इलेक्ट्रिक": FuelType.ELECTRIC,
    # Phase 12I: Hindi Devanagari spellings ("डीजल"/"डीज़ल" alongside Marathi
    # "डिझेल"; Hindi "पेट्रोल" already covered above).
    "डीजल": FuelType.DIESEL, "डीज़ल": FuelType.DIESEL,
}

COLOR_WORDS: Dict[str, str] = {
    "white": "White", "safed": "White",
    "black": "Black", "kaali": "Black", "kala": "Black", "kaala": "Black",
    "silver": "Silver",
    "grey": "Grey", "gray": "Grey",
    "blue": "Blue", "neeli": "Blue", "neela": "Blue",
    "red": "Red", "laal": "Red", "lal": "Red",
    "brown": "Brown",
    "gold": "Gold",
    "beige": "Beige", "cream": "Beige", "champagne": "Beige",
    "green": "Green", "hara": "Green", "hari": "Green",
    "orange": "Orange", "narangi": "Orange",
    "maroon": "Maroon", "wine": "Maroon",
    "purple": "Purple", "violet": "Purple",
    "navy": "Blue", "navy blue": "Blue", "sky blue": "Blue",
    "off white": "White", "pearl white": "White",
    "metallic grey": "Grey", "metallic gray": "Grey",
    # Marathi
    "pandhra": "White", "pandra": "White",
    "nila": "Blue", "piwala": "Yellow", "hirwa": "Green",
}
# merge additional slang colours (lowest precedence; do not override above)
for _c_alias, _c_canon in COLOR_ADDITIONS.items():
    COLOR_WORDS.setdefault(_c_alias, _c_canon)

REEL_WORDS = [
    "reel wali", "reel mein", "video wali", "video mein", "story wali",
    "insta pe", "instagram pe", "post wali", "reel ki", "reel", "story", "insta",
]

OFFSHEET_TOPICS: Dict[str, str] = {
    "finance": "finance", "loan": "finance",
    # Phase 12D: "sunroof" / "airbag(s)" removed — they are now real answerable
    # inventory fields (Phase 12B), handled by field_intents, not routed off-sheet.
    # "service history" removed — now answered from data (Phase 7D)
    "exchange": "exchange",
}

# condition / accident-history words (Phase 6C TASK7) — answered from available
# inventory fields (owners, km), not off-sheet.
CONDITION_WORDS = [
    "condition", "car condition", "accident", "accidental",
    "accident history", "accident free", "no accident",
    # Phase 7H: broaden condition / accident-history coverage (answered from
    # owners / km / available fields — still no fabrication).
    "scratch", "scratches", "dent", "dents", "rust", "paint", "repaint",
    "repainted", "interior", "engine condition", "odometer", "km driven",
    "kms driven", "kilometers", "kilometres", "kitni chali", "km kitne",
    "kitne km", "how used", "condition report", "good condition", "overall",
    "tyre", "tyres", "tire", "tires", "glass", "electrical", "ac working",
    "ac service",
    # Phase 7I.3/7I.4: km-amount phrasings (broken-Hindi + Marathi). NOTE:
    # "low km"/"kam km"/"kami km"/"less driven" are handled by LOW_KM_WORDS as a
    # km-ascending sort (Phase 7L), not as a condition report.
    "kiti km", "kiti kilometer", "kiti chalali",
    # accident / damage sub-types
    "damage", "damages", "damaged", "crash", "crash history", "repair",
    "repairs", "repaired", "major repair", "airbag", "airbag deployment",
    # Phase 11A: touch-up / denting-painting phrasings (hyphens fold to spaces)
    "touch up", "touchup", "touch up hua", "denting", "denting painting",
    "denting paint", "body work", "bodywork", "panel", "panels", "putty",
    "was it hit", "hit", "frame damage", "chassis", "structural", "fire damage",
    "insurance claim", "claim history", "halat", "halaat", "kitni chali",
    "kitne km", "km chali", "bijli", "jang", "zang",
    # Phase 7H.2 broken-Hindi accident/condition
    "hadsa", "hadse", "hadsa histri", "hadsewali", "tkkar", "takkar", "thokar",
    "nuksaan", "nuksan", "mrammat", "marammat", "pani mein dooba", "pani me dooba",
    "aag lagi", "minor hadsa", "koi hadsa",
    # Marathi (Devanagari)
    "स्थिती", "गंज", "खरचटले", "खरचटलेले", "किती चालली", "किती वापरली",
    "वापरलेली", "काच", "अपघात", "नुकसान", "धडक", "पाण्यात बुडाली", "आग लागली",
    "मोठे नुकसान", "अपघातमुक्त", "एकूण स्थिती", "स्थितीत", "चांगल्या स्थिती",
    "चालतो का", "ac चालतो", "ac chal raha", "chal raha", "zargi",
    # Phase 7M: accident-denial phrasing ("nothing happened" = no accident)
    "काहीच झाले नाही", "काही झाले नाही", "काहीही झाले नाही",
]

# Phase 7L: low-km / least-driven phrasings. These do NOT ask about one car's
# condition — they request the inventory sorted by km ascending (lowest first).
# Deterministic; English + broken-Hindi + Marathi (Latin/Devanagari).
LOW_KM_WORDS = [
    "low km", "lowest km", "low kms", "lowest kms", "lowkm",
    "least km", "least kms", "low kilometer", "low kilometre",
    "lowest kilometer", "lowest kilometre", "low kilometers", "low kilometres",
    "less driven", "least driven", "low driven", "less used", "least used",
    "minimum km", "min km", "sabse kam km", "sabse kam chali",
    # broken-Hindi / Marathi (Latin)
    "kam km", "kam km wali", "kami km", "kam kilometer", "kam kilometre",
    "kami kilometer", "kami kilometre", "kam chali",
    "kam chalai", "kam chalali", "kami chalali", "kam chali hui", "kam driven",
    # Devanagari (Hindi + Marathi)
    "कम किमी", "कमी किमी", "कमी km", "कम km", "कमी चाललेली", "कम चली",
]

# downpayment / EMI words (Phase 6C TASK8) — when a vehicle is identified,
# answered with a 20% estimate based on the listed price.
DOWNPAYMENT_WORDS = [
    "downpayment", "down payment", "emi",
    # Phase 7I.3: phonetic / broken-Hindi spellings (not caught by typo map)
    "daun peyment", "down peyment", "daunpeyment", "downpeyment",
    "dawn payment", "dp kitna", "kitni emi", "emi kitni", "emi kitna",
    "monthly kitna", "kist kitni", "kist kitna",
    # Phase 11A: bare instalment phrasings ("kitni kist", "monthly installment")
    "kist", "kitni kist", "installment", "instalment", "installments",
    "monthly installment", "monthly instalment", "emi option", "monthly payment",
    # Devanagari
    "डाउन पेमेंट", "ईएमआय", "ईएमआई", "हप्ता", "किती हप्ता", "मासिक हप्ता",
]


# ─────────────────────────────────────────────────────────────────────────────
# Phase 11A: attribute-QUESTION words — "what is THIS car's <field>?" These carry
# NO field value (a value would be a filter/browse), so they are matched only when
# the corresponding filter did not resolve. Answered from the pinned vehicle.
# ─────────────────────────────────────────────────────────────────────────────
COLOR_QUERY_WORDS = [
    "color", "colour", "colar", "coler", "kaunsa color", "kaunsa colour",
    "kaun sa color", "kaun sa colour", "konsa color", "konsa colour",
    "which color", "which colour", "what color", "what colour", "color kya",
    "colour kya", "color kaunsa", "colour kaunsa", "car color", "gaadi ka color",
    "kaunsa rang", "kaun sa rang", "konsa rang", "rang kya", "kya rang",
    "rang kaunsa", "rang", "kaunsa kalar", "kalar",
    # Devanagari (Hindi + Marathi)
    "रंग", "कोणता रंग", "रंग कोणता", "कौन सा रंग", "कलर", "रंग काय",
]
FUEL_QUERY_WORDS = [
    "fuel", "fuel type", "kaunsa fuel", "kaun sa fuel", "konsa fuel",
    "which fuel", "what fuel", "fuel kya", "kya fuel", "fuel kaunsa",
    "kis fuel", "engine kaunsa", "kaunsa engine",
    # Devanagari
    "इंधन", "कोणते इंधन", "ईंधन", "फ्युएल",
]
TRANSMISSION_QUERY_WORDS = [
    "transmission", "transmission kya", "kaunsa transmission",
    "which transmission", "gearbox", "gear box", "gear kaisa", "gear kaisi",
    "gear kya", "kaunsa gear", "kaun sa gear", "konsa gear", "gear type",
    "gear system", "kis gear",
    # Devanagari
    "गिअरबॉक्स", "गियरबॉक्स", "ट्रान्समिशन", "कोणते गिअर",
]
SEATS_QUERY_WORDS = [
    "kitni seat", "kitni seats", "kitne seat", "kitne seats", "how many seats",
    "how many seat", "seat kitni", "seats kitni", "seating capacity",
    "kitni seating", "kitne log baith", "kitne log", "how many seater",
    "seating kitni", "capacity kya",
    # Phase 12J: bare "seater" question forms ("kitne seater hai?", "seater kitna")
    "kitne seater", "kitna seater", "kitni seater", "seater kitna", "seater kitni",
    "kitne seater hai", "how many seater hai",
    # Devanagari
    "किती सीट", "कितनी सीट", "किती जण बसतात", "आसन क्षमता", "किती सीटर", "कितने सीटर",
]

# ── Phase 12G: contextual attribute-question vs search/variant discriminators ──
# A bare yes/no or attribute question about a car's model year / odometer /
# transmission ("2019 model hai?", "kam km chali hai?", "automatic hai?") is a
# QUESTION about the specific (pinned) car — not a fresh inventory browse/sort. It
# only becomes a search when the wording explicitly asks to browse or narrow. This
# set is the deterministic search/variant marker (mirrors field_intents filter cues
# plus plural-browse / superlative / "koi hai" cues). Substring match (same style
# as field_intents._FILTER_CUES).
_SEARCH_VARIANT_CUES = (
    "wali", "wale", "wala", "vali", "vale", "vala", "walon", "walo", "waali",
    "chahiye", "chaahiye", "chaiye", "chahie", "chaeye",
    "dikhao", "dikha do", "dikha de", "dikhaao", "dikha", "show", "show me",
    "cars", "gaadiyan", "gaadiya", "gadiyan", "gadiya", "gaadiyaan",
    "sabse", "koi hai", "koi aur", "aur koi", "mein koi", "me koi",
    "options", "list", "with ", "batao options",
    # Marathi search / want
    "पाहिजे", "हवी", "हव्या", "दाखवा", "असलेली", "असलेल्या", "वाली", "वाले", "सर्वात",
)
# question-form markers (text is already _norm'd, so punctuation is gone — rely on
# the interrogative words). Presence means "this is a question, not a bare filter".
_ATTR_QUESTION_WORDS = (
    "hai", "hain", "hai kya", "kya", "he", "aahe", "ahe", "hai na", "kaisa",
    "kaisi", "kitna", "kitni", "kitne", "kya hai", "है", "आहे", "का", "क्या",
)
# odometer-READING question cues ("how much has THIS car run"): distinguishes an
# odometer question from a low-km inventory sort.
_ODO_QUESTION_CUES = (
    "chali", "chala", "chalali", "chalai", "running", "odometer", "odo",
    "kitna chal", "kitni chal", "km reading", "reading", "kitna chala",
    "kitni chali", "चालली", "चालला", "रनिंग",
)
# explicit model-year question phrases (no numeric year needed).
_YEAR_QUESTION_WORDS = (
    "model year", "kaunsa year", "kaunsi year", "konsa year", "konsi year",
    "kaun sa year", "kis year", "kis year ki", "year kya", "year konsa",
    "year kaunsa", "which year", "what year", "kaunsa saal", "kaunsi saal",
    "kis saal", "kis saal ki", "konsa saal", "saal kya", "saal kaunsa",
    "manufacturing year", "make year", "model kaunsa saal", "kitne model",
    # Devanagari (Hindi + Marathi)
    "मॉडेल इयर", "कोणते वर्ष", "कोणत्या वर्षी", "कोणता साल", "साल कोणता",
    "वर्ष कोणते", "कौन सा साल", "किस साल",
)


# Phase 12I: genuinely ambiguous BARE field words. Each maps to no single
# answerable schema field (multiple candidate meanings), so a bare form is a
# clarify — never a guess and never a fresh search. Value = clarify text.
AMBIGUOUS_FIELDS: Dict[str, str] = {
    "engine": ("Engine ke baare mein kya jaanna hai — capacity (CC), power (BHP), "
               "ya engine condition?"),
    "battery": ("Battery — normal 12V battery ki baat kar rahe ho ya EV battery "
                "health?"),
    "safety": ("Safety mein kya dekhna hai — airbags, ABS, ya NCAP rating?"),
    "safety features": ("Safety mein kya dekhna hai — airbags, ABS, ya NCAP "
                        "rating?"),
    "features": ("Kaunse features dekhne hain — sunroof, camera, touchscreen, ya "
                 "kuch aur?"),
    # Phase 12J: bare "mileage?" is ambiguous — running (km chali) vs fuel
    # efficiency (km/l). "mileage kitna/kya hai" resolves the ARAI field above and
    # "kitne km chali"/"running" resolves the odometer, so only the bare word asks.
    "mileage": ("Aap running (kitne km chali hai) pooch rahe ho ya mileage "
                "(km/l average)?"),
}
# words stripped when testing whether the message is essentially a bare ambiguous
# field (question particles + generic filler). Devanagari question words included.
_AMBIG_STRIP = {
    "hai", "hain", "kya", "he", "aahe", "ahe", "kaisa", "kaisi", "kaise", "kitna",
    "kitni", "kitne", "details", "detail", "ka", "ki", "ke", "batao", "bata",
    "ye", "yeh", "is", "isme", "ismein", "iska", "iski", "car", "gaadi", "gadi",
    "wala", "wali", "na", "about", "the", "of", "this", "tell", "me", "gimme",
    "है", "आहे", "क्या", "काय", "का",
}


def _has_search_cue(text: str) -> bool:
    return any(c in text for c in _SEARCH_VARIANT_CUES)


def _bare_ambiguous_field(text: str) -> Optional[str]:
    """Return the ambiguous key if `text` is essentially one bare ambiguous field
    word (after removing question/filler tokens), else None."""
    toks = [t for t in text.split() if t not in _AMBIG_STRIP]
    phrase = " ".join(toks)
    return phrase if phrase in AMBIGUOUS_FIELDS else None


def _is_attr_question(text: str) -> bool:
    return any(_has(text, w) for w in _ATTR_QUESTION_WORDS)


def _is_odo_question(text: str) -> bool:
    return any(_has(text, w) for w in _ODO_QUESTION_CUES)


def _is_year_question(text: str, q: "Query") -> bool:
    if any(c in text for c in _YEAR_QUESTION_WORDS):
        return True
    # bare "YYYY model hai?" / "ye 2019 hai?" — a concrete year + a question form.
    if q.year_exact is not None and _is_attr_question(text):
        return True
    return False


# Indian vehicle registration plate, e.g. "MH01BK9444" / "MH 01 BK 9444".
_REGISTRATION_RE = re.compile(r"\b[A-Za-z]{2}\s?\d{1,2}\s?[A-Za-z]{1,2}\s?\d{3,4}\b")

# bare 4-digit model year, e.g. "2019 nexon photos"
_YEAR_EXACT_RE = re.compile(r"\b(19[5-9]\d|20[0-3]\d)\b")


def extract_registration(message: str) -> Optional[str]:
    m = _REGISTRATION_RE.search(message or "")
    if not m:
        return None
    return re.sub(r"\s+", "", m.group(0)).upper()


# ─────────────────────────────────────────────────────────────────────────────
# Typo normalization (Phase 6C TASK4) — applied to raw text before parsing
# ─────────────────────────────────────────────────────────────────────────────
_TYPO_MAP = {
    r"\bphotu\b": "photo", r"\bphotoo\b": "photo", r"\bfotoo\b": "photo",
    r"\bfoto\b": "photo", r"\bfotu\b": "photo", r"\bpiks\b": "pics",
    r"\btsveer\b": "tasveer", r"\btsavir\b": "tasveer",
    r"\bvidoe\b": "video", r"\bvedio\b": "video", r"\bvidio\b": "video",
    r"\bvideoo\b": "video",
    r"\binsurence\b": "insurance", r"\binsurancee\b": "insurance",
    r"\binsurens\b": "insurance", r"\binsurans\b": "insurance",
    r"\bcatelogue\b": "catalogue", r"\bcatalog\b": "catalogue",
    r"\bkatalog\b": "catalogue", r"\bkatlog\b": "catalogue",
    # Phase 7H.2: broken-Hindi phonetic spellings normalized before parsing
    r"\bwaranti\b": "warranty", r"\bwarranti\b": "warranty", r"\bwaranty\b": "warranty",
    r"\bservis\b": "service", r"\bservise\b": "service",
    r"\bdiseil\b": "diesel", r"\bdizel\b": "diesel", r"\bdijal\b": "diesel",
    r"\bmileej\b": "mileage", r"\bmilej\b": "mileage", r"\bmaileej\b": "mileage",
    r"\bhetchbek\b": "hatchback", r"\bhechbek\b": "hatchback",
    r"\bbuking\b": "booking",
    r"\bsartifiket\b": "certificate", r"\bsertifiket\b": "certificate",
    r"\bchaalan\b": "challan", r"\bchalaan\b": "challan",
    r"\bodomitr\b": "odometer", r"\bodometr\b": "odometer",
    r"\binjan\b": "engine", r"\benjan\b": "engine",
    r"\bsiter\b": "seater", r"\bsitter\b": "seater",
    r"\bfamili\b": "family", r"\bfemily\b": "family",
    r"\bhypothication\b": "hypothecation",
    r"\blak\b": "lakh", r"\blakhs\b": "lakh", r"\blacs\b": "lakh", r"\blkh\b": "lakh",
    r"\bvolkswagan\b": "volkswagen",
    r"\baxident\b": "accident", r"\baksident\b": "accident",
    r"\bwagan r\b": "wagon r", r"\bwagan\b": "wagon",
    r"\bneksn\b": "nexon",
}


def normalize_typos(text: str) -> str:
    out = text or ""
    for pat, repl in _TYPO_MAP.items():
        out = re.sub(pat, repl, out, flags=re.I)
    return out


# A pasted URL / social link (e.g. an Instagram reel link) must NEVER contribute an
# inventory filter — its random shortcode digits/letters would otherwise be mis-read
# as a partial number plate ("…/reel/DG9444kLm/" -> reg 9444 -> a wrong car) or a
# model alias. Drop any whitespace-delimited token that looks like a URL/link before
# parsing. The reel/insta INTENT is still detected upstream (media_lookup runs on the
# raw message), so a link is correctly treated as a reel-discovery query and the bot
# asks for the car number / model — it just can't extract a car FROM the link text.
_URL_TOKEN_RE = re.compile(
    r"https?://|www\.|instagr|\.com\b|\.com/|\.in/|youtu|/reel|/p/|t\.me/", re.I)


def strip_urls(text: str) -> str:
    return " ".join(t for t in (text or "").split() if not _URL_TOKEN_RE.search(t))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=8192)
def _norm(text: str) -> str:
    t = text.lower()
    # drop zero-width joiner / non-joiner ENTIRELY (not to a space) so Devanagari
    # words that carry them (some Marathi spellings) stay intact instead of being
    # split — e.g. an adjustable-seat/accessories label survives normalization.
    t = t.replace("‍", "").replace("‌", "")
    t = t.replace("+", " plus ")
    # keep word chars, spaces, dots, AND the full Devanagari block (U+0900-097F).
    # \w excludes Devanagari combining vowel marks (matras, category Mn), so
    # without this they'd be stripped and shatter every Devanagari word
    # (e.g. "लाख" -> "ल ख", "विमा" -> "व म"), breaking Hindi/Marathi matching.
    t = re.sub(r"[^\w\s\.ऀ-ॿ]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


# Phase 11A perf: `_has` is called ~1000+ times per parse against fixed phrase
# vocabularies. Compiling the boundary regex per call thrashed the stdlib `re`
# cache (512 entries) once the vocab grew, making parse ~300 ms. Cache the
# compiled pattern per phrase — same semantics, ~100x faster.
@lru_cache(maxsize=None)
def _has_pattern(phrase: str):
    return re.compile(rf"(?<!\w){re.escape(phrase)}(?!\w)")


def _has(text: str, phrase: str) -> bool:
    return _has_pattern(phrase).search(text) is not None


# ─────────────────────────────────────────────────────────────────────────────
# Parse
# ─────────────────────────────────────────────────────────────────────────────
def parse(utterance: str) -> Query:
    # Drop pasted URLs/links first so a reel link's shortcode never becomes a
    # spurious model / partial-plate filter (a wrong-car answer). The reel intent
    # is still detected upstream from the raw message.
    raw = strip_urls(normalize_typos(utterance or ""))
    q = Query(raw=raw)
    q.registration = extract_registration(raw)
    text = _norm(raw)

    # ── G-REEL: strip reel/insta words (no inventory meaning) ──
    for w in REEL_WORDS:
        if _has(text, w):
            q.reel_stripped.append(w)
            text = re.sub(rf"(?<!\w){re.escape(w)}(?!\w)", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    # ── off-sheet detection (G-OFFSHEET-DETECT) ──
    for word, topic in OFFSHEET_TOPICS.items():
        if _has(text, word):
            q.off_sheet = True
            q.off_sheet_topic = topic
            break

    # insurance is a real (advisory) column -> soft answer, not fabrication
    # Phase 11A: "papers" moved to the documents/RC bucket; added claim / NCB /
    # policy phrasings ("Claim hua?", "no claim bonus", "cover valid hai").
    if (_has(text, "insurance") or _has(text, "insured")
            or _has(text, "policy") or _has(text, "bima") or _has(text, "beema")
            or _has(text, "cover note") or _has(text, "policy details")
            or _has(text, "claim") or _has(text, "claims") or _has(text, "ncb")
            or _has(text, "no claim") or _has(text, "no claim bonus")
            or _has(text, "insurance cover") or _has(text, "cover valid")
            or _has(text, "विमा") or _has(text, "विम्याचे") or _has(text, "विम्याची")
            or _has(text, "पॉलिसी") or _has(text, "क्लेम") or _has(text, "विमा दावा")):
        # Phase 11C: "which cars HAVE insurance" is an inventory-wide FILTER
        # ("insurance kis kis ka hai", "insurance wali gaadi", "विमा असलेल्या
        # गाड्या"), not an attribute question about one pinned car.
        if any(_has(text, w) for w in (
                "kis kis", "kin kin", "kaun kaun", "kaun si", "kaunsi",
                "konsi", "kon kon", "wali", "vali", "walon", "jinka",
                "jis jis", "which cars", "which all", "what all", "all cars",
                "sab", "sabhi", "saari", "sari", "list",
                "कौन कौन", "किस किस", "कोणत्या", "असलेल्या", "कोण कोण")):
            q.has_insurance = True
            q.intents.add("availability")
        else:
            q.insurance_query = True
            q.intents.add("insurance")

    # ── Phase 7L: low-km / least-driven -> sort inventory by km ascending ──
    if any(_has(text, _norm(w)) for w in LOW_KM_WORDS):
        q.sort_low_km = True
        q.intents.add("low_km")

    # ── condition / accident history (TASK7) ──
    if not q.sort_low_km and any(_has(text, _norm(w)) for w in CONDITION_WORDS):
        q.condition_query = True
        q.intents.add("condition")

    # ── km reading ("kitne km chali hai") -> this car's odometer, NOT the
    #    condition report. Overrides condition when the ask is clearly about km.
    _KM_READING_WORDS = [
        "kitne km", "km kitne", "kitni km", "km kitni", "kitne kilometer",
        "kitne kilometre", "kitni chali", "kiti chali", "kiti km", "km chali",
        "kitni chalali", "kiti chalali", "kitni chali", "odometer",
        "km driven", "kms driven", "kilometer chali", "kitne km chali",
        "km kitne chale", "किती चालली", "किती किलोमीटर", "किती वापरली",
        # Phase 11A: bare odometer asks ("KM?", "Running?", "Kilometer?", "odo?")
        "km", "kms", "kilometer", "kilometre", "kilometers", "kilometres",
        "running", "kitni running", "running kitni", "odo", "odo reading",
        "km reading", "odometer reading", "kitna chala", "kitna chali",
        "distance", "distance covered", "how many km", "how much km",
        "kitne kilometre chali", "kitne kilometer chali",
        # Hindi / Marathi (Devanagari)
        "कितने km", "कितनी चली", "कितने किलोमीटर", "किलोमीटर", "किमी",
        "कितना चला", "रनिंग",
    ]
    if (not q.sort_low_km and q.km_max is None
            and any(_has(text, _norm(w)) for w in _KM_READING_WORDS)):
        q.km_reading_query = True
        q.condition_query = False        # answer the odometer, not the condition

    # ── downpayment / EMI (TASK8) ──
    if any(_has(text, _norm(w)) for w in DOWNPAYMENT_WORDS):
        q.downpayment_query = True
        q.intents.add("downpayment")

    # ── Phase 7D: service history ──
    _SERVICE_WORDS = [
        "service history", "service record", "service records", "serviced",
        "last service", "service kab", "service kiya", "service hua",
        "service date", "authorized service", "authorised service", "multi brand",
        # Phase 7H: broaden service-history coverage
        "maintenance history", "maintenance", "regular service", "dealer service",
        "oil change", "service due", "service center", "service centre",
        "service interval", "service intervals", "all services", "services done",
        "pending service", "transmission service", "engine service",
        # Phase 7H.2: "servis" normalized to "service" by normalize_typos, so
        # "servis histri"/"servis rekords" become "service histri" etc.
        "service histri", "service rekords", "service book", "service due",
        "service sentr", "service centr",
        # Marathi (Devanagari)
        "सर्व्हिस", "सर्व्हिस इतिहास", "नियमित सर्व्हिस", "इंजिन सर्व्हिस", "सर्विस",
        # Phase 7I.3/7I.4: bare "service" / "servis" (normalized to "service")
        "service",
    ]
    if any(_has(text, _norm(w)) for w in _SERVICE_WORDS):
        q.service_query = True
        q.intents.add("service")

    # ── Phase 7D: RC / loan / NOC / documents ──
    _RC_WORDS = [
        "rc clear", "rc status", "loan on car", "loan on gaadi",
        "hypothecation", "noc available", "noc milega", "loan close",
        "loan baki", "loan chal raha", "bank loan", "finance clear",
        "rc transfer status", "loan closed",
        # Phase 7H: broaden RC / document coverage
        "document status", "documents status", "fc done", "fitness certificate",
        "challan", "challan pending", "puc", "puc valid", "duplicate rc",
        "document verification", "rc in whose name", "rc name", "insurance copy",
        "registration certificate", "papers ready", "documents ready",
        # Phase 7H.2 broken-Hindi
        "rc h kya", "rc asli", "kagzat", "kagaz", "kaagaz", "kagad", "kaagad",
        "fc hua", "fitness certificate", "rc kis ke naam", "sab kagzat",
        # Marathi (Devanagari)
        "कागदपत्रे", "कागद", "विम्याची copy", "rc आहे", "fc झाली",
        "rc कुणाच्या", "कुणाच्या नावाने",
        # Phase 7M: fixes for "RC Original आहे" → trust_reviews and "RC पत्ता सारखा" → address
        "rc original", "rc पत्ता",
        # Phase 11A: bare RC / registration / documents / fitness / transfer / NOC.
        # These bundle into the documents/RC answer (rc_status, hypothecation, loan,
        # NOC, finance_eligible). "papers" moved here from the insurance bucket.
        "rc", "rc hai", "rc h", "rc kaisa", "rc kaisi", "rc ka scene",
        "rc ready", "rc available", "rc kiske naam", "registration",
        "registration certificate", "registration hai", "reg certificate",
        "transfer", "rc transfer", "transfer hoga", "transfer ho jayega",
        "name transfer", "naam transfer", "noc", "n o c", "noc de doge",
        "fitness", "fitness certificate", "fitness cert", "fc", "fc valid",
        "rto", "rto clear", "rto work", "rto transfer",
        "documents", "document", "docs", "papers", "paper", "paperwork",
        "original papers", "papers complete", "paper complete", "papers ready",
        "puc certificate", "tax paid", "road tax",
        # Hindi / Marathi (Devanagari)
        "आरसी", "आरसी आहे", "रजिस्ट्रेशन", "ट्रान्सफर", "एनओसी", "फिटनेस",
        "फिटनेस प्रमाणपत्र", "कागदपत्र", "कागदपत्रे पूर्ण", "आरटीओ",
    ]
    if any(_has(text, _norm(w)) for w in _RC_WORDS):
        q.rc_query = True
        q.intents.add("rc")

    # ── Phase 7D: flood / water damage ──
    _FLOOD_WORDS = [
        "flood", "flood damage", "water damage", "baarish mein", "barish mein",
        "pani se", "flood affected", "water logged", "waterlogged",
    ]
    if any(_has(text, _norm(w)) for w in _FLOOD_WORDS):
        q.flood_query = True
        q.condition_query = True   # flood is a condition sub-type
        q.intents.add("condition")

    # ── Phase 7D: warranty on a specific vehicle ──
    _WARRANTY_VEHICLE_WORDS = [
        "warranty hai kya", "warranty milegi", "warranty milega",
        "warranty on this", "warranty on car", "is par warranty",
        "warranty kab tak", "warranty expiry", "warranty provider",
        "koi warranty hai", "engine warranty", "warranty bacha",
        # Phase 7I.3/7I.4: broaden warranty phrasings so a follow-up like
        # "warranty period?", "any warranty?", "warranti card", "वॉरंटी किती"
        # is answered from the (selected) vehicle's data, not a generic template.
        # ("warranti"/"waranti"/"waranty" are normalized to "warranty" upstream.)
        "warranty", "warranty period", "any warranty", "warranty card",
        "warranty kitni", "warranty status", "warranty available",
        "warranty details", "warranty cover", "warranty left", "warranty hai",
        # Phase 11A: guarantee synonyms + typos (route to the vehicle warranty
        # answer, not the generic FAQ template).
        "guarantee", "gaurantee", "guaranty", "garanti", "garantee",
        "guarantee hai", "koi guarantee", "guarantee milegi", "assurance",
        # Devanagari (Hindi + Marathi)
        "वॉरंटी", "वारंटी", "वॉरन्टी", "वॉरंटी किती", "वॉरंटी आहे",
        "गॅरंटी", "हमी", "गॅरंटी आहे",
    ]
    if any(_has(text, _norm(w)) for w in _WARRANTY_VEHICLE_WORDS):
        q.warranty_detail_query = True
        q.intents.add("warranty_detail")

    # ── Phase 7H: ownership / owner-history questions (answered from owners field) ──
    _OWNERSHIP_QUERY_WORDS = [
        "owner", "owners", "ownership", "number of owners", "how many owners", "kitne owner",
        "kitne malik", "owner history", "owner details", "previous owner",
        "previous user", "owner certificate", "owner verification", "owner change",
        "how many hands", "used by", "used by how many", "taxi car", "corporate car",
        "private use", "family used", "family ne use", "first owner", "single owner",
        # Phase 7H.2 broken-Hindi
        "malik", "maalik", "malik histri", "asli malik", "ghar ne use",
        "company car", "teksi", "teksi thi", "personal use", "malik badla",
        "kitno ne use", "kaun chalata", "pehle kaun chalata",
        # Phase 7I.4 Marathi (Latin) owner words
        "malak", "maalak", "ek malak", "kiti malak", "pahila malak", "malak kon",
        # Marathi (Devanagari)
        "मालक", "किती मालक", "एकच मालक", "एकाच हाताची", "किती हातांनी",
        "कुटुंबाने वापरली", "आधीचा मालक", "किती जणांनी वापरली", "मालक इतिहास",
        "company गाडी", "taxi होती", "personal वापर", "कोण चालवत होते",
        "चालवत होते", "किती हाताची",
        # Phase 12I: Hindi Devanagari owner spellings ("मालिक" vs Marathi "मालक")
        "मालिक", "कितने मालिक", "मालिक कितने", "कितने मालिक हैं", "मालिक कौन",
        "पहला मालिक", "एक मालिक",
    ]
    if any(_has(text, _norm(w)) for w in _OWNERSHIP_QUERY_WORDS):
        q.ownership_query = True
        q.intents.add("ownership")

    # ── make ──
    for word in sorted(MAKE_WORDS, key=lambda s: -len(s)):
        if _has(text, word):
            q.make = MAKE_WORDS[word]
            break

    # ── model (longest phrase first) ──
    for phrase in _MODEL_PHRASES:
        if _has(text, phrase):
            q.model = MODEL_LOOKUP[phrase]
            break

    # ── fuel (G-FUEL) ──
    for word, fuel in FUEL_WORDS.items():
        if _has(text, word):
            q.fuel = fuel
            q.intents.add("fuel")
            break

    # ── transmission ── ('at' deliberately excluded: too collision-prone)
    _auto_terms = [
        "automatic", "auto gear", "auto", "clutch wali nahi", "no clutch",
        "amt", "cvt", "dct", "dsg", "imt",
        # Phase 7H: automatic synonyms
        "at car", "clutchless", "easydrive", "easy drive", "no gear",
        # Phase 7H.2 broken-Hindi / Marathi
        "clach nahi", "clach nako", "gear nahi", "गिअर नसलेली", "क्लच नको",
        "at गाडी", "सोपी गाडी", "ऑटोमॅटिक",
    ] + TRANSMISSION_AUTO_TERMS
    _manual_terms = [
        "manual", "gear wali", "stick", "clutch wali", "मॅन्युअल",
    ] + TRANSMISSION_MANUAL_TERMS
    if any(_has(text, w) for w in _auto_terms):
        q.transmission = Transmission.AUTOMATIC
        q.intents.add("transmission")
    elif any(_has(text, w) for w in _manual_terms):
        q.transmission = Transmission.MANUAL
        q.intents.add("transmission")

    # ── colour (G-COLOR) ──
    for word, color in COLOR_WORDS.items():
        if _has(text, word):
            q.color = color
            q.intents.add("color")
            break

    # ── Phase 11A: attribute-QUESTION intents (answer the pinned car's field) ──
    # A "petrol ya diesel" / "manual ya automatic" ask sets a spurious filter via
    # the loops above — clear it and treat the utterance as a field QUESTION. A
    # plain field-name question ("fuel?", "kaunsa rang", "how many seats") becomes
    # a *_query only when its own filter did NOT resolve (a resolved value means a
    # browse/filter, never a question). All deterministic; no LLM.
    _fuel_or = re.search(r"\b(petrol|diesel|cng|hybrid|electric|gas)\b\s*"
                         r"(?:ya|or|va|kya|hai ya|ki| या)\s*"
                         r"\b(petrol|diesel|cng|hybrid|electric|gas)\b", text)
    # "fuel efficient / economy / average / mileage" is an economy browse, never a
    # "which fuel is this car" question — exclude it from fuel_query.
    _fuel_econ = any(w in text for w in ("efficient", "economy", "average",
                                         "mileage", "kitna deti", "kitni deti",
                                         "milage", "avg", "kmpl"))
    if _fuel_or:
        q.fuel = None
        q.intents.discard("fuel")
        q.fuel_query = True
    elif (q.fuel is None and not _fuel_econ
          and any(_has(text, _norm(w)) for w in FUEL_QUERY_WORDS)):
        q.fuel_query = True

    _trans_or = re.search(r"\b(manual|automatic|auto)\b\s*(?:ya|or|va|या)\s*"
                          r"\b(manual|automatic|auto)\b", text)
    if _trans_or:
        q.transmission = None
        q.intents.discard("transmission")
        q.transmission_query = True
    elif (q.transmission is None
          and any(_has(text, _norm(w)) for w in TRANSMISSION_QUERY_WORDS)):
        q.transmission_query = True

    if q.color is None and any(_has(text, _norm(w)) for w in COLOR_QUERY_WORDS):
        q.color_query = True

    if q.seats is None and any(_has(text, _norm(w)) for w in SEATS_QUERY_WORDS):
        q.seats_query = True

    # ── ownership ──
    if any(_has(text, w) for w in OWNERSHIP_FIRST):
        q.ownership_exact = 1
        q.intents.add("ownership")
    elif any(_has(text, w) for w in OWNERSHIP_SECOND):
        q.ownership_exact = 2
        q.intents.add("ownership")
    elif any(_has(text, w) for w in OWNERSHIP_FEW):
        q.ownership_max = 2
        q.intents.add("ownership")

    # ── category / seats ──
    if any(_has(text, w) for w in (
            "7 seater", "saat seater", "seven seater", "7 seat", "8 seater",
            "8 seat", "7 log", "saat log")):
        q.seats = 7
        q.intents.add("category")
    if any(_has(text, w) for w in ("5 seater", "paanch seater", "5 seat")):
        q.seats = 5
        q.intents.add("category")
    # generic "N seater" (2/3/4/6/9 …) — lets impossible asks ("2 seater")
    # honestly return no matches instead of a vague clarifier
    if q.seats is None:
        _m_seats = re.search(r"\b([2-9])\s*[- ]?\s*(?:seater|seat)s?\b", text)
        if _m_seats:
            q.seats = int(_m_seats.group(1))
            q.intents.add("category")
    if any(_has(text, w) for w in ("suv", "suvs", "compact suv", "compact suvs",
                                   "crossover", "crossovers", "high clearance",
                                   "high ground clearance", "high clach",
                                   "उंच क्लीअरन्स", "उंच गाडी")):
        q.category = "SUV"; q.intents.add("category")
    elif any(_has(text, w) for w in ("sedan", "sedans", "dickey wali", "सेदान")):
        # Phase 12I: bare "boot" removed as a Sedan cue — it is a boot-space
        # ATTRIBUTE question ("boot?" -> boot_litres via field_intents), not a
        # request for sedans. "dickey wali" remains the deterministic sedan cue.
        q.category = "Sedan"; q.intents.add("category")
    elif any(_has(text, w) for w in (
            "hatchback", "hatchbacks", "choti gaadi", "chhoti gaadi",
            "choti car", "chhoti car", "chota car", "hatch", "small car",
            "compact car", "mini car", "city car", "sheher mein chalane",
            "sheher ke liye", "sheher", "entry level", "pehli baar",
            "first time buyer", "5 door",
            # Marathi
            "छोटी गाडी", "शहरात", "शहरासाठी", "पहिल्यांदा")):
        q.category = "Hatchback"; q.intents.add("category")
    elif any(_has(text, w) for w in (
            "family car", "family wali", "muv", "mpv",
            "7 seater", "8 seater", "family", "for family", "wife and kids",
            "spacious", "family trips", "family use", "biwi bachon", "biwi bacho",
            "biwi aur bach", "ghar mein", "log hain ghar", "log ke liye",
            "bacha hai", "bachon ke liye", "daily use",
            # Marathi
            "फॅमिली", "कुटुंब", "कुटुंबासाठी", "जण आहोत", "बायको मुलांसाठी",
            "आरामदायक", "मोठी गाडी", "रोज वापरासाठी", "जणांसाठी", "सीटर",
            "biwi ke liye")):
        q.category = "MUV"; q.intents.add("category")
    elif any(_has(text, w) for w in ("luxury", "premium car", "premium gaadi")):
        q.category = "Luxury"; q.intents.add("category")
    elif any(_has(text, w) for w in ("badi gaadi", "badi car", "big car", "big suv")):
        q.category = "SUV"; q.intents.add("category")

    # ── price / budget ──
    _parse_price(text, q)

    # ── km limit: "under 20000 km", "20k km se kam", "within 50,000 kms" ──
    _parse_km_limit(text, q)

    # ── ambiguous bare budget: "4 ke andar", "7 mein", "5 tak SUV" ──
    # Trigger only when no price/year/model/category already resolved.
    # Requires a budget-direction word to appear immediately after the number
    # (tight 15-char window) to avoid false positives like "7 log hain".
    if (q.price_max is None and q.price_min is None and
            q.model is None and q.make is None and
            q.seats is None):
        _BARE_BUDGET_CTX = (
            "ke andar", "tak", "andar", "under", "below", "within",
            "mein", "budget", "dikhao", "dikha", "batao",
            "milega", "milegi", "hai kya", "kuch hai", "koi hai",
            "के अंदर", "तक", "में",
        )
        for _bm in re.finditer(r"\b([1-9]|1\d|20)\b", text):
            _n = int(_bm.group(1))
            _after = text[_bm.end():_bm.end() + 15]
            if any(w in _after for w in _BARE_BUDGET_CTX):
                q.clarify_budget = _n
                break

    # ── bare 4-digit model year, e.g. "2019 nexon photos" (TASK3) ──
    if q.year_min is None and q.price_max is None and q.price_min is None:
        m = _YEAR_EXACT_RE.search(text)
        if m:
            q.year_exact = int(m.group(0))

    # ── intents: availability ──
    _avail_base = [
        "available", "hai kya", "stock", "abhi hai", "milegi", "milega",
        "stock mein", "piece hai", "chalu hai", "sold out", "sold ho",
        "bik gayi", "abhi bhi hai", "still available", "in stock",
    ]
    if any(_has(text, w) for w in _avail_base + AVAILABILITY_TERMS):
        q.intents.add("availability")

    # ── intents: price ──
    _price_base = [
        "kitne ki", "kitne mein", "price", "kitne ka", "rate", "daam",
        "kitne", "kitna", "how much", "cost", "bhav",
        # Phase 7I.3/7I.4: price synonyms (broken-Hindi + Marathi Latin/Devanagari)
        "kimat", "kimmat", "keemat", "kemat", "kiimat", "daam kya", "kya daam",
        "किंमत", "किमत", "दाम", "भाव",
    ]
    if any(_has(text, w) for w in _price_base + PRICE_TERMS):
        # Phase 12K (F9 fix): a bare AMBIGUOUS field question ("engine kitna hai?",
        # "battery kitni hai?") carries a loose quantity word (kitna/kitne) that
        # belongs to the FIELD, not to price. _bare_ambiguous_field strips only
        # those filler quantity words — an explicit price word ("engine price",
        # "engine ka daam") is NOT stripped, so it still returns None and price
        # stays. When it IS a bare ambiguous field, suppress the spurious price
        # intent so the 12I clarify (capacity/power/condition?) fires instead of
        # the bot wrongly quoting the car's price.
        if not _bare_ambiguous_field(text):
            q.intents.add("price")

    # ── partial registration search (Phase 11C) ──
    # "MH01" -> every car whose number starts MH01; "6922" -> cars whose
    # number contains/ends with those digits. Only when no FULL registration
    # was found, and bare digits only when clearly a number lookup (so years,
    # budgets and km limits are never hijacked).
    if q.registration is None and q.reg_partial is None:
        m = re.search(r"\b([a-z]{2}[\s-]?\d{1,2}(?:[\s-]?[a-z]{1,2})?"
                      r"(?:[\s-]?\d{1,4})?)\b", text)
        if m:
            cand = re.sub(r"[\s-]", "", m.group(1)).upper()
            # letter-led partials must look like a plate start (MH, DL, GJ, …)
            if (len(cand) >= 3 and cand[:2].isalpha()
                    and any(ch.isdigit() for ch in cand)
                    and cand[:2] in ("MH", "DL", "KA", "TN", "GJ", "RJ", "UP",
                                     "HR", "PB", "AP", "TS", "KL", "MP", "CG",
                                     "OD", "WB", "BR", "JH", "AS", "UK", "GA",
                                     "HP", "JK", "CH", "DN")):
                q.reg_partial = cand
        if q.reg_partial is None and q.km_max is None \
                and q.price_max is None and q.price_min is None \
                and q.year_exact is None and q.seats is None:
            # A standalone 3-6 digit number ANYWHERE in the query is treated as a
            # (partial) plate — the last few digits of a registration — so
            # "9999", "price of 9999", "9999 ka price", "insurance of 6922" all
            # resolve to the car. But NOT when the number is clearly a quantity
            # the dedicated parsers didn't catch: a km / lakh / rupee amount
            # (unit word right after) or a budget ("budget 500000", "under …").
            m2 = re.search(r"(?<!\d)(\d{3,6})(?!\d)", text)
            if m2 and not re.fullmatch(r"(19|20)\d{2}", m2.group(1)):
                after = text[m2.end():]
                before = text[:m2.start()]
                unit_after = re.match(
                    r"\s*(km|kms|kilometers?|kilometres?|lakhs?|lacs?|crores?|"
                    r"rupees?|rs)\b", after)
                cue_before = re.search(
                    r"(budget|under|below|upto|up\s*to|niche|andar|kam|"
                    r"less\s*than|max|maximum|rupees?|rs\.?|price\s*range)\s*$",
                    before)
                # Phase 12K: "360 camera" / "360 degree camera" is a FEATURE
                # question — the 360 is part of the camera spec, not a plate. Don't
                # let the standalone-digit heuristic hijack it into a reg lookup.
                spec_number = (m2.group(1) == "360"
                               and re.match(r"\s*(degree\s*)?camera", after))
                if not unit_after and not cue_before and not spec_number:
                    q.reg_partial = m2.group(1)
        if q.reg_partial:
            q.intents.add("availability")

    # ── Phase 12D: new vehicle-detail fields (specs / features / EV / keys /
    #    extra documents). Data-driven detector; reuses cached _has. Deconflicts
    #    the few substring collisions with loose 11A signals. ──
    _af, _ff = field_intents.detect(text)
    if _af or _ff:
        q.attr_fields = _af
        q.feature_filters = _ff
        _all = list(_af) + list(_ff.keys())
        # "boot space" contains "boot" (a Sedan cue) — clear the spurious category
        if "boot_litres" in _af and q.category == "Sedan" and not _has(text, "sedan"):
            q.category = None; q.intents.discard("category")
        # "android auto" contains "auto" (an automatic cue) — clear unless the user
        # also gave an explicit transmission word
        if "android_auto_carplay" in _all and not re.search(
                r"\b(automatic|manual|amt|cvt|dct|dsg|imt|clutch)\b", text):
            q.transmission = None; q.transmission_query = False
            q.intents.discard("transmission")
        # "fuel tank" contains "fuel" — it is a capacity question, not fuel_query
        if "fuel_tank_l" in _af:
            q.fuel_query = False
        # "ev range" contains "ev" (Electric cue) — an EV attribute question, not a
        # fuel browse (unless the user explicitly said 'electric')
        if any(a in _af for a in ("real_range_km", "battery_health_pct",
                                  "charger_type", "charging_time",
                                  "battery_warranty_till", "battery_owned")):
            if q.fuel == FuelType.ELECTRIC and not _has(text, "electric"):
                q.fuel = None; q.intents.discard("fuel")
        if q.attr_fields:
            q.intents.add("field_query")

    # ── Phase 12G: contextual attribute questions (year / odometer / transmission)
    # A bare yes/no or attribute-style question about the car's model year, running
    # or transmission — with NO explicit search/variant wording and NO OTHER model/
    # make/category named — is a QUESTION about the specific car, not a fresh browse
    # or sort. Reinterpret the mis-parsed FILTER as the matching *_query attribute
    # flag: the existing 11A/12D pinned-answer path then answers that car, and when
    # no car is pinned the same flags yield the existing safe "which car?"
    # clarification (never a fabricated answer). A specific registration/partial
    # plate does NOT block this (it pins a single car); only a model/make/category
    # (a class of cars) keeps the search/filter behaviour. Explicit search language
    # ("...wali/chahiye/dikhao/cars/sabse/koi hai") is untouched and keeps searching.
    _p12g_search = _has_search_cue(text)
    _p12g_names_class = (q.model is not None or q.make is not None
                         or q.category is not None)
    if not _p12g_search and not _p12g_names_class:
        # RULE C — transmission: "automatic hai?", "manual hai?", "transmission
        # automatic hai?" set a transmission FILTER above; make it a question.
        if (q.transmission is not None and not q.transmission_query
                and _is_attr_question(text)):
            q.transmission = None
            q.intents.discard("transmission")
            q.transmission_query = True
        # RULE B — odometer: "kam km chali hai?" tripped the low-km SORT; make it
        # this car's odometer question when phrased as a reading question.
        if (q.sort_low_km and q.km_max is None and _is_odo_question(text)):
            q.sort_low_km = False
            q.intents.discard("low_km")
            q.km_reading_query = True
            q.condition_query = False
        # RULE A — year: "2019 model hai?" set a year FILTER, "model year kya hai?"
        # set nothing; make it this car's model-year question.
        if _is_year_question(text, q):
            q.year_exact = None
            q.year_min = None
            q.year_query = True
        # RULE D — fuel (Phase 12I): "petrol hai?", "ye diesel hai?", "पेट्रोल है?"
        # set a fuel FILTER above; with an attribute-question form, no search cue
        # and no other car class or browse filter, treat it as THIS car's fuel
        # question (the fuel analog of RULE C for transmission). A value used as a
        # filter ("petrol wali dikhao", "diesel chahiye", "diesel under 8 lakh")
        # keeps searching — it carries a search cue or a browse filter and never
        # reaches here.
        if (q.fuel is not None and not q.fuel_query
                and _is_attr_question(text)
                and q.price_max is None and q.price_min is None
                and q.km_max is None and q.seats is None
                and not q.sort_cheapest):
            q.fuel = None
            q.intents.discard("fuel")
            q.fuel_query = True
        # RULE E — attribute-PAIR ambiguity (Phase 12J): "automatic aur petrol?"
        # leaves BOTH a transmission and a fuel FILTER set (no `hai` -> RULE C/D
        # did not fire), joined by a coordinator, with no search cue and no browse
        # filter. This is genuinely ambiguous (this car's attributes vs a search),
        # so flag it for a deterministic clarify. "automatic aur petrol hai?" (both
        # converted to queries above) and "automatic petrol wali/chahiye" (search
        # cue) never reach here.
        if (q.transmission is not None and q.fuel is not None
                and not q.transmission_query and not q.fuel_query
                and q.price_max is None and q.price_min is None
                and q.km_max is None and q.seats is None
                and not q.sort_cheapest
                and re.search(r"(?<!\w)(aur|and|plus|va|और|आणि|तसेच|अन्)(?!\w)", text)):
            q.attr_pair_ambiguous = True

    # ── Phase 12I: bare ambiguous field ("engine?", "battery?", "safety
    # features?") — set ONLY when nothing answerable resolved, so the caller can
    # ask ONE clarify instead of dead-ending in a search / "exhausted". Never a
    # guess. A fuller form ("engine capacity", "engine condition", "battery
    # health", "safety rating") resolves a real field above and never reaches
    # here. ──
    if (not q.attr_fields and not q.feature_filters
            and not q.active_filters() and not q.sort_cheapest
            and not q.sort_low_km and not q.registration and not q.reg_partial
            and not q.off_sheet
            and not any(getattr(q, _f, False) for _f in (
                "insurance_query", "service_query", "warranty_detail_query",
                "rc_query", "ownership_query", "condition_query", "flood_query",
                "downpayment_query", "km_reading_query", "color_query",
                "fuel_query", "transmission_query", "seats_query", "year_query"))
            and "price" not in q.intents):
        _amb = _bare_ambiguous_field(text)
        if _amb:
            q.ambiguous_field = _amb

    # default intent if nothing else: availability
    if not q.intents:
        q.intents.add("availability")

    # ── vague-reel clarify (G-REEL aftermath): reel words but no concrete filter ──
    if q.reel_stripped and not q.has_any_filter() and not q.registration:
        q.clarify_needed = True

    return q


_KM_UNIT_RE = r"(?:km|kms|kilometers?|kilometres?|किमी)"


def _parse_km_limit(text: str, q: Query) -> None:
    """Odometer ceiling: 'under 20000 km', '20k kms se kam', 'within 50,000 km',
    '२०००० किमी च्या आत'. Requires an explicit km unit so it never collides with
    price ('under 5 lakh') or year parsing."""
    m = re.search(r"(?:under|below|less than|within|upto|up to|max|maximum|andar)"
                  r"\s+(\d[\d,]*)\s*(k\b)?\s*" + _KM_UNIT_RE, text)
    if not m:
        m = re.search(r"(\d[\d,]*)\s*(k\b)?\s*" + _KM_UNIT_RE +
                      r"\s*(?:se kam|se kum|se km|kam|kum|ke andar|ke under"
                      r"|se niche|se neeche|ke niche|ke neeche|tak"
                      r"|पेक्षा कमी|च्या आत)", text)
    if not m:
        return
    n = int(m.group(1).replace(",", ""))
    if m.group(2):                     # "20k km" → 20,000
        n *= 1000
    q.km_max = n
    q.intents.add("availability")


def _parse_price(text: str, q: Query) -> None:
    """Extract price_max / price_min from lakh / lac / lakhs / L phrases. Deterministic."""
    _CEIL_WORDS = ("under", "below", "within", "tak", "andar", "neeche", "niche",
                   "ke andar", "maximum", "max", "mॅks", "upto", "up to", "se kam",
                   "se kum", "budget", "between", "range", "aas pass", "aas paas",
                   "ke aas",
                   # Hindi / Marathi
                   "खाली", "पर्यंत", "पेक्षा कमी", "पेक्षा", "मॅक्स", "कमी",
                   "रेंज", "आसपास", "बजेट", "के अंदर", "तक")
    _FLOOR_WORDS = ("upar", "above", "over", "se zyada", "se upar",
                    "minimum", "more than", "plus", "se jyada",
                    "पेक्षा जास्त", "जास्त", "वर", "से ज्यादा")

    # "<n> lakh / lac / lakhs" — e.g. "8 lakh", "10 lakhs", "12.5 lac"
    # (broken-Hindi "lak"/"lacs" already normalized to "lakh" by normalize_typos)
    # Also handles reversed order: "lakh 8 ke andar" (from "lak 8 ke andar").
    for m in re.finditer(r"(?:lakh|lac|lakhs)\s+(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:lakh|lac|lakhs)\b", text):
        # group(1) = reversed "lakh N", group(2) = normal "N lakh"
        raw_val = m.group(1) or m.group(2)
        value = int(float(raw_val) * 100_000)
        window = text[max(0, m.start() - 22): m.end() + 14]
        if any(w in window for w in _CEIL_WORDS):
            q.price_max = value
        elif any(w in window for w in _FLOOR_WORDS):
            q.price_min = value
        else:
            q.price_max = value
        q.intents.add("price")

    # Phase 7H.2: Devanagari "लाख" (Marathi/Hindi). Suffixes agglutinate
    # (लाखात, लाखाखाली, लाखापर्यंत…) so match लाख + optional trailing word chars.
    if q.price_max is None and q.price_min is None:
        for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:लाख|लाक)\w*", text):
            value = int(float(m.group(1)) * 100_000)
            window = text[max(0, m.start() - 8): m.end() + 16]
            if any(w in window for w in _FLOOR_WORDS):
                q.price_min = value
            else:
                q.price_max = value      # default + ceil words -> max
            q.intents.add("price")

    # bare "<n>L" or "<n>l" shorthand — e.g. "8L", "10l", "12.5L"
    # only when NOT already parsed above (avoid double-counting)
    if q.price_max is None and q.price_min is None:
        for m in re.finditer(r"(\d+(?:\.\d+)?)\s*l\b", text):
            val_f = float(m.group(1))
            if val_f >= 1:        # guard against "1l km" etc
                value = int(val_f * 100_000)
                window = text[max(0, m.start() - 22): m.end() + 14]
                if any(w in window for w in _CEIL_WORDS):
                    q.price_max = value
                elif any(w in window for w in _FLOOR_WORDS):
                    q.price_min = value
                else:
                    q.price_max = value
                q.intents.add("price")
                break   # only first match

    # "X thousand" / "Xk" budget (entry-level)
    if q.price_max is None and q.price_min is None:
        for m in re.finditer(r"(\d+)\s*(?:thousand|k)\b", text):
            value = int(m.group(1)) * 1000
            if 50_000 <= value <= 20_000_000:   # sanity: 50k to 2Cr
                q.price_max = value
                q.intents.add("price")
                break

    # "X crore" (luxury)
    if q.price_max is None and q.price_min is None:
        for m in re.finditer(r"(\d+(?:\.\d+)?)\s*crore\b", text):
            value = int(float(m.group(1)) * 10_000_000)
            q.price_max = value
            q.intents.add("price")
            break

    # "₹X" or "X rs" or "X rupees"
    if q.price_max is None and q.price_min is None:
        for m in re.finditer(r"(?:₹|rs\.?|rupees?)\s*(\d+(?:\.\d+)?)\b", text):
            value = int(float(m.group(1)))
            if value >= 100_000:    # at least 1 lakh — otherwise not a car budget
                q.price_max = value
                q.intents.add("price")
                break

    # Phase 11A: "below 8" / "under 6" / "upto 10" — a bare small number after an
    # English ceiling word, no unit, is a lakh budget for a used car (nobody means
    # ₹8 for a car). Guarded to 1–40 so it never eats a km ceiling ("under 20000
    # km", handled by _parse_km_limit) or a year.
    if q.price_max is None and q.price_min is None:
        m = re.search(r"\b(?:under|below|upto|up to|within|less than|max|maximum"
                      r"|niche|neeche)\s+(\d{1,2})(?!\d)", text)
        if m:
            n = int(m.group(1))
            after = text[m.end():m.end() + 12]
            if 1 <= n <= 40 and not re.match(
                    r"\s*(k\b|km|kms|kilo|thousand|hazaar|seater|seat|log)", after):
                q.price_max = n * 100_000
                q.intents.add("price")

    if any(_has(text, w) for w in ("sasti", "sasta", "cheapest", "kam budget",
                                   "budget", "sabse kam", "lowest price",
                                   "sasti gaadi", "cheap car")):
        q.sort_cheapest = True
        q.intents.add("price")


# ── Phase 12D: new vehicle-detail field detector (imported last to avoid a
#    circular import — field_intents imports _norm/_has from this module). ──
import field_intents                                              # noqa: E402
