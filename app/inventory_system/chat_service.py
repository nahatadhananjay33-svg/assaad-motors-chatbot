"""
chat_service.py
===============

Framework-agnostic orchestration layer for the chatbot backend. Wraps the
Phase-2B pipeline (parser -> engine -> formatter) behind a single, reusable
`ChatService.handle(message)` call that returns a structured, customer-safe
response.

  message → query_parser → retrieval_engine → response_formatter → response

NO LLM, NO voice, NO WhatsApp, NO frontend — this is the shared brain that a
website chatbot, WhatsApp bot, Android app, or future voice agent all call.

Design:
  * Inventory is loaded ONCE at construction and reused for every request.
  * Output never contains internal fields (reg / LOC slot / stock#) — the
    formatter's G-EXPOSE guarantee plus a safe public-vehicle serializer.
  * Structured JSON logging on every request (one line per call).
  * Explicit error handling: bad input raises `ChatInputError` (-> HTTP 400);
    anything unexpected is caught and returned as a safe error response.
"""

from __future__ import annotations

import os
import json
import re
import time
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import inventory_loader as L
from inventory_models import utcnow_iso
from query_parser import (parse, Query, normalize_typos, extract_registration,
                          AMBIGUOUS_FIELDS, register_inventory_models)
from retrieval_engine import RetrievalEngine
from response_formatter import (format_response, FormattedResponse,
                                _attr_intent_clauses, _attr_intent_signature,
                                VISIT_PIVOT)
import faq_engine
from faq_router import FAQRouter
from faq_templates import render_unknown, render as render_template
from lead_capture import extract_phone
from routing_metrics import RoutingMetrics
from analytics import AnalyticsEngine, AnalyticsEvent, AnalyticsStore
from lead_capture import LeadCaptureEngine
from lead_storage import LeadStore
from unknown_query_store import UnknownQueryStore
from inventory_sync import sync_inventory, InMemoryInventoryStore
from media_lookup import detect_media_intent, INSTAGRAM_REQUEST
from marathi_response import to_marathi
from language_detector import detect_language
import consultative_sales as CSL
from media_service import (MediaService, InventoryMediaProvider, STATUS_OK,
                           STATUS_VEHICLE_NOT_IDENTIFIED, STATUS_MULTIPLE_MATCHES,
                           STATUS_MEDIA_UNAVAILABLE)
import config
from security import mask_pii
# Phase 11B: deterministic intent intelligence — READ-ONLY layer (additive).
from intent_intelligence import (analyze as intel_analyze, detect_conflicts,
                                 conflict_clarification)
from intent_analytics import IntentAnalyticsStore
import conversation_policy               # Phase 12E: conversation mode classifier

# Phase 11B: when a query names two contradictory values for ONE dimension
# ("petrol diesel", "automatic manual", "white black", "first owner second
# owner"), the parser silently keeps the first — a proven guessing bug. With this
# ON, the bot asks which one instead of guessing (STEP 3/9). Deterministic; only
# fires on genuine same-dimension contradictions (a disjunction "petrol YA
# diesel" is a question, not a conflict, and is never caught here). Flip to False
# to fully restore the pre-11B behaviour.
INTEL_CONFLICT_CLARIFY = True

DEFAULT_XLSX = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")
MAX_MESSAGE_LEN = 500
# Phase 11B: how often the anonymous intent-analytics snapshot is flushed to disk.
_INTEL_EXPORT_EVERY = 100


# ─────────────────────────────────────────────────────────────────────────────
# Errors
# ─────────────────────────────────────────────────────────────────────────────
class ChatInputError(ValueError):
    """Raised for malformed/empty caller input — maps to HTTP 400."""


# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────
def _build_logger() -> logging.Logger:
    logger = logging.getLogger("chat")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        # Phase 11: also persist the JSON event stream to disk so activity
        # survives console restarts (rotate via logrotate on the VPS).
        try:
            # config.DATA_DIR follows CHAT_DATA_DIR — in Docker this is the
            # mounted /data volume, so access.log persists across redeploys
            # (locally it resolves to the same <module>/data path as before).
            _log_dir = config.DATA_DIR
            os.makedirs(_log_dir, exist_ok=True)
            fh = logging.FileHandler(os.path.join(_log_dir, "access.log"),
                                     encoding="utf-8", delay=True)
            fh.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(fh)
        except OSError:
            pass                       # console logging still works
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def _log(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    record = {"event": event, **fields}
    logger.log(level, json.dumps(record, ensure_ascii=False, default=str))


# ─────────────────────────────────────────────────────────────────────────────
# Intent classification (single best label for the response)
# ─────────────────────────────────────────────────────────────────────────────
_SINGLE_DIM_INTENT = {
    "fuel": "fuel",
    "transmission": "transmission",
    "ownership_exact": "ownership",
    "ownership_max": "ownership",
    "color": "color",
    "model": "availability",
    "make": "availability",
    "category": "availability",
    "seats": "availability",
    "year_min": "availability",
}


def classify_intent(q: Query, result) -> str:
    if q.off_sheet:
        return "off_sheet"
    if result.needs_clarification:
        return "clarify"
    if q.sort_low_km:
        return "low_km"
    active = q.active_filters()
    nonprice = [k for k in active if k not in ("price_max", "price_min")]
    if len(nonprice) >= 2:
        return "combination"
    if "price_max" in active or "price_min" in active or q.sort_cheapest:
        return "budget"
    if "price" in q.intents:
        return "price"
    if len(nonprice) == 1:
        return _SINGLE_DIM_INTENT.get(nonprice[0], "availability")
    return "availability"


# ─────────────────────────────────────────────────────────────────────────────
# Safe vehicle serialization (NEVER leaks internal fields)
# ─────────────────────────────────────────────────────────────────────────────
def public_vehicle(item) -> Dict[str, Any]:
    """Customer-facing fields only. Unknown year/km -> None (no fabrication)."""
    return {
        "registration_no": item.registration_no,
        "make": item.make_full,
        "model": item.model,
        "year": item.year_int,                               # None if unknown
        "fuel": item.fuel_norm,
        "transmission": item.transmission_norm,
        "color": item.color_norm,
        "owners": item.ownership_count,
        "seats": item.seats,
        "body_type": item.body_type,
        "price_lakh": item.price_lakh if item.price_quotable else None,
        "price_quotable": item.price_quotable,
        "km": item.km_driven,                                # None if unknown
    }


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ChatResult:
    intent: str
    response: str
    vehicles: List[Dict[str, Any]]
    status: str
    count: int
    filters: Dict[str, Any] = field(default_factory=dict)
    guardrails: List[str] = field(default_factory=list)
    request_id: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)
    media: Optional[Dict[str, Any]] = None   # Phase 4B.1: media payload (additive)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "intent": self.intent,
            "response": self.response,
            "vehicles": self.vehicles,
            "status": self.status,
            "count": self.count,
            "filters": self.filters,
            "guardrails": self.guardrails,
            "request_id": self.request_id,
            "meta": self.meta,
        }
        if self.media is not None:
            d["media"] = self.media
        return d


_OPTION_RE = re.compile(r"^\s*(?:option\s*)?([1-3])\s*(?:one)?\s*$", re.I)
_ORDINAL_MAP = {"first": "1", "second": "2", "third": "3"}
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_MEDIA_INTENT_WORD = {
    "photo_request": "photo", "video_request": "video",
    "instagram_request": "instagram", "youtube_request": "youtube",
    "link_request": "link",
}

# ── Phase 7O.3: crisp media replies (no LLM) ──────────────────────────────────
# When a single vehicle is already selected in the conversation, a photo / video
# ask is answered DIRECTLY — short, vehicle-named, no re-asking the car. The
# upstream Phase-7I.2 follow-up memory has already appended the selected vehicle
# to the message, so `get_media` resolves it to that one car. `{v}` = vehicle label.
# Default ON. Flipped to False only by the A/B validation harness to reproduce
# the exact pre-7O.3 response wording; nothing else depends on it.
MEDIA_CRISP_REPLIES = True

_MEDIA_OK_RESP = {
    "photo_request":     "{v} ke photos available hain.",
    "video_request":     "{v} ka video available hai.",
    "instagram_request": "{v} ka Instagram link:",
    "youtube_request":   "{v} ka YouTube link:",
    "link_request":      "{v} ke links:",
}
# Identified single vehicle, but no asset on file — answer crisply, don't re-ask.
_MEDIA_UNAVAIL_RESP = {
    "photo_request":     "{v} ke photos abhi available nahi — visit pe dikha denge.",
    "video_request":     "{v} ka video abhi available nahi — visit pe dikha denge.",
    "instagram_request": "{v} ka Instagram link abhi available nahi — visit pe dikha denge.",
    "youtube_request":   "{v} ka YouTube link abhi available nahi — visit pe dikha denge.",
    "link_request":      "{v} ke Instagram/YouTube links abhi available nahi — visit pe dikha denge.",
}
# No vehicle in context (or unresolvable) — crisp, media-aware clarification.
_MEDIA_CLARIFY_RESP = {
    "photo_request":     "Kaunsi gaadi ke photos chahiye?",
    "video_request":     "Kaunsi gaadi ka video chahiye?",
    # Phase 12K (F1): reel-aware — a customer asking for Instagram/reel media (even
    # with a send cue like "bhejo") usually saw a reel, so also offer the reel link
    # as an identifier, not just "which car?".
    "instagram_request": ("Kaunsi gaadi ke Instagram reels chahiye? Us gaadi ka "
                          "number ya model bata do — ya jis reel ki baat kar rahe "
                          "ho uska link bhej do, main pehchan leta hoon."),
    "youtube_request":   "Kaunsi gaadi ka YouTube video chahiye?",
    "link_request":      "Kaunsi gaadi ke links chahiye? Number ya model bata do.",
}
# media intents whose actual URLs should be appended to the reply text (so a
# "link bhejo" delivers the link immediately, not just a "available hai" line).
_LINK_INTENTS = {"instagram_request", "youtube_request", "link_request"}

