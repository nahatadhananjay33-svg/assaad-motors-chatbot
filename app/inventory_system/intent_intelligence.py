"""
intent_intelligence.py
======================

Phase 11B — Deterministic Intent Intelligence.

A READ-ONLY intelligence layer that sits ON TOP of the Phase-11A parser. It does
not modify the parser, retrieval, memory, media or browse logic. Given a customer
message (and, optionally, the already-parsed `Query`), it produces a structured,
fully deterministic `IntentAnalysis`:

  * per-intent confidence SCORES              (STEP 2)
  * a confidence BAND + recommendation        (STEP 3: answer / clarify / ask)
  * MULTI-INTENT detection                     (STEP 4)
  * CROSS-FIELD family relationships           (STEP 5)
  * normalized NUMERICS                         (STEP 6)
  * deterministic TYPO resolution (Levenshtein)(STEP 7)
  * INTENT FAMILIES (tiered vocabularies)       (STEP 8)
  * CONFLICT detection (same-dimension)         (STEP 9)

NO LLM. NO ML. NO embeddings. NO vector search. NO randomness. Same input always
yields the same output. Scoring is rational arithmetic over fixed vocabularies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, List, Optional, Tuple
import re

from query_parser import (parse, Query, normalize_typos, _norm, _has,
                           FUEL_WORDS, COLOR_WORDS)


# ─────────────────────────────────────────────────────────────────────────────
# Confidence bands (STEP 3)
# ─────────────────────────────────────────────────────────────────────────────
BAND_HIGH = "high"        # answer immediately
BAND_MEDIUM = "medium"    # clarify
BAND_LOW = "low"          # do not guess — ask

HIGH_THRESHOLD = 0.80
MEDIUM_THRESHOLD = 0.45

# tier base scores (STEP 2)
_TIER = {"strong": 0.97, "exact": 0.90, "synonym": 0.82, "weak": 0.55, "vague": 0.30}


# ─────────────────────────────────────────────────────────────────────────────
# Intent families (STEP 8) — tiered vocabularies per canonical intent.
#  strong  : specific, unambiguous multi-word phrases
#  exact   : canonical field-name tokens
#  synonym : aliases / other-language equivalents
#  weak    : broad, needs context  -> medium band -> clarify
#  vague   : very ambiguous        -> low band    -> ask
# Kept intentionally aligned with query_parser's Phase-11A vocabularies so the
# score never disagrees with what the parser would actually do.
# ─────────────────────────────────────────────────────────────────────────────
FAMILIES: Dict[str, Dict[str, List[str]]] = {
    "rc": {
        "strong": ["rc transfer status", "registration certificate", "loan closed",
                   "duplicate rc", "hypothecation", "noc available", "rc status",
                   "fitness certificate", "rto transfer", "puc certificate"],
        "exact": ["rc", "registration", "transfer", "noc", "fitness", "fc", "rto",
                  "documents", "document", "rc transfer", "name transfer"],
        "synonym": ["kagzat", "kagaz", "kaagaz", "kagad", "kaagad", "आरसी",
                    "रजिस्ट्रेशन", "ट्रान्सफर", "एनओसी", "फिटनेस", "कागदपत्र", "आरटीओ"],
        "weak": ["papers", "paper", "docs", "paperwork", "road tax", "tax paid"],
    },
    "insurance": {
        "strong": ["no claim bonus", "insurance cover", "policy valid",
                   "cover note", "policy details", "insurance claim"],
        "exact": ["insurance", "insured", "policy", "claim", "claims", "ncb",
                  "bima", "beema"],
        "synonym": ["विमा", "पॉलिसी", "क्लेम", "विमा दावा", "no claim"],
        "weak": ["cover", "valid"],
    },
    "ownership": {
        "strong": ["number of owners", "how many owners", "single owner",
                   "first owner", "second owner", "owner history"],
        "exact": ["owner", "owners", "malik", "maalik", "malak", "maalak"],
        "synonym": ["kitne owner", "kitne malik", "मालक", "किती मालक", "एकच मालक",
                    "pahila malak", "ek malak"],
        "weak": ["hands", "used by"],
    },
    "km": {
        "strong": ["odometer reading", "km reading", "kitne km chali",
                   "how many km", "km driven"],
        "exact": ["km", "kms", "kilometer", "kilometre", "kilometers", "kilometres",
                  "odometer", "odo", "running", "mileage reading"],
        "synonym": ["kitni chali", "km chali", "kitna chala", "किलोमीटर", "किमी",
                    "कितनी चली", "रनिंग", "chali"],
        "weak": ["distance", "reading", "chalti"],
    },
    "condition": {
        "strong": ["accident history", "accident free", "flood damage",
                   "body condition", "engine condition", "denting painting",
                   "condition report"],
        "exact": ["condition", "accident", "accidental", "damage", "damaged",
                  "scratch", "dent", "repaint", "repainted", "rust", "touchup",
                  "touch up", "denting", "crash"],
        "synonym": ["halat", "halaat", "hadsa", "takkar", "nuksan", "nuksaan",
                    "अपघात", "नुकसान", "स्थिती", "गंज"],
        "weak": ["paint", "body", "putty", "panel", "interior"],
    },
    "color": {
        "strong": ["which colour", "which color", "what colour", "what color",
                   "kaunsa rang", "kaun sa rang", "konsa rang"],
        "exact": ["color", "colour", "rang", "kalar"],
        "synonym": ["रंग", "कलर", "कोणता रंग", "रंग काय", "color kya", "rang kya"],
        "weak": ["shade"],
    },
    "fuel": {
        "strong": ["fuel type", "kaunsa fuel", "which fuel", "petrol ya diesel",
                   "diesel ya petrol"],
        "exact": ["fuel", "petrol", "diesel", "cng", "hybrid", "electric"],
        "synonym": ["इंधन", "कोणते इंधन", "फ्युएल", "gas wali", "battery wali"],
        "weak": ["gas"],
    },
    "transmission": {
        "strong": ["manual ya automatic", "automatic ya manual",
                   "which transmission", "gear type"],
        "exact": ["transmission", "automatic", "manual", "amt", "cvt", "gearbox",
                  "gear box"],
        "synonym": ["गिअरबॉक्स", "ट्रान्समिशन", "कोणते गिअर", "gear kaisa", "auto gear"],
        "weak": ["gear", "clutch", "stick"],
    },
    "seats": {
        "strong": ["how many seats", "seating capacity", "kitni seats",
                   "kitne log baith"],
        "exact": ["seater", "seats", "seat", "seating"],
        "synonym": ["किती सीट", "कितनी सीट", "आसन क्षमता", "kitni seat"],
        "weak": ["capacity", "log"],
    },
    "price": {
        "strong": ["how much", "price kya hai", "kitne ka hai", "kitne ki hai",
                   "on road price"],
        "exact": ["price", "rate", "cost", "daam", "bhav", "kimat", "kimmat",
                  "keemat", "kemat"],
        "synonym": ["किंमत", "दाम", "भाव", "kitne ka", "kitne ki", "kitne mein"],
        "weak": ["final", "kitna", "kitne", "quote"],
    },
    "budget": {
        "strong": ["ke andar", "se kam", "under budget", "budget mein"],
        "exact": ["budget", "under", "below", "upto", "within", "sasti", "cheapest"],
        "synonym": ["सस्ती", "बजेट", "के अंदर", "पेक्षा कमी", "kam budget"],
        "weak": ["cheap", "affordable"],
    },
    "finance": {
        "strong": ["down payment", "monthly installment", "emi kitni",
                   "finance available", "loan milega"],
        "exact": ["finance", "loan", "emi", "downpayment", "kist", "installment",
                  "instalment"],
        "synonym": ["हप्ता", "ईएमआई", "डाउन पेमेंट", "किती हप्ता", "dp kitna"],
        "weak": ["monthly", "credit"],
    },
    "warranty": {
        "strong": ["warranty period", "warranty available", "engine warranty",
                   "warranty card", "warranty status"],
        "exact": ["warranty", "guarantee", "gaurantee", "guaranty", "assurance"],
        "synonym": ["वॉरंटी", "गॅरंटी", "हमी", "वारंटी", "garanti"],
        "weak": ["cover", "protection"],
    },
    "service": {
        "strong": ["service history", "service record", "last service",
                   "maintenance history", "service center"],
        "exact": ["service", "serviced", "maintenance", "servicing"],
        "synonym": ["सर्व्हिस", "सर्विस", "servis", "oil change"],
        "weak": ["records"],
    },
    "photo": {
        "strong": ["interior photos", "exterior photos", "send photos"],
        "exact": ["photo", "photos", "pic", "pics", "picture", "pictures", "image",
                  "images", "snaps"],
        "synonym": ["tasveer", "foto", "फोटो", "चित्र", "तस्वीर"],
        "weak": ["gallery"],
    },
    "video": {
        "strong": ["walkaround video", "send video"],
        "exact": ["video", "videos", "walkaround", "clip", "clips"],
        "synonym": ["व्हिडिओ", "chalti gaadi"],
        "weak": [],
    },
    "instagram": {
        "strong": ["instagram reel", "insta link"],
        "exact": ["instagram", "insta", "reel", "reels"],
        "synonym": ["insta pe", "ig video"],
        "weak": ["story"],
    },
    "youtube": {
        "strong": ["youtube video", "youtube link", "youtube shorts", "yt shorts"],
        "exact": ["youtube", "you tube", "shorts"],
        "synonym": ["yt video", "yt link"],
        "weak": [],
    },
    "availability": {
        "strong": ["available hai", "in stock", "abhi hai", "still available"],
        "exact": ["available", "stock", "availability", "milega", "milegi"],
        "synonym": ["उपलब्ध", "स्टॉक", "abhi", "chalu hai"],
        "weak": [],
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Cross-field family relationships (STEP 5) — understanding, NOT merging.
# ─────────────────────────────────────────────────────────────────────────────
CROSS_FIELD: Dict[str, List[str]] = {
    "finance": ["loan", "hypothecation", "noc", "rc", "emi", "budget", "price"],
    "rc": ["finance", "noc", "hypothecation", "insurance", "documents"],
    "condition": ["accident", "flood", "touchup", "paint", "body", "engine", "km"],
    "price": ["negotiable", "budget", "finance", "emi"],
    "budget": ["price", "finance", "emi"],
    "media": ["photo", "video", "instagram", "youtube"],
    "photo": ["video", "instagram", "youtube"],
    "video": ["photo", "instagram", "youtube"],
    "insurance": ["rc", "claim", "documents"],
    "warranty": ["service", "condition"],
    "service": ["warranty", "condition"],
    "km": ["condition", "service"],
}


# ─────────────────────────────────────────────────────────────────────────────
# Dimension VALUE sets — for conflict detection (STEP 9). A "dimension" is a slot
# that can hold exactly one value; two distinct values = a contradiction.
# ─────────────────────────────────────────────────────────────────────────────
_FUEL_VALUES = {  # phrase -> canonical
    "petrol": "Petrol", "diesel": "Diesel", "cng": "CNG", "gas": "CNG",
    "hybrid": "Hybrid", "electric": "Electric", "ev": "Electric",
}
_TRANS_VALUES = {
    "automatic": "Automatic", "auto": "Automatic", "amt": "Automatic",
    "cvt": "Automatic", "dct": "Automatic", "dsg": "Automatic",
    "manual": "Manual", "stick": "Manual", "gear wali": "Manual",
}
_OWNER_VALUES = {
    "first owner": 1, "single owner": 1, "1 owner": 1, "one owner": 1,
    "pehla owner": 1, "second owner": 2, "2 owner": 2, "two owner": 2,
    "doosra owner": 2, "third owner": 3, "3 owner": 3,
}


# ─────────────────────────────────────────────────────────────────────────────
# Numeric normalization (STEP 6)
# ─────────────────────────────────────────────────────────────────────────────
_INT_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _to_int(num_str: str) -> float:
    return float(num_str.replace(",", ""))


def _amount_norm(text: str) -> str:
    """Lowercase + collapse spaces but PRESERVE commas/dots (so Indian grouping
    like '8,00,000' survives — `_norm` would shatter it into '8 00 000')."""
    t = (text or "").lower().replace("₹", " rs ")
    t = re.sub(r"[^\w\s\.,]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def normalize_amount(text: str) -> Optional[int]:
    """Normalize any money expression to integer rupees. Deterministic.
    8L / 8 l / 8 lac / 8 lakh / ₹8 lakh / 800000 / 8,00,000 / 0.8 million ->800000."""
    t = _amount_norm(text)
    # crore
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(?:crore|cr)\b", t)
    if m:
        return int(_to_int(m.group(1)) * 10_000_000)
    # million
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(?:million|mn)\b", t)
    if m:
        return int(_to_int(m.group(1)) * 1_000_000)
    # lakh / lac / l  (also handles "lakh 8")
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(?:lakh|lakhs|lac|lacs|l)\b", t) \
        or re.search(r"(?:lakh|lakhs|lac|lacs)\s+(\d[\d,]*(?:\.\d+)?)", t)
    if m:
        return int(_to_int(m.group(1)) * 100_000)
    # thousand / k
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(?:thousand|k)\b", t)
    if m:
        return int(_to_int(m.group(1)) * 1_000)
    # explicit currency -> any amount
    m = re.search(r"(?:rs\.?|rupees?)\s*(\d[\d,]*(?:\.\d+)?)\b", t)
    if m:
        return int(_to_int(m.group(1)))
    # bare number: only when it is clearly a price (>= 5 digits, i.e. >= 10,000)
    # and NOT immediately a km / seat / owner quantity, so a 4-digit model year
    # like "2019" and "20000 km" are never read as rupees.
    m = re.search(r"\b(\d[\d,]{4,})\b(?!\s*(?:km|kms|kilomet|seat|owner|malik))", t)
    if m and len(m.group(1).replace(",", "")) >= 5:
        return int(_to_int(m.group(1)))
    return None


def normalize_numbers(text: str) -> Dict[str, object]:
    """Extract every numeric dimension deterministically."""
    t = _norm(text)
    out: Dict[str, object] = {}
    amt = normalize_amount(text)
    if amt is not None:
        out["amount_inr"] = amt
    m = re.search(r"(\d[\d,]*)\s*(?:km|kms|kilometers?|kilometres?|किमी)", t)
    if m:
        km = int(_to_int(m.group(1)))
        # "20k km" style
        if re.search(r"\d\s*k\s*(?:km|kms)", t):
            km *= 1000
        out["km"] = km
    m = re.search(r"(\d)\s*(?:owner|owners|malik|malak)\b", t)
    if m:
        out["owners"] = int(m.group(1))
    m = re.search(r"(\d)\s*(?:seater|seat|seats)\b", t)
    if m:
        out["seats"] = int(m.group(1))
    m = re.search(r"\b(19[5-9]\d|20[0-3]\d)\b", t)
    if m:
        out["year"] = int(m.group(1))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Deterministic typo intelligence (STEP 7) — classic Levenshtein, closed vocab.
# ─────────────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=20000)
def _lev(a: str, b: str) -> int:
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > 2:            # early out — we never accept distance > 2
        return 3
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[lb]


# closed correction vocabulary: canonical keyword -> family
_CORRECTION_VOCAB: Dict[str, str] = {}
for _fam, _tiers in FAMILIES.items():
    for _tier in ("strong", "exact", "synonym"):
        for _ph in _tiers.get(_tier, []):
            for _tok in _ph.split():
                if _tok.isascii() and len(_tok) >= 5:   # only meaningful ASCII words
                    _CORRECTION_VOCAB.setdefault(_tok, _fam)
# add a few high-value canonical spellings customers misspell
for _w, _f in {"insurance": "insurance", "transmission": "transmission",
               "automatic": "transmission", "warranty": "warranty",
               "diesel": "fuel", "petrol": "fuel", "registration": "rc",
               "documents": "rc", "colour": "color", "mileage": "km",
               "odometer": "km", "condition": "condition",
               "instagram": "instagram", "youtube": "youtube",
               "hypothecation": "rc"}.items():
    _CORRECTION_VOCAB[_w] = _f

_VOCAB_WORDS = tuple(sorted(_CORRECTION_VOCAB))


def resolve_typo(token: str) -> Optional[Tuple[str, str, int]]:
    """Return (corrected_word, family, distance) if `token` is a confident typo of
    exactly one vocab word, else None. Deterministic: fixed threshold + uniqueness."""
    token = token.lower()
    if len(token) < 5 or token in _CORRECTION_VOCAB:
        return None
    thresh = 1 if len(token) <= 6 else 2
    best: List[Tuple[int, str]] = []
    for w in _VOCAB_WORDS:
        if abs(len(w) - len(token)) > thresh:
            continue
        d = _lev(token, w)
        if d <= thresh:
            best.append((d, w))
    if not best:
        return None
    best.sort()
    # confident only if the single nearest is strictly closer than the next
    if len(best) > 1 and best[0][0] == best[1][0]:
        return None
    d, w = best[0]
    return (w, _CORRECTION_VOCAB[w], d)


def resolve_typos(text: str) -> Dict[str, Tuple[str, str, int]]:
    out: Dict[str, Tuple[str, str, int]] = {}
    for tok in set(_norm(text).split()):
        r = resolve_typo(tok)
        if r:
            out[tok] = r
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Scoring engine (STEP 2)
# ─────────────────────────────────────────────────────────────────────────────
def _family_score(text: str, family: str, tiers: Dict[str, List[str]],
                  typo_families: Dict[str, int]) -> Tuple[float, str]:
    """Best deterministic score for one family + the evidence phrase."""
    best = 0.0
    best_ev = ""
    for tier in ("strong", "exact", "synonym", "weak", "vague"):
        base = _TIER.get(tier, 0.0)
        if base <= best:
            continue
        for ph in tiers.get(tier, []):
            if _has(text, ph):
                # specificity bonus: multi-word / longer phrase is more certain
                bonus = 0.0
                if " " in ph:
                    bonus += 0.02
                if len(ph) >= 8:
                    bonus += 0.01
                s = min(base + bonus, 0.99)
                if s > best:
                    best, best_ev = s, ph
                break
    # typo-corrected evidence (lower confidence — penalty per edit)
    if family in typo_families:
        d = typo_families[family]
        s = max(_TIER["exact"] - 0.15 * d, 0.5)
        if s > best:
            best, best_ev = s, f"typo(d={d})"
    return best, best_ev


@dataclass
class IntentAnalysis:
    message: str
    normalized: str
    scores: Dict[str, float]                       # intent -> confidence (STEP 2)
    primary: Optional[str]                          # highest-scoring intent
    confidence: float
    band: str                                      # high | medium | low (STEP 3)
    recommendation: str                            # answer | clarify | ask
    multi_intents: List[str] = field(default_factory=list)   # STEP 4
    related: List[str] = field(default_factory=list)          # STEP 5 cross-field
    numbers: Dict[str, object] = field(default_factory=dict)  # STEP 6
    typos: Dict[str, Tuple[str, str, int]] = field(default_factory=dict)  # STEP 7
    conflicts: List[Dict[str, object]] = field(default_factory=dict)      # STEP 9

    def to_dict(self) -> Dict[str, object]:
        return {
            "primary": self.primary, "confidence": round(self.confidence, 3),
            "band": self.band, "recommendation": self.recommendation,
            "multi_intents": self.multi_intents, "related": self.related,
            "numbers": self.numbers,
            "typos": {k: {"word": v[0], "family": v[1], "distance": v[2]}
                      for k, v in self.typos.items()},
            "conflicts": self.conflicts,
            "top_scores": dict(sorted(self.scores.items(),
                                      key=lambda kv: -kv[1])[:6]),
        }


_DISJUNCTION_RE = re.compile(r"(?<!\w)(ya|or|va|athva|अथवा|या|किंवा)(?!\w)")


def _detect_conflicts(text: str) -> List[Dict[str, object]]:
    """Same-dimension contradictions (STEP 9). Two+ distinct values in one slot.
    A disjunction ("petrol YA diesel", "automatic OR manual") makes it a CHOICE
    question, not a contradiction — those are handled as *_query questions, so we
    never flag them as conflicts."""
    if _DISJUNCTION_RE.search(text):
        return []
    conflicts: List[Dict[str, object]] = []

    def _distinct(values_map):
        found = []
        for phrase, canon in values_map.items():
            if _has(text, phrase) and canon not in found:
                found.append(canon)
        return found

    fuels = _distinct(_FUEL_VALUES)
    if len(fuels) >= 2:
        conflicts.append({"dimension": "fuel", "values": fuels})
    trans = _distinct(_TRANS_VALUES)
    if len(trans) >= 2:
        conflicts.append({"dimension": "transmission", "values": trans})
    owners = _distinct(_OWNER_VALUES)
    if len(owners) >= 2:
        conflicts.append({"dimension": "ownership", "values": owners})
    # colours: use the parser's own colour map, count distinct canonicals
    colors = []
    for phrase, canon in COLOR_WORDS.items():
        if _has(text, phrase) and canon not in colors:
            colors.append(canon)
    if len(colors) >= 2:
        conflicts.append({"dimension": "color", "values": colors})
    return conflicts


# multi-word phrases whose presence should suppress a bare-token false positive
# handled implicitly by tier ordering; nothing extra needed here.

def analyze(message: str, q: Optional[Query] = None) -> IntentAnalysis:
    """The deterministic intelligence pass. Reuses `q` if supplied (no re-parse)."""
    normalized = normalize_typos(message or "")
    text = _norm(normalized)
    if q is None:
        q = parse(message or "")

    numbers = normalize_numbers(normalized)
    typos = resolve_typos(normalized)
    typo_families: Dict[str, int] = {}
    for _tok, (_w, _fam, _d) in typos.items():
        typo_families[_fam] = min(typo_families.get(_fam, 9), _d)

    scores: Dict[str, float] = {}
    evidence: Dict[str, str] = {}
    for fam, tiers in FAMILIES.items():
        s, ev = _family_score(text, fam, tiers, typo_families)
        if s > 0:
            scores[fam] = s
            evidence[fam] = ev

    # Phase 12D: new vehicle-detail fields — reuse the parser's field_intents
    # detection (no vocab duplication) so scoring / multi-intent / analytics cover
    # specs, features, EV, keys and extra documents too. High-confidence match.
    for _a in list(getattr(q, "attr_fields", None) or []) + \
            list(getattr(q, "feature_filters", None) or {}):
        scores.setdefault(_a, 0.9)
        evidence.setdefault(_a, "field_intents")

    conflicts = _detect_conflicts(text)

    # primary = highest score
    primary, confidence = None, 0.0
    if scores:
        primary = max(scores, key=lambda k: scores[k])
        confidence = scores[primary]

    # multi-intent (STEP 4): every family that is confidently present (high band),
    # ordered by score. Never lose a secondary intent.
    multi = [k for k, v in sorted(scores.items(), key=lambda kv: -kv[1])
             if v >= HIGH_THRESHOLD]

    # cross-field related (STEP 5)
    related: List[str] = []
    for fam in multi[:3]:
        for rel in CROSS_FIELD.get(fam, []):
            if rel not in related and rel not in multi:
                related.append(rel)

    # confidence band + recommendation (STEP 3)
    if conflicts:
        band, rec = BAND_MEDIUM, "clarify"          # contradiction -> clarify
    elif confidence >= HIGH_THRESHOLD:
        band, rec = BAND_HIGH, "answer"
    elif confidence >= MEDIUM_THRESHOLD:
        band, rec = BAND_MEDIUM, "clarify"
    else:
        band, rec = BAND_LOW, "ask"

    return IntentAnalysis(
        message=message or "", normalized=normalized, scores=scores,
        primary=primary, confidence=confidence, band=band, recommendation=rec,
        multi_intents=multi, related=related, numbers=numbers, typos=typos,
        conflicts=conflicts)


def detect_conflicts(message: str) -> List[Dict[str, object]]:
    """Public wrapper: same-dimension contradictions in a raw message (STEP 9)."""
    return _detect_conflicts(_norm(normalize_typos(message or "")))


# human clarifications for a detected contradiction (STEP 3 conflict -> clarify)
_CONFLICT_CLARIFY = {
    "fuel":        "{a} ya {b} — kaunsa fuel chahiye?",
    "transmission": "{a} ya {b} — kaunsa chahiye?",
    "color":       "{a} ya {b} — kaunsa colour chahiye?",
    "ownership":   "{a} owner ya {b} owner — kaunsa chahiye?",
}


def conflict_clarification(conflicts: List[Dict[str, object]]) -> Optional[str]:
    """A single deterministic clarify line for the first detected conflict."""
    if not conflicts:
        return None
    c = conflicts[0]
    vals = c["values"]
    tmpl = _CONFLICT_CLARIFY.get(c["dimension"], "{a} ya {b} — kaunsa chahiye?")
    return tmpl.format(a=vals[0], b=vals[1])


# ─────────────────────────────────────────────────────────────────────────────
# Conversation intelligence (STEP 10) — deterministic turn interpretation.
# READ-ONLY: mirrors the signals chat_service already acts on, so it never
# disagrees with the live memory flow; it only *labels* the turn (for meta /
# analytics). It does NOT change the memory architecture.
# ─────────────────────────────────────────────────────────────────────────────
TURN_NEW_VEHICLE = "new_vehicle"          # names a new model / make / registration
TURN_ATTRIBUTE_FOLLOWUP = "attribute_followup"  # field question about the pinned car
TURN_SAME_MODEL_VARIANT = "same_model_variant"  # "any blue one", "automatic?" -> same model
TURN_NEW_BROWSE = "new_browse"            # category / seats / budget / km ceiling -> fresh
TURN_CONTINUATION = "continuation"        # "aur", "haan", "more"
TURN_STANDALONE = "standalone"            # first turn / no prior context

_VARIANT_FIELDS = ("color", "fuel", "transmission", "ownership_exact",
                   "ownership_max")
_BROWSE_FIELDS = ("category", "seats", "km_max", "price_max", "price_min")
_ATTR_FLAGS = ("insurance_query", "service_query", "warranty_detail_query",
               "rc_query", "ownership_query", "condition_query", "flood_query",
               "downpayment_query", "km_reading_query", "color_query",
               "fuel_query", "transmission_query", "seats_query")
_CONT_WORDS = {"aur", "haan", "haa", "han", "ji", "ok", "okay", "more", "next",
               "yes", "aur dikhao", "और", "हो", "अजून"}


def classify_turn(message: str, prev_ctx: Optional[Dict[str, object]] = None,
                  q: Optional[Query] = None) -> str:
    """Label a conversation turn deterministically relative to prior context.
    `prev_ctx` = {'reg':..., 'model':...} or None."""
    if q is None:
        q = parse(message or "")
    t = re.sub(r"\s+", " ", (message or "").strip().lower())
    if t in _CONT_WORDS:
        return TURN_CONTINUATION
    if q.model or q.make or q.registration or q.reg_partial:
        return TURN_NEW_VEHICLE
    # a fresh-browse filter (different class of car) is a new search
    if any(getattr(q, f) is not None for f in _BROWSE_FIELDS) or q.sort_low_km:
        return TURN_NEW_BROWSE
    # a variant filter on an existing pin -> "another one like this" (same model)
    if prev_ctx and any(getattr(q, f) is not None for f in _VARIANT_FIELDS):
        return TURN_SAME_MODEL_VARIANT
    # a field question about the pinned car
    if any(getattr(q, f, False) for f in _ATTR_FLAGS) or "price" in q.intents:
        return (TURN_ATTRIBUTE_FOLLOWUP if prev_ctx and (prev_ctx.get("reg")
                or prev_ctx.get("model")) else TURN_STANDALONE)
    return TURN_STANDALONE


if __name__ == "__main__":
    for m in ["RC?", "Paper?", "Clear?", "automatic diesel", "petrol diesel",
              "white black", "7 seater diesel", "insurence", "8L", "8,00,000",
              "0.8 million", "warenty", "rc insurance", "first owner second owner"]:
        a = analyze(m)
        print(f"{m:26s} -> {a.primary}/{a.band}/{a.recommendation} "
              f"conf={a.confidence:.2f} multi={a.multi_intents} "
              f"conflicts={[c['dimension'] for c in a.conflicts]} nums={a.numbers}")
