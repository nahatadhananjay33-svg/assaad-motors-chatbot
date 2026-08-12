"""
response_formatter.py
====================

Turns a `RetrievalResult` into a customer-safe answer. This is the last line of
defence (STAGE 3 of retrieval_guardrails.md) — it guarantees the spoken output
never fabricates a price/km/year/feature and never leaks an internal field.

Format-time guardrails implemented:
  G-PRICE / G-PRICE-UNIT  — coded RATE never a number; quotable price -> lakhs
  G-KM                    — blank/non-numeric km -> "confirm exact kms"
  G-YEAR                  — blank/0 year -> "confirm exact saal"
  G-INS                   — insurance asked -> soft "team confirms at visit"
  G-OFFSHEET              — off-sheet topic -> route to team, never invent
  G-VARIANT               — speak model+year+fuel, never the cryptic variant code
  G-MULTI                 — count + top 1-2 + one clarifier, never a silent pick
  G-RELAX / G-SEGMENT     — announce relaxation / segment alternative
  G-FRESH                 — availability answers carry an as-of hedge
  G-EXPOSE                — final scrub: no LOC slot / stock# / full reg in output
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from inventory_models import InventoryItem
from query_parser import Query, _norm, _has
from retrieval_engine import RetrievalResult
import field_intents                      # Phase 12D: new vehicle-detail fields

# "Data not available." — shown when a schema field exists but has no value.
_DNA = "Data not available."


def _yn(val: Optional[bool], yes: str = "Yes", no: str = "No") -> str:
    """Render a bool field as Yes/No or DNA."""
    if val is True:
        return yes
    if val is False:
        return no
    return _DNA


def _val(val) -> str:
    """Render any field value; None -> DNA."""
    if val is None:
        return _DNA
    return str(val)


# Single public-facing location (LOC slot is NEVER disclosed) — G-EXPOSE
GARAGE_NAME = "Assad Motors"
GARAGE_ADDRESS = "Marol, Andheri East, Mumbai"
PUBLIC_LOCATION = f"{GARAGE_NAME}, {GARAGE_ADDRESS}"
VISIT_PIVOT = f"aap aaj aa ke dekh lo — {PUBLIC_LOCATION}."
FRESH_HEDGE = "(abhi available hai, visit pe confirm kar dete hain)"


@dataclass
class FormattedResponse:
    status: str                                  # found|multi|segment|not_found|clarify|off_sheet
    spoken: str
    shown: List[Dict] = field(default_factory=list)   # safe, customer-facing fields only
    guardrails_fired: List[str] = field(default_factory=list)
    visit_pivot: bool = False
    contains_forbidden: bool = False             # must always be False
    relaxed: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict:
        return {
            "status": self.status,
            "spoken": self.spoken,
            "shown": self.shown,
            "guardrails_fired": self.guardrails_fired,
            "visit_pivot": self.visit_pivot,
            "contains_forbidden": self.contains_forbidden,
            "relaxed": self.relaxed,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Safe per-vehicle rendering
# ─────────────────────────────────────────────────────────────────────────────
def _safe_fields(it: InventoryItem, q: Query, fired: List[str]) -> Dict:
    """Only ever expose customer-facing fields (never LOC/stock/reg). G-EXPOSE."""
    d = {
        "make": it.make_full,
        "model": it.model,
        "year": it.year_int,                 # None -> caller must hedge (G-YEAR)
        "fuel": it.fuel_norm,
        "transmission": it.transmission_norm,
        "color": it.color_norm,
        "owners": it.ownership_count,
        "price_lakh": None,
        "price_quotable": it.price_quotable,
        "km": it.km_driven,                  # None -> hedge (G-KM)
    }
    if it.price_quotable and it.price_lakh is not None:
        d["price_lakh"] = it.price_lakh
    else:
        if "G-PRICE" not in fired:
            fired.append("G-PRICE")
    if it.year_int is None and "G-YEAR" not in fired:
        fired.append("G-YEAR")
    if it.km_driven is None and "G-KM" not in fired:
        fired.append("G-KM")
    return d


def _field_answer(it: InventoryItem, attr: str) -> str:
    """Phase 12D: render one new-field value from the vehicle, deterministically.
    Missing value -> 'Data not available' (never fabricated)."""
    v = getattr(it, attr, None)
    disp = field_intents.display(attr)
    if v is None or (isinstance(v, str) and not v.strip()):
        return f"{disp}: {_DNA}"
    t = field_intents.ftype(attr)
    if attr == "sunroof_type":
        return "Sunroof: " + ("nahi hai" if str(v).lower() == "none" else f"haan ({v})") + "."
    if attr == "camera_type":
        return "Camera: " + ("nahi hai" if str(v).lower() == "none" else f"{v}") + "."
    if t == "bool":
        return f"{disp}: " + ("haan" if v is True else "nahi") + "."
    return f"{disp}: {v}{field_intents.unit(attr)}."


# ── Phase 12I: multi-attribute answer (never silently drop a secondary intent) ─
_EXPLICIT_PRICE_WORDS = (
    "price", "daam", "rate", "cost", "kimat", "kimmat", "keemat", "kemat", "bhav",
    "kitne ka", "kitne ki", "kitne mein", "kitne me", "how much", "on road price",
    "किंमत", "किमत", "दाम", "भाव",
)


def _explicit_price_intent(text: str) -> bool:
    """True only for an EXPLICIT price word — not the loose 'kitna/kitne' that the
    parser also tags as price. So a pure km/other question is never mislabelled as
    also-price in the multi-attribute combiner."""
    return any(_has(text, w) for w in _EXPLICIT_PRICE_WORDS)


def _attr_intent_clauses(it: InventoryItem, q: Query) -> List[str]:
    """One short clause per attribute intent present on this turn, in a stable
    order. Deterministic. Missing values render 'Data not available' / a confirm
    hedge — never fabricated. The last group is the 12D `attr_fields`."""
    text = _norm(q.raw)
    c: List[str] = []
    if (_explicit_price_intent(text) and q.price_max is None
            and q.price_min is None and not q.sort_cheapest):
        if it.price_quotable and it.price_lakh is not None:
            c.append(f"Price ₹{it.price_lakh:.2f} lakh.")
        else:
            c.append("Price exact confirm kar ke bata deta hoon.")
    if getattr(q, "km_reading_query", False):
        c.append(f"{it.km_driven:,} km chali hai." if it.km_driven is not None
                 else "Exact km visit pe confirm.")
    if q.ownership_query:
        n = it.ownership_count
        c.append(((f"{n} owner" if n == 1 else f"{n} owners") + ".") if n
                 else "Owner details visit pe confirm.")
    if q.fuel_query:
        c.append(f"Fuel {it.fuel_norm}." if it.fuel_norm and it.fuel_norm != "Unknown"
                 else "Fuel visit pe confirm.")
    if q.transmission_query:
        c.append(f"{it.transmission_norm} (gear)." if it.transmission_norm
                 and it.transmission_norm != "Unknown"
                 else "Transmission visit pe confirm.")
    if q.color_query:
        c.append(f"Colour {it.color_norm}." if it.color_norm
                 else "Colour visit pe confirm.")
    if q.seats_query:
        c.append(f"{it.seats} seater." if it.seats else "Seating visit pe confirm.")
    if getattr(q, "year_query", False):
        c.append(f"{it.year_int} model." if it.year_int
                 else "Exact model year visit pe confirm.")
    if q.condition_query:
        c.append("Accident free: "
                 + _yn(it.accident_free, "Yes", "No (history on record)") + ".")
    if q.insurance_query:
        c.append(f"Insurance: {_val(it.insurance_type)}")   # _val ends in '.'
    if q.service_query:
        c.append("Service history: "
                 + _yn(it.service_history_available, "Yes", "Not available") + ".")
    if q.warranty_detail_query:
        c.append("Warranty: " + _yn(it.warranty_available, "Yes", "No") + ".")
    if q.rc_query:
        c.append(f"RC status: {_val(it.rc_status)}")         # _val ends in '.'
    if q.downpayment_query:
        if it.price_quotable and it.price_lakh:
            c.append(f"Downpayment ~₹{it.price_lakh * 0.2:.2f} lakh (20%).")
        else:
            c.append("Downpayment visit pe confirm.")
    for a in getattr(q, "attr_fields", None) or []:
        c.append(_field_answer(it, a))
    return c


def _attr_intent_signature(it: InventoryItem, q: Query) -> tuple:
    """Phase 12J: the raw values behind the asked attribute intents, as a tuple —
    for deciding whether every car of a model shares the SAME value (answer the
    common value) or they DIFFER (clarify which). Mirrors `_attr_intent_clauses`."""
    text = _norm(q.raw)
    sig = []
    if (_explicit_price_intent(text) and q.price_max is None
            and q.price_min is None and not q.sort_cheapest):
        sig.append(("price", it.price_lakh if it.price_quotable else None))
    if getattr(q, "km_reading_query", False):
        sig.append(("km", it.km_driven))
    if q.ownership_query:
        sig.append(("owners", it.ownership_count))
    if q.fuel_query:
        sig.append(("fuel", it.fuel_norm))
    if q.transmission_query:
        sig.append(("trans", it.transmission_norm))
    if q.color_query:
        sig.append(("color", it.color_norm))
    if q.seats_query:
        sig.append(("seats", it.seats))
    if getattr(q, "year_query", False):
        sig.append(("year", it.year_int))
    if q.condition_query:
        sig.append(("acc", it.accident_free))
    if q.insurance_query:
        sig.append(("ins", it.insurance_type))
    if q.service_query:
        sig.append(("svc", it.service_history_available))
    if q.warranty_detail_query:
        sig.append(("war", it.warranty_available))
    if q.rc_query:
        sig.append(("rc", it.rc_status))
    if q.downpayment_query:
        sig.append(("dp", it.price_lakh if it.price_quotable else None))
    for a in getattr(q, "attr_fields", None) or []:
        sig.append((a, getattr(it, a, None)))
    return tuple(sig)


def _phrase(it: InventoryItem) -> str:
    """A short spoken descriptor: '2016 Silver Creta, petrol'. G-VARIANT: no variant."""
    bits = []
    if it.year_int:
        bits.append(str(it.year_int))
    if it.color_norm:
        bits.append(it.color_norm)
    if it.model:
        bits.append(it.model)
    head = " ".join(bits) if bits else (it.model or "gaadi")
    tail = it.fuel_norm if it.fuel_norm and it.fuel_norm != "Unknown" else ""
    return f"{head}, {tail}".rstrip(", ") if tail else head


def _price_clause(it: InventoryItem, q: Query, fired: List[str]) -> str:
    """G-PRICE / G-PRICE-UNIT: only speak a number for a quotable price."""
    if "price" not in q.intents:
        return ""
    if it.price_quotable and it.price_lakh is not None:
        if "G-PRICE-UNIT" not in fired:
            fired.append("G-PRICE-UNIT")
        return f" — ₹{it.price_lakh:.2f} lakh"
    # coded / unknown price -> never a number
    if "G-PRICE" not in fired:
        fired.append("G-PRICE")
    return " — iska exact best price main confirm kar ke bata deta hoon"


# ─────────────────────────────────────────────────────────────────────────────
# Main entry
# ─────────────────────────────────────────────────────────────────────────────
def format_response(result: RetrievalResult) -> FormattedResponse:
    q = result.query
    fired: List[str] = []

    # ── off-sheet (G-OFFSHEET) — route, never invent ──
    if q.off_sheet:
        fired.append("G-OFFSHEET")
        spoken = (f"Yeh hamari team aapko visit pe confirm kar degi — "
                  f"{VISIT_PIVOT}")
        return _finalize(FormattedResponse(
            status="off_sheet", spoken=spoken, guardrails_fired=fired,
            visit_pivot=True), result)

    # ── Phase 12I: MULTI-ATTRIBUTE combiner — a pinned single car asked 2+
    #    attribute questions at once ("price aur insurance", "km aur owners",
    #    "RC aur insurance batao") answers EACH intent, never silently dropping a
    #    secondary. Fires only when at least one old-style/price intent is present
    #    (2+ total): pure 12D multi-field asks ("sunroof aur airbags") keep using
    #    the dedicated attr_fields branch below (identical output). Missing values
    #    → "Data not available" / confirm hedge — never fabricated, never a
    #    search. ──
    if result.count == 1:
        _clauses = _attr_intent_clauses(result.matches[0], q)
        _nonfield = len(_clauses) - len(getattr(q, "attr_fields", None) or [])
        if len(_clauses) >= 2 and _nonfield >= 1:
            fired.append("G-MULTI-ATTR")
            it = result.matches[0]
            shown = [_safe_fields(x, q, fired) for x in result.matches[:2]]
            spoken = f"{_phrase(it)} — " + " ".join(_clauses) + f" {VISIT_PIVOT}"
            return _finalize(FormattedResponse(
                status="found", spoken=spoken, shown=shown, guardrails_fired=fired,
                visit_pivot=True), result)

    # ── km reading ("kitne km chali hai") -> this car's odometer. Only when the
    #    answer is about ONE car; a plural browse ("kam km cars") falls through
    #    to the normal multi handler (G-MULTI safety). ──
    if q.km_reading_query and result.count == 1:
        fired.append("G-KM-READING")
        it = result.matches[0]
        shown = [_safe_fields(x, q, fired) for x in result.matches[:2]]
        if it.km_driven is not None:
            spoken = f"{_phrase(it)} — {it.km_driven:,} km chali hai. {VISIT_PIVOT}"
        else:
            spoken = f"{_phrase(it)} — exact km visit pe confirm kar dete hain. {VISIT_PIVOT}"
        return _finalize(FormattedResponse(
            status="found", spoken=spoken, shown=shown, guardrails_fired=fired,
            visit_pivot=True), result)

    # ── ownership ("kitne owner") -> this car's owner count. One car only;
    #    "first owner cars" (many) falls through to the multi handler. ──
    if q.ownership_query and result.count == 1:
        fired.append("G-OWNER")
        it = result.matches[0]
        shown = [_safe_fields(x, q, fired) for x in result.matches[:2]]
        n = it.ownership_count
        if n:
            owner_txt = f"{n} owner" if n == 1 else f"{n} owners"
            spoken = f"{_phrase(it)} — yeh {owner_txt} wali gaadi hai. {VISIT_PIVOT}"
        else:
            spoken = f"{_phrase(it)} — owner details visit pe confirm kar dete hain. {VISIT_PIVOT}"
        return _finalize(FormattedResponse(
            status="found", spoken=spoken, shown=shown, guardrails_fired=fired,
            visit_pivot=True), result)

    # ── Phase 12D: new vehicle-detail fields (specs / features / EV / keys /
    #    extra documents). Answer the pinned car's field(s) directly; multi-field
    #    supported. One car only (a plural browse never sets attr_fields). No
    #    fabrication — a missing value renders "Data not available". ──
    if q.attr_fields and result.count == 1:
        fired.append("G-FIELD")
        it = result.matches[0]
        shown = [_safe_fields(x, q, fired) for x in result.matches[:2]]
        parts = [_field_answer(it, a) for a in q.attr_fields]
        spoken = f"{_phrase(it)} — " + " ".join(parts) + f" {VISIT_PIVOT}"
        return _finalize(FormattedResponse(
            status="found", spoken=spoken, shown=shown, guardrails_fired=fired,
            visit_pivot=True), result)

    # ── Phase 11A: attribute questions (colour / fuel / transmission / seats) —>
    #    answer the pinned car's field directly. One car only; a plural browse
    #    ("automatic cars") never sets these flags (that is a filter), so this is
    #    safe. Falls through to multi/not-found when the car is not pinned. ──
    if q.color_query and result.count == 1:
        fired.append("G-ATTR-COLOR")
        it = result.matches[0]
        shown = [_safe_fields(x, q, fired) for x in result.matches[:2]]
        if it.color_norm:
            spoken = f"{_phrase(it)} — colour {it.color_norm} hai. {VISIT_PIVOT}"
        else:
            spoken = f"{_phrase(it)} — exact colour visit pe confirm kar dete hain. {VISIT_PIVOT}"
        return _finalize(FormattedResponse(
            status="found", spoken=spoken, shown=shown, guardrails_fired=fired,
            visit_pivot=True), result)

    if q.fuel_query and result.count == 1:
        fired.append("G-ATTR-FUEL")
        it = result.matches[0]
        shown = [_safe_fields(x, q, fired) for x in result.matches[:2]]
        if it.fuel_norm and it.fuel_norm != "Unknown":
            spoken = f"{_phrase(it)} — fuel {it.fuel_norm} hai. {VISIT_PIVOT}"
        else:
            spoken = f"{_phrase(it)} — fuel type visit pe confirm kar dete hain. {VISIT_PIVOT}"
        return _finalize(FormattedResponse(
            status="found", spoken=spoken, shown=shown, guardrails_fired=fired,
            visit_pivot=True), result)

    if q.transmission_query and result.count == 1:
        fired.append("G-ATTR-TRANSMISSION")
        it = result.matches[0]
        shown = [_safe_fields(x, q, fired) for x in result.matches[:2]]
        if it.transmission_norm and it.transmission_norm != "Unknown":
            spoken = f"{_phrase(it)} — {it.transmission_norm} (gear) hai. {VISIT_PIVOT}"
        else:
            spoken = f"{_phrase(it)} — transmission visit pe confirm kar dete hain. {VISIT_PIVOT}"
        return _finalize(FormattedResponse(
            status="found", spoken=spoken, shown=shown, guardrails_fired=fired,
            visit_pivot=True), result)

    if q.seats_query and result.count == 1:
        fired.append("G-ATTR-SEATS")
        it = result.matches[0]
        shown = [_safe_fields(x, q, fired) for x in result.matches[:2]]
        if it.seats:
            spoken = f"{_phrase(it)} — {it.seats} seater hai. {VISIT_PIVOT}"
        else:
            spoken = f"{_phrase(it)} — seating capacity visit pe confirm kar dete hain. {VISIT_PIVOT}"
        return _finalize(FormattedResponse(
            status="found", spoken=spoken, shown=shown, guardrails_fired=fired,
            visit_pivot=True), result)

    # ── Phase 12G: model-year question ("2019 model hai?", "kaunsa year?") -> this
    #    car's model year. One car only; never fabricated (unknown -> confirm on
    #    visit). "2019 model chahiye" stays a filter search (never reaches here). ──
    if q.year_query and result.count == 1:
        fired.append("G-ATTR-YEAR")
        it = result.matches[0]
        shown = [_safe_fields(x, q, fired) for x in result.matches[:2]]
        if it.year_int:
            spoken = f"{_phrase(it)} — yeh {it.year_int} model hai. {VISIT_PIVOT}"
        else:
            spoken = f"{_phrase(it)} — exact model year visit pe confirm kar dete hain. {VISIT_PIVOT}"
        return _finalize(FormattedResponse(
            status="found", spoken=spoken, shown=shown, guardrails_fired=fired,
            visit_pivot=True), result)

    # ── condition / accident history (Phase 7D — data-driven) ──
    if q.condition_query:
        fired.append("G-CONDITION")
        if result.found:
            it = result.matches[0]
            shown = [_safe_fields(it, q, fired) for it in result.matches[:2]]
            acc = _yn(it.accident_free, "Yes, accident free", "No — accident history on record")
            flood = _yn(it.flood_damage, "Yes, flood damage recorded", "No flood damage")
            repaint = _yn(it.repainted, "Yes, repainted", "No repainting")
            body = _val(it.body_condition)
            engine = _val(it.engine_condition)
            interior = _val(it.interior_condition)
            spoken = (
                f"{_phrase(it)} — "
                f"Accident free: {acc}. "
                f"Flood damage: {flood}. "
                f"Repainted: {repaint}. "
                f"Body condition: {body}. "
                f"Engine condition: {engine}. "
                f"Interior condition: {interior}. "
                f"{VISIT_PIVOT}"
            )
            return _finalize(FormattedResponse(
                status="found", spoken=spoken, shown=shown, guardrails_fired=fired,
                visit_pivot=True), result)
        spoken = f"Gaadi nahi mili — model ya budget bata do, main check karta hoon."
        return _finalize(FormattedResponse(
            status="not_found", spoken=spoken, guardrails_fired=fired), result)

    # ── downpayment / EMI estimate (TASK8) ──
    if q.downpayment_query:
        fired.append("G-DOWNPAYMENT")
        if result.found:
            it = result.matches[0]
            shown = [_safe_fields(it, q, fired) for it in result.matches[:2]]
            if it.price_quotable and it.price_lakh:
                dp = it.price_lakh * 0.2
                spoken = (f"{_phrase(it)} (₹{it.price_lakh:.2f} lakh) ke liye estimated "
                          f"downpayment ~₹{dp:.2f} lakh (20%) hoga — exact EMI/terms "
                          f"visit pe confirm. {VISIT_PIVOT}")
            else:
                spoken = f"Downpayment/EMI visit pe team confirm karegi — {VISIT_PIVOT}"
            return _finalize(FormattedResponse(
                status="found", spoken=spoken, shown=shown, guardrails_fired=fired,
                visit_pivot=True), result)
        spoken = f"Downpayment/EMI visit pe team confirm karegi — {VISIT_PIVOT}"
        return _finalize(FormattedResponse(
            status="off_sheet", spoken=spoken, guardrails_fired=fired,
            visit_pivot=True), result)

    # ── insurance (Phase 7D — structured data first, hint fallback) ──
    if q.insurance_query:
        fired.append("G-INS")
        if result.found:
            it = result.matches[0]
            shown = [_safe_fields(it, q, fired) for it in result.matches[:2]]
            ins_type   = _val(it.insurance_type)
            ins_expiry = _val(it.insurance_expiry)
            zdep       = _yn(it.zero_dep)
            claim_hist = _yn(it.insurance_claim_history, "Yes, claim made", "No claims")
            spoken = (
                f"{_phrase(it)} — "
                f"Insurance type: {ins_type}. "
                f"Valid till: {ins_expiry}. "
                f"Zero dep: {zdep}. "
                f"Claim history: {claim_hist}. "
                f"{VISIT_PIVOT}"
            )
            return _finalize(FormattedResponse(
                status="found", spoken=spoken, shown=shown, guardrails_fired=fired,
                visit_pivot=True), result)
        spoken = f"Insurance details — {_DNA} {VISIT_PIVOT}"
        return _finalize(FormattedResponse(
            status="off_sheet", spoken=spoken, guardrails_fired=fired,
            visit_pivot=True), result)

    # ── service history (Phase 7D) ──
    if q.service_query:
        fired.append("G-SERVICE")
        if result.found:
            it = result.matches[0]
            shown = [_safe_fields(it, q, fired) for it in result.matches[:2]]
            svc_hist  = _yn(it.service_history_available, "Yes, available", "Not available")
            last_svc  = _val(it.last_service_date)
            svc_ctr   = _val(it.service_center_type)
            spoken = (
                f"{_phrase(it)} — "
                f"Service history: {svc_hist}. "
                f"Last service date: {last_svc}. "
                f"Service center: {svc_ctr}. "
                f"{VISIT_PIVOT}"
            )
            return _finalize(FormattedResponse(
                status="found", spoken=spoken, shown=shown, guardrails_fired=fired,
                visit_pivot=True), result)
        spoken = f"Gaadi nahi mili — model ya budget bata do."
        return _finalize(FormattedResponse(
            status="not_found", spoken=spoken, guardrails_fired=fired), result)

    # ── RC / loan / NOC (Phase 7D) ──
    if q.rc_query:
        fired.append("G-RC")
        if result.found:
            it = result.matches[0]
            shown = [_safe_fields(it, q, fired) for it in result.matches[:2]]
            rc_st    = _val(it.rc_status)
            hyp_bank = _val(it.hypothecation_bank) if it.rc_status == "Hypothecated" else "N/A"
            loan_cl  = _yn(it.loan_closed, "Yes, loan closed", "Loan still open")
            noc      = _yn(it.noc_available, "Yes, NOC available", "NOC not available")
            fin_elig = _yn(it.finance_eligible, "Yes", "No")
            spoken = (
                f"{_phrase(it)} — "
                f"RC status: {rc_st}. "
                f"Hypothecation bank: {hyp_bank}. "
                f"Loan closed: {loan_cl}. "
                f"NOC available: {noc}. "
                f"Finance eligible: {fin_elig}. "
                f"{VISIT_PIVOT}"
            )
            return _finalize(FormattedResponse(
                status="found", spoken=spoken, shown=shown, guardrails_fired=fired,
                visit_pivot=True), result)
        spoken = f"Gaadi nahi mili — model ya registration bata do."
        return _finalize(FormattedResponse(
            status="not_found", spoken=spoken, guardrails_fired=fired), result)

    # ── warranty detail on a specific vehicle (Phase 7D) ──
    if q.warranty_detail_query:
        fired.append("G-WARRANTY-DETAIL")
        if result.found:
            it = result.matches[0]
            shown = [_safe_fields(it, q, fired) for it in result.matches[:2]]
            w_avail   = _yn(it.warranty_available, "Yes, warranty available", "No warranty")
            w_expiry  = _val(it.warranty_expiry)
            w_prov    = _val(it.warranty_provider)
            tyre      = _val(it.tyre_condition)
            brake     = _val(it.brake_condition)
            clutch    = _val(it.clutch_condition)
            spoken = (
                f"{_phrase(it)} — "
                f"Warranty: {w_avail}. "
                f"Expires: {w_expiry}. "
                f"Provider: {w_prov}. "
                f"Tyre condition: {tyre}. "
                f"Brake condition: {brake}. "
                f"Clutch condition: {clutch}. "
                f"{VISIT_PIVOT}"
            )
            return _finalize(FormattedResponse(
                status="found", spoken=spoken, shown=shown, guardrails_fired=fired,
                visit_pivot=True), result)
        spoken = f"Gaadi nahi mili — model ya budget bata do."
        return _finalize(FormattedResponse(
            status="not_found", spoken=spoken, guardrails_fired=fired), result)

    # ── vague reel clarify (G-REEL aftermath) — exactly one clarifier ──
    if result.needs_clarification:
        spoken = ("Kaunsi gaadi pasand aayi — model ya budget bata do, "
                  "main check karta hoon.")
        return _finalize(FormattedResponse(
            status="clarify", spoken=spoken, guardrails_fired=["G-REEL"]), result)

    # ── nothing matched, no segment alternative ──
    if not result.found:
        spoken = ("Woh abhi available nahi lagti — lekin similar gaadi dikha "
                  "doon? Model ya budget bata do, main best nikaal deta hoon.")
        return _finalize(FormattedResponse(
            status="not_found", spoken=spoken), result)

    shown = [_safe_fields(it, q, fired) for it in result.matches[:2]]

    # ── segment alternative (G-SEGMENT) ──
    if result.alternative_segment:
        fired.append("G-SEGMENT")
        want = q.model or (q.category or "woh gaadi")
        alts = "; ".join(_phrase(it) for it in result.matches[:2])
        spoken = (f"{want} abhi available nahi, lekin same type mein {alts} hai — "
                  f"dikha doon? {VISIT_PIVOT}")
        return _finalize(FormattedResponse(
            status="segment", spoken=spoken, shown=shown,
            guardrails_fired=fired, visit_pivot=True,
            relaxed=result.relaxed), result)

    # ── single clean match ──
    if result.count == 1:
        it = result.matches[0]
        if result.relaxed:
            fired.append("G-RELAX")
        if it.location_type == "custody":
            fired.append("G-LOC")
        price = _price_clause(it, q, fired)
        relax_note = _relax_note(result.relaxed)
        avail = ""
        if "availability" in q.intents:
            fired.append("G-FRESH")
            avail = f" {FRESH_HEDGE}"
        spoken = (f"Haan{relax_note}, {_phrase(it)} available hai{price}. "
                  f"{VISIT_PIVOT}{avail}")
        return _finalize(FormattedResponse(
            status="found", spoken=spoken, shown=shown, guardrails_fired=fired,
            visit_pivot=True, relaxed=result.relaxed), result)

    # ── multiple matches (G-MULTI) — count + top 1-2 + ONE clarifier ──
    fired.append("G-MULTI")
    if result.relaxed:
        fired.append("G-RELAX")
    if "availability" in q.intents:
        fired.append("G-FRESH")
    top = "; ".join(_phrase(it) for it in result.matches[:2])
    relax_note = _relax_note(result.relaxed)
    spoken = (f"Haan{relax_note}, {result.count} options hain — jaise {top}. "
              f"Konsi dekhni hai — saal ya budget bata do? {VISIT_PIVOT}")
    return _finalize(FormattedResponse(
        status="multi", spoken=spoken, shown=shown, guardrails_fired=fired,
        visit_pivot=True, relaxed=result.relaxed), result)


def _relax_note(relaxed: List[str]) -> str:
    if not relaxed:
        return ""
    human = {"color": "exact colour", "transmission": "exact gear",
             "year_min": "exact saal", "ownership_exact": "owner count",
             "ownership_max": "owner count"}
    names = ", ".join(human.get(r, r) for r in relaxed)
    return f" ({names} thoda adjust kiya)"


# ─────────────────────────────────────────────────────────────────────────────
# G-EXPOSE — final scrub: assert no internal token leaked into the spoken string
# ─────────────────────────────────────────────────────────────────────────────
def _finalize(resp: FormattedResponse, result: RetrievalResult) -> FormattedResponse:
    forbidden = []
    for it in result.matches:
        forbidden.append(it.registration_no)
        if it.location_code:
            forbidden.append(it.location_code)
        if it.stock_no is not None:
            forbidden.append(str(it.stock_no))
    low = resp.spoken
    leaked = any(tok and tok in low for tok in forbidden if tok and len(str(tok)) >= 4)
    # also catch any MH-registration pattern defensively
    import re
    if re.search(r"MH\d{2}[A-Z]{0,3}\d{3,4}", low):
        leaked = True
    resp.contains_forbidden = bool(leaked)
    if "G-EXPOSE" not in resp.guardrails_fired:
        resp.guardrails_fired.append("G-EXPOSE")
    return resp


if __name__ == "__main__":
    from inventory_loader import load_inventory
    from query_parser import parse
    from retrieval_engine import RetrievalEngine
    eng = RetrievalEngine(load_inventory("../IVR_Sheet.xlsx"))
    for utt in ["Swift available hai?", "Creta available?", "Diesel SUV under 8 lakh",
                "White automatic Honda", "First owner cars", "Fortuner price?",
                "Creta mein sunroof hai?", "Jo reel mein thi woh gaadi"]:
        r = format_response(eng.search(parse(utt)))
        print(f"\nQ: {utt}\n  [{r.status}] forbidden={r.contains_forbidden} "
              f"fired={r.guardrails_fired}\n  {r.spoken}")