# ── Reel / Instagram DISCOVERY flow ───────────────────────────────────────────
# The dealership has a large Instagram following, so most customers reference a
# reel/post to IDENTIFY a car and ask if it is available ("ye reel wali gaadi hai
# kya?", "jo reel me thi wo gaadi available hai?"). That is a VEHICLE-identification
# / availability question — NOT a request to be SENT reel/photo/video media. We
# only keep the media-send behaviour when the customer explicitly asks to be sent
# something (a send cue, or a photo/video word). Deterministic; no LLM.
_MEDIA_SEND_CUES = (
    " bhej", "bhejo", "bhejiye", "bhejna", "bhej do", "bhej dena", " send", "share",
    "forward", "link do", "link bhej", "link chahiye", "whatsapp", "de do",
    "de dena", "bhej de", "पाठवा", "पाठव", "लिंक",
)
_MEDIA_ASSET_WORDS = (
    "photo", "photos", "pic", "pics", "picture", "pictures", "image", "images",
    "video", "videos", "tasveer", "snaps", "फोटो", "व्हिडिओ",
)
# Reel-aware clarify — asks for the best identifiers from a reel (the car number
# is often on-screen / in the caption), then model+colour, then the reel link.
_REEL_CLARIFY = (
    "Reel me jo gaadi dekhi — uska number (jaise MH01AB1234) ya model aur colour "
    "bata do, main abhi check karta hoon available hai ya nahi. Ya us reel/post "
    "ka link bhej do, main pehchan leta hoon."
)


def _is_reel_source_query(message: str) -> bool:
    """True when a reel/insta reference is used to IDENTIFY a car / ask availability
    ('reel wali gaadi hai kya', 'jo reel me thi wo gaadi'), NOT a request to be sent
    reel/photo/video media. Only fires when the sole media signal is the reel
    reference — no send cue and no photo/video word."""
    if detect_media_intent(message) != INSTAGRAM_REQUEST:
        return False
    t = f" {(message or '').lower()} "
    if any(c in t for c in _MEDIA_SEND_CUES):
        return False
    if any(w in t for w in _MEDIA_ASSET_WORDS):
        return False
    # Reel-DISCOVERY (customer saw the car in a reel and asks about it) fires on:
    #   * an explicit reel/story marker ("reel wali", "insta pe dekhi", …), or
    #   * a pasted instagram/social URL, or
    #   * a bare platform mention with NO car named (ask which car).
    if any(mk in t for mk in _REEL_DISCOVERY_MARKERS):
        return True
    if ("instagram.com" in t or "instagr" in t and "/" in t
            or "/reel/" in t or "/p/" in t):
        return True
    # Part 12: a NAMED car + bare "instagram" / "instagram link" (no reel marker,
    # no URL) is a request to SEND that car's Instagram link, not discovery.
    _q = parse(message)
    if _q.registration or _q.reg_partial or _q.model or _q.make:
        return False
    return True


# Reel/story DISCOVERY markers — the customer references seeing the car in a reel
# (identify + ask availability), as opposed to asking us to send the IG link.
_REEL_DISCOVERY_MARKERS = (
    "reel", "रील", "insta pe", "insta pr", "instagram pe", "instagram wali",
    "insta wali", "instagram wale", "dekhi thi", "dekha tha", "dekhe the",
    "story", "स्टोरी", "in the reel", "me thi", "mein thi", "me dekhi",
)

_CATALOGUE_PHRASES = {
    "catalogue", "catalog", "full catalogue", "show inventory", "all cars",
    # Phase 7L: bare inventory / stock asks surface the grouped catalogue summary
    "inventory", "full inventory", "current inventory", "show catalogue",
    "stock", "all stock", "all vehicles", "all gaadi", "all gadi", "puri list",
}

# Phase 6D TASK2: vehicle-agnostic follow-up words — when none of these come
# with a model/make/registration/etc, reuse the session's last vehicle.
_FOLLOWUP_WORDS = [
    "price", "downpayment", "down payment", "emi", "insurance", "condition",
    "car condition", "accident", "accident history", "photo", "photos",
    "video", "videos", "details", "detail",
]


def _is_vehicle_followup(message: str, q: Query) -> bool:
    if q.has_any_filter():
        return False
    text = (message or "").strip().lower()
    return any(w in text for w in _FOLLOWUP_WORDS)


# ── Phase 7I.2: broadened follow-up memory ───────────────────────────────────
# A vehicle-attribute follow-up is any question ABOUT the already-selected car —
# price / insurance / service / warranty / condition / owner / km / EMI / photos
# / videos — that does NOT itself name a new vehicle. These reuse the session's
# selected vehicle so the bot stops forgetting it (Lost Context) or defaulting to
# the first inventory item (Vehicle Switched). Deterministic; no LLM.
# km is its own bucket because a bare "km"/"low km" carries no parser filter/flag.
_KM_FOLLOWUP_WORDS = (
    " km", "km ", "kms", "kilometer", "kilometre", "kitne km", "km kitne",
    "km kitna", "kitna chala", "kitni chali", "kitna chali", "kitni chala",
    "chali hai", "chala hai", "chalti hai", "kam km", "low km", "running",
    "odometer", "किमी", "किलोमीटर", "किती किमी", "kiti km", "kitni chali hai",
)
# Explicit price-question phrases. We deliberately do NOT use the parser's loose
# `price` intent here because it tags bare "kitne"/"kitna" as price, which would
# hijack timing questions like "kitne baje tak open" (a visit/timing FAQ).
_PRICE_FOLLOWUP_WORDS = (
    "price", "daam", "rate", "cost", "how much", "kitne ka", "kitne ki",
    "kitne mein", "kitne me", "kimat", "kimmat", "keemat", "kemat", "bhav",
    "kitna hai", "kitne ka hai", "iska daam", "uska daam",
    # Phase 11A: bare "final?" as a price follow-up on the pinned car. ("final
    # price"/"final rate"/"last price" stay FAQ negotiation — those route to FAQ
    # first, so this only affects the inventory/unknown follow-up path.)
    "final",
    "किंमत", "किमत", "दाम", "भाव",
)


def _followup_text(message: str) -> str:
    """Padded + lowercased message for the substring gates below, run through the
    parser's normalization first. That is what lets the Hindi / phonetic spellings
    of the price noun (कीमत, मूल्य, keemaat, keemath …) arrive here as the
    canonical "price" token — the same vocabulary the parser and the response
    formatter see — instead of each gate carrying its own synonym list."""
    return f" {normalize_typos((message or '').strip()).lower()} "


def _is_attr_followup(message: str, q: Query) -> bool:
    """True when `message` asks about an attribute of an already-selected
    vehicle (so we should reuse session context), as opposed to a fresh search."""
    # Phase 7L: a low-km / less-driven ask is a fresh inventory sort, never a
    # follow-up about the already-selected car's odometer reading.
    if q.sort_low_km:
        return False
    # Phase 11C: a km CEILING ("less than 40000 km") or an inventory-wide
    # insurance filter ("insurance kis kis ka hai") is a fresh search too.
    if getattr(q, "km_max", None) is not None or getattr(q, "has_insurance", None):
        return False
    # Phase 12K (F9 fix): a bare AMBIGUOUS field ("engine kitna hai?") trips the
    # loose "kitna hai" price word below, which would append the pinned car's reg
    # and re-parse — losing the ambiguous flag and quoting price. It is not an
    # answerable attribute follow-up: let it reach the pin-independent 12I clarify.
    if getattr(q, "ambiguous_field", None):
        return False
    # Phase 12K (M-1 fix): a NEGOTIATION / DISCOUNT ask ("last price?", "best
    # price?") contains "price" but must NOT append the pinned reg — the reg would
    # then force an inventory price quote and bypass the FAQ negotiation script.
    if faq_engine.detect_intent(message) in ("negotiation", "discount"):
        return False
    if (q.insurance_query or q.service_query or q.warranty_detail_query
            or q.condition_query or q.ownership_query or q.downpayment_query
            or q.rc_query or q.km_reading_query
            # Phase 11A: colour / fuel / transmission / seats attribute questions
            or q.color_query or q.fuel_query or q.transmission_query
            or q.seats_query
            # Phase 12G: model-year attribute question (pinned reuse)
            or getattr(q, "year_query", False)
            # Phase 12D: new vehicle-detail attribute questions (pinned reuse)
            or bool(getattr(q, "attr_fields", None))):
        return True
    if detect_media_intent(message):
        return True
    text = _followup_text(message)
    # km / price questions — but never a budget search ("under 5 lakh", which
    # carries a price_max/min filter or a cheapest sort).
    if q.price_max is None and q.price_min is None and not q.sort_cheapest:
        if any(w in text for w in _PRICE_FOLLOWUP_WORDS):
            return True
        if any(w in text for w in _KM_FOLLOWUP_WORDS):
            return True
    return False


# ── Phase 7O.4: price follow-up accuracy ──────────────────────────────────────
# A bare price question ("Price?", "kitne ka hai", "daam") that names NO new
# vehicle and carries NO budget / cheapest / low-km filter is a follow-up about
# the conversation's active vehicle. It must answer THAT vehicle's price — never
# fall through to the generic retrieval path, which clarifies (multi-car model)
# or dumps the whole catalogue (no context). Default ON; the validation harness
# flips it to reproduce the pre-7O.4 behaviour.
PRICE_FOLLOWUP_PIN = True


# ── Phase 7P.1: consultative selling layer ────────────────────────────────────
# For a broad "entry" intent (family / budget / SUV / sedan / hatchback / CNG /
# automatic / city-use / first-car) the bot replaces the inventory-dump TEXT
# ("Haan, 8 options hain — jaise ...") with ONE recommendation (max 2 cars drawn
# from the current matches) + ONE consultative question, while leaving the
# vehicle cards untouched. Purely a wording change; retrieval, memory, price,
# media, Marathi, low-KM, Astor-fix and lead capture are all unaffected. Default
# ON; the A/B validation harness flips it to reproduce the pre-7P.1 wording.
CONSULTATIVE_LAYER = True


