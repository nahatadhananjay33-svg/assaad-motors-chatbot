"""
model_aliases.py
================

Extended model alias dictionary for query_parser.py.
Supplements inventory_loader.MODEL_ALIASES with the full Indian used-car market
covering models that appear in buyer queries but may not be in current DNJ stock.

Format: {alias_lower: canonical_name}

Includes:
  - spacing variations  (xuv 700 / xuv700 / xuv-700)
  - hyphen variations   (scorpio-n / scorpio n)
  - case-folded forms   (handled by caller via .lower())
  - common misspellings (scorpion, ertica, ...)
  - number-name models  (3 series, q3, a4, ...)
"""

from __future__ import annotations
from typing import Dict

EXTENDED_MODEL_ALIASES: Dict[str, str] = {
    # ── Mahindra ─────────────────────────────────────────────────────────────
    "scorpio": "Scorpio",
    "scorpion": "Scorpio",           # common misspelling
    "scorpio n": "Scorpio N",
    "scorpio-n": "Scorpio N",
    "scorpioo n": "Scorpio N",
    "scorpio classic": "Scorpio Classic",
    "scorpio clasic": "Scorpio Classic",
    "xuv700": "XUV700",
    "xuv 700": "XUV700",
    "xuv-700": "XUV700",
    "xuv 700 ax7": "XUV700",
    "xuv300": "XUV300",
    "xuv 300": "XUV300",
    "xuv-300": "XUV300",
    "xuv3xo": "XUV300",
    "3xo": "XUV300",
    "thar": "Thar",
    "thar roxx": "Thar Roxx",
    "bolero": "Bolero",
    "bolero neo": "Bolero Neo",
    "bolero plus": "Bolero",
    "marazzo": "Marazzo",
    "marazo": "Marazzo",

    # ── Tata ─────────────────────────────────────────────────────────────────
    "harrier": "Harrier",
    "safari": "Safari",
    "altroz": "Altroz",
    "tigor": "Tigor",
    "tigor ev": "Tigor EV",
    "tigor e v": "Tigor EV",
    "tiago": "Tiago",
    "tiago nrg": "Tiago NRG",
    "tiago ev": "Tiago EV",
    "tiago e v": "Tiago EV",
    "nexon ev": "Nexon EV",
    "nexon e v": "Nexon EV",
    "curvv": "Curvv",
    "exter": "Exter",
    "nexon": "Nexon",

    # ── Maruti Suzuki ─────────────────────────────────────────────────────────
    "baleno": "Baleno",
    "baleno alpha": "Baleno",
    "baleno zeta": "Baleno",
    "glanza": "Glanza",
    "fronx": "Fronx",
    "jimny": "Jimny",
    "grand vitara": "Grand Vitara",
    "grandvitara": "Grand Vitara",
    "xl6": "XL6",
    "xl 6": "XL6",
    "xl-6": "XL6",
    "s-presso": "S-Presso",
    "spresso": "S-Presso",
    "s presso": "S-Presso",
    "ignis": "Ignis",
    "celerio x": "Celerio X",
    "s cross": "S-Cross",
    "s-cross": "S-Cross",
    "scross": "S-Cross",
    "dzire": "Dzire",
    "swift dzire": "Dzire",
    "ertica": "Ertiga",         # misspelling
    "ertiga": "Ertiga",
    "ciaz": "Ciaz",
    "alto k10": "Alto K10",
    "celerio": "Celerio",

    # ── Hyundai ──────────────────────────────────────────────────────────────
    "aura": "Aura",
    "venue": "Venue",
    "alcazar": "Alcazar",
    "tucson": "Tucson",
    "kona": "Kona",
    "kona ev": "Kona EV",
    "i20 n line": "i20 N Line",
    "i20 nline": "i20 N Line",
    "i20 n": "i20 N Line",
    "verna": "Verna",
    "elantra": "Elantra",
    "creta": "Creta",

    # ── Kia ──────────────────────────────────────────────────────────────────
    "sonet": "Sonet",
    "seltos": "Seltos",
    "carens": "Carens",
    "carnival": "Carnival",
    "ev6": "EV6",
    "ev 6": "EV6",

    # ── Toyota ───────────────────────────────────────────────────────────────
    "urban cruiser": "Urban Cruiser",
    "hyryder": "Hyryder",
    "urban cruiser hyryder": "Hyryder",
    "taisor": "Taisor",
    "rumion": "Rumion",
    "hilux": "Hilux",
    "vellfire": "Vellfire",
    "innova hycross": "Innova Hycross",
    "hycross": "Innova Hycross",
    "innova crysta": "Innova Crysta",
    "crysta": "Innova Crysta",
    "fortuner": "Fortuner",
    "legender": "Fortuner",         # sub-variant
    "innova": "Innova",

    # ── Volkswagen / Skoda ───────────────────────────────────────────────────
    "virtus": "Virtus",
    "taigun": "Taigun",
    "tiguan": "Tiguan",
    "slavia": "Slavia",
    "kushaq": "Kushaq",
    "kodiaq": "Kodiaq",
    "octavia": "Octavia",
    "superb": "Superb",
    "rapid": "Rapid",
    "vento": "Vento",
    "polo": "Polo",

    # ── MG ───────────────────────────────────────────────────────────────────
    "hector": "Hector",
    "hector plus": "Hector Plus",
    "gloster": "Gloster",
    "astor": "Astor",
    "comet": "Comet EV",
    "comet ev": "Comet EV",
    "zs ev": "ZS EV",
    "zs": "ZS EV",

    # ── Honda ────────────────────────────────────────────────────────────────
    "elevate": "Elevate",
    "city": "City",
    "amaze": "Amaze",
    "jazz": "Jazz",
    "wrv": "WRV",
    "wr v": "WRV",
    "brv": "BRV",
    "br v": "BRV",
    "crv": "CRV",

    # ── Renault / Nissan ─────────────────────────────────────────────────────
    "magnite": "Magnite",
    "kiger": "Kiger",
    "triber": "Triber",
    "kicks": "Kicks",
    "duster": "Duster",
    "kwid": "Kwid",
    "kwid climber": "Kwid",
    "terrano": "Terrano",

    # ── Premium / Luxury — BMW ───────────────────────────────────────────────
    "3 series": "3 Series",
    "3series": "3 Series",
    "5 series": "5 Series",
    "5series": "5 Series",
    "7 series": "7 Series",
    "7series": "7 Series",
    "x1": "X1",
    "bmw x1": "X1",
    "x3": "X3",
    "bmw x3": "X3",
    "x5": "X5",
    "bmw x5": "X5",
    "x7": "X7",
    "bmw x7": "X7",
    "320d": "320d",
    "320": "320d",
    "520d": "520d",
    "530d": "530d",

    # ── Premium / Luxury — Audi ──────────────────────────────────────────────
    "q3": "Q3",
    "audi q3": "Q3",
    "q5": "Q5",
    "audi q5": "Q5",
    "q7": "Q7",
    "audi q7": "Q7",
    "a4": "A4",
    "audi a4": "A4",
    "a6": "A6",
    "audi a6": "A6",
    "a8": "A8",
    "audi a8": "A8",

    # ── Premium / Luxury — Mercedes ──────────────────────────────────────────
    "gla": "GLA",
    "gla class": "GLA",
    "mercedes gla": "GLA",
    "glc": "GLC",
    "glc class": "GLC",
    "gle": "GLE",
    "glb": "GLB",
    "c class": "C Class",
    "c-class": "C Class",
    "e class": "E Class",
    "e-class": "E Class",
    "cla": "CLA",
    "a class": "A Class",
    "a-class": "A Class",

    # ── Premium / Luxury — Volvo ──────────────────────────────────────────────
    "xc40": "XC40",
    "xc 40": "XC40",
    "xc60": "XC60",
    "xc 60": "XC60",
    "xc90": "XC90",

    # ── Jeep ─────────────────────────────────────────────────────────────────
    "compass": "Compass",
    "meridian": "Meridian",
    "wrangler": "Wrangler",
    "grand cherokee": "Grand Cherokee",

    # ── Jaguar / Land Rover ───────────────────────────────────────────────────
    "discovery": "Discovery",
    "range rover": "Range Rover",
    "defender": "Defender",
    "f-pace": "F-Pace",
    "f pace": "F-Pace",

    # ── Misc / one-line aliases ───────────────────────────────────────────────
    "swift": "Swift",
    "wagonr": "WagonR",
    "wagon r": "WagonR",
    "alto": "Alto",
    "alto 800": "Alto 800",
    "santro": "Santro",
}
