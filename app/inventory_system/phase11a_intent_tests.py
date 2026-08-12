"""
phase11a_intent_tests.py
========================

Phase 11A — Universal Inventory Intent Engine.

Deterministic coverage tests for inventory-FIELD intent recognition across
English / Hindi / Hinglish / Marathi, including short forms, long forms, spoken
variants, question forms and spelling mistakes. NO LLM.

For every field we generate >= 50 utterances (base TERMS x question FRAMES) and
assert the parser (query_parser.parse + media_lookup.detect_media_intent) maps
each to the intended field. This is the executable form of
`phase11A_intent_dictionary.md`.
"""

from __future__ import annotations

import unittest

from query_parser import parse
from media_lookup import detect_media_intent


# ── how the deterministic engine resolves a message to ONE field (mirrors the
#    priority the responders use) ────────────────────────────────────────────
def detected_field(msg: str) -> str:
    mi = detect_media_intent(msg)
    if mi:
        return {"photo_request": "photo", "video_request": "video",
                "instagram_request": "instagram", "youtube_request": "youtube"}[mi]
    q = parse(msg)
    if q.rc_query:            return "rc"
    if q.insurance_query:     return "insurance"
    if q.service_query:       return "service"
    if q.warranty_detail_query: return "warranty"
    if q.ownership_query:     return "ownership"
    if q.km_reading_query:    return "km"
    if q.flood_query:         return "condition"
    if q.condition_query:     return "condition"
    if q.downpayment_query:   return "finance"
    if q.off_sheet and q.off_sheet_topic == "finance": return "finance"
    if q.sort_low_km:         return "low_km"
    if q.color_query:         return "color"
    if q.fuel_query:          return "fuel"
    if q.transmission_query:  return "transmission"
    if q.seats_query:         return "seats"
    if q.fuel:                return "fuel"
    if q.transmission:        return "transmission"
    if q.color:               return "color"
    if q.seats is not None:   return "seats"
    if q.category:            return "category"
    if q.price_max is not None or q.price_min is not None or q.sort_cheapest:
        return "budget"
    if "price" in q.intents:  return "price"
    return "availability"


# neutral question frames — they never introduce a competing field token
_FRAMES = ["{t}", "{t}?", "{t} hai?", "{t} kya hai", "gaadi ka {t}?",
           "is car ka {t}?", "{t} bata do"]

# each field: base TERMS (any one alone must resolve to the field)
FIELD_TERMS = {
    "rc": [
        "rc", "rc hai", "rc status", "rc clear", "registration",
        "registration certificate", "rc transfer", "transfer", "noc",
        "fitness", "fitness certificate", "fc", "rto", "documents", "document",
        "papers", "paper", "original papers", "kagzat", "kagaz", "loan closed",
        "hypothecation", "duplicate rc", "puc certificate",
        "आरसी", "रजिस्ट्रेशन", "ट्रान्सफर", "एनओसी", "फिटनेस", "कागदपत्र",
    ],
    "insurance": [
        "insurance", "insured", "policy", "policy valid", "bima", "beema",
        "claim", "claim hua", "no claim", "no claim bonus", "ncb", "cover note",
        "insurance cover", "cover valid", "policy details", "insurance kitni",
        "विमा", "पॉलिसी", "क्लेम",
    ],
    "ownership": [
        "owner", "owners", "kitne owner", "single owner", "first owner",
        "second owner", "how many owners", "malik", "kitne malik", "maalik",
        "previous owner", "owner history", "number of owners", "owner details",
        "ek malak", "pahila malak", "मालक", "किती मालक", "एकच मालक",
    ],
    "km": [
        "km", "kms", "kilometer", "kilometre", "kilometers", "kilometres",
        "running", "odo", "odometer", "km driven", "kitni chali", "km chali",
        "kitne km", "distance", "km reading", "odometer reading", "kitna chala",
        "how many km", "कितनी चली", "किलोमीटर", "किमी", "रनिंग", "कितने किलोमीटर",
    ],
    "condition": [
        "accident", "accidental", "accident history", "damage", "damaged",
        "scratch", "dent", "paint", "repaint", "touch up", "touchup", "denting",
        "denting painting", "rust", "condition", "body condition",
        "engine condition", "interior", "tyre", "crash", "hadsa", "takkar",
        "nuksan", "अपघात", "नुकसान", "स्थिती",
    ],
    "color": [
        "color", "colour", "colar", "coler", "rang", "kaunsa rang", "kaun sa rang",
        "which color", "which colour", "what color", "color kya", "colour kya",
        "rang kya", "kya rang", "car color", "gaadi ka color", "kalar",
        "रंग", "कलर", "कोणता रंग", "रंग काय",
    ],
    "fuel": [
        "fuel", "fuel type", "kaunsa fuel", "kaun sa fuel", "which fuel",
        "what fuel", "fuel kya", "kya fuel", "petrol ya diesel", "diesel ya petrol",
        "इंधन", "फ्युएल", "कोणते इंधन",
    ],
    "transmission": [
        "transmission", "gearbox", "gear box", "gear kaisa", "gear kya",
        "kaunsa gear", "which transmission", "gear type", "manual ya automatic",
        "automatic ya manual", "automatic", "manual", "amt", "cvt",
        "ट्रान्समिशन", "गिअरबॉक्स", "कोणते गिअर",
    ],
    "seats": [
        "kitni seat", "kitni seats", "kitne seat", "how many seats",
        "how many seat", "seat kitni", "seating capacity", "kitni seating",
        "kitne log baith", "5 seater", "6 seater", "7 seater", "8 seater",
        "किती सीट", "कितनी सीट", "आसन क्षमता",
    ],
    "warranty": [
        "warranty", "warranty period", "warranty hai", "warranty status",
        "warranty card", "engine warranty", "warranty available", "warranty left",
        "guarantee", "gaurantee", "guaranty", "garanti", "assurance",
        "वॉरंटी", "गॅरंटी", "हमी",
    ],
    "service": [
        "service", "service history", "service record", "serviced",
        "last service", "maintenance", "maintenance history", "service book",
        "oil change", "service due", "service center", "regular service",
        "सर्व्हिस", "सर्विस",
    ],
    "finance": [
        "emi", "downpayment", "down payment", "kist", "kitni kist", "installment",
        "instalment", "dp kitna", "monthly kitna", "emi kitni", "monthly payment",
        "loan", "finance", "हप्ता", "ईएमआई", "किती हप्ता",
    ],
    "price": [
        "price", "rate", "cost", "daam", "kimat", "kimmat", "keemat", "bhav",
        "how much", "kitna hai", "kitne ka hai", "kitne ki", "kitne mein",
        "kya daam", "price kya hai", "किंमत", "दाम", "भाव",
    ],
    "video": [
        "video", "videos", "walkaround", "walk around", "clip", "clips",
        "video bhejo", "video dikhao", "chalti gaadi", "व्हिडिओ",
    ],
    "instagram": [
        "instagram", "insta", "reel", "reels", "insta link", "instagram reel",
        "insta pe", "ig video", "story",
    ],
    "youtube": [
        "youtube", "you tube", "youtube video", "youtube link", "youtube shorts",
        "yt video", "yt link", "yt shorts", "shorts",
    ],
}