def _is_price_followup(message: str, q: Query) -> bool:
    """Bare price question relying on context: a price word, no NEW vehicle named,
    no budget / cheapest / low-km filter. `q` must be parse() of the ORIGINAL
    message (not the context-augmented one)."""
    # A concrete car reference — model / make / full OR partial registration
    # (e.g. "9999 ka price") — is a fresh lookup, not a context follow-up, so it
    # resolves against the current message rather than the remembered vehicle.
    if q.model or q.make or q.registration or q.reg_partial:
        return False
    if q.price_max is not None or q.price_min is not None or q.sort_cheapest:
        return False
    if q.sort_low_km or getattr(q, "clarify_budget", None) is not None:
        return False
    # Phase 12K (M-1 fix): a NEGOTIATION / DISCOUNT ask ("last price?", "final
    # price?", "best price?", "lowest price?") contains the word "price" and would
    # otherwise be shortcut to a plain price quote — bypassing the FAQ negotiation
    # script ("price fixed, no mol-bhaav"). Those are handled by the FAQ layer, so
    # never treat them as a price follow-up. A plain "price?" / "kitne ka?" is not
    # a negotiation intent and still takes the fast pinned-price path.
    if faq_engine.detect_intent(message) in ("negotiation", "discount"):
        return False
    # Phase 12I: a price word that is only part of a LARGER attribute question
    # ("km kitna hai?" trips the loose "kitna hai") or a genuine MULTI-INTENT ask
    # ("price aur insurance?", "price aur km batao") must NOT be shortcut to a
    # price-only follow-up. When any other attribute intent is present, defer to
    # the normal retrieval path so the km / insurance / multi-attribute answer is
    # produced. Pure "price?" / "kitne ka?" / "final?" (no other attribute) still
    # takes the fast pinned-price path.
    if (getattr(q, "km_reading_query", False) or q.insurance_query
            or q.service_query or q.warranty_detail_query or q.rc_query
            or q.ownership_query or q.condition_query or q.downpayment_query
            or q.color_query or q.fuel_query or q.transmission_query
            or q.seats_query or getattr(q, "year_query", False)
            or bool(getattr(q, "attr_fields", None))
            # Phase 12K (F9 fix): a bare AMBIGUOUS field question ("engine kitna
            # hai?", "battery kitni hai?") trips the loose "kitna hai" price word
            # but is NOT a price question — it must reach the 12I clarify
            # (capacity/power/condition?), never quote the car's price.
            or getattr(q, "ambiguous_field", None)):
        return False
    text = _followup_text(message)
    return any(w in text for w in _PRICE_FOLLOWUP_WORDS)


def _price_line(it: Any) -> str:
    """Crisp one-line price for a single vehicle (never fabricates a number)."""
    bits = [str(it.year_int) if it.year_int else "", it.color_norm or "",
            it.model or ""]
    label = " ".join(b for b in bits if b).strip() or (it.make_full or "Yeh gaadi")
    if it.price_quotable and it.price_lakh is not None:
        return f"{label} ₹{it.price_lakh:.2f} lakh."
    return f"{label} — exact best price main confirm kar ke bata deta hoon."


# ── Phase 8A.2: deterministic conversation helpers (no LLM) ───────────────────
# Issue A — contact sharing. Detect a valid mobile, or a contact keyword with a
# long digit run (handles "mera number 982001128", "call me ...", "माझा नंबर ...").
_CONTACT_WORDS = ("number", "नंबर", "नम्बर", "nmbr", "no.", "call me", "contact",
                  "whatsapp", "mobile", "mob ", "naam", "phone", "नाव", "कॉल")

def _is_contact_share(message: str) -> bool:
    if extract_phone(message):
        return True
    if len(re.findall(r"\d", message or "")) >= 7:
        low = (message or "").lower()
        if any(w in low for w in _CONTACT_WORDS):
            return True
    return False

# Issue B — continuation / affirmation tokens ("show more", "aur", "haan", "हो").
_CONTINUATION_WORDS = {
    "aur", "aur batao", "aur dikhao", "aur kuch", "aur options", "aur dikha",
    "haan", "haa", "han", "ji haan", "theek hai", "thik hai", "thik", "theek",
    "ok", "okay", "okk", "hmm", "hm", "yes", "yeah", "yep", "sure",
    "show more", "more", "next", "next results", "continue", "go on",
    "और", "अजून", "अजून दाखवा", "हो", "होय", "बरं", "ठीक", "ठीक आहे", "और दिखाओ",
}

def _is_continuation(message: str) -> bool:
    t = re.sub(r"\s+", " ", (message or "").strip().lower())
    if t in _CONTINUATION_WORDS:
        return True
    words = t.split()
    return bool(words) and len(words) <= 3 and all(w in _CONTINUATION_WORDS for w in words)

# Issue E/F — budget clarification. User says "4 ke andar" (no unit) → ask to
# confirm as ₹4 lakh.  On "haan"/"yes"/"ji" → run inventory search.
_BUDGET_CONFIRM_WORDS = {
    "haan", "haa", "han", "ji haan", "ji", "yes", "yeah", "yep", "yup",
    "correct", "right", "bilkul", "sahi", "sahi hai", "ha",
    "हाँ", "हां", "हो", "होय", "जी", "बरोबर",
}

def _is_budget_confirm(message: str) -> bool:
    t = re.sub(r"\s+", " ", (message or "").strip().lower())
    return t in _BUDGET_CONFIRM_WORDS

# Phase 12K (I-1 fix): explicit BROWSE verbs ("dikhao", "show me", "cars",
# "options", "list") — the customer wants a FRESH inventory browse. Unlike the
# bare "wali"/"chahiye" same-model-variant cues (12E), these override a pinned
# single car: "automatic wali dikhao" after pinning a manual Fortuner must show
# real automatic cars, never relax back to the pinned car and (mis)recommend it.
_EXPLICIT_BROWSE_CUES = (
    " dikhao", " dikha do", " dikha de", " dikhaao", " dikha", " show me", " show ",
    " cars", " gaadiyan", " gaadiya", " gadiyan", " gadiya", " options",
    " list", " दाखवा",
)


def _has_browse_cue(message: str) -> bool:
    return any(c in f" {(message or '').strip().lower()} " for c in _EXPLICIT_BROWSE_CUES)


# Explicit "narrow within the current results" signals. Only these keep a new
# primary-dimension filter as a REFINEMENT of the previous browse; without one, a
# bare fuel/transmission/colour/category/seats browse is a FRESH browse showing
# ALL matching cars (Excel-filter behaviour the owner asked for). Deliberately
# excludes "and"/"aur" (they appear inside ordinary phrases, e.g. "red and black").
_NARROW_CUES = (" only ", " sirf ", " isme ", " isme se ", " ismein ", " inme ",
                " inme se ", " inmein ", " in these ", " of these ", " among these ",
                " inhi ", " inhi me ", " sirf ", " केवल ", " इनमें ", " इनमे ")


def _is_explicit_narrow(message: str) -> bool:
    return any(c in f" {(message or '').strip().lower()} " for c in _NARROW_CUES)


# ── Part G: a bare "cars dikhao" must GUIDE, not dump the whole catalogue. Only
#    an EXPLICIT "show me all cars" opens the full book (price-ascending, capped). ─
_ALL_CARS_CUES = (
    "all cars", "all the cars", "show all", "show me all", "saari gaadi",
    "saari car", "sari gaadi", "sari car", "saare cars", "sabhi gaadi",
    "sabhi car", "sabhi cars", "sab gaadi", "sab car", "poori list", "puri list",
    "complete list", "full list", "whole inventory", "full inventory",
    "entire inventory", "poora stock", "pura stock", "sari cars",
    "सारी गाड़ी", "सभी गाड़ी", "सभी गाड़ियां", "पूरी लिस्ट", "सारी गाड़ियां",
)


def _wants_all_cars(message: str) -> bool:
    t = f" {(message or '').strip().lower()} "
    return any(c in t for c in _ALL_CARS_CUES)


_BROWSE_GUIDE = ("Zaroor! Aap kis type ki gaadi dhoond rahe hain — budget, fuel "
                 "(petrol / diesel / CNG), automatic ya manual, SUV, 7-seater, "
                 "ya koi khaas model? Bata dijiye, main turant dikha deta hoon.")


# Issue C — a standalone attribute refinement carries a filter but no model/reg.
_REFINEMENT_FIELDS = ("fuel", "transmission", "color", "category", "seats",
                      "price_max", "price_min", "ownership_exact", "ownership_max",
                      "year_min", "year_exact")

def _has_refinement(q: Query) -> bool:
    if q.model or q.registration or q.make:
        return False
    # Phase 7L.2: "low km" / "less driven" is an additive refinement (km sort)
    # over the active candidate set — not a fresh full-inventory search.
    if q.sort_low_km:
        return True
    return any(getattr(q, f) is not None for f in _REFINEMENT_FIELDS)

def _merge_query(base: Query, new: Query) -> Query:
    """Copy base and override with the non-None filter fields present in `new`."""
    import copy
    merged = copy.deepcopy(base)
    for f in _REFINEMENT_FIELDS:
        v = getattr(new, f)
        if v is not None:
            setattr(merged, f, v)
    # Phase 7L.2: carry the low-km sort onto the preserved context.
    if new.sort_low_km:
        merged.sort_low_km = True
    merged.intents = set(base.intents) | set(new.intents)
    return merged

def _context_for_memory(q: Query) -> Query:
    """Phase 7L.2 (item 4): remember the search FILTERS for the next turn, but
    clear the one-shot low_km sort so it does not leak into later refinements."""
    import copy
    ctx = copy.deepcopy(q)
    ctx.sort_low_km = False
    return ctx


def _resolve_followup(message: str, candidates: List[Any]) -> Optional[str]:
    """Phase 6B/6C/6D: resolve a short follow-up (year / option number / ordinal
    word / bare registration) against the last shown candidate list. Returns
    the matching registration_no, or None."""
    if not candidates:
        return None

    # option number: "1", "2", "3", "option 1", "first one", "second one", ...
    norm = (message or "").strip().lower()
    for word, num in _ORDINAL_MAP.items():
        norm = re.sub(rf"\b{word}\b", num, norm)
    m = _OPTION_RE.match(norm)
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(candidates):
            return candidates[idx].registration_no

    # bare registration number
    reg = extract_registration(message)
    if reg:
        hits = [c for c in candidates if (c.registration_no or "").upper() == reg]
        if hits:
            return hits[0].registration_no

    # year: e.g. "2019 photos" — must uniquely match one candidate's year
    m = _YEAR_RE.search(message)
    if m:
        year = int(m.group(0))
        hits = [c for c in candidates if c.year_int == year]
        if len(hits) == 1:
            return hits[0].registration_no

    return None


