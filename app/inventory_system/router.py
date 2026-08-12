"""
router.py
=========

Intent Router for the chatbot backend. Chooses, **deterministically**, between
three handlers for every customer message:

    customer message
          │
          ▼  IntentRouter.decide()
    ┌─────────────┬──────────────────────┬───────────────────────────┐
    │ RETRIEVAL   │ TEMPLATE             │ LLM (grounded fallback)   │
    │ inventory   │ FAQ / business rules │ recommend / compare /     │
    │ queries     │ (location, finance,  │ family-fit / vague-reel / │
    │ (primary)   │  test-drive, …)      │ ambiguous / multi-turn    │
    └─────────────┴──────────────────────┴───────────────────────────┘

Rules enforced here:
  * Retrieval is PRIMARY. The router only sends a message to the LLM when a
    deterministic retrieval/template answer is NOT possible (comparison,
    recommendation, suitability, vague/ambiguous reference).
  * The LLM is GROUNDED: it receives ONLY real inventory rows (via the
    retrieval engine) as facts and is instructed never to invent a vehicle,
    price, or availability. The structured `vehicles` returned ALWAYS come from
    inventory, never from the LLM.
  * If no LLM client is configured, the LLM route degrades to a safe,
    inventory-grounded deterministic answer — the system never blocks.

No vehicle/price/availability fact is ever produced by the LLM; those come only
from inventory data.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol

from inventory_models import InventoryItem, BodyType
from query_parser import Query, MODEL_LOOKUP, _MODEL_PHRASES, _norm, _has
from retrieval_engine import RetrievalEngine


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────
class Route(str, Enum):
    RETRIEVAL = "retrieval"
    TEMPLATE = "template"
    LLM = "llm"


@dataclass
class RouteDecision:
    route: Route
    reason: str
    template_key: Optional[str] = None      # set when route == TEMPLATE
    llm_kind: Optional[str] = None          # comparison|recommendation|suitability|vague
    models: List[str] = field(default_factory=list)   # models mentioned (for LLM)


# ─────────────────────────────────────────────────────────────────────────────
# Trigger vocabularies (deterministic)
# ─────────────────────────────────────────────────────────────────────────────
# strong cues = comparison even with one named model (the other may be unknown/
# out of stock); weak cues need two known models to avoid stealing simple queries.
STRONG_COMPARE_WORDS = ["vs", "versus", "compare", "comparison", "difference between",
                        "which is better", "konsi behtar", "kaunsi behtar"]
WEAK_COMPARE_WORDS = ["better", "cheaper", "sasti konsi", "konsi achhi", "or", "ya"]
RECO_WORDS = ["recommend", "suggest", "suggestion", "advice", "advise",
              "konsi lu", "kaunsi lu", "kaun si lu", "which should i",
              "which car should", "kya lu", "kya lena chahiye", "sabse achhi",
              "best car", "best gaadi", "achhi gaadi konsi", "konsi gaadi lu"]
FAMILY_WORDS = ["family", "parivaar", "parivar", "bacche", "bacchon", "kids",
                "children", "ghar ke liye"]
SUITABILITY_CUES = ["suitable", "good for", "achhi rahegi", "theek rahegi",
                    "chalegi", "best for", "konsi", "which", "sahi rahegi",
                    "ke liye theek"]


def extract_models(message: str) -> List[str]:
    """All distinct known models mentioned (longest-phrase-first, deduped)."""
    text = _norm(message)
    found: List[str] = []
    consumed = text
    for phrase in _MODEL_PHRASES:
        if _has(consumed, phrase):
            canon = MODEL_LOOKUP[phrase]
            if canon not in found:
                found.append(canon)
            # blank out the matched phrase so sub-strings don't double count
            consumed = re.sub(rf"(?<!\w){re.escape(phrase)}(?!\w)", " ", consumed)
    return found


# ─────────────────────────────────────────────────────────────────────────────
# FAQ / business-rule templates (no inventory facts, no invented business terms)
# ─────────────────────────────────────────────────────────────────────────────
PUBLIC_LOCATION = "Vasant Oasis Car Parking, Andheri East, Mumbai"

FAQ_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "greeting": {
        "patterns": ["hello", "hi", "hey", "namaste", "namaskar", "salaam", "good morning",
                     "good evening"],
        "response": (f"Namaste! Vasant Oasis Car Parking mein aapka swagat hai. "
                     f"Kaunsi gaadi dhundh rahe ho — model ya budget bata do?"),
    },
    "thanks": {
        "patterns": ["thank", "thanks", "shukriya", "dhanyavaad"],
        "response": ("Welcome! Aa ke gaadi dekh lo — "
                     f"{PUBLIC_LOCATION}."),
    },
    "location": {
        "patterns": ["where are you", "where is your", "location", "address", "kahan ho",
                     "kahan hai", "kaise aau", "kaise aaye", "reach", "pata kya", "map"],
        "response": (f"Hum yahan hain — {PUBLIC_LOCATION}. "
                     f"Aap aaj aa ke gaadiyan dekh sakte ho; location WhatsApp pe bhej doon?"),
    },
    "timings": {
        "patterns": ["timing", "kab tak khula", "kab khulta", "open hours", "what time",
                     "kab aau", "kab tak open"],
        "response": ("Aap aaram se aa ke gaadi dekh sakte ho — exact timing main "
                     f"confirm kar deta hoon. {PUBLIC_LOCATION}."),
    },
    "finance": {
        "patterns": ["finance", "loan", "emi", "down payment", "kist", "installment",
                     "financing"],
        "response": ("Finance aur EMI ki suvidha available hai — exact terms aur "
                     "eligibility hamari team aapko visit pe bata degi. Aa ke gaadi "
                     f"bhi dekh lo, {PUBLIC_LOCATION}."),
    },
    "documents": {
        "patterns": ["documents", "papers chahiye", "kya documents", "kagzaat",
                     "what documents", "id proof"],
        "response": ("Required documents hamari team aapko visit pe bata degi — "
                     f"zyada kuch nahi lagta. {PUBLIC_LOCATION}."),
    },
    "test_drive": {
        "patterns": ["test drive", "test-drive", "chala ke dekh", "drive kar ke"],
        "response": ("Test drive available hai — aa ke gaadi chala ke dekh sakte ho. "
                     f"{PUBLIC_LOCATION}."),
    },
    "exchange": {
        "patterns": ["exchange", "purani gaadi de", "old car exchange", "buy back",
                     "exchange policy"],
        "response": ("Exchange ho jata hai — aap apni purani gaadi laao, team "
                     f"evaluate kar ke best value bata degi. {PUBLIC_LOCATION}."),
    },
    "warranty": {
        "patterns": ["warranty", "guarantee", "guaranty"],
        "response": ("Warranty aur post-sale details hamari team aapko visit pe "
                     f"confirm kar degi. {PUBLIC_LOCATION}."),
    },
}


class TemplateResponder:
    def match(self, message: str) -> Optional[str]:
        text = _norm(message)
        for key, spec in FAQ_TEMPLATES.items():
            for pat in spec["patterns"]:
                if _has(text, _norm(pat)):
                    return key
        return None

    def answer(self, key: str) -> str:
        return FAQ_TEMPLATES[key]["response"]


# ─────────────────────────────────────────────────────────────────────────────
# LLM client abstraction (pluggable; default None -> deterministic grounding)
# ─────────────────────────────────────────────────────────────────────────────
class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str:
        ...


class GroqLLMClient:
    """Optional real client (mirrors the voice agent's Groq usage). Lazy import."""

    def __init__(self, api_key: Optional[str] = None, model: str = "llama-3.1-8b-instant"):
        import os
        from groq import Groq  # optional dependency
        self._client = Groq(api_key=api_key or os.getenv("GROQ_API_KEY"))
        self._model = model

    def complete(self, system: str, user: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=0.3, max_tokens=220,
        )
        return resp.choices[0].message.content or ""


LLM_SYSTEM_PROMPT = (
    "You are the inventory assistant for Vasant Oasis Car Parking, Andheri East, "
    "Mumbai. You may ONLY talk about the vehicles listed in FACTS. NEVER invent a "
    "vehicle, price, year, kilometres, or availability that is not in FACTS. "
    "If asked about a car not in FACTS, say it is not currently in stock and "
    "suggest one from FACTS instead. Prices are in lakhs exactly as given; never "
    "state a price that is not in FACTS. Be concise and warm, reply in Hinglish, "
    "and always end by inviting the customer to visit the lot. Do NOT mention "
    "registration numbers, parking slots, or stock numbers."
)


# ─────────────────────────────────────────────────────────────────────────────
# Grounded LLM fallback
# ─────────────────────────────────────────────────────────────────────────────
_REG_RE = re.compile(r"MH\d{2}[A-Z]{0,3}\d{3,4}")


@dataclass
class LLMResult:
    response: str
    vehicles: List[Dict[str, Any]]
    llm_kind: str
    llm_used: bool
    grounded: bool = True


class LLMFallback:
    def __init__(self, engine: RetrievalEngine, llm_client: Optional[LLMClient] = None,
                 *, max_facts: int = 6):
        self.engine = engine
        self.llm_client = llm_client
        self.max_facts = max_facts

    # -- gather REAL inventory rows to ground the answer --
    def _gather(self, message: str, query: Query, decision: RouteDecision) -> List[InventoryItem]:
        pool = self.engine.all_facing
        items: List[InventoryItem] = []
        seen = set()

        # explicit models named in a comparison/recommendation
        for model in decision.models:
            for it in pool:
                if (it.model or "").lower() == model.lower() and it.registration_no not in seen:
                    items.append(it); seen.add(it.registration_no)

        # filter-driven candidates (recommendation / suitability with constraints)
        if query.has_any_filter():
            r = self.engine.search(query)
            for it in r.matches:
                if it.registration_no not in seen:
                    items.append(it); seen.add(it.registration_no)

        # family suitability with no explicit filter -> surface 7-seaters
        if decision.llm_kind == "suitability" and not items:
            for it in pool:
                if it.seats == 7 and it.registration_no not in seen:
                    items.append(it); seen.add(it.registration_no)

        # last resort: a representative spread (newest first) so we never answer blind
        if not items:
            items = sorted(pool, key=lambda i: -(i.year_int or 0))

        return items[: self.max_facts]

    def answer(self, message: str, query: Query, decision: RouteDecision) -> LLMResult:
        from chat_service import public_vehicle  # local import avoids a cycle
        candidates = self._gather(message, query, decision)
        facts = [public_vehicle(it) for it in candidates]

        if self.llm_client is not None:
            user = self._build_user(message, facts)
            try:
                text = self.llm_client.complete(LLM_SYSTEM_PROMPT, user)
                text = self._scrub(text, candidates)
                return LLMResult(text, facts, decision.llm_kind or "complex", True)
            except Exception:
                # any LLM failure -> safe deterministic grounding (never block)
                pass

        text = self._deterministic(message, query, decision, candidates)
        return LLMResult(text, facts, decision.llm_kind or "complex", False)

    # -- prompt construction (facts only) --
    @staticmethod
    def _build_user(message: str, facts: List[Dict[str, Any]]) -> str:
        import json
        lean = [{k: f[k] for k in ("make", "model", "year", "fuel", "transmission",
                                   "color", "owners", "seats", "body_type",
                                   "price_lakh", "price_quotable")} for f in facts]
        return (f"Customer: {message}\n\n"
                f"FACTS (these are the ONLY vehicles that exist; prices in lakhs):\n"
                f"{json.dumps(lean, ensure_ascii=False)}\n\nAnswer:")

    # -- safety scrub on LLM output --
    @staticmethod
    def _scrub(text: str, candidates: List[InventoryItem]) -> str:
        text = _REG_RE.sub("", text)
        for it in candidates:
            if it.location_code:
                text = text.replace(it.location_code, "")
            text = text.replace(it.registration_no, "")
        return re.sub(r"\s{2,}", " ", text).strip()

    # -- deterministic grounded answer (no LLM available) --
    def _deterministic(self, message: str, query: Query, decision: RouteDecision,
                       candidates: List[InventoryItem]) -> str:
        loc = f"aaj aa ke dekh lo — {PUBLIC_LOCATION}."

        def desc(it: InventoryItem) -> str:
            bits = [str(it.year_int) if it.year_int else "", it.color_norm or "",
                    it.model or ""]
            head = " ".join(b for b in bits if b)
            price = f" ({it.price_lakh:.2f} lakh)" if it.price_quotable and it.price_lakh else ""
            return f"{head}, {it.fuel_norm}{price}".strip()

        kind = decision.llm_kind
        if kind == "vague":
            return ("Kaunsi gaadi pasand aayi — model ya budget bata do, "
                    "main best option nikaal deta hoon.")

        if kind == "comparison":
            named = decision.models
            present = {(c.model or "").lower(): c for c in candidates}
            lines = []
            for m in named:
                if m.lower() in present:
                    lines.append(desc(present[m.lower()]))
                else:
                    lines.append(f"{m} abhi stock mein nahi")
            if not lines:
                lines = [desc(c) for c in candidates[:2]]
            return ("Dono compare karun toh — " + "; ".join(lines) +
                    f". Aap {loc} dono dekh ke best laga wala le lena.")

        # recommendation / suitability
        if candidates:
            top = "; ".join(desc(c) for c in candidates[:3])
            lead = ("Family ke liye yeh achhe rahenge"
                    if kind == "suitability" else "Aapke liye yeh suit karenge")
            return f"{lead} — {top}. {loc.capitalize()}"
        return f"Aap budget ya type bata do, main best nikaal deta hoon — {PUBLIC_LOCATION}."


# ─────────────────────────────────────────────────────────────────────────────
# The router
# ─────────────────────────────────────────────────────────────────────────────
class IntentRouter:
    def __init__(self, templater: Optional[TemplateResponder] = None):
        self.templater = templater or TemplateResponder()

    def decide(self, message: str, query: Query) -> RouteDecision:
        text = _norm(message)
        models = extract_models(message)

        # ── 0) registration number -> exact vehicle, skip ambiguity/clarify/FAQ ──
        if query.registration:
            return RouteDecision(Route.RETRIEVAL, "registration: exact vehicle match")

        # ── 1) COMPLEX -> LLM (only things deterministic paths cannot answer) ──
        # comparison: a strong compare cue + >=1 model (other may be unknown),
        # or a weak cue with >=2 known models.
        strong = any(_has(text, _norm(w)) for w in STRONG_COMPARE_WORDS)
        weak = any(_has(text, _norm(w)) for w in WEAK_COMPARE_WORDS)
        if strong and len(models) >= 1:
            return RouteDecision(Route.LLM, "comparison: strong cue + model",
                                 llm_kind="comparison", models=models)
        if weak and len(models) >= 2:
            return RouteDecision(Route.LLM, "comparison: weak cue + two models",
                                 llm_kind="comparison", models=models)

        # recommendation
        if any(_has(text, _norm(w)) for w in RECO_WORDS):
            return RouteDecision(Route.LLM, "recommendation phrase",
                                 llm_kind="recommendation", models=models)

        # family suitability (family word + a suitability/question cue, not just
        # the 'family car' category lookup which retrieval handles)
        if any(_has(text, w) for w in FAMILY_WORDS) and \
           any(_has(text, _norm(w)) for w in SUITABILITY_CUES):
            return RouteDecision(Route.LLM, "family suitability question",
                                 llm_kind="suitability", models=models)

        # vague / ambiguous (reel reference with no concrete filter)
        if query.clarify_needed:
            return RouteDecision(Route.LLM, "vague/ambiguous reference",
                                 llm_kind="vague", models=models)

        # ── 2) FAQ / business rule -> TEMPLATE ──
        key = self.templater.match(message)
        if key:
            # don't let a stray FAQ keyword steal a concrete inventory lookup
            inventory_strong = bool(query.model or query.fuel or query.color or
                                    query.transmission or query.category or
                                    query.seats is not None or
                                    query.price_max is not None or
                                    query.price_min is not None or
                                    query.ownership_exact is not None or
                                    query.ownership_max is not None)
            if not inventory_strong:
                return RouteDecision(Route.TEMPLATE, f"faq:{key}", template_key=key)

        # ── 3) default -> RETRIEVAL (primary, deterministic) ──
        if query.has_any_filter() or query.intents:
            return RouteDecision(Route.RETRIEVAL, "deterministic inventory query")

        # nothing concrete, not FAQ, not complex -> ambiguous -> LLM clarifier
        return RouteDecision(Route.LLM, "no concrete intent -> clarifier",
                             llm_kind="vague", models=models)
