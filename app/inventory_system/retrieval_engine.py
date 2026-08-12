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

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from inventory_models import InventoryItem, BodyType, LocationType
from query_parser import Query

# category -> body_type set the customer likely means
CATEGORY_BODY_TYPES = {
    "SUV": {BodyType.SUV, BodyType.COMPACT_SUV},
    "Sedan": {BodyType.SEDAN},
    "Hatchback": {BodyType.HATCHBACK},
    "MUV": {BodyType.MUV, BodyType.SUV},
    "Luxury": {BodyType.LUXURY},
}
LUXURY_MAKES = {"MERC", "BMW", "AUDI", "JAGUAR", "RANGE", "VOLV"}

# softest-first relaxation order (G-RELAX). Hard constraints (model, fuel,
# budget, seats, category) are never relaxed.
RELAX_ORDER = ["color", "year_min", "ownership_exact", "ownership_max", "transmission"]


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
        if (item.model or "").lower() != q.model.lower():
            return False
    if q.make and "make" not in skip:
        if item.make != q.make:
            return False
    if q.fuel and "fuel" not in skip:
        if item.fuel_norm != q.fuel:
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
    if q.seats is not None and "seats" not in skip:
        if item.seats is not None:
            if item.seats != q.seats:
                return False
        else:
            # blank seat cell -> infer from body type (a sedan/hatchback IS a
            # 5-seater; an MUV is a 7-seater) so Excel-style seat filters see
            # the whole stock, not just rows where the cell was filled in
            if item.body_type == BodyType.MUV:
                inferred = 7
            elif item.body_type in (BodyType.HATCHBACK, BodyType.SEDAN,
                                    BodyType.COMPACT_SUV, BodyType.SUV,
                                    BodyType.LUXURY):
                inferred = 5
            else:
                inferred = None
            if inferred != q.seats:
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
            if item.make not in LUXURY_MAKES and item.body_type != BodyType.LUXURY:
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

    # -- pool selection: default IVR>2; full catalogue for a named model (G-SOURCE-FALLBACK)
    def _pool(self, q: Query):
        if q.registration or q.model or q.reg_partial:
            return self.all_facing, False           # named car/number: search everything
        ivr = [i for i in self.all_facing if i.is_ivr_eligible]
        # Phase 11C: an explicit budget ceiling invites budget cars — extend the
        # default (>2L) pool with sub-2L cars that fit the stated budget, so
        # "2 lakh ke niche" actually shows the Altos/City/Spark instead of
        # a false "not available".
        if q.price_max is not None:
            extra = [i for i in self.all_facing
                     if not i.is_ivr_eligible
                     and i.price_inr is not None and i.price_inr <= q.price_max]
            if extra:
                return ivr + extra, False
        if ivr:
            return ivr, False
        return self.all_facing, True                # nothing >2L: fall back

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

        matches = [i for i in pool if _matches(i, q)]

        # ── G-RELAX: zero after AND -> relax softest active constraint, in order ──
        if not matches and not q.registration:
            active = q.active_filters()
            skip = set()
            for cons in RELAX_ORDER:
                if cons in active or (cons in ("ownership_exact", "ownership_max")
                                      and active.get(cons) is not None):
                    skip.add(cons)
                    trial = [i for i in pool if _matches(i, q, skip=skip)]
                    if trial:
                        matches = trial
                        result.relaxed = sorted(skip)
                        break

        # ── G-SEGMENT: still zero -> same body-type alternative (drop model) ──
        if not matches and not q.registration and (q.model or q.category):
            body_types = self._target_body_types(q)
            if body_types:
                seg = [i for i in pool
                       if i.body_type in body_types and _matches(
                           i, q, skip={"model", "make", "color", "transmission",
                                       "year_min", "ownership_exact", "ownership_max"})]
                if seg:
                    matches = seg
                    result.alternative_segment = True

        # ── rank ──
        if q.sort_low_km:
            matches = sorted(matches, key=_low_km_key)
        elif q.sort_cheapest:
            matches = sorted(matches, key=_cheapest_key)
        else:
            matches = sorted(matches, key=_rank_key)

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
        if (i.model or "").lower() == model.lower():
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
