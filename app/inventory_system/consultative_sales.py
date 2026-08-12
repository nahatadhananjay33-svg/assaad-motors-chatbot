"""
consultative_sales.py  —  Phase 7P.1 consultative selling layer
================================================================

A *very small* recommendation layer that makes the bot sound like a salesperson
instead of an inventory search engine. It is purely additive and changes ONLY
the response TEXT for broad "entry" intents (family / budget / SUV / sedan /
hatchback / CNG / automatic / city-use / first-car). It NEVER touches:

    retrieval · memory · inventory matching · price logic · media logic ·
    Marathi logic · low-KM · Astor fix · lead capture

Before (inventory dump):
    "Haan, 8 options hain — jaise 2019 Blue Ertiga, 2019 ..."
After (consultative):
    "Family ke liye Ertiga aur Marazzo achi rahengi.

     Kitne members hain family mein?"

The vehicle cards (ChatResult.vehicles) are left completely untouched — only the
spoken intro is replaced with ONE recommendation (max 2 vehicles) + ONE question.

Design guarantees:
  * Recommendations come ONLY from CURRENT inventory. We pick from the actual
    ranked match models of THIS search (which already respect every filter,
    including price), so a named car is always available and in-budget. No
    hardcoded unavailable cars.
  * Exactly one question, every response under three lines.
  * Deterministic; no LLM.
"""
from __future__ import annotations

import re
from typing import List, Optional

# ─────────────────────────────────────────────────────────────────────────────
# Per-intent recommendation preference + the single consultative question.
# `prefs`   : model names we PREFER to headline, in order. Only those that are
#             actually in this search's matches are ever named, so nothing
#             unavailable is recommended.
# `lead`    : recommendation sentence template ({a} / {b} = vehicle names).
# `question`: the ONE consultative follow-up question.
# ─────────────────────────────────────────────────────────────────────────────
_INTENTS = {
    "family": {
        "prefs": ["Ertiga", "Marazzo", "Innova", "Mobilio"],
        "lead_two": "Family ke liye {a} aur {b} achi rahengi.",
        "lead_one": "Family ke liye {a} achi rahegi.",
        "question": "Kitne members hain family mein?",
    },
    "suv": {
        "prefs": ["Nexon", "Sonet", "Creta", "Astor", "EcoSport", "WRV", "TUV300"],
        "lead_two": "SUV mein {a} aur {b} achi options hain.",
        "lead_one": "SUV mein {a} achi option hai.",
        "question": "City use ya highway use?",
    },
    "sedan": {
        "prefs": ["City", "Ciaz", "Corolla Altis", "Dzire", "Rapid", "Vento", "Xcent"],
        "lead_two": "Sedan mein {a} aur {b} achi rahengi.",
        "lead_one": "Sedan mein {a} achi rahegi.",
        "question": "Zyada city use ya highway?",
    },
    "hatchback": {
        "prefs": ["Polo", "Grand i10", "WagonR", "Alto", "Spark"],
        "lead_two": "City ke liye {a} aur {b} hatchback achi hain.",
        "lead_one": "City ke liye {a} hatchback achi hai.",
        "question": "Daily city use ke liye chahiye?",
    },
    "budget": {
        "prefs": ["Polo", "Grand i10", "KUV100", "WagonR", "Alto", "Spark", "Tigor"],
        "lead_two": "Budget mein {a} aur {b} value ke liye best hain.",
        "lead_one": "Budget mein {a} value ke liye best hai.",
        "question": "Budget flexible hai ya strict?",
    },
    "cng": {
        "prefs": ["Tigor", "WagonR", "Alto", "Ciaz", "Xcent", "Dzire"],
        "lead_two": "CNG mein {a} aur {b} best rahengi.",
        "lead_one": "CNG mein {a} best rahegi.",
        "question": "Daily running zyada hai?",
    },
    "automatic": {
        "prefs": ["Ertiga", "Nexon", "C Class", "TUV300", "Tigor", "A4"],
        "lead_two": "Automatic mein {a} aur {b} achi rahengi.",
        "lead_one": "Automatic mein {a} achi rahegi.",
        "question": "Daily traffic use ke liye chahiye?",
    },
    "city_use": {
        "prefs": ["Grand i10", "WagonR", "Polo", "Alto", "City", "Spark"],
        "lead_two": "City use ke liye {a} aur {b} perfect hain.",
        "lead_one": "City use ke liye {a} perfect hai.",
        "question": "Roz kitne km chalana hota hai?",
    },
    "first_car": {
        "prefs": ["Alto", "Grand i10", "WagonR", "Polo", "Spark"],
        "lead_two": "Pehli car ke liye {a} aur {b} easy aur reliable hain.",
        "lead_one": "Pehli car ke liye {a} easy aur reliable hai.",
        "question": "Budget kitna soch rahe hain?",
    },
}