# ── Phase 7O.2: Astor default-leak guard ─────────────────────────────────────
# Vehicle-specific attribute questions (insurance / warranty / service history /
# condition / accident / owner count / RC / loan / flood / body / engine) must
# NEVER be answered from the default rank-#1 inventory item. With no model / make
# / registration in the query — and no active vehicle context, which would have
# appended one upstream (Phase 7I.2) — the formatter would otherwise read
# matches[0] (currently the 2022 Black Astor) and leak it. Ask which car instead.
_ATTR_QUERY_FLAGS = ("insurance_query", "service_query", "warranty_detail_query",
                     "rc_query", "ownership_query", "flood_query", "condition_query",
                     # Phase 11A: km reading + colour / fuel / transmission / seats
                     # attribute questions also need a "which car?" when unpinned.
                     "km_reading_query", "color_query", "fuel_query",
                     "transmission_query", "seats_query",
                     # Phase 12G: model-year question with no pinned car -> ask which
                     "year_query")

_ATTR_CLARIFY = {
    "insurance_query":       "Kaunsi gaadi ki insurance details chahiye?",
    "service_query":         "Service history kis gaadi ki dekhni hai?",
    "warranty_detail_query": "Warranty kis gaadi ki dekhni hai?",
    "rc_query":              "RC / documents kis gaadi ke chahiye?",
    "ownership_query":       "Owner details kis gaadi ke chahiye?",
    "flood_query":           "Flood/condition details kis gaadi ki chahiye?",
    "condition_query":       "Condition kis gaadi ki dekhni hai?",
    "km_reading_query":      "Kis gaadi ki km reading chahiye?",
    "color_query":           "Kis gaadi ka colour poochh rahe hain?",
    "fuel_query":            "Kis gaadi ka fuel type chahiye?",
    "transmission_query":    "Kis gaadi ka transmission chahiye?",
    "seats_query":           "Kis gaadi ki seating chahiye?",
    "year_query":            "Kis gaadi ka model year chahiye?",
}


def _attr_clarification(q: Query) -> Optional[str]:
    """Return a 'which car?' clarification when `q` is a vehicle-specific
    attribute question with NO vehicle selected and NO scoping filter, else None.
    `has_any_filter()` covers model / make / registration plus concrete filters
    (fuel, colour, ownership_exact/max, price, year, category, sorts) — any of
    these means the search is genuinely scoped, so it is not a default-rank leak
    (e.g. "first owner cars" is a real filtered search, not an Astor leak)."""
    if q.has_any_filter():
        return None
    # Phase 12D: a new-field attribute question with no vehicle -> ask which car
    if getattr(q, "attr_fields", None):
        return "Sure — kis gaadi ke details chahiye?"
    for flag in _ATTR_QUERY_FLAGS:
        if getattr(q, flag, False):
            return _ATTR_CLARIFY.get(flag, "Kaunsi gaadi ki details chahiye?")
    return None


# Phase 12J: deterministic clarify for an ambiguous two-attribute pair
# ("automatic aur petrol?" — no `hai`, no search word). Ask instead of guessing.
_ATTR_PAIR_CLARIFY = (
    "Aap poochh rahe ho ki yeh gaadi in dono attributes ki hai — to sawal aise "
    "poochho 'automatic petrol hai?'. Aur agar aisi cars dhundni hain to "
    "'automatic petrol wali dikhao'."
)


def _norm_catalogue(message: str) -> str:
    return re.sub(r"\s+", " ", (message or "").strip().lower())


def _candidate_label(it: Any) -> str:
    bits = []
    if it.year_int:
        bits.append(str(it.year_int))
    if it.color_norm:
        bits.append(it.color_norm)
    bits.append(it.model or "")
    label = " ".join(b for b in bits if b)
    reg = it.registration_no
    return f"{label} ({reg})" if reg else label