# budget is generated separately (self-contained numeric ceilings)
def _budget_cases():
    out = []
    for n in (3, 4, 5, 6, 7, 8, 9, 10, 12):
        out += [f"under {n} lakh", f"{n} lakh ke andar", f"{n} lakh tak",
                f"below {n}", f"upto {n} lakh", f"within {n} lakh"]
    return out


def _expand(terms):
    seen, out = set(), []
    for t in terms:
        for fr in _FRAMES:
            p = fr.format(t=t)
            if p not in seen:
                seen.add(p)
                out.append(p)
    return out


class TestFieldIntentCoverage(unittest.TestCase):
    THRESHOLD = 0.96          # >=96% of generated utterances must resolve correctly

    def _check(self, field, phrases, accept=None):
        accept = accept or {field}
        misses = [p for p in phrases if detected_field(p) not in accept]
        rate = 1 - len(misses) / len(phrases)
        self.assertGreaterEqual(
            len(phrases), 50, f"{field}: only {len(phrases)} utterances (<50)")
        self.assertGreaterEqual(
            rate, self.THRESHOLD,
            f"{field}: {rate:.0%} ({len(misses)} miss) e.g. {misses[:8]}")

    def test_rc_documents_transfer_fitness(self):
        self._check("rc", _expand(FIELD_TERMS["rc"]))

    def test_insurance(self):
        self._check("insurance", _expand(FIELD_TERMS["insurance"]))

    def test_ownership(self):
        self._check("ownership", _expand(FIELD_TERMS["ownership"]))

    def test_km_reading(self):
        self._check("km", _expand(FIELD_TERMS["km"]))

    def test_condition_accident(self):
        self._check("condition", _expand(FIELD_TERMS["condition"]))

    def test_color(self):
        self._check("color", _expand(FIELD_TERMS["color"]))

    def test_fuel(self):
        self._check("fuel", _expand(FIELD_TERMS["fuel"]))

    def test_transmission(self):
        self._check("transmission", _expand(FIELD_TERMS["transmission"]))

    def test_seats(self):
        self._check("seats", _expand(FIELD_TERMS["seats"]))

    def test_warranty(self):
        self._check("warranty", _expand(FIELD_TERMS["warranty"]))

    def test_service(self):
        self._check("service", _expand(FIELD_TERMS["service"]))

    def test_finance_emi(self):
        self._check("finance", _expand(FIELD_TERMS["finance"]))

    def test_price(self):
        self._check("price", _expand(FIELD_TERMS["price"]))

    def test_video(self):
        self._check("video", _expand(FIELD_TERMS["video"]))

    def test_instagram(self):
        self._check("instagram", _expand(FIELD_TERMS["instagram"]))

    def test_youtube(self):
        self._check("youtube", _expand(FIELD_TERMS["youtube"]))

    def test_budget(self):
        self._check("budget", _budget_cases())


if __name__ == "__main__":
    # print a per-field coverage table
    total_p = total_t = 0
    for f, terms in FIELD_TERMS.items():
        phrases = _expand(terms)
        accept = {f}
        p = sum(1 for x in phrases if detected_field(x) in accept)
        total_p += p; total_t += len(phrases)
        flag = "OK " if p == len(phrases) else "GAP"
        print(f"[{flag}] {f:13s} {p}/{len(phrases)}")
    bud = _budget_cases()
    pb = sum(1 for x in bud if detected_field(x) == "budget")
    total_p += pb; total_t += len(bud)
    print(f"[{'OK ' if pb==len(bud) else 'GAP'}] {'budget':13s} {pb}/{len(bud)}")
    print(f"\nTOTAL {total_p}/{total_t} ({100*total_p/total_t:.1f}%)")
