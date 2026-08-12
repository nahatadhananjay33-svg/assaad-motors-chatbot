"""
slang_aliases.py
================

Hinglish / Marathi slang normalization tables for query_parser.py.
These are attribute / intent phrase variants — NOT make/model names.

Imported by query_parser.py only.  No business logic here.
"""

from __future__ import annotations
from typing import Dict, List

# ── Fuel slang (alias -> FuelType string) ────────────────────────────────────
FUEL_SLANG: Dict[str, str] = {
    "dijal":           "Diesel",
    "diesel wali":     "Diesel",
    "diesel wala":     "Diesel",
    "diesel gaadi":    "Diesel",
    "petrol wali":     "Petrol",
    "petrol wala":     "Petrol",
    "peterol":         "Petrol",
    "patrol":          "Petrol",        # common misspelling
    "petrol gaadi":    "Petrol",
    "electric wali":   "Electric",
    "electric wala":   "Electric",
    "battery wali":    "Electric",
    "battery wala":    "Electric",
    "charging wali":   "Electric",
    "ev wali":         "Electric",
    "ev gaadi":        "Electric",
    "cng wali":        "CNG",
    "cng wala":        "CNG",
    "cng gaadi":       "CNG",
    "cng kit":         "CNG",
    "gas wali":        "CNG",
    "gas gaadi":       "CNG",
    "petrol cng":      "Petrol+CNG",
    "dual fuel":       "Petrol+CNG",
    "hybrid wali":     "Hybrid",
    "hybrid wala":     "Hybrid",
    "strong hybrid":   "Hybrid",
    "self charging":   "Hybrid",
}

# ── Transmission: automatic indicators ───────────────────────────────────────
TRANSMISSION_AUTO_TERMS: List[str] = [
    "gear nahi", "clutch nahi", "no clutch", "bina clutch",
    "bina gear", "clutch free", "gear free",
    "automatic wali", "automatic wala", "auto wali", "auto wala",
    "amt wali", "amt wala", "amt gaadi",
    "cvt wali", "cvt wala",
    "dct", "dsg", "imt", "tiptronic", "torque converter",
    "automatic transmission", "automatic gaadi",
    "gear nahi chahiye", "self drive", "self gear",
    "selfie gear",
    # Hinglish combos
    "auto gear", "at gear",
]

# ── Transmission: manual indicators ─────────────────────────────────────────
TRANSMISSION_MANUAL_TERMS: List[str] = [
    "manual gear", "manual wali", "manual wala",
    "haath wali gear", "haath se gear",
    "manual transmission", "manual gaadi",
    "clutch wali gaadi", "clutch wala",
]

# ── Availability slang ───────────────────────────────────────────────────────
AVAILABILITY_TERMS: List[str] = [
    # Hinglish
    "hai kya", "abhi hai", "stock mein hai", "available hai kya",
    "milega kya", "milegi kya", "piece hai kya", "chalu hai kya",
    "bik gayi kya", "sold ho gayi kya", "chali gayi kya",
    "gayi toh nahi", "sold out toh nahi",
    "still with you", "still there",
    "rok ke rakhoge", "hold kar sakte",
    # Marathi Latin
    "aahe ka", "aahet ka", "ahe ka",
    "piece aahe ka", "piece ahe ka",
    "milel ka", "milel kaa",
    "vikli geli ka", "vikla ka", "vikle ka",
    "baki aahe ka", "sadhya aahe", "sadhya ahe",
    "ajun aahe", "ajun ahe",
    "ti aahe ka", "ti ahe ka",
    "sold zali ka", "sold zala ka",
    "thevu shakta ka",
]

# ── Price / rate slang ────────────────────────────────────────────────────────
PRICE_TERMS: List[str] = [
    "kitne ki", "kitne ka", "kitne mein",
    "rate kya", "rate batao", "rate bolo",
    "price kya", "daam kya", "bhav kya",
    "last kya", "last kitna", "last price kya",
    "how much for", "cost kya",
    # Marathi
    "kiti aahe", "kiti ahe", "kiti deta", "kiti gheta",
]

# ── Ownership: first owner phrases ────────────────────────────────────────────
OWNERSHIP_FIRST: List[str] = [
    "first owner", "single owner", "1st owner", "one owner",
    "ek owner", "ek hi owner", "first hand", "ek hi haath",
    "pehla malik", "pehle malik", "pehla owner", "ek malik",
    "1 owner", "one hand", "single hand",
    "pehla haath", "ek haath",
    # Marathi
    "pahila malik", "ek maalik", "pahilya hatacha",
]

# ── Ownership: second owner phrases ───────────────────────────────────────────
OWNERSHIP_SECOND: List[str] = [
    "second owner", "2nd owner", "2 owner", "doosra owner",
    "doosra malik", "dusra owner", "2nd hand", "second hand",
]

# ── Ownership: max / "fewer owners" phrases ───────────────────────────────────
# "Few owners" FILTER phrases only (=> ownership_max=2). Phase 12K: the QUESTION
# forms ("kitne owner", "how many owners", "kitne maalik", "kiti malik/maalik")
# were removed from here — they are owner-COUNT questions (handled by
# ownership_query), NOT a "≤2 owners" filter. Leaving them here made
# "kitne owner the?" silently filter out cars with 3+ owners (J multi-car bug).
OWNERSHIP_FEW: List[str] = [
    "kam owner", "kam maalik", "ek hi maalik", "kam malik",
]

# ── Color additions (alias -> canonical color string) ────────────────────────
COLOR_ADDITIONS: Dict[str, str] = {
    "maroon":          "Maroon",
    "wine":            "Maroon",
    "wine red":        "Maroon",
    "purple":          "Purple",
    "violet":          "Purple",
    "bronze":          "Bronze",
    "copper":          "Bronze",
    "sky blue":        "Blue",
    "navy":            "Blue",
    "navy blue":       "Blue",
    "royal blue":      "Blue",
    "off white":       "White",
    "pearl white":     "White",
    "pearl":           "White",
    "cream":           "Beige",
    "ivory":           "Beige",
    "champagne":       "Beige",
    "metallic grey":   "Grey",
    "metallic gray":   "Grey",
    "metallic silver": "Silver",
    "dark grey":       "Grey",
    "dark gray":       "Grey",
    # Hindi
    "safed":           "White",
    "kaala":           "Black",
    "kala":            "Black",
    "laal":            "Red",
    "lal":             "Red",
    "neela":           "Blue",
    "neeli":           "Blue",
    "hara":            "Green",
    "hari":            "Green",
    "peela":           "Yellow",
    "pila":            "Yellow",
    "naaraingi":       "Orange",
    "narangi":         "Orange",
    # Marathi
    "pandhra":         "White",
    "pandra":          "White",
    "piwala":          "Yellow",
    "hirwa":           "Green",
    "nila":            "Blue",
}
