"""
retrieval_engine.py
===================

Deterministic inventory search. Converts a parsed `Query` into a ranked set of
`InventoryItem`s, operating ENTIRELY on inventory records — NO LLM, NO vector
DB, NO embeddings, NO RAG.

Implements the retrieval contract from:
  * inventory_retrieval_rules.md  (pipeline §1, ranking §1.6, query playbook §3)
  * retrieval_guardrails.md        (G-SOLD, G-PHANTOM, G-MULTI, G-RELAX,
                                    G-SEGMENT, G-SOURCE-FALLBACK, G-LOC)

Hard exclusions are applied first (sold / placeholder), then AND-filters, then
zero-match relaxation, then ranking. The engine never auto-picks a single car
when several match (G-MULTI) — it returns the ranked set and lets the formatter
surface count + top-N + one clarifier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from inventory_models import InventoryItem, BodyType, LocationType
from query_parser import Query


# A fuel that is FITTED ON TOP of a base fuel. Indian bi-fuel cars are recorded
# as "Petrol+CNG", and a customer asking for a CNG car means exactly those.
_SECONDARY_FUELS = {"cng", "lpg"}


def _fuel_matches(item_fuel: Optional[str], want: str) -> bool:
    """True when the car answers the requested fuel, deliberately asymmetric.

    * Asking for CNG/LPG matches combined values — "cng cars" must find the 14
      Petrol+CNG cars as well as the 9 pure CNG ones. Exact equality found 9 of
      23, so most of the CNG stock was invisible.
    * Asking for petrol/diesel stays an EXACT column match, like an Excel filter.
      A Petrol+CNG car is sold as a CNG car; folding it into "petrol cars" would
      inflate that count (89 -> 103) and hand a CNG-kitted car to someone who
      asked for a plain petrol one."""
    if not item_fuel:
        return False
    w = str(want).strip().lower()
    if w in _SECONDARY_FUELS:
        have = {p.strip().lower()
                for p in re.split(r"[+/,&]| and ", str(item_fuel)) if p.strip()}
        return w in have
    return str(item_fuel).strip().lower() == w


def _model_key(s: str) -> str:
    """Space/hyphen-insensitive model key so an inventory spelling and its market
    alias fold together: 'Xuv 700' == 'XUV700' == 'xuv-700'. Prevents an
    in-stock model from being missed just because the Excel and the alias table
    space it differently."""
    return (s or "").lower().replace(" ", "").replace("-", "")


# category -> body_type set the customer means. SUV intentionally includes
# Compact SUV (a defined hierarchy the dealership wants). MUV is its OWN category
# and is NOT a silent SUV substitute — an MUV search returns MUVs only.
CATEGORY_BODY_TYPES = {
    "SUV": {BodyType.SUV, BodyType.COMPACT_SUV},
    "Sedan": {BodyType.SEDAN},
    "Hatchback": {BodyType.HATCHBACK},
    "MUV": {BodyType.MUV},
    # "Luxury" is handled by the is_luxury column, not a body-type set.
}
# LUXURY_MAKES removed: luxury now comes ONLY from the "Luxury" Excel column
# (InventoryItem.is_luxury). No brand-based luxury inference anywhere. A shim is
# kept so the one-time Excel seeding script and any old import still resolve.
LUXURY_MAKES = {"MERC", "BMW", "AUDI", "JAGUAR", "RANGE", "VOLV"}


@dataclass
class RetrievalResult:
    query: Query
    matches: List[InventoryItem] = field(default_factory=list)
    relaxed: List[str] = field(default_factory=list)     # constraints dropped
    alternative_segment: bool = False                    # G-SEGMENT fired
    source_fallback: bool = False                        # searched beyond IVR>2
    needs_clarification: bool = False
    clarify_reason: Optional[str] = None

    @property
    def count(self) -> int:
        return len(self.matches)

    @property
    def found(self) -> bool:
        return self.count > 0


# ─────────────────────────────────────────────────────────────────────────────
# Filter predicates
# ─────────────────────────────────────────────────────────────────────────────
def _matches(item: InventoryItem, q: Query, *, skip: Optional[set] = None) -> bool:
    skip = skip or set()

    # registration is the strongest identifier: exact match, skip everything else
    if q.registration:
        return (item.registration_no or "").upper() == q.registration

    # partial registration:
    #   * letter-led ("MH01")  -> prefix/substring of the plate (area search)
    #   * digits ("9999")      -> must be the EXACT trailing number group of the
    #     plate (the real last-4). "9999" matches MH99ZZ9999, but "999" / "99"
    #     do NOT — never a loose substring. If it doesn't match, no car is found.
    if q.reg_partial and "reg_partial" not in skip:
        plate = (item.registration_no or "").upper().replace(" ", "")
        rp = q.reg_partial
        if rp.isdigit():
            # the digits must equal the complete trailing digit-run of the plate
            if not (plate.endswith(rp)
                    and (len(plate) == len(rp) or not plate[-(len(rp) + 1)].isdigit())):
                return False
        elif rp not in plate:
            return False

    if q.model and "model" not in skip:
        if _model_key(item.model) != _model_key(q.model):
            return False
    if q.make and "make" not in skip:
        if item.make != q.make:
            return False
    if q.fuel and "fuel" not in skip:
        if not _fuel_matches(item.fuel_norm, q.fuel):
            return False
    if q.transmission and "transmission" not in skip:
        if item.transmission_norm != q.transmission:
            return False
    if q.color and "color" not in skip:
        if (item.color_norm or "") != q.color:
            return False
    if q.ownership_exact is not None and "ownership_exact" not in skip:
        if item.ownership_count != q.ownership_exact:
            return False
    if q.ownership_max is not None and "ownership_max" not in skip:
        if item.ownership_count is None or item.ownership_count > q.ownership_max:
            return False
    # Seats: EXACT match against the "Seats" Excel column only. No inference from
    # body type / model. A blank seat cell (item.seats is None) is "unknown" and
    # therefore never matches a seat filter — the Excel is the single source.
    if q.seats is not None and "seats" not in skip:
        if item.seats != q.seats:
            return False
    # km ceiling ("under 20000 km") — never relaxed, mirrors an Excel filter;
    # unknown odometer never sneaks under a km limit
    if q.km_max is not None and "km_max" not in skip:
        if item.km_driven is None or item.km_driven > q.km_max:
            return False
    # insured cars only ("insurance kis kis ka hai") — needs an insurance date;
    # a parseable date in the past (expired policy) does not count
    if q.has_insurance and "has_insurance" not in skip:
        _ins = item.insurance_expiry or item.insurance_hint
        if not _ins:
            return False
        try:
            from datetime import date
            if date.fromisoformat(str(_ins)[:10]) < date.today():
                return False
        except ValueError:
            pass                       # unparseable note still counts as insured
    if q.category and "category" not in skip:
        if q.category == "Luxury":
            # ONLY the Excel Luxury column decides this — no brand inference.
            if not item.is_luxury:
                return False
        else:
            if item.body_type not in CATEGORY_BODY_TYPES.get(q.category, set()):
                return False
    if q.year_min is not None and "year_min" not in skip:
        if item.year_int is None or item.year_int < q.year_min:
            return False
    if q.year_exact is not None and "year_exact" not in skip:
        if item.year_int != q.year_exact:
            return False
    # price filters apply only to quotable prices (never invent a price band)
    if q.price_max is not None and "price_max" not in skip:
        if item.price_inr is None or item.price_inr > q.price_max:
            return False
    if q.price_min is not None and "price_min" not in skip:
        if item.price_inr is None or item.price_inr < q.price_min:
            return False
    # ── Phase 12D: feature filters ("sunroof wali", "6 airbags wali", "alloy
    #    wheels wali"). Hard AND-filter (never relaxed). want=None -> feature must
    #    be present/truthy; want=value -> must equal. Unknown value never passes. ──
    if getattr(q, "feature_filters", None) and "feature_filters" not in skip:
        for attr, want in q.feature_filters.items():
            iv = getattr(item, attr, None)
            if want is None:
                if iv is True:
                    continue
                if isinstance(iv, (int, float)) and not isinstance(iv, bool) and iv > 0:
                    continue
                if isinstance(iv, str) and iv.strip() and iv.strip().lower() not in (
                        "none", "no", "false", "0"):
                    continue
                return False
            elif isinstance(want, int):
                if not (isinstance(iv, (int, float)) and not isinstance(iv, bool)
                        and int(iv) == want):
                    return False
            else:
                if iv is None or str(iv).strip().lower() != str(want).strip().lower():
                    return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Ranking (inventory_retrieval_rules.md §1.6)
# ─────────────────────────────────────────────────────────────────────────────
def _rank_key(item: InventoryItem):
    quotable_first = 0 if item.price_quotable else 1            # quotable before coded
    year_desc = -(item.year_int or 0)                           # newer first
    if item.km_driven is None:                                  # numeric km before blank
        km_key = (1, 0)
    else:
        km_key = (0, item.km_driven)
    owners = item.ownership_count if item.ownership_count is not None else 99
    custody = 1 if item.location_type == LocationType.CUSTODY else 0  # slot before custody
    return (quotable_first, year_desc, km_key, owners, custody)


def _cheapest_key(item: InventoryItem):
    return item.price_inr if item.price_inr is not None else 10**12


def _price_asc_key(item: InventoryItem):
    """Default ordering: cheapest first. Cars with no valid rupee price sink to
    the bottom; equal prices fall back to newer-year-first for a stable order."""
    price = item.price_inr if item.price_inr is not None else 10**12
    return (price, -(item.year_int or 0))


def _low_km_key(item: InventoryItem):
    # Phase 7L: km ascending (lowest first); unknown km sinks to the bottom.
    return item.km_driven if item.km_driven is not None else 10**12


# ─────────────────────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────────────────────
class RetrievalEngine:
    def __init__(self, items: List[InventoryItem], *, top_n: int = 3):
        # G-SOLD / G-PHANTOM already enforced by InventoryItem.is_customer_facing,
        # but we re-assert here so the engine is safe regardless of caller.
        self.all_facing = [i for i in items if i.is_customer_facing]
        self.top_n = top_n

    # -- pool selection: ALWAYS the whole customer-facing book.
    # The old ">₹2 lakh IVR" restriction is gone: it silently hid the sub-2L cars
    # from any search. Every query — filtered or not — now sees the full current
    # inventory, exactly like an Excel filter. (A bare no-criteria "cars dikhao"
    # is guided upstream in chat_service, so it never reaches here as a dump.)
    def _pool(self, q: Query):
        return self.all_facing, False

    def search(self, q: Query) -> RetrievalResult:
        result = RetrievalResult(query=q)

        # vague reel query -> one clarifier (G-REEL aftermath)
        if q.clarify_needed:
            result.needs_clarification = True
            result.clarify_reason = "vague_no_filter"
            return result

        # off-sheet topic: no inventory answer to compute; formatter routes it
        # (we still run a search so an accompanying model/colour can be confirmed)

        pool, fallback = self._pool(q)
        result.source_fallback = fallback

        # EXACT filtering — every constraint the customer stated is an AND that is
        # never silently dropped. G-RELAX (silently relaxing colour/year/owner/
        # transmission) and G-SEGMENT (silently swapping a model for another car
        # of the same body type) have been REMOVED: a zero-match search returns
        # zero, and chat_service says so honestly and may offer a CLEARLY-LABELLED
        # alternative. What the customer asked for is exactly what is filtered.
        matches = [i for i in pool if _matches(i, q)]

        # ── rank: PRICE ASCENDING (cheapest first) by default. Sorting happens
        #    only AFTER filtering and never changes which cars match. ──
        if q.sort_low_km:
            matches = sorted(matches, key=_low_km_key)
        else:
            matches = sorted(matches, key=_price_asc_key)

        result.matches = matches
        return result

    def _target_body_types(self, q: Query):
        if q.category:
            if q.category == "Luxury":
                return {BodyType.LUXURY}
            return CATEGORY_BODY_TYPES.get(q.category, set())
        if q.model:
            # derive the named model's body type from any catalogue example
            bt = _body_type_of_model(self.all_facing, q.model)
            if bt and bt != BodyType.UNKNOWN:
                return {bt}
            # fall back to the static map in the loader
            import inventory_loader as L
            bt2 = L._body_type_for(q.model)
            return {bt2} if bt2 != BodyType.UNKNOWN else set()
        return set()


def _body_type_of_model(items, model: str):
    for i in items:
        if _model_key(i.model) == _model_key(model):
            return i.body_type
    import inventory_loader as L
    return L._body_type_for(model)


if __name__ == "__main__":
    from inventory_loader import load_inventory
    from query_parser import parse
    eng = RetrievalEngine(load_inventory("../IVR_Sheet.xlsx"))
    for utt in ["Swift available hai?", "Creta available?", "Diesel SUV under 8 lakh",
                "White automatic Honda", "First owner cars", "CNG cars"]:
        r = eng.search(parse(utt))
        models = [f"{m.model}/{m.year_int}" for m in r.matches[:3]]
        print(f"{utt:32} -> n={r.count} relaxed={r.relaxed} seg={r.alternative_segment} {models}")