# Detection keywords. Order in `_DETECT_ORDER` is the priority when several match.
_KEYWORDS = {
    "family":     (" family", " parivar", " ghar ke liye", " bacho", " bachho", " kids"),
    "first_car":  (" first car", " pehli car", " pehli gaadi", " pehli gadi",
                   " naya driver", " learner", " beginner"),
    "city_use":   (" city use", " city ke liye", " shahar", " sheher", " local use"),
    "suv":        (" suv",),
    "sedan":      (" sedan",),
    "hatchback":  (" hatchback", " hatch back", " chhoti car", " choti car"),
    "cng":        (" cng",),
    "automatic":  (" automatic", " auto gear", " automatic gear"),
    "budget":     (" budget", " sasti", " saste", " cheap", " affordable",
                   " kam paise", " kam daam"),
}
# Higher-signal / more specific intents win over generic ones.
_DETECT_ORDER = ["first_car", "family", "city_use", "suv", "sedan", "hatchback",
                 "cng", "automatic", "budget"]


def detect_intent(message: str, q) -> Optional[str]:
    """Return the consultative entry-intent for `message`, or None.

    Combines the parsed query `q` (so "SUV chahiye" / "sedan dikhao" /
    "CNG car" / "automatic" / "5 lakh ke andar" are caught structurally) with a
    light keyword scan for the soft intents the parser does not categorise
    (family / first-car / city-use / budget-only). A query that already names a
    specific model / make / registration is NOT a broad entry intent."""
    if q is None:
        return None
    if q.model or q.make or q.registration:
        return None
    # low-KM is its own (untouched) sort path — never a consultative entry.
    if getattr(q, "sort_low_km", False):
        return None

    text = " " + re.sub(r"\s+", " ", (message or "").strip().lower()) + " "

    # 1) keyword detection, by priority
    for intent in _DETECT_ORDER:
        if any(k in text for k in _KEYWORDS[intent]):
            return intent

    # 2) structural detection from the parsed query
    cat = (q.category or "")
    if cat == "MUV":
        return "family"
    if cat in ("SUV", "Compact-SUV"):
        return "suv"
    if cat == "Sedan":
        return "sedan"
    if cat == "Hatchback":
        return "hatchback"
    if q.fuel == "CNG":
        return "cng"
    if q.transmission == "Automatic":
        return "automatic"
    # budget-only: a price ceiling/floor or cheapest sort with NO other dimension.
    if (q.price_max is not None or q.price_min is not None
            or getattr(q, "sort_cheapest", False)):
        return "budget"
    return None


def _distinct_models(model_list: List[str]) -> List[str]:
    seen, out = set(), []
    for m in model_list:
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


def pick_recommendations(intent: str, match_models: List[str]) -> List[str]:
    """Up to TWO model names to headline, drawn ONLY from this search's ranked
    match models (so they are guaranteed available and within every active
    filter). Preferred models for the intent are surfaced first; any remaining
    slot is filled from the top of the ranked matches."""
    avail = _distinct_models(match_models)
    if not avail:
        return []
    spec = _INTENTS.get(intent, {})
    prefs = spec.get("prefs", [])
    recs = [m for m in prefs if m in avail][:2]
    if len(recs) < 2:
        for m in avail:
            if m not in recs:
                recs.append(m)
            if len(recs) >= 2:
                break
    return recs[:2]


def build_intro(intent: str, recs: List[str]) -> Optional[str]:
    """Two-line consultative intro: ONE recommendation (<=2 cars) + ONE question.
    Returns None if there is nothing concrete to recommend."""
    spec = _INTENTS.get(intent)
    if not spec or not recs:
        return None
    if len(recs) >= 2:
        lead = spec["lead_two"].format(a=recs[0], b=recs[1])
    else:
        lead = spec["lead_one"].format(a=recs[0])
    return f"{lead}\n\n{spec['question']}"


def consultative_intro(intent: str, match_models: List[str]) -> Optional[str]:
    """Convenience: detect -> recommend -> build, given the intent and the
    search's ranked match models. Returns the intro text or None."""
    recs = pick_recommendations(intent, match_models)
    return build_intro(intent, recs)
