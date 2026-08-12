"""
faq_router.py
=============

The new front-door router (Phase 3B). Deterministic — NO LLM.

    customer message
          │
          ▼  FAQRouter.classify()
    ┌──────────────┬──────────────────────┬───────────────────────────┐
    │ FAQ query    │ inventory query      │ unknown                   │
    │ → faq_engine │ → retrieval_engine   │ → mark_for_future_llm     │
    └──────────────┴──────────────────────┴───────────────────────────┘

Precedence:
  1. FAQ      — `faq_engine.resolve()` matches a supported FAQ intent.
  2. Inventory — the message carries a concrete inventory signal
                 (a model/make/colour/fuel/… filter, or an availability/price word).
  3. Unknown  — none of the above. We DO NOT call an LLM here; we only return
                `intent = "unknown"` and flag `mark_for_future_llm = True`.

The router itself does not run retrieval — it returns `kind="inventory"` plus the
parsed query, and the caller (chat_service) runs the existing retrieval path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import faq_engine
import faq_templates as T
from faq_engine import FAQResult
from language_detector import detect_language
from media_lookup import detect_media_intent
from query_parser import parse, Query, _norm, _has


class RouteKind:
    FAQ = "faq"
    INVENTORY = "inventory"
    UNKNOWN = "unknown"


@dataclass
class RouteResult:
    kind: str                       # faq | inventory | unknown
    language: str
    intent: Optional[str] = None    # faq intent, or 'unknown'; None for inventory
    faq: Optional[FAQResult] = None
    query: Optional[Query] = None
    mark_for_future_llm: bool = False


# words that indicate a genuine inventory lookup even without an extracted filter
_INVENTORY_WORDS = [
    "available", "availability", "stock", "in stock", "milega", "milegi",
    "abhi hai", "hai kya", "kitne ki", "kitne mein", "kitna", "kitne",
    "price", "rate", "daam", "kaise hai", "konsi gaadi hai", "koi gaadi",
    # Phase 7H: catalogue / "show me everything" inventory asks (no filter)
    "what cars", "what car", "what do you have", "whats available",
    "what's available", "show catalogue", "show catalog", "show all",
    "show everything", "all options", "all cars", "full list", "full inventory",
    "current inventory", "complete list", "fresh arrivals", "new arrivals",
    "cars added", "new stock", "list please", "show me", "options available",
    "fuel efficient", "fuel economy", "good mileage", "best mileage", "mileage",
    # Phase 7H.2 broken-Hindi catalogue / price
    "kya kya car", "kya kya gaadi", "puri list", "sab dikhao", "sab options",
    "naya kya aaya", "aaj kya add", "katalog dikhao", "sab car",
    "kimat", "kimmat", "quote", "quote do", "kitne ki hai", "daam kya",
    # Marathi (Devanagari) catalogue / price
    "कोणत्या गाड्या", "सगळ्या उपलब्ध", "पूर्ण list", "सगळे पर्याय", "नवीन काय आले",
    "सगळे दाखवा", "आज काय", "गाड्या आहेत", "किंमत", "किती आहे", "एकूण किती",
    "बेस्ट किंमत", "फायनल किंमत", "खरी किंमत", "सगळ्यात कमी किंमत", "quote द्या",
    "catalogue", "मायलेज", "इंधन", "इंधन कमी", "इंधन बचत", "कमी खाणारी",
    "records पूर्ण",
]


# ── Phase 4C.2: generic "I want a car" buyer-intent words (no filter present) ──
_GENERAL_INTENT_WORDS = [
    "gaadi chahiye", "gadi chahiye", "car chahiye", "vehicle chahiye",
    "gaadi dekhna", "gaadi dekh", "gaadi le", "car le raha", "car lena",
    "looking for a used car", "looking for a car", "looking to buy a car",
    "find a good car", "find a car", "buy a car", "good car",
    "suggest karo", "suggest kijiye", "konsa lu", "konsi le", "kya le",
    "kya lena chahiye", "best kya hai", "achi gaadi", "achhi gaadi",
    # Phase 7I.3/7I.4: bare "car / gaadi / gadi" buyer intent (broken-Hindi/Marathi)
    "gaadi", "gadi", "bhai gadi", "bhai gaadi", "gaddi", "ek gaadi", "ek gadi",
    # Hindi (Devanagari)
    "गाड़ी चाहिए", "गाड़ी देखनी", "गाड़ी के बारे में जानकारी", "कार चाहिए",
    "गाड़ी लेनी है", "अच्छी गाड़ी",
    # Marathi
    "gaadi pahije", "gadi pahije", "gaadi ghyaychi", "gadi ghyaychi",
    "gaadi havi", "gadi havi",
]


def has_general_intent(message: str) -> bool:
    text = _norm(message)
    return any(_has(text, _norm(w)) for w in _GENERAL_INTENT_WORDS)


# ── Phase 7H: deterministic greeting detection (no LLM) ──────────────────────
_GREETING_WORDS = [
    "hi", "hii", "hiii", "hello", "helo", "hey", "heyy", "heyyy", "hey there",
    "hello there", "hello hello", "hello team", "good morning", "good afternoon",
    "good evening", "gud morning", "morning", "namaste", "namaskar", "namaskaar",
    "salaam", "salam", "anyone there", "is anyone there", "hi good morning",
    # Phase 7H.2 broken-Hindi greeting variants
    "namste", "namste ji", "namste bhai", "subh prabhat", "shubh prabhat",
    "subh din", "shubh din", "kya ho bhai", "kya haal", "kya chal raha",
    "kaise ho", "kaise hain", "bhai sab theek", "sab theek", "ram ram",
    # Devanagari (Hindi + Marathi)
    "नमस्ते", "नमस्कार", "हॅलो", "हाय", "सुप्रभात", "हेलो", "शुभ सकाळ",
    "कसे आहात", "बरं आहे का", "कसं आहे", "राम राम",
]


def is_greeting(message: str) -> bool:
    text = _norm(message)
    return any(_has(text, _norm(w)) for w in _GREETING_WORDS)


# ── Phase 7H: vague follow-up phrases (need prior-turn context we don't have) ─
_VAGUE_FOLLOWUP_WORDS = [
    "tell me more", "show more about", "more about it", "more about that",
    "that car you showed", "the car you showed", "car you showed earlier",
    "the one you showed", "about that one", "that one",
    # Phase 7H.2 broken-Hindi
    "uske bare mein", "uske baare mein", "wo car jo dikhayi", "wo car jo dikhaya",
    "pehle wali car", "pehle wali", "ab bhi h kya", "wo neksn", "wo wali",
    # Marathi (Devanagari)
    "त्याबद्दल अजून", "तुम्ही दाखवलेली गाडी", "आधीची गाडी", "त्याच गाडी",
    "अजून उपलब्ध आहे",
]


def is_vague_followup(message: str) -> bool:
    text = _norm(message)
    return any(_has(text, _norm(w)) for w in _VAGUE_FOLLOWUP_WORDS)


def has_inventory_signal(message: str, q: Query) -> bool:
    if q.has_any_filter():           # a concrete filter was extracted
        return True
    if q.model or q.make:            # a vehicle was named
        return True
    text = _norm(message)
    return any(_has(text, _norm(w)) for w in _INVENTORY_WORDS)


class FAQRouter:
    def classify(self, message: str, language: Optional[str] = None) -> RouteResult:
        # `language` override (Phase 7O.6): when supplied, it is used as the reply
        # language instead of per-message detection. detect_intent / template_key
        # / inventory-signal decisions are all language-INDEPENDENT, so this only
        # changes the rendered reply language, never the routing or the query.
        language = language or detect_language(message)

        # 0) registration number -> exact vehicle, takes precedence over FAQ
        # (e.g. "finance MH01BK9444" should resolve the car, not the FAQ template)
        q = parse(message)
        if q.registration:
            return RouteResult(kind=RouteKind.INVENTORY, language=language, query=q)

        # 0.5) Vehicle-specific detail queries bypass FAQ templates so
        # response_formatter can answer from actual spreadsheet data.
        _detail_query = (
            q.condition_query or q.downpayment_query or
            q.service_query or q.rc_query or
            q.flood_query or q.warranty_detail_query or
            q.insurance_query or
            # Phase 11A: km reading + colour / fuel / transmission / seats
            q.km_reading_query or q.color_query or q.fuel_query or
            q.transmission_query or q.seats_query or
            # Phase 12D: new vehicle-detail attribute questions
            bool(q.attr_fields)
        )
        if _detail_query and (q.model or q.registration or q.make):
            return RouteResult(kind=RouteKind.INVENTORY, language=language, query=q)

        # Also route bare detail queries (no vehicle specified) to inventory so
        # response_formatter can show DNA ("Data not available.") rather than a
        # generic FAQ template when no matching car is found.
        # Phase 7H: include condition / insurance / ownership so these stop
        # falling through to "unknown" when no vehicle is named.
        # Phase 12K (N-1): `warranty_detail_query` is deliberately EXCLUDED here.
        # With NO vehicle named/pinned, a bare "warranty milegi?" / "warranty
        # available?" is a general POLICY question — it should fall through to the
        # FAQ warranty template below, not dead-end in a "which car?" clarify. A
        # warranty question ON a specific car still routes to inventory via the
        # vehicle-named block above (and, for a pinned car, via the appended reg).
        if (q.service_query or q.rc_query or q.flood_query
                or q.condition_query or q.insurance_query or q.ownership_query
                # Phase 11A: km reading + colour / fuel / transmission / seats
                or q.km_reading_query or q.color_query or q.fuel_query
                or q.transmission_query or q.seats_query
                or bool(q.attr_fields)):          # Phase 12D new-field attr Qs
            return RouteResult(kind=RouteKind.INVENTORY, language=language, query=q)

        # Phase 12I: a bare AMBIGUOUS field ("engine?", "battery?", "safety
        # features?") routes to inventory so _handle_retrieval can return ONE
        # deterministic clarify — never "unknown", never a guessed answer, never a
        # fresh inventory dump.
        if getattr(q, "ambiguous_field", None):
            return RouteResult(kind=RouteKind.INVENTORY, language=language, query=q)

        # 1) FAQ — deterministic, highest precedence
        faq = faq_engine.resolve(message, language)
        if faq is not None:
            return RouteResult(kind=RouteKind.FAQ, language=language,
                               intent=faq.intent, faq=faq)

        # 2) Inventory — concrete inventory signal
        if has_inventory_signal(message, q):
            return RouteResult(kind=RouteKind.INVENTORY, language=language, query=q)

        # 2.5) Phase 4C.2 — no concrete filter/model extracted, but the message
        # is still a clear buyer-intent / media / comparison ask. Resolve these
        # deterministically with a clarifying FAQ-style response instead of
        # falling through to "unknown".
        no_filter = not q.has_any_filter() and not q.model and not q.make

        if no_filter and detect_media_intent(message):
            resp = T.render("media_clarify", language)
            faq = FAQResult(intent="media_clarify", response=resp,
                            language=language, template_key="media_clarify")
            return RouteResult(kind=RouteKind.FAQ, language=language,
                               intent=faq.intent, faq=faq)

        if no_filter and has_general_intent(message):
            resp = T.render("general_help", language)
            faq = FAQResult(intent="general_intent", response=resp,
                            language=language, template_key="general_help")
            return RouteResult(kind=RouteKind.FAQ, language=language,
                               intent=faq.intent, faq=faq)

        # 2.55) Phase 7H — vague follow-up with no vehicle context (stateless).
        # "tell me more", "that car you showed" etc. carry no filter and depend
        # on a prior turn we don't have here → ask a clarifying question rather
        # than returning "unknown".
        if no_filter and is_vague_followup(message):
            resp = T.render("general_help", language)
            faq = FAQResult(intent="clarify", response=resp,
                            language=language, template_key="general_help")
            return RouteResult(kind=RouteKind.FAQ, language=language,
                               intent=faq.intent, faq=faq)

        # 2.6) Phase 7H — pure greeting (checked LAST so a real query that merely
        # opens with "hi ..." still routes to FAQ/inventory above). Deterministic.
        if no_filter and is_greeting(message):
            resp = T.render("greeting", language)
            faq = FAQResult(intent="greeting", response=resp,
                            language=language, template_key="greeting")
            return RouteResult(kind=RouteKind.FAQ, language=language,
                               intent=faq.intent, faq=faq)

        # 3) Unknown — defer (no LLM in this phase)
        return RouteResult(kind=RouteKind.UNKNOWN, language=language,
                           intent="unknown", query=q, mark_for_future_llm=True)


if __name__ == "__main__":
    r = FAQRouter()
    for m in ["Loan milega?", "Finance available?", "Last price?", "Discount?",
              "Address bhejo", "Location send karo", "Exchange karoge?",
              "आज ओपन आहे का?", "फायनान्स मिळेल का?",
              "Creta available?", "SUV under 8 lakh", "Fortuner price?",
              "jo reel mein thi woh gaadi", "hello there"]:
        rr = r.classify(m)
        print(f"{rr.kind:10} intent={str(rr.intent):12} lang={rr.language:8} <- {m}")
