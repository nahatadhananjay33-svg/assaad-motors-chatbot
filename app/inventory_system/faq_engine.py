"""
faq_engine.py
=============

Deterministic FAQ resolver — NO LLM. Detects one of the supported FAQ intents
from a customer message and returns the right templated response in the
detected language.

Supported intents (Phase 3B + Phase 4C.1):
    address, location, visit, timing, finance, loan, exchange,
    discount, negotiation, booking,
    rc_transfer, price_inclusions, finance_details,
    warranty, trust_reviews, business_age, refund_policy

Business rules:
  * discount / negotiation -> `price_fixed` template (prices are fixed).
  * finance / loan         -> `finance` (2014+ eligible, no guarantee);
                              if a pre-2014 year is mentioned -> `finance_ineligible`.
  * exchange               -> available, inspection required, no valuation.
  * rc_transfer / papers   -> policy statement (RC + NOC handled at showroom).
  * price_inclusions       -> quoted price is car only; RTO/insurance separate.
  * finance_details        -> EMI/down-payment/interest: visit to confirm.
  * warranty               -> select cars only; eligibility confirmed at visit.
  * trust_reviews          -> verified inventory, honest disclosure.
  * business_age           -> established dealer, visit to verify reputation.
  * refund_policy          -> booking/return terms at showroom.

`resolve()` returns None when the message is not an FAQ (so the router can fall
through to inventory retrieval).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

import faq_templates as T
from language_detector import detect_language


# ─────────────────────────────────────────────────────────────────────────────
# Intent keyword tables (latin lowercased + Devanagari). Substring match.
# Ordered by precedence — first hit wins.
# ─────────────────────────────────────────────────────────────────────────────
_NEGOTIATION = [
    "last price", "best price", "final price", "final rate", "lowest price",
    "best rate", "last rate", "lowest rate", "negotiable", "negotiate",
    "negotiation", "bargain", "mol bhav", "mol-bhav", "kam karo", "kam karoge",
    "kam ho", "kam hoga", "kam kar do", "thoda kam", "price kam", "rate kam",
    "kuch kam", "sasta kar", "final kar", "aakhri", "aakhiri",
    "कम करो", "कम होगा", "कम कर", "दाम कम", "भाव कम", "कमी करा", "कमी होईल",
    "घासाघीस", "आखरी", "अंतिम",
    # ── Phase 12I: indirect price objections (no "discount"/"kam" trigger word) ──
    # These are a polite fixed-price/value response, NOT a fresh budget browse
    # and NOT a fabricated discount. Specific multi-word phrases only, so a
    # genuine cheapest-car search ("sasti gaadi dikhao") is never captured.
    "mehenga", "mehengi", "mehnga", "mehngi", "mahanga", "mahangi", "mahnga",
    "expensive", "too expensive", "so expensive", "very expensive", "costly",
    "too costly", "overpriced", "bahut mehenga", "bahut mehengi",
    "itna mehenga", "itni mehengi", "mehenga kyun", "mehengi kyun",
    "mehenga hai", "mehengi hai", "expensive hai", "expensive kyun",
    "why so expensive", "why expensive", "zyada price", "price zyada",
    "rate zyada", "bahut zyada", "kaafi zyada",
    "itne mein nahi", "itne me nahi", "itne mein nahi lunga",
    "nahi lunga", "nahi loonga", "nahi kharidunga",
    "dusri jagah sasti", "dusri jagah sasta", "dusri jagah kam",
    "kahin aur sasti", "kahin aur sasta", "kahin aur kam",
    "sasti mil rahi", "sasta mil raha", "kam mil rahi", "kam mil raha",
    "last kya karoge", "last kya", "kya lagaoge", "kitne mein doge",
    "kitne me doge", "kitne mein de doge",
    # Devanagari (Hindi + Marathi)
    "महंगी", "महंगा", "महाग", "महागडी", "बहुत महंगा", "बहुत महंगी",
    "इतना महंगा", "इतनी महंगी", "महंगा क्यों", "इतके नाही", "इतक्यात नाही",
    "दुसरीकडे स्वस्त", "जास्त आहे", "खूप महाग",
]
_DISCOUNT = [
    "discount", "koi discount", "any discount", "chhoot", "chhut",
    "छूट", "सूट", "सवलत", "डिस्काउंट", "discount milega", "discount hai",
]
_FINANCE = [
    "finance", "financing", "फाइनेंस", "फायनान्स", "finance hoga",
    "finance milega", "finance available",
]
_LOAN = [
    "loan", "car loan", "karz", "कर्ज", "लोन", "loan milega", "loan hoga",
    "loan available", "lon milega",
]
_EXCHANGE = [
    "exchange", "एक्सचेंज", "purani gaadi", "purani car", "old car",
    "badle mein", "बदले", "अदला", "exchange karoge", "exchange hoga",
    "exchange milega", "बदलून", "exchange policy", "buy back",
]
_BOOKING = [
    "booking", "book kar", "book karna", "book karu", "book karna hai",
    "book a car", "book the", "बुक", "बुकिंग", "token", "advance de",
    "अड्वांस", "bayana", "बयाना", "reserve", "reservation", "book it",
    # Phase 12I: booking / token / reservation asks own these (moved out of
    # finance_details so "booking?", "booking amount?", "token amount?" answer
    # the booking policy, not EMI). "booking"/"token" above already cover the
    # "... amount" forms via substring; explicit forms added for clarity.
    "booking amount", "token amount", "minimum booking", "booking kaise",
    "booking kaise karni", "kaise book", "book karne", "car book",
    "gaadi book", "reserve kar", "reserve karna", "book करायला", "बुक करायचं",
    "बुक कसं", "टोकन",
]
_VISIT = [
    "visit", "can i come", "can i visit", "aa sakta", "aa sakte", "aa jau",
    "aa jaun", "aane", "dekhne aa", "dekhne aau", "showroom aa", "aaun",
    "aa sakta hu", "आ सकता", "आ सकते", "भेट", "भेट द्या", "यायचं", "येऊ का",
    "येऊ शकतो", "come and see", "come see",
    # Phase 7H
    "appointment", "appointment needed", "walk in", "walkin", "walk-in",
    "without appointment", "can i walk in",
    # Phase 7H.2: test drive / inspection / Marathi visit
    "test drive", "test draiv", "inspection", "inspection ke liye",
    "आज येता", "येता येईल", "येऊ", "येऊ का", "inspection साठी", "test drive मिळेल",
    # Phase 8A.4: colloquial/typo visit phrases ("aaj aa skte", "aa skta hu")
    "aa skte", "aa skta", "aaj aa", "visit karna", "dekhne aana", "dekhne jana",
    "showroom dekhna", "aaj dekhne", "aaj visit",
]
_TIMING = [
    "timing", "open", "khula", "khulta", "kitne baje", "kab tak", "kab aau",
    "kab khul", "time kya", "kya time", "aaj open", "kab band", "kitne baje tak",
    "कब तक", "कब खुल", "कितने बजे", "समय", "खुला", "ओपन", "कधी", "किती वाजता",
    "उघड", "वेळ", "open hai", "open aahe", "khule",
    # Phase 7H.2
    "किती वाजेपर्यंत", "वाजेपर्यंत",
]
_LOCATION = [
    "location", "google map", "google maps", "share location", "location bhejo",
    "location send", "send location", "नकाशा", "लोकेशन", "map bhejo", "gps",
    "location kya", "location de", "location send karo", "maps link", "pin location",
]
_ADDRESS = [
    "address", "address bhejo", "address send", "address kya", "address de",
    "poora pata", "pata bhejo", "pata send", "pata kya", "pata do",
    "kahan ho", "kahan hai", "kahan par", "kahan sthit", "where are you",
    "where is your", "where r u", "पता", "पत्ता", "कहाँ हो", "कहाँ है",
    "कुठे आहे", "कुठे आहात", "address chahiye",
    # Phase 4C.2: typo + extra variants
    "adress", "addres", "locaton", "kaha ho", "kaha hai", "kaha par",
    "kaha pe ho", "kahan pe ho", "aapka office kaha", "office kaha hai",
    "kaunsa area", "kis area me", "kis area mein", "shop kaha hai",
    "showroom kaha hai", "dukan kahan",
]

# ── Phase 4C.1: new FAQ intents ──────────────────────────────────────────────
_RC_TRANSFER = [
    "rc transfer", "rto transfer", "name transfer", "naam transfer",
    "ownership transfer", "transfer hoga", "transfer ho", "transfer karo",
    "papers", "documents", "document ready", "doc ready", "kagaz",
    "kaagaz", "noc", "no objection", "rc ready", "rc kab", "rc milega",
    "registration", "insurance transfer", "loan noc",
    # Marathi
    "kagad", "kaagad", "naam transfer", "नाव ट्रान्सफर", "आरसी", "कागदपत्रे",
    # Hindi
    "kagaz pura", "papers sahi", "कागज", "दस्तावेज़",
]

_PRICE_INCLUSIONS = [
    "included", "on-road", "on road", "ex-showroom", "ex showroom",
    "insurance included", "rto included", "extra charge",
    "upar se", "upar ka", "hidden charge", "koi extra", "extra lagta",
    "extra nahi", "extra toh nahi", "sab included", "all included",
    "total price", "all in price", "on road price", "road tax",
    # Phase 7H
    "total cost", "how much does it cost", "how much it cost", "how much for this",
    "what's the total", "whats the total", "final cost",
    # Marathi
    "var kahi", "extra charge nahi", "sagle included",
    # Hindi
    "सब शामिल", "कोई एक्स्ट्रा", "ऊपर से",
]

_FINANCE_DETAILS = [
    "emi", "down payment", "downpayment", "interest rate", "interest",
    "kitni emi", "emi kitni", "kitna down", "down payment kitna",
    "monthly", "monthly kitna", "kist", "kiraya",
    "cash discount", "cash mein", "cash doon", "cash de",
    "zero down", "zero percent", "0 down", "0%",
    "finance kitna", "kitna milega", "loan amount",
    # Phase 7H: downpayment / advance / upfront phrasings
    "advance", "advance payment", "advance to book", "how much advance",
    "minimum advance", "upfront", "pay upfront", "initial payment",
    "initial deposit", "deposit", "first payment", "how much first",
    "pay now", "to pay now", "monthly payment", "monthly installment",
    "daun", "daun peyment", "down peyment",
    # Phase 12I: "booking amount", "token amount", "minimum booking", "booking",
    # "book करायला" MOVED to the booking intent — a booking/token ask is a
    # reservation question, not an EMI/finance one. finance_details keeps only
    # genuine finance words (EMI, down payment, interest, advance, deposit).
    # Marathi (Devanagari)
    "hasth", "emi kiti", "व्याज", "हप्ता", "किती हप्ता",
    "आधी किती द्यायचे", "आत्ता किती द्यायचे", "किती द्यायचे", "पहिले payment",
    "डाउन पेमेंट",
]

_WARRANTY = [
    "warranty", "guarantee", "engine guarantee", "assurance",
    "engine warranty", "gearbox warranty", "mechanical warranty",
    "koi guarantee", "koi warranty", "warranty milegi", "warranty hai",
    "certified", "inspected car", "warranty doge", "warranty dete ho",
    # Phase 7H.2 ("warranti"→"warranty" via normalize_typos already)
    "grantee", "guarntee", "extended warranty", "extanded warranty",
    "powertrain", "warranty card", "warranty claim", "remaining warranty",
    # Marathi
    "वॉरंटी", "हमी", "guarantee aahe", "वॉरंटी आहे",
    # Hindi
    "गारंटी", "वारंटी",
]

_TRUST_REVIEWS = [
    "genuine", "real", "fake nahi", "original",
    "review", "reviews", "customer review", "feedback",
    "trust", "trusted", "reliable dealer", "verified",
    "fasvto", "dhokha", "fraud", "scam", "safe hai",
    "how are you different", "better than", "why buy from",
    "legit", "authentic", "certified dealer",
    # Marathi
    "खरे आहात", "विश्वास", "खरोखर",
    # Hindi
    "भरोसेमंद", "असली", "नकली तो नहीं",
]

_BUSINESS_AGE = [
    "kitne saal", "kitne sal", "since when", "years in business",
    "kab se", "how long", "how old", "experience",
    "established", "started when", "kiti varsh",
    "kiti varshe", "business kab se",
    # Marathi
    "kitne varsh", "कितनी साल", "kitne salo",
    # Hindi
    "कब से", "कितने साल",
]

_REFUND_POLICY = [
    "refund", "return", "cancel", "cancellation",
    "paisa wapas", "paise wapas", "money back",
    "booking cancel", "cancel karna", "cancel kar sakte",
    "return policy", "kya wapas", "wapas ho", "wapas milega",
    # Marathi
    "पैसे परत", "रद्द", "परत मिळेल",
    # Hindi
    "पैसे वापस", "रिफंड",
]

# ── Phase 4C.2: comparison / "show me another" intent ───────────────────────
_COMPARISON = [
    "compare karo", "compare kar", "compare these", "compare both",
    "dono me kya farak", "dono mein kya farak", "kya farak hai",
    "difference between", "vs ", " ya ", "better option",
    "dusri wali dikhao", "dusri wali", "doosri wali dikhao", "doosri wali",
    "koi aur option", "kuch aur dikhao", "alag dikhao", "another option",
    "any other option", "konsi achi rahegi", "konsi achi hai",
    "kaunsi achi rahegi", "kaunsi achi hai", "which one is better",
    "jaisi kuch", "type kuch hai", "isi type ki", "isi type ka",
    # Marathi
    "doghat kay farak", "kontli changli aahe", "ajun dakhva",
]

_DISTANCE_ROUTE = [
    "how far", "kitna door", "kitna dur", "best route",
    "kaise aaun", "kaise aau", "route kya", "distance",
    "station se", "metro se", "bus stop se", "railway se",
    "nearest station", "nearest metro", "auto milega",
    "cab se", "uber se", "ola se", "reach kaise",
    # Phase 7H
    "how to reach", "how do i reach", "how to get there", "how to get to",
    "near thane", "near navi mumbai", "near nashik", "nashik branch",
    "thane branch", "another branch", "other branch", "branch in",
    # Phase 7H.2 broken-Hindi
    "thane ke paas", "navi mumbai paas", "pune kahan", "mere nazdik", "nazdik",
    "showrum ka pata", "branch h kya",
    # Marathi (Devanagari)
    "किती दूर", "कसे यायचे", "ठाण्याजवळ", "नवी मुंबईजवळ", "पुण्यात कुठे",
    "नाशिक", "माझ्या जवळ", "जवळ", "branch आहे",
]

# (intent, keyword list) in precedence order
_INTENT_TABLE: List[Tuple[str, List[str]]] = [
    # high-specificity first to avoid false shadowing
    ("rc_transfer",       _RC_TRANSFER),
    ("price_inclusions",  _PRICE_INCLUSIONS),
    ("finance_details",   _FINANCE_DETAILS),
    ("warranty",          _WARRANTY),
    ("trust_reviews",     _TRUST_REVIEWS),
    ("business_age",      _BUSINESS_AGE),
    ("refund_policy",     _REFUND_POLICY),
    ("comparison",        _COMPARISON),
    ("distance_route",    _DISTANCE_ROUTE),
    # existing intents
    ("negotiation",       _NEGOTIATION),
    ("discount",          _DISCOUNT),
    ("finance",           _FINANCE),
    ("loan",              _LOAN),
    ("exchange",          _EXCHANGE),
    ("booking",           _BOOKING),
    ("visit",             _VISIT),
    ("timing",            _TIMING),
    ("location",          _LOCATION),
    ("address",           _ADDRESS),
]

_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")

# intent -> template key (loan shares finance; discount/negotiation share price_fixed)
_TEMPLATE_KEY = {
    "address":          "address",
    "location":         "location",
    "visit":            "visit",
    "timing":           "timing",
    "finance":          "finance",
    "loan":             "finance",
    "exchange":         "exchange",
    "discount":         "price_fixed",
    "negotiation":      "price_fixed",
    "booking":          "booking",
    # Phase 4C.1 additions
    "rc_transfer":      "rc_transfer",
    "price_inclusions": "price_inclusions",
    "finance_details":  "finance_details",
    "warranty":         "warranty",
    "trust_reviews":    "trust_reviews",
    "business_age":     "business_age",
    "refund_policy":    "refund_policy",
    "distance_route":   "location",   # reuse location template (shares WhatsApp location)
    "comparison":       "comparison",
}

SUPPORTED_INTENTS = tuple(_TEMPLATE_KEY.keys())


@dataclass
class FAQResult:
    intent: str            # the business intent (one of SUPPORTED_INTENTS)
    response: str          # rendered, language-specific text
    language: str
    template_key: str      # the template actually used


def _kw_in(kw: str, text: str) -> bool:
    """Keyword membership with a LEFT word-boundary for ASCII keywords, so a
    keyword never false-matches inside a longer word. Without this, the exchange
    keyword 'old car' matched inside 'g|old car|s' and routed "gold cars" (a
    colour browse) to the exchange FAQ. Devanagari / non-ASCII keywords keep the
    plain substring test (\\b is unreliable there); the collisions are all ASCII."""
    if kw[:1].isascii() and kw[:1].isalnum():
        return re.search(r"(?<![a-z0-9])" + re.escape(kw), text) is not None
    return kw in text


def detect_intent(message: str) -> Optional[str]:
    """Return the FAQ intent or None (not an FAQ)."""
    text = (message or "").lower()
    for intent, keywords in _INTENT_TABLE:
        for kw in keywords:
            if _kw_in(kw, text):
                return intent
    return None


def _pre_2014_year(message: str) -> bool:
    for m in _YEAR_RE.finditer(message or ""):
        if int(m.group(1)) < 2014:
            return True
    return False


def resolve(message: str, language: Optional[str] = None) -> Optional[FAQResult]:
    """Resolve an FAQ deterministically, or None if the message is not an FAQ."""
    intent = detect_intent(message)
    if intent is None:
        return None
    lang = language or detect_language(message)

    template_key = _TEMPLATE_KEY[intent]
    # finance/loan business rule: pre-2014 vehicle -> ineligible variant
    if intent in ("finance", "loan") and _pre_2014_year(message):
        template_key = "finance_ineligible"

    response = T.render(template_key, lang)
    return FAQResult(intent=intent, response=response, language=lang,
                     template_key=template_key)


if __name__ == "__main__":
    tests = ["Loan milega?", "Finance available?", "Finance for a 2010 car?",
             "Last price?", "Discount?", "Address bhejo", "Location send karo",
             "Exchange karoge?", "आज ओपन आहे का?", "फायनान्स मिळेल का?",
             "Fortuner price?"]
    for t in tests:
        r = resolve(t)
        if r:
            print(f"[{r.intent:11}|{r.language:8}|{r.template_key:18}] {t}")
        else:
            print(f"[NOT-FAQ                                  ] {t}")
