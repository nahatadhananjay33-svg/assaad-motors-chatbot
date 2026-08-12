"""
visit_conversion.py
===================

Turns a customer message into **visit-conversion signals** and a **lead score**.
Deterministic — reuses the FAQ intent detector, query parser, and language
detector. No LLM.

Lead score (per the spec):
  * HIGH   — asks location / address / visit timing / vehicle availability
             (plus an explicit inspection request — a strong visit signal)
  * MEDIUM — asks finance / exchange / budget
  * LOW    — generic browsing

Visit signals (tracked separately for "visit-ready" detection):
  * wants_address
  * wants_location
  * asks_opening_hours
  * asks_vehicle_inspection
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

from query_parser import parse, _norm, _has
from language_detector import detect_language
import faq_engine

# ── signal names ──
WANTS_ADDRESS = "wants_address"
WANTS_LOCATION = "wants_location"
ASKS_HOURS = "asks_opening_hours"
ASKS_INSPECTION = "asks_vehicle_inspection"
ASKS_AVAILABILITY = "asks_availability"
ASKS_FINANCE = "asks_finance"
ASKS_EXCHANGE = "asks_exchange"
ASKS_BUDGET = "asks_budget"
BROWSING = "browsing"

# the four visit signals
VISIT_SIGNAL_KEYS = (WANTS_ADDRESS, WANTS_LOCATION, ASKS_HOURS, ASKS_INSPECTION)

# scoring buckets
HIGH_SIGNALS: Set[str] = {
    WANTS_LOCATION, WANTS_ADDRESS, ASKS_HOURS, ASKS_AVAILABILITY, ASKS_INSPECTION,
}
MEDIUM_SIGNALS: Set[str] = {ASKS_FINANCE, ASKS_EXCHANGE, ASKS_BUDGET}

# keyword tables (matched on normalized text)
_AVAILABILITY_WORDS = ["available", "availability", "in stock", "stock mein",
                       "stock", "hai kya", "abhi hai", "milega", "milegi"]
_INSPECTION_WORDS = ["inspect", "inspection", "test drive", "test-drive",
                     "dekhne", "dekh sakta", "dekh sakte", "see the car",
                     "come and see", "check the car", "gaadi dekhni"]
_FINANCE_WORDS = ["finance", "financing", "loan", "emi", "karz", "karz",
                  "फायनान्स", "फाइनेंस", "कर्ज", "लोन"]
_EXCHANGE_WORDS = ["exchange", "purani gaadi", "purani car", "old car",
                   "badle mein", "एक्सचेंज", "बदलून"]


@dataclass
class LeadScore:
    level: str                                   # High | Medium | Low
    points: int
    reasons: List[str] = field(default_factory=list)
    visit_signals: Dict[str, bool] = field(default_factory=dict)
    visit_ready: bool = False


def extract_message_signals(message: str) -> Tuple[Set[str], Dict]:
    """Return (signals, meta{intent, language, query}) for one message."""
    text = _norm(message)
    intent = faq_engine.detect_intent(message)
    q = parse(message)
    lang = detect_language(message)
    sig: Set[str] = set()

    # FAQ-intent driven signals (one primary intent per message)
    if intent == "address":
        sig.add(WANTS_ADDRESS)
    elif intent == "location":
        sig.add(WANTS_LOCATION)
    elif intent == "timing":
        sig.add(ASKS_HOURS)
    elif intent == "visit":
        sig.add(ASKS_INSPECTION)

    # finance / exchange detected INDEPENDENTLY so one message can express both
    if intent in ("finance", "loan") or any(_has(text, _norm(w)) for w in _FINANCE_WORDS):
        sig.add(ASKS_FINANCE)
    if intent == "exchange" or any(_has(text, _norm(w)) for w in _EXCHANGE_WORDS):
        sig.add(ASKS_EXCHANGE)

    # inspection keywords (independent of FAQ intent)
    if any(_has(text, _norm(w)) for w in _INSPECTION_WORDS):
        sig.add(ASKS_INSPECTION)

    # availability only when it's NOT an FAQ message (avoids "finance available")
    if intent is None and any(_has(text, _norm(w)) for w in _AVAILABILITY_WORDS):
        sig.add(ASKS_AVAILABILITY)

    # budget signal
    if q.price_max is not None or q.price_min is not None or q.sort_cheapest \
            or _has(text, "budget"):
        sig.add(ASKS_BUDGET)

    if not sig:
        sig.add(BROWSING)
    return sig, {"intent": intent, "language": lang, "query": q}


def visit_signal_map(signals: Set[str]) -> Dict[str, bool]:
    return {key: key in signals for key in VISIT_SIGNAL_KEYS}


def score(signals: Set[str]) -> LeadScore:
    """Classify accumulated signals into a High/Medium/Low lead score."""
    real = {s for s in signals if s != BROWSING}
    high = real & HIGH_SIGNALS
    medium = real & MEDIUM_SIGNALS

    if high:
        level = "High"
    elif medium:
        level = "Medium"
    else:
        level = "Low"

    points = 10 * len(high) + 5 * len(medium)
    if not real:
        points = 1  # generic browsing

    vmap = visit_signal_map(real)
    return LeadScore(
        level=level,
        points=points,
        reasons=sorted(high | medium) or [BROWSING],
        visit_signals=vmap,
        visit_ready=any(vmap.values()),
    )


if __name__ == "__main__":
    samples = ["What's your address?", "Is the Creta available?",
               "Can I get finance?", "Exchange karoge?", "10 lakh budget",
               "just looking around", "I want to inspect the Fortuner, where are you?"]
    for s in samples:
        sig, meta = extract_message_signals(s)
        ls = score(sig)
        print(f"[{ls.level:6} {ls.points:>2}] visit_ready={ls.visit_ready} "
              f"{sorted(sig)}  <- {s}")
