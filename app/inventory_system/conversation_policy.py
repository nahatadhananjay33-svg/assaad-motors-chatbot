"""
conversation_policy.py
======================

Phase 12E — deterministic CONVERSATION MODE classifier.

This is a thin, READ-ONLY labelling layer on top of the existing Phase 11A/11B/12D
engine. It does NOT change routing, retrieval, memory or answers — it only decides
WHICH conversation mode a turn is, from signals the parser already produced, so the
behaviour can be observed (meta / analytics) and tested. NO LLM.

The seven modes (Phase 12E STEP 2):

    CURRENT_CAR        — attribute question about the pinned car
    SAME_MODEL_VARIANT — "automatic wali?", "petrol wali?" on the pinned model
    NEW_SEARCH         — a genuinely different model / category / budget / filter
    MULTI_INTENT       — two+ attributes asked at once
    CLARIFY            — not enough info (no car pinned) OR a same-dimension conflict
    FAQ                — finance / negotiation / location / visit / etc.
    OFFSHEET_UNKNOWN   — off-sheet topic or unknown; never fabricate

The actual behaviour for each mode is already implemented (11A pinned answers,
12D new-field answers, chat_service variant/browse memory, 11B conflict clarify,
FAQ router). This module just names the turn.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from query_parser import parse, Query
from intent_intelligence import detect_conflicts

MODE_CURRENT_CAR = "current_car"
MODE_SAME_MODEL_VARIANT = "same_model_variant"
MODE_NEW_SEARCH = "new_search"
MODE_MULTI_INTENT = "multi_intent"
MODE_CLARIFY = "clarify"
MODE_FAQ = "faq"
MODE_OFFSHEET_UNKNOWN = "offsheet_unknown"

# old-style single-attribute question flags (Phase 11A/7D) + price
_ATTR_FLAGS = ("insurance_query", "service_query", "warranty_detail_query",
               "rc_query", "ownership_query", "condition_query", "flood_query",
               "downpayment_query", "km_reading_query", "color_query",
               "fuel_query", "transmission_query", "seats_query",
               "year_query")           # Phase 12G
# a "variant refinement" over the pinned model (not a fresh browse)
_VARIANT_FIELDS = ("color", "fuel", "transmission", "ownership_exact",
                   "ownership_max")
# a "different class of car" → fresh browse
_BROWSE_FIELDS = ("model", "make", "category", "seats", "km_max",
                  "price_max", "price_min", "year_min", "year_exact")


def _attr_intents(q: Query):
    """All attribute-question fields on this turn (new 12D + old 11A + price)."""
    fields = list(getattr(q, "attr_fields", None) or [])
    for f in _ATTR_FLAGS:
        if getattr(q, f, False):
            fields.append(f)
    # "price" is a loose intent (bare "kitna"/"kitne" trips it). Count it as an
    # attribute ONLY when it is the sole signal — otherwise "boot space kitna"
    # would look multi-intent.
    if not fields and "price" in q.intents and not (
            q.price_max or q.price_min or q.sort_cheapest):
        fields.append("price")
    return fields


def _is_variant_refine(q: Query) -> bool:
    if any(getattr(q, f) is not None for f in _BROWSE_FIELDS) or q.feature_filters:
        return False
    return (q.sort_low_km or
            any(getattr(q, f) is not None for f in _VARIANT_FIELDS))


def classify(message: str, prev_ctx: Optional[Dict[str, Any]] = None,
             *, rr_kind: Optional[str] = None, q: Optional[Query] = None) -> str:
    """Return the conversation mode for a turn. `prev_ctx` = {'reg','model'} or None.
    `rr_kind` (faq|inventory|unknown) is used when available (from the router)."""
    if q is None:
        q = parse(message or "")
    pinned = bool(prev_ctx and (prev_ctx.get("reg") or prev_ctx.get("model")))

    # 1) genuine same-dimension conflict -> clarify (Phase 11B)
    if detect_conflicts(message or ""):
        return MODE_CLARIFY
    # 2) FAQ (finance / negotiation / location / visit / …) — the router's verdict
    #    wins (finance/loan/exchange are FAQ-handled even though also "off-sheet").
    if rr_kind == "faq":
        return MODE_FAQ
    # 3) off-sheet / unknown -> never fabricate
    if q.off_sheet or rr_kind == "unknown":
        return MODE_OFFSHEET_UNKNOWN

    attrs = _attr_intents(q)
    # 4) multi-intent (two+ attributes at once)
    if len(attrs) >= 2:
        return MODE_MULTI_INTENT
    # 5) a genuinely different requirement -> fresh browse
    if any(getattr(q, f) is not None for f in _BROWSE_FIELDS) or q.feature_filters \
            or q.sort_cheapest or q.registration or q.reg_partial:
        # a variant refinement (colour/fuel/owner/automatic/low-km) on the pinned
        # model is NOT a fresh browse
        if pinned and _is_variant_refine(q) and not any(
                getattr(q, f) is not None for f in _BROWSE_FIELDS) \
                and not q.registration and not q.reg_partial:
            return MODE_SAME_MODEL_VARIANT
        return MODE_NEW_SEARCH
    # 6) a variant refinement with a pin, no browse field
    if pinned and _is_variant_refine(q):
        return MODE_SAME_MODEL_VARIANT
    # 7) a single attribute question
    if attrs:
        return MODE_CURRENT_CAR if pinned else MODE_CLARIFY
    # nothing concrete
    return MODE_NEW_SEARCH if rr_kind == "inventory" else MODE_CLARIFY


if __name__ == "__main__":
    ctx = {"reg": None, "model": "Ertiga"}
    for m, c in [("RC?", ctx), ("RC?", None), ("automatic wali?", ctx),
                 ("7 seater chahiye", ctx), ("sunroof aur airbags hain?", ctx),
                 ("petrol diesel", ctx), ("finance milega?", None),
                 ("boot space kitna?", ctx), ("SUV under 8 lakh", ctx)]:
        print(f"{m:26} ctx={bool(c)} -> {classify(m, c)}")
