"""
lead_capture.py
==============

Captures a dealership **lead** from a conversation and keeps it scored and
stored. Deterministic — reuses the query parser, FAQ intent detector, language
detector, and visit-conversion scorer. No LLM.

Captured fields:
  phone, name, interested_vehicle, budget_min/max, finance_interest,
  exchange_interest, visit_intent, language, created_at, updated_at
plus the derived lead score (High/Medium/Low), visit signals, and visit_ready.

A conversation is identified by `session_id`; each turn merges new information
into the single accumulating lead (sticky booleans, latest vehicle/budget) and
re-scores over all signals seen so far.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from inventory_models import utcnow_iso
from inventory_loader import MAKE_MAP
import visit_conversion as vc
from lead_storage import LeadStore

_LEAD_NS = uuid.UUID("1ead0000-0000-4a00-9000-100000000000")

# ── phone (Indian mobile) ──
_PHONE_RE = re.compile(r"(\+?91[\-\s]?|0)?([6-9]\d{4}[\-\s]?\d{5}|[6-9]\d{9})")

# ── name cues ──
_NAME_PATTERNS = [
    re.compile(r"\bmy name is\s+([a-z]+(?:\s+[a-z]+)?)", re.I),
    re.compile(r"\bmyself\s+([a-z]+(?:\s+[a-z]+)?)", re.I),
    re.compile(r"\bi am\s+([a-z]+(?:\s+[a-z]+)?)", re.I),
    re.compile(r"\bi'?m\s+([a-z]+)", re.I),
    re.compile(r"\bmera naam\s+([a-z]+(?:\s+[a-z]+)?)", re.I),
    re.compile(r"\bnaam\s+([a-z]+)\s+hai", re.I),
    re.compile(r"\bmain\s+([a-z]+)\s+(?:hu|hoon|bol)", re.I),
]
_NAME_STOPWORDS = {
    "interested", "looking", "calling", "from", "here", "just", "asking",
    "searching", "wondering", "trying", "the", "a", "an", "ok", "okay",
    "fine", "good", "available", "ready",
}
# Hinglish fillers that can trail a captured name (e.g. "naam Sunil hai")
_NAME_FILLERS = {"hai", "hu", "hoon", "ji", "bol", "bolta", "bolti", "speaking",
                 "this", "side", "raha", "rahi"}


def extract_phone(message: str) -> Optional[str]:
    for m in _PHONE_RE.finditer(message or ""):
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        elif len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        if len(digits) == 10 and digits[0] in "6789":
            return digits
    return None


def extract_name(message: str) -> Optional[str]:
    for pat in _NAME_PATTERNS:
        m = pat.search(message or "")
        if not m:
            continue
        tokens = [t for t in m.group(1).split() if t.lower() not in _NAME_FILLERS]
        if not tokens or tokens[0].lower() in _NAME_STOPWORDS:
            continue
        return " ".join(tokens[:2]).title()       # at most first + last name
    return None


def extract_vehicle(query) -> Optional[str]:
    """Compose a short interested-vehicle label from parsed filters."""
    parts: List[str] = []
    if query.color:
        parts.append(query.color)
    if query.model:
        parts.append(query.model)
    elif query.category:
        if query.fuel:
            parts.append(query.fuel)
        parts.append(query.category)
    elif query.make:
        parts.append(MAKE_MAP.get(query.make, query.make))
    label = " ".join(parts).strip()
    return label or None


# ─────────────────────────────────────────────────────────────────────────────
# Lead model
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Lead:
    session_id: str
    lead_id: str = ""
    phone: Optional[str] = None
    name: Optional[str] = None
    interested_vehicle: Optional[str] = None
    budget_min: Optional[int] = None
    budget_max: Optional[int] = None
    finance_interest: bool = False
    exchange_interest: bool = False
    visit_intent: bool = False
    language: Optional[str] = None
    score_level: str = "Low"
    score_points: int = 0
    visit_ready: bool = False
    observed_signals: List[str] = field(default_factory=list)
    visit_signals: Dict[str, bool] = field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def __post_init__(self):
        if not self.lead_id:
            self.lead_id = "LD-" + uuid.uuid5(_LEAD_NS, self.session_id).hex[:12]

    def to_record(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_record(cls, rec: Dict[str, Any]) -> "Lead":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in rec.items() if k in known})


# ─────────────────────────────────────────────────────────────────────────────
# Capture engine
# ─────────────────────────────────────────────────────────────────────────────
class LeadCaptureEngine:
    def __init__(self, store: Optional[LeadStore] = None):
        self.store = store or LeadStore(":memory:")

    def capture(self, session_id: str, message: str,
                *, now: Optional[str] = None) -> Lead:
        now = now or utcnow_iso()
        existing = self.store.get(session_id)
        lead = Lead.from_record(existing) if existing else Lead(
            session_id=session_id, created_at=now)

        sig, meta = vc.extract_message_signals(message)
        q = meta["query"]

        # ── field extraction (merge, never clobber a known value with None) ──
        phone = extract_phone(message)
        if phone:
            lead.phone = phone
        name = extract_name(message)
        if name and not lead.name:
            lead.name = name
        vehicle = extract_vehicle(q)
        if vehicle:
            lead.interested_vehicle = vehicle          # latest interest wins
        if q.price_max is not None:
            lead.budget_max = q.price_max
        if q.price_min is not None:
            lead.budget_min = q.price_min

        # sticky interest booleans
        if vc.ASKS_FINANCE in sig:
            lead.finance_interest = True
        if vc.ASKS_EXCHANGE in sig:
            lead.exchange_interest = True
        if sig & set(vc.VISIT_SIGNAL_KEYS) or vc.ASKS_AVAILABILITY in sig:
            lead.visit_intent = True

        lead.language = meta["language"]

        # ── accumulate signals & re-score ──
        accumulated = set(lead.observed_signals or []) | sig
        if len(accumulated) > 1:
            accumulated.discard(vc.BROWSING)           # browsing only if nothing else
        lead.observed_signals = sorted(accumulated)

        ls = vc.score(accumulated)
        lead.score_level = ls.level
        lead.score_points = ls.points
        lead.visit_signals = ls.visit_signals
        lead.visit_ready = ls.visit_ready

        lead.created_at = lead.created_at or now
        lead.updated_at = now

        self.store.upsert(lead.to_record())
        return lead

    def get(self, session_id: str) -> Optional[Lead]:
        rec = self.store.get(session_id)
        return Lead.from_record(rec) if rec else None


if __name__ == "__main__":
    eng = LeadCaptureEngine()
    sid = "sess-1"
    turns = [
        "Hi, I'm Rahul, looking for a white Creta",
        "Can I get finance on it?",
        "What's your address? I'll come today. My number is 9876543210",
    ]
    for t in turns:
        lead = eng.capture(sid, t)
        print(f"[{lead.score_level:6} {lead.score_points:>2}] visit_ready={lead.visit_ready} "
              f"name={lead.name} phone={lead.phone} veh={lead.interested_vehicle} "
              f"fin={lead.finance_interest} <- {t}")