class ChatService:
    def __init__(self, xlsx_path: str = None, *, top_n: int = None,
                 logger: Optional[logging.Logger] = None, llm_client=None,
                 leads_db: str = None, analytics_db: str = None,
                 unknown_db: str = None):
        self.logger = logger or _build_logger()
        self.top_n = top_n if top_n is not None else config.TOP_N
        self.xlsx_path = xlsx_path or config.XLSX_PATH
        # mask PII (phone/name) in logs unless disabled in config
        self._mask = mask_pii if config.LOG_PII_MASKING else (lambda x: x)
        t0 = time.perf_counter()
        items = L.load_inventory(self.xlsx_path)
        self.engine = RetrievalEngine(items)
        self.inventory_count = len(self.engine.all_facing)
        # inventory is the source of truth for the model recognizer too, so cars
        # whose model isn't in the static market list are still searchable by name
        register_inventory_models(i.model for i in self.engine.all_facing)
        # Phase 4B.1: media service (reads InventoryItem.media — no Supabase yet)
        self.media_service = MediaService(self.engine, InventoryMediaProvider())
        # Phase 3B routing: FAQ (deterministic) -> inventory -> unknown. No LLM.
        self.llm_client = llm_client
        self.faq_router = FAQRouter()
        self.metrics = RoutingMetrics()
        # inventory sync target (wired for /admin/refresh_inventory)
        self.inventory_store = InMemoryInventoryStore()
        # ── PERSISTENT storage (survives restart) ──
        config.ensure_data_dir()
        self.analytics = AnalyticsEngine(
            AnalyticsStore(analytics_db or config.ANALYTICS_DB),
            UnknownQueryStore(unknown_db or config.UNKNOWN_DB))
        self.lead_engine = LeadCaptureEngine(LeadStore(leads_db or config.LEADS_DB))
        # Phase 6B: minimal follow-up selection — last shown candidate list per session
        self._last_candidates: Dict[str, Any] = {}
        # Phase 6D: last/previous resolved vehicle per session (registration -> item lookup)
        self._last_vehicle: Dict[str, Any] = {}
        # Phase 7I.2: selected-vehicle context for broadened follow-up memory.
        # {session_id: {"reg": <reg or None>, "model": <canonical model or None>}}
        self._followup_ctx: Dict[str, Dict[str, Any]] = {}
        self._reg_lookup = {i.registration_no: i for i in self.engine.all_facing
                             if i.registration_no}
        # Phase 8A.2: per-session last inventory search (for continuation /
        # attribute-refinement). Stores the Query and how many cards were shown.
        self._last_search: Dict[str, Query] = {}
        self._last_search_offset: Dict[str, int] = {}
        # Phase 8 final patch: pending bare-budget clarification per session.
        self._pending_budget: Dict[str, int] = {}
        # Phase 7O.6: per-session language memory for Marathi CONSISTENCY. Once a
        # session is established as Marathi, its short / ambiguous follow-up turns
        # (detected as english/hinglish/hindi) keep replying Marathi. Only a
        # Marathi turn writes this; English-/Hindi-only sessions are never set.
        self._session_lang: Dict[str, str] = {}
        # Phase 11B: anonymous intent analytics (aggregate only; no user data).
        # Auto-exports to data/intent_analytics.json every _INTEL_EXPORT_EVERY reqs.
        self.intent_analytics = IntentAnalyticsStore()
        self._intel_req_count = 0
        _log(self.logger, logging.INFO, "service_init",
             xlsx=os.path.basename(self.xlsx_path),
             inventory_count=self.inventory_count,
             load_ms=round((time.perf_counter() - t0) * 1000, 1))

    # ── runtime inventory refresh (no restart; sessions preserved) ──
    def refresh_inventory(self) -> Dict[str, Any]:
        items = L.load_inventory(self.xlsx_path)
        report = sync_inventory(items, self.inventory_store)
        self.engine = RetrievalEngine(items)            # atomic swap
        self.media_service = MediaService(self.engine, InventoryMediaProvider())  # atomic swap
        self.inventory_count = len(self.engine.all_facing)
        self._reg_lookup = {i.registration_no: i for i in self.engine.all_facing
                             if i.registration_no}
        # keep the model recognizer in sync with the (possibly new) fleet
        register_inventory_models(i.model for i in self.engine.all_facing)
        _log(self.logger, logging.INFO, "inventory_refresh",
             inventory_count=self.inventory_count, **report.as_dict())
        return {"status": "ok", "inventory_count": self.inventory_count,
                "sync": report.as_dict()}

    def close(self) -> None:
        """Close DB connections (for clean shutdown / tests)."""
        for s in (self.lead_engine.store, self.analytics.store,
                  self.analytics.unknown_store):
            try:
                s.close()
            except Exception:
                pass
        # Phase 11B: flush the anonymous intent-analytics snapshot on shutdown.
        try:
            self.intent_analytics.export()
        except Exception:
            pass

    # -- health snapshot --
    def health(self) -> Dict[str, Any]:
        return {
            "status": "ok",
            "inventory_count": self.inventory_count,
            "source": os.path.basename(self.xlsx_path),
            "coverage": self.metrics.coverage(),
        }

    # -- main entry --
    def handle(self, message: Any, *, request_id: Optional[str] = None,
               session_id: Optional[str] = None) -> ChatResult:
        rid = request_id or uuid.uuid4().hex[:12]
        t0 = time.perf_counter()

        # ── input validation (-> 400) ──
        if message is None or not isinstance(message, str) or not message.strip():
            _log(self.logger, logging.WARNING, "bad_request",
                 request_id=rid, reason="empty_message")
            raise ChatInputError("`message` must be a non-empty string.")
        if len(message) > MAX_MESSAGE_LEN:
            _log(self.logger, logging.WARNING, "bad_request",
                 request_id=rid, reason="message_too_long", length=len(message))
            raise ChatInputError(f"`message` exceeds {MAX_MESSAGE_LEN} characters.")

        # ── Phase 12E: snapshot the PRIOR follow-up context (before this turn
        #    updates it) so the conversation-mode classifier sees what was pinned
        #    when the customer spoke. ──
        _prev_ctx = self._followup_ctx.get(session_id) if session_id else None

        # ── Phase 6C TASK4: typo normalization, applied before any parsing ──
        message = normalize_typos(message)

        # ── Phase 6C TASK5: catalogue / full inventory summary ──
        if _norm_catalogue(message) in _CATALOGUE_PHRASES:
            return self._handle_catalogue(rid)

        # ── Phase 6B: minimal follow-up selection (year / option number) ──
        # If the previous turn showed a candidate list, resolve a short
        # follow-up against it by appending the matched registration number —
        # the existing registration-priority logic then takes over. If the
        # follow-up itself carries no media word (e.g. "option 2"), reuse the
        # media intent word from the turn that produced the candidate list.
        effective_message = message
        if session_id:
            entry = self._last_candidates.get(session_id)
            candidates = entry[1] if entry else None
            reg = _resolve_followup(message, candidates) if candidates else None
            if reg:
                effective_message = f"{message} {reg}"
                if entry[0] and not detect_media_intent(message):
                    effective_message = f"{_MEDIA_INTENT_WORD[entry[0]]} {effective_message}"

        # ── Phase 12J: model-only pin with MULTIPLE cars, and the ambiguous
        # attribute-pair ("automatic aur petrol?"). Computed BEFORE the follow-up
        # token is appended, so an attribute question on a multi-car model is
        # answered as a common value / clarify (never a silent pick), and the
        # ambiguous pair asks instead of guessing. Both flow through the normal
        # tail (Marathi / lead / analytics). ──
        model_multi_out = None
        attr_pair_out = None
        if session_id and effective_message == message:
            model_multi_out = self._model_multi_followup(message, _prev_ctx, rid)
        if model_multi_out is None and effective_message == message \
                and getattr(parse(message), "attr_pair_ambiguous", False):
            attr_pair_out = ChatResult(
                intent="clarify", response=_ATTR_PAIR_CLARIFY, vehicles=[],
                status="clarify", count=0, filters={},
                guardrails=["G-ATTR-PAIR-CLARIFY"], request_id=rid,
                meta={"inventory_count": self.inventory_count, "returned": 0,
                      "route": "clarify", "attr_pair": True})

        # ── Phase 7I.2: broadened vehicle-agnostic follow-up memory ──
        # Any attribute question (price / insurance / service / warranty /
        # condition / owner / km / EMI / photos / videos) that names NO new
        # vehicle reuses the session's selected vehicle. A single pinned car ->
        # its registration (exact, per-vehicle answer); otherwise the selected
        # model name (keeps results on that model instead of the first item).
        if (model_multi_out is None and attr_pair_out is None
                and session_id and effective_message == message):
            q_check = parse(message)
            # A partial plate ("9999 ka insurance") names a NEW car just like a
            # full registration, so it must NOT reuse the remembered vehicle.
            names_new_vehicle = bool(q_check.model or q_check.make
                                     or q_check.registration or q_check.reg_partial)
            # Owner's universal rule: a query that carries concrete BROWSE filters
            # (colour / fuel / transmission / seats / category / price / km) is a
            # FRESH browse, never a follow-up about a pinned single-result car —
            # even if it also mentions an attribute like "first owner". Without
            # this, "7 seater diesel automatic" (1 car -> pinned) then "white petrol
            # automatic first owner" reused the pinned car's reg and returned that
            # blue diesel Safari instead of the white petrol match.
            _has_browse_filters = bool(
                q_check.fuel or q_check.transmission or q_check.color
                or q_check.category or q_check.seats is not None
                or q_check.price_max is not None or q_check.price_min is not None
                or q_check.km_max is not None
                or q_check.year_min is not None or q_check.year_exact is not None)
            if (not names_new_vehicle and not _has_browse_filters
                    and _is_attr_followup(message, q_check)):
                token = self._followup_token(session_id)
                if token:
                    effective_message = f"{message} {token}"

        # ── route: FAQ (deterministic) -> inventory (retrieval) -> unknown ──
        # No LLM in this phase; unknown queries are flagged mark_for_future_llm.
        rr = self.faq_router.classify(effective_message)

        # ── Phase 7O.6: Marathi conversation CONSISTENCY (no LLM) ──
        # detect_language is stateless, so a Marathi customer's short / ambiguous
        # follow-up ("photo", "2019", "haan", a bare model name) is detected as
        # english/hinglish/hindi and the reply reverts language mid-conversation.
        # Once a session is established as Marathi, carry that forward: re-render
        # this turn in Marathi. Routing / intent / query are language-independent,
        # so the re-classify yields the SAME route and the SAME vehicles — only
        # the reply LANGUAGE changes. ONLY a Marathi turn establishes the memory,
        # so English-only and Hindi-only sessions are never touched.
        if session_id:
            if detect_language(message) == "marathi":
                self._session_lang[session_id] = "marathi"
            elif (self._session_lang.get(session_id) == "marathi"
                  and rr.language != "marathi"):
                rr = self.faq_router.classify(effective_message, language="marathi")

        self.metrics.record(rr.kind, intent=rr.intent, language=rr.language)

        # ── Phase 8A.2: deterministic conversation handlers (contact / continuation
        # / attribute-refinement). Session-only; returns None to defer to routing. ──
        # ── Reel / Instagram DISCOVERY (no LLM) ──
        # A reel reference used to identify a car (not a media-send request): if a
        # car is identified, let the normal AVAILABILITY answer stand (the media
        # override is suppressed below); if no car is identified, ask for the car
        # number / model / reel link instead of a generic media clarify.
        reel_source = _is_reel_source_query(effective_message)
        reel_clarify_out = None
        if reel_source:
            _rq = parse(effective_message)
            _reel_has_car = bool(_rq.model or _rq.make or _rq.registration
                                 or _rq.reg_partial or _rq.category
                                 or _rq.seats is not None)
            if not _reel_has_car:
                reel_clarify_out = ChatResult(
                    intent="reel_clarify", response=_REEL_CLARIFY, vehicles=[],
                    status="clarify", count=0, filters={},
                    guardrails=["G-REEL-CLARIFY"], request_id=rid,
                    meta={"inventory_count": self.inventory_count, "returned": 0,
                          "route": "clarify", "reel": True})

        conv_out = self._conversation_override(message, rr, session_id, rid) \
            if (session_id and model_multi_out is None
                and attr_pair_out is None and reel_clarify_out is None) else None

        # ── Phase 11B: same-dimension contradiction -> clarify (never guess) ──
        # Highest precedence: if the customer named two conflicting values for one
        # slot ("petrol diesel", "automatic manual", "white black", "first owner
        # second owner"), ask which — instead of the parser silently keeping the
        # first. Disjunction forms ("petrol YA diesel") are questions, not
        # conflicts, and are NOT caught here. Flows through the normal tail
        # (Marathi / lead / analytics). Never fabricates.
        conflict_out = None
        if INTEL_CONFLICT_CLARIFY:
            _conflicts = detect_conflicts(message)
            if _conflicts:
                conflict_out = ChatResult(
                    intent="clarify", response=conflict_clarification(_conflicts),
                    vehicles=[], status="clarify", count=0, filters={},
                    guardrails=["G-CONFLICT-CLARIFY"], request_id=rid,
                    meta={"inventory_count": self.inventory_count, "returned": 0,
                          "route": "clarify",
                          "conflict": [c["dimension"] for c in _conflicts]})

        if conflict_out is not None:
            out = conflict_out
        elif model_multi_out is not None:      # Phase 12J: multi-car model context
            out = model_multi_out
        elif attr_pair_out is not None:        # Phase 12J: ambiguous attribute pair
            out = attr_pair_out
        elif reel_clarify_out is not None:     # reel discovery, no car identified
            out = reel_clarify_out
        elif conv_out is not None:
            out = conv_out
        elif rr.kind == "faq":
            out = self._handle_faq(rr, rid)
        elif rr.kind == "inventory":
            out = self._handle_retrieval(rr.query, rid)
        else:
            out = self._handle_unknown(rr, rid)

        out.meta["route"] = out.meta.get("route", rr.kind)
        out.meta["language"] = rr.language

        # Remember the last real inventory search so a later "aur" / "white" can
        # continue or refine it.
        if (session_id and conv_out is None and rr.kind == "inventory"
                and out.count and out.vehicles):
            self._last_search[session_id] = _context_for_memory(rr.query)
            self._last_search_offset[session_id] = len(out.vehicles)

        # ── Phase 7P.1: consultative selling intro ──
        # Whenever the FINAL reply is a broad-entry inventory listing — a fresh
        # "family car" / "SUV" open OR a mid-conversation category/budget switch
        # that merged into a listing — replace the inventory-dump text with ONE
        # recommendation + ONE question. Gated to real listings only:
        #   * match_models in meta  → came through _handle_retrieval (so NOT a
        #     continuation "aur", FAQ, catalogue, price-follow-up or clarify),
        #   * a broad entry intent  → NOT a specific model / media / low-KM ask,
        #   * effective_message == message → no follow-up token was appended.
        # Vehicle cards are never altered (additive wording only). Runs before
        # the Marathi conversion below so the intro is localised too.
        if (CONSULTATIVE_LAYER and effective_message == message
                and out.vehicles and out.meta.get("match_models") is not None
                and rr.query is not None and not detect_media_intent(message)):
            _ci = CSL.detect_intent(message, rr.query)
            if _ci:
                _intro = CSL.consultative_intro(_ci, out.meta.get("match_models", []))
                if _intro:
                    out.response = _intro
                    out.guardrails = list(out.guardrails) + ["G-CONSULT"]
                    out.meta["consultative"] = _ci

        # ── Phase 12K: honest "model ka <variant> nahi hai" note ──────────────
        # A same-model-variant browse whose variant doesn't exist in the model was
        # re-run as a fresh browse; prepend the honest note HERE so the consultative
        # layer (above) can't overwrite it, and before the Marathi pass (below).
        _vnote = out.meta.get("variant_note")
        if _vnote and out.response and not out.response.startswith(_vnote):
            out.response = f"{_vnote} — {out.response}"

        # ── Phase 4B.1: media exposure — additive to vehicle cards ──
        # detect_media_intent was already imported for analytics; reuse here.
        # A reel-as-source query (customer saw the car in a reel and wants to know
        # if it is available) is NOT a media-send request, so we do NOT override the
        # availability answer with a "reel/photos" media message.
        _media_intent = None if reel_source else detect_media_intent(effective_message)
        if _media_intent:
            _media_data = self.media_service.get_media(effective_message)
            _candidate_items = _media_data.pop("_candidate_items", None)
            out.media = _media_data
            _ms = _media_data.get("status")
            out.meta["media_status"] = _ms
            # Override intent to media type only when a vehicle was identified
            # (even if unavailable / multiple matches). When no vehicle at all
            # → keep original route intent so 'unknown' still signals need-clarify.
            if _ms != STATUS_VEHICLE_NOT_IDENTIFIED:
                out.intent = _media_intent
                veh = _media_data.get("vehicle") or "Is gaadi"
                # ── Phase 7O.3: a single vehicle is selected → answer the media
                # request DIRECTLY with one short, crisp line. Never re-ask the
                # vehicle name. Covers the reg-lookup case that the FAQ router had
                # left as a "which car?" clarify, plus any context-pinned car. ──
                if MEDIA_CRISP_REPLIES and _ms == STATUS_OK:
                    out.response = _MEDIA_OK_RESP.get(
                        _media_intent, "{v} ke photos/video available hain."
                    ).format(v=veh)
                    # Deliver the actual link(s) inline for a link/IG/YT ask —
                    # the customer asked for a link, so give it, short and direct.
                    if _media_intent in _LINK_INTENTS:
                        _urls = (list(_media_data.get("instagram") or [])
                                 + list(_media_data.get("youtube") or []))
                        if _urls:
                            out.response = out.response + " " + " ".join(_urls)
                elif MEDIA_CRISP_REPLIES and _ms == STATUS_MEDIA_UNAVAILABLE:
                    out.response = _MEDIA_UNAVAIL_RESP.get(
                        _media_intent, "{v} ka media abhi available nahi."
                    ).format(v=veh)
                elif (not MEDIA_CRISP_REPLIES) and _ms == STATUS_OK and rr.kind == "faq":
                    # pre-7O.3 behaviour (kept only for A/B validation): a reg
                    # lookup found media after the FAQ router emitted a clarify.
                    reg = _media_data.get("registration_no")
                    veh_line = f"{veh}\nReg: {reg}" if reg else veh
                    out.response = f"{veh_line}\n\nHaan, photos/videos bhej rahe hain."

                # ── Phase 6C TASK1/TASK2: numbered clarify list with reg numbers ──
                if _ms == STATUS_MULTIPLE_MATCHES and _candidate_items:
                    lines = [f"{i+1}. {_candidate_label(c)}"
                             for i, c in enumerate(_candidate_items)]
                    out.response = ("\n".join(lines) +
                                     "\n\nNumber, year, ya reg number bata do.")
            # ── Phase 7O.3: no vehicle in context → crisp, media-aware clarify
            # ("Kaunsi gaadi ke photos chahiye?") instead of a generic prompt. ──
            elif MEDIA_CRISP_REPLIES and _media_intent in _MEDIA_CLARIFY_RESP:
                out.response = _MEDIA_CLARIFY_RESP[_media_intent]

            # ── Phase 6B: remember candidate list for the next turn's follow-up ──
            if session_id:
                if _ms == STATUS_MULTIPLE_MATCHES and _candidate_items:
                    self._last_candidates[session_id] = (_media_intent, _candidate_items)
                else:
                    self._last_candidates.pop(session_id, None)

        # ── Phase 6D TASK1/3: remember the resolved vehicle for this session ──
        if session_id:
            resolved_item = None
            if out.vehicles and len(out.vehicles) == 1:
                resolved_item = self._reg_lookup.get(out.vehicles[0].get("registration_no"))
            elif out.media and out.media.get("status") == STATUS_OK:
                resolved_item = self._reg_lookup.get(out.media.get("registration_no"))
            if resolved_item:
                brief = {"registration_no": resolved_item.registration_no,
                         "year": resolved_item.year_int,
                         "model": resolved_item.model,
                         "make": resolved_item.make_full}
                prev_entry = self._last_vehicle.get(session_id)
                cur = prev_entry[0] if prev_entry else None
                if cur and cur.get("registration_no") == brief["registration_no"]:
                    previous = prev_entry[1] if prev_entry else None
                else:
                    previous = cur
                self._last_vehicle[session_id] = (brief, previous)

        # ── Phase 7I.2: maintain the session's selected-vehicle context ──
        # A single pinned car -> reg + model. A named-model search (even multi-
        # match) -> model scope (reg=None). Bare follow-ups / no-vehicle turns
        # leave the context unchanged so it survives across the conversation.
        if session_id:
            new_reg = new_model = None
            if out.vehicles and len(out.vehicles) == 1:
                new_reg = out.vehicles[0].get("registration_no")
                new_model = out.vehicles[0].get("model")
            elif out.media and out.media.get("status") == STATUS_OK:
                _it = self._reg_lookup.get(out.media.get("registration_no"))
                if _it:
                    new_reg, new_model = _it.registration_no, _it.model
            if new_model is None and rr.query is not None and rr.query.model:
                new_model = rr.query.model
            if new_reg or new_model:
                self._followup_ctx[session_id] = {"reg": new_reg, "model": new_model}

        # ── Phase 7O.5: Marathi response language ──
        # The deterministic reply paths (response_formatter + the short crisp
        # chat_service replies) emit Hinglish; FAQ templates are already Marathi.
        # For a Marathi customer, convert the reply language only — logic, data
        # values and structure are untouched. No effect on any other language.
        if rr.language == "marathi" and out.response:
            out.response = to_marathi(out.response)

        # ── lead capture (only when a conversation session is supplied) ──
        lead_level, visit_ready = None, False
        if session_id:
            lead = self.lead_engine.capture(session_id, message)
            lead_level, visit_ready = lead.score_level, lead.visit_ready
            out.meta["lead_level"] = lead_level
            out.meta["visit_ready"] = visit_ready

        # ── analytics (record-only; never changes the response) ──
        vq = rr.query if rr.query is not None else parse(effective_message)
        self.analytics.record(AnalyticsEvent(
            session_id=session_id or rid, query=message, route=rr.kind,
            intent=out.intent, language=rr.language, lead_level=lead_level,
            visit_ready=visit_ready, is_media=bool(detect_media_intent(effective_message)),
            vehicle=(vq.model or vq.category), timestamp=utcnow_iso()))

        # ── Phase 11B: deterministic intent intelligence (additive only) ──
        # Attaches scores / multi-intent / conflicts / confidence to meta and
        # records anonymous analytics. NEVER changes response/vehicles/status/
        # intent, so every existing behaviour and test is unaffected. Fully
        # guarded — a fault here can never break a customer reply.
        try:
            _intel = intel_analyze(message, rr.query)
            out.meta["intelligence"] = _intel.to_dict()
            # Phase 12E: label the conversation mode (read-only; meta only).
            # Classify on the ORIGINAL message (not rr.query, which may carry a
            # follow-up token) so the turn's own intent is judged.
            out.meta["conversation_mode"] = conversation_policy.classify(
                message, _prev_ctx, rr_kind=rr.kind)
            self.intent_analytics.record(_intel, message=message)
            self._intel_req_count += 1
            if self._intel_req_count % _INTEL_EXPORT_EVERY == 0:
                self.intent_analytics.export()
        except Exception:                      # pragma: no cover - defensive
            pass

        out.meta["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)

        _log(self.logger, logging.INFO, "chat",
             request_id=rid, message=self._mask(message), route=rr.kind,
             language=rr.language, intent=out.intent, status=out.status,
             count=out.count, guardrails=out.guardrails,
             latency_ms=out.meta["latency_ms"])
        return out

    # ── Phase 7I.2: follow-up context token ───────────────────────────────────
    def _followup_token(self, session_id: str) -> Optional[str]:
        """Best vehicle reference for a follow-up question: a pinned single
        car's registration if known, else the selected model name. The token is
        appended to the message so the existing parser/router resolves it."""
        ctx = self._followup_ctx.get(session_id)
        if not ctx:
            return None
        return ctx.get("reg") or ctx.get("model")

    # ── route handlers ──────────────────────────────────────────────────────
    def _handle_retrieval(self, q: Query, rid: str) -> ChatResult:
        # Phase 12I: a bare AMBIGUOUS field ("engine?", "battery?", "safety
        # features?") — ask ONE deterministic clarify (which aspect?) instead of
        # guessing or dumping the inventory. Applies with or without a pinned car,
        # because the word maps to no single answerable field either way.
        amb = getattr(q, "ambiguous_field", None)
        if amb:
            return ChatResult(
                intent="clarify",
                response=AMBIGUOUS_FIELDS.get(amb, "Aap kis detail ke baare mein "
                                              "pooch rahe hain?"),
                vehicles=[], status="clarify", count=0, filters={},
                guardrails=["G-AMBIGUOUS-FIELD"], request_id=rid,
                meta={"inventory_count": self.inventory_count, "returned": 0,
                      "route": "clarify", "ambiguous_field": amb})
        # Phase 7O.2: never answer a vehicle-specific attribute question from the
        # default rank-#1 vehicle when no car has been selected — ask which car.
        clar = _attr_clarification(q)
        if clar is not None:
            return ChatResult(
                intent="clarify", response=clar, vehicles=[], status="clarify",
                count=0, filters={}, guardrails=["G-ATTR-CLARIFY"], request_id=rid,
                meta={"inventory_count": self.inventory_count, "returned": 0,
                      "route": "clarify"})
        # ── Part G: browse guard. A query with NO real criteria (no model, make,
        #    registration, filter, or sort) must not dump the catalogue. Guide the
        #    customer instead — UNLESS they explicitly asked to see everything, in
        #    which case we fall through and show the whole book (price-ascending,
        #    capped downstream). ──
        if (not q.has_any_filter() and not _wants_all_cars(q.raw)
                and not detect_media_intent(q.raw)):
            return ChatResult(
                intent="clarify", response=_BROWSE_GUIDE, vehicles=[],
                status="clarify", count=0, filters={},
                guardrails=["G-BROWSE-GUIDE"], request_id=rid,
                meta={"inventory_count": self.inventory_count, "returned": 0,
                      "route": "clarify", "browse_guide": True})
        result = self.engine.search(q)
        formatted: FormattedResponse = format_response(result)
        intent = classify_intent(q, result)
        # A filtered / explicit browse behaves like an Excel filter: EVERY matching
        # car is returned, never a cheapest-N slice. The old top_n cap silently hid
        # every car ranked below the cap — e.g. a "manual cars" browse (131 matches)
        # showed only the 50 cheapest and dropped the ₹6.99L manual Astor and ~80
        # others. Any category the customer names (manual / automatic / CNG / luxury
        # / sunroof / 7-seater / colour / price / owner / model …) sets a filter, so
        # has_any_filter() is True and the full set is shown. A bare no-criteria
        # browse can only reach here when the customer explicitly asked for all cars
        # (the browse guard above blocks every other no-filter case), so that too is
        # shown in full. Pagination still works: _last_search_offset is set to the
        # full count downstream, so a later "aur" honestly says nothing more remains.
        if q.has_any_filter() or _wants_all_cars(q.raw):
            _shown_matches = result.matches
        else:
            _shown_matches = result.matches[:self.top_n]
        vehicles = [public_vehicle(it) for it in _shown_matches]
        # Phase 7P.1: ranked distinct match models (filter-respecting) so the
        # consultative layer can recommend only currently-available cars.
        _seen, match_models = set(), []
        for it in result.matches:
            if it.model and it.model not in _seen:
                _seen.add(it.model)
                match_models.append(it.model)

        # defensive: never serve a leaking answer (G-EXPOSE backstop)
        if formatted.contains_forbidden:
            _log(self.logger, logging.ERROR, "leak_blocked", request_id=rid)
            formatted.spoken = ("Main aapko visit pe poori detail bata deta hoon — "
                                "Assad Motors, Marol, Andheri East, Mumbai.")
            vehicles = []

        return ChatResult(
            intent=intent, response=formatted.spoken, vehicles=vehicles,
            status=formatted.status, count=result.count,
            filters=q.active_filters(), guardrails=formatted.guardrails_fired,
            request_id=rid,
            meta={"inventory_count": self.inventory_count, "returned": len(vehicles),
                  "relaxed": formatted.relaxed,
                  "source_fallback": result.source_fallback,
                  "match_models": match_models},
        )

    def _handle_catalogue(self, rid: str) -> ChatResult:
        # Phase 6C TASK5: grouped inventory summary — never render every card.
        groups: Dict[str, int] = {}
        for it in self.engine.all_facing:
            key = f"{it.body_type or 'Other'} - {it.model or 'Unknown'}"
            groups[key] = groups.get(key, 0) + 1
        lines = [f"{name}: {count}" for name, count in sorted(groups.items())]
        response = (f"Hamare paas total {self.inventory_count} cars hain:\n"
                     + "\n".join(lines) +
                     "\n\nKisi specific model/budget ke baare mein pucho, main detail bata deta hoon.")
        return ChatResult(
            intent="catalogue", response=response, vehicles=[], status="catalogue",
            count=self.inventory_count, filters={}, guardrails=["G-CATALOGUE"], request_id=rid,
            meta={"inventory_count": self.inventory_count, "returned": 0},
        )

    def _handle_faq(self, rr, rid: str) -> ChatResult:
        faq = rr.faq
        return ChatResult(
            intent=faq.intent, response=faq.response, vehicles=[],
            status="faq", count=0, filters={}, guardrails=["FAQ"], request_id=rid,
            meta={"inventory_count": self.inventory_count, "returned": 0,
                  "faq_intent": faq.intent, "template_key": faq.template_key},
        )

    def _handle_unknown(self, rr, rid: str) -> ChatResult:
        # Phase 3B: no LLM. We only flag the query for a future LLM phase.
        text = render_unknown(rr.language)
        return ChatResult(
            intent="unknown", response=text, vehicles=[], status="unknown",
            count=0, filters={}, guardrails=["UNKNOWN"], request_id=rid,
            meta={"inventory_count": self.inventory_count, "returned": 0,
                  "mark_for_future_llm": True},
        )

    # ── Phase 7O.4: price follow-up handler ───────────────────────────────────
    def _price_followup(self, session_id: str, rid: str) -> ChatResult:
        """Answer the price of the conversation's active vehicle. With a single
        pinned car → that car; with a model context → the top match of that model.
        Never dumps the catalogue, never clarifies when a vehicle is in context.
        No active vehicle → a short clarification (never a dump)."""
        ctx = self._followup_ctx.get(session_id) if session_id else None
        if ctx and (ctx.get("reg") or ctx.get("model")):
            pq = Query(raw="price")
            if ctx.get("reg"):
                pq.registration = ctx["reg"]
            else:
                pq.model = ctx["model"]
            pq.intents.add("price")
            result = self.engine.search(pq)
            if result.found and result.matches:
                it = result.matches[0]
                return ChatResult(
                    intent="price", response=_price_line(it),
                    vehicles=[public_vehicle(it)], status="found", count=1,
                    filters=pq.active_filters(), guardrails=["G-PRICE-FOLLOWUP"],
                    request_id=rid,
                    meta={"inventory_count": self.inventory_count, "returned": 1,
                          "route": "inventory", "price_followup": True})
        # no active vehicle → clarify, never dump the inventory
        return ChatResult(
            intent="clarify", response="Kis gaadi ki price chahiye?",
            vehicles=[], status="clarify", count=0, filters={},
            guardrails=["G-PRICE-CLARIFY"], request_id=rid,
            meta={"inventory_count": self.inventory_count, "returned": 0,
                  "route": "clarify", "price_followup": True})

    # ── Phase 12J: model-only pin with MULTIPLE cars ──────────────────────────
    def _variant_descriptor(self, it: Any) -> str:
        """A short 'year transmission fuel' label to distinguish same-model cars."""
        bits = []
        if it.year_int:
            bits.append(str(it.year_int))
        if it.transmission_norm and it.transmission_norm != "Unknown":
            bits.append(it.transmission_norm)
        if it.fuel_norm and it.fuel_norm != "Unknown":
            bits.append(it.fuel_norm)
        return " ".join(bits) if bits else (it.color_norm or it.model or "gaadi")

    def _model_multi_followup(self, message: str,
                              prev_ctx: Optional[Dict[str, Any]],
                              rid: str) -> Optional[ChatResult]:
        """When the pinned context is a MODEL (no single reg) that has >1 facing
        car, an attribute question must NOT silently answer one car. If every
        matching car shares the SAME value for the asked attribute(s) -> answer the
        common value; otherwise -> clarify WHICH variant. A single-car model, a new
        vehicle, a search cue, or a filter/variant browse all defer to the normal
        flow. Deterministic; no fabrication."""
        if not prev_ctx or prev_ctx.get("reg") or not prev_ctx.get("model"):
            return None
        model = prev_ctx["model"]
        items = [i for i in self.engine.all_facing if i.model == model]
        if len(items) <= 1:
            return None
        q = parse(message)
        # a new vehicle named -> fresh lookup, not a follow-up on the pinned model
        if q.model or q.make or q.registration or q.reg_partial:
            return None
        from query_parser import _has_search_cue, _norm
        if _has_search_cue(_norm(q.raw)):
            return None
        # a filter / variant / browse -> keep the existing same-model variant path
        if (q.category or q.seats is not None or q.km_max is not None
                or q.price_max is not None or q.price_min is not None
                or q.year_exact is not None or q.year_min is not None
                or q.sort_low_km or q.sort_cheapest
                or q.fuel is not None or q.transmission is not None
                or q.color is not None or q.feature_filters
                or q.ownership_exact is not None or q.ownership_max is not None):
            return None
        sig0 = _attr_intent_signature(items[0], q)
        if not sig0:                       # not an attribute question -> normal flow
            return None
        items_sorted = sorted(items, key=lambda it: (it.year_int or 0), reverse=True)
        sigs = [_attr_intent_signature(it, q) for it in items_sorted]
        n = len(items_sorted)
        if all(s == sigs[0] for s in sigs):
            # provably identical across all matches -> answer the common value
            clauses = _attr_intent_clauses(items_sorted[0], q)
            prefix = "Dono" if n == 2 else f"Saari {n}"
            resp = f"{prefix} {model} — " + " ".join(clauses) + f" {VISIT_PIVOT}"
            return ChatResult(
                intent="model_common", response=resp, vehicles=[], status="found",
                count=n, filters={}, guardrails=["G-MODEL-COMMON"], request_id=rid,
                meta={"inventory_count": self.inventory_count, "returned": 0,
                      "route": "inventory", "model_multi": model, "common": True})
        # values differ -> clarify which specific car, never pick one silently
        joiner = " ya " if n == 2 else ", "
        descriptors = joiner.join(self._variant_descriptor(it) for it in items_sorted)
        resp = (f"Humare paas {n} {model} hain — {descriptors}. "
                f"Aap kaunsi wali pooch rahe hain?")
        return ChatResult(
            intent="clarify", response=resp, vehicles=[], status="clarify",
            count=n, filters={}, guardrails=["G-MODEL-CLARIFY"], request_id=rid,
            meta={"inventory_count": self.inventory_count, "returned": 0,
                  "route": "clarify", "model_multi": model, "common": False})

    # ── Phase 8A.2: deterministic conversation handlers (no LLM) ──────────────
    def _conversation_override(self, message: str, rr, session_id: str,
                               rid: str) -> Optional[ChatResult]:
        """Issue A/B/C handlers. Returns a ChatResult to override routing, or
        None to defer to the normal FAQ/inventory/unknown path."""
        # A — contact sharing → acknowledge (lead capture still runs in the tail).
        if _is_contact_share(message):
            resp = render_template("contact_ack", rr.language)
            return ChatResult(intent="contact_shared", response=resp, vehicles=[],
                              status="contact", count=0, filters={},
                              guardrails=["CONTACT"], request_id=rid,
                              meta={"inventory_count": self.inventory_count,
                                    "returned": 0, "route": "contact"})
        # ── Phase 7O.4: price follow-up. A bare price question that would
        # otherwise hit inventory retrieval (clarify on a multi-car model, or dump
        # the catalogue with no context) — or that routes to "unknown" and falls
        # into the show-more safety net below (e.g. "How much for that?") — is
        # pinned to the active vehicle. Gated to inventory/unknown so FAQ
        # negotiation asks (last price / discount → price_fixed) stay untouched. ──
        if PRICE_FOLLOWUP_PIN and rr.kind in ("inventory", "unknown") \
                and _is_price_followup(message, parse(message)):
            return self._price_followup(session_id, rid)
        # E — pending bare-budget confirmed ("haan", "yes", "ji" after clarify prompt).
        _pending = self._pending_budget.get(session_id)
        if _pending is not None and _is_budget_confirm(message):
            del self._pending_budget[session_id]
            price_q = Query(raw=f"{_pending} lakh ke andar")
            price_q.price_max = _pending * 100_000
            price_q.intents.add("price")
            base = self._last_search.get(session_id)
            merged = _merge_query(base, price_q) if base is not None else price_q
            out = self._handle_retrieval(merged, rid)
            out.meta["route"] = "inventory"
            out.meta["budget_confirmed"] = True
            if out.count and out.vehicles:
                self._last_search[session_id] = merged
                self._last_search_offset[session_id] = len(out.vehicles)
            return out
        # B — continuation / affirmation → show more from the last search.
        if _is_continuation(message):
            return self._show_more(session_id, rr.language, rid)
        # C — standalone attribute refinement → merge onto the last search.
        base = self._last_search.get(session_id)
        if base is not None and rr.query is not None and _has_refinement(rr.query):
            _new_class = rr.query.category is not None or rr.query.seats is not None
            _base_class = (getattr(base, "category", None) is not None
                           or getattr(base, "seats", None) is not None)
            # UNIVERSAL RULE (owner's decision): until a specific CAR is pinned — a
            # model, make, or registration is in context — EVERY filter query is a
            # FRESH browse showing ALL matching cars, never an implicit multi-turn
            # refinement of the previous browse. "Maruti cars" -> "5000 km se kam"
            # must show ALL low-km cars, not the low-km Marutis. The ONLY things that
            # keep the previous context are (a) an explicit narrow ("sirf/only/isme
            # se"), or (b) a pinned specific car/MODEL (handled in the branches
            # below, e.g. "Show me Ertiga" -> "automatic wali?" = the automatic
            # Ertiga). A bare MAKE/company browse ("Maruti cars") does NOT pin — the
            # owner's rule: "Maruti cars" then "50000 se kam chali" shows ALL low-km
            # cars, not the low-km Marutis. Only a MODEL / registration pins.
            _base_pinned = bool(getattr(base, "model", None)
                                or getattr(base, "registration", None)
                                or getattr(base, "reg_partial", None))
            if _has_browse_cue(message) or (not _base_pinned
                                            and not _is_explicit_narrow(message)):
                # Phase 12K: an explicit "X dikhao" is a FRESH browse — show ALL
                # matching cars, never carry over the previous search's filters.
                # After "7 seater dikhao", "automatic wali dikhao" must show ALL
                # automatic cars (not 7-seater automatics), and "5 lakh ke andar
                # dikhao" all cars under 5 lakh. Bare refinements without a browse
                # cue ("petrol wali", "kam km") still narrow the current set.
                base = None
            elif _new_class and _base_class:
                # Phase 12K: switching vehicle CLASS (body category / seating) is a
                # FRESH browse — never stack one class on another. "7 seater dikhao"
                # then "SUV dikhao" must show ALL SUVs, not collapse to the lone
                # 7-seat SUV. Non-class filters (budget / fuel / colour) still stack
                # onto a class (e.g. "under 5 lakh" then "SUV dikhao").
                base = None
            elif base.registration or base.reg_partial:
                # Phase 12K (I-1): an explicit BROWSE ("automatic wali dikhao",
                # "petrol cars dikhao") is a fresh inventory search, NOT a variant
                # refinement of the pinned car — otherwise the filter relaxes back
                # to the pinned car and mis-recommends it (e.g. a manual Fortuner
                # for an "automatic" browse).
                if _has_browse_cue(message):
                    base = None
                # Pinned to ONE specific car. A "different class of car" filter —
                # seating, body category, a km ceiling or a budget — means the
                # customer wants to browse the whole stock afresh.
                elif (rr.query.category or rr.query.seats is not None
                        or rr.query.km_max is not None
                        or rr.query.price_max is not None
                        or rr.query.price_min is not None):
                    base = None
                else:
                    # A VARIANT filter (other colour / fuel / owner / automatic /
                    # less-driven) means "is there another one like THIS car?" —
                    # keep the memory but look across the pinned car's MODEL, so
                    # we show other same-model cars (e.g. another Swift). If none
                    # exist the retrieval returns 0 and we offer other options.
                    _ctx = self._followup_ctx.get(session_id) or {}
                    _pm = _ctx.get("model")
                    _mb = parse(_pm) if _pm else None
                    base = _mb if (_mb and _mb.model) else None
            # Phase 11C / 12K: a category / seats browse, OR an explicit BROWSE cue
            # ("automatic wali dikhao"), after a MODEL pin is a fresh inventory
            # browse — not a variant of that model. Otherwise the filter relaxes
            # back to the pinned model's car and mis-recommends it (e.g. the manual
            # Fortuner for an "automatic" browse). A bare "automatic wali?" (no
            # browse cue) stays a same-model-variant ask (12E).
            elif base.model and (_has_browse_cue(message)
                                 or rr.query.category or rr.query.seats is not None):
                base = None
        if base is not None and rr.query is not None and _has_refinement(rr.query):
            merged = _merge_query(base, rr.query)
            out = self._handle_retrieval(merged, rid)
            # Phase 12K: a same-model-variant browse ("automatic wali?" after a model
            # was pinned) whose asked filter got RELAXED means that model has no such
            # variant. Never present the relaxed (wrong-variant) car as a match — say
            # so honestly and browse that variant across ALL stock instead. (Fixes
            # "Automatic mein Fortuner achi rahegi" when the Fortuner is manual.)
            _relaxed = set(out.meta.get("relaxed") or [])
            _asked = {d for d in ("transmission", "fuel", "color",
                                  "ownership_exact", "ownership_max")
                      if getattr(rr.query, d, None) is not None}
            _hit = _relaxed & _asked
            # The model lacks the asked variant if the filter was RELAXED (engine
            # returned a wrong-variant car) OR the merged search came back EMPTY.
            if base.model and _asked and (_hit or out.count == 0):
                _dim = sorted(_hit or _asked)[0]
                _val = getattr(rr.query, _dim, None)
                if _dim == "color":
                    _note = f"{base.model} {_val} colour mein nahi hai"
                elif _dim in ("ownership_exact", "ownership_max"):
                    _note = f"{base.model} us ownership mein available nahi hai"
                else:                                   # transmission / fuel
                    _note = f"{base.model} ka {_val} nahi hai"
                fresh = self._handle_retrieval(rr.query, rid)
                if fresh.count and fresh.vehicles:
                    # store the note in meta; it is prepended AFTER the consultative
                    # layer (which would otherwise overwrite a response prefix).
                    fresh.meta["variant_note"] = _note
                    fresh.meta["route"] = "inventory"
                    fresh.meta["refined"] = True
                    fresh.meta["variant_not_in_model"] = base.model
                    self._last_search[session_id] = _context_for_memory(rr.query)
                    self._last_search_offset[session_id] = len(fresh.vehicles)
                    return fresh
                return ChatResult(
                    intent="availability",
                    response=f"{_note}, aur abhi stock mein aisa koi aur option bhi "
                             f"nahi hai. Kuch aur dikhaoon?",
                    vehicles=[], status="exhausted", count=0, filters={},
                    guardrails=["G-VARIANT-NONE"], request_id=rid,
                    meta={"inventory_count": self.inventory_count, "returned": 0,
                          "route": "inventory", "variant_not_in_model": base.model})
            if out.count and out.vehicles:
                self._last_search[session_id] = _context_for_memory(merged)
                self._last_search_offset[session_id] = len(out.vehicles)
                out.meta["route"] = "inventory"
                out.meta["refined"] = True
                if merged.sort_low_km:
                    out.meta["low_km"] = True
                return out
        # F — ambiguous bare budget ("4 ke andar", "7 mein", "5 tak"): ask to confirm.
        _qf = parse(message)
        if _qf.clarify_budget is not None:
            cb = _qf.clarify_budget
            self._pending_budget[session_id] = cb
            resp = f"Kya aap ₹{cb} lakh ke budget ki baat kar rahe hain?"
            return ChatResult(
                intent="clarify", response=resp, vehicles=[],
                status="clarify", count=0, filters={},
                guardrails=["G-BUDGET-CLARIFY"], request_id=rid,
                meta={"inventory_count": self.inventory_count, "returned": 0,
                      "route": "clarify", "clarify_budget": cb})
        # D — mid-conversation safety net: anything that would be "unknown" while a
        # search context exists becomes a continuation prompt, never "unknown".
        if rr.kind == "unknown" and base is not None:
            return self._show_more(session_id, rr.language, rid)
        return None

    def _show_more(self, session_id: str, language: str, rid: str) -> ChatResult:
        """Return the next slice of the session's last inventory search; fall back
        to the remembered media candidate list, else a gentle clarify prompt."""
        base = self._last_search.get(session_id)
        if base is not None:
            result = self.engine.search(base)
            matches = result.matches
            offset = self._last_search_offset.get(session_id, 0)
            sl = matches[offset:offset + self.top_n]
            if sl:
                self._last_search_offset[session_id] = offset + len(sl)
                return ChatResult(
                    intent="availability",
                    response=render_template("more_options", language),
                    vehicles=[public_vehicle(it) for it in sl],
                    status="multi", count=result.count,
                    filters=base.active_filters(), guardrails=["G-MORE"],
                    request_id=rid,
                    meta={"inventory_count": self.inventory_count,
                          "returned": len(sl), "route": "continuation"})
            self._last_search_offset[session_id] = 0
            return ChatResult(
                intent="availability",
                response=render_template("no_more_options", language),
                vehicles=[], status="exhausted", count=result.count, filters={},
                guardrails=["G-MORE"], request_id=rid,
                meta={"inventory_count": self.inventory_count, "returned": 0,
                      "route": "continuation"})
        # media candidate list remembered from a prior "which car?" turn
        entry = self._last_candidates.get(session_id)
        if entry and entry[1]:
            items = entry[1]
            lines = [f"{i+1}. {_candidate_label(c)}" for i, c in enumerate(items)]
            return ChatResult(
                intent=entry[0] or "clarify",
                response="\n".join(lines) + "\n\nNumber, year, ya reg number bata do.",
                vehicles=[], status="clarify", count=len(items), filters={},
                guardrails=["G-MORE"], request_id=rid,
                meta={"inventory_count": self.inventory_count, "returned": 0,
                      "route": "continuation"})
        # nothing to continue — gentle prompt, never "unknown"
        return ChatResult(
            intent="clarify", response=render_template("general_help", language),
            vehicles=[], status="clarify", count=0, filters={},
            guardrails=["G-MORE"], request_id=rid,
            meta={"inventory_count": self.inventory_count, "returned": 0,
                  "route": "continuation"})

    # -- routing coverage snapshot --
    def coverage(self) -> Dict[str, Any]:
        return self.metrics.coverage()


# module-level singleton so the API loads inventory only once
_service: Optional[ChatService] = None


def get_service() -> ChatService:
    global _service
    if _service is None:
        _service = ChatService()
    return _service


if __name__ == "__main__":
    svc = ChatService()
    for msg in ["SUV under 8 lakh", "Swift available hai?", "Fortuner price?",
                "Creta mein sunroof hai?", ""]:
        try:
            r = svc.handle(msg)
            print(f"\n[{r.intent}/{r.status}] {msg!r}\n  {r.response}\n  vehicles={len(r.vehicles)}")
        except ChatInputError as e:
            print(f"\n[400] {msg!r} -> {e}")
