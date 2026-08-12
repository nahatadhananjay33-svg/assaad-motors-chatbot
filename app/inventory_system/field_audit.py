"""
field_audit.py — data-driven Excel-column -> intent -> retrieval audit framework
================================================================================

Reusable, schema-driven, inventory-driven verification of the core chain:

    customer question -> intent -> Excel column -> current inventory
                      -> filter / lookup -> correct value -> response

It discovers the customer-facing field universe automatically:
  * 8 core (Phase 11A) fields answered via query_parser flags / intent, and
  * every extended (Phase 12D) field straight from ``field_intents.FIELD_SPECS``.

Questions are generated from each field's OWN vocabulary; expected values come
from whatever inventory is CURRENTLY loaded. Nothing is tied to a specific
model / registration / count, so this keeps working when the Excel changes.

Used by ``field_audit_tests.py`` (permanent regression) and can be run against
any ChatService instance.  NO LLM, NO new infrastructure — pure inspection.
"""
from __future__ import annotations

import field_intents as FI
import query_parser as QP


def _num(v):
    return v not in (None, "")

# ── core 11A fields (parser flags / intent, not FIELD_SPECS) ──
CORE = {
    "price": dict(display="Price", role="attr", is_price=True,
        labels=["price?", "price kya hai", "kitne ki hai", "kitne ka hai", "daam kya hai"],
        present=lambda c: bool(c.price_quotable and c.price_lakh),
        value=lambda c: f"{c.price_lakh:.2f}"),
    "km": dict(display="KM", role="both", flag="km_reading_query",
        labels=["km kitna hai", "kitne km chali hai", "kitna chala hai", "running kitni hai"],
        present=lambda c: _num(c.km_driven), value=lambda c: f"{c.km_driven:,}"),
    "fuel": dict(display="Fuel", role="both", flag="fuel_query",
        labels=["fuel kya hai", "kaunsa fuel", "petrol hai ya diesel"],
        present=lambda c: _num(c.fuel_norm), value=lambda c: c.fuel_norm),
    "transmission": dict(display="Transmission", role="both", flag="transmission_query",
        labels=["transmission kya hai", "automatic hai ya manual", "gearbox kaunsa hai"],
        present=lambda c: _num(c.transmission_norm), value=lambda c: c.transmission_norm),
    "color": dict(display="Colour", role="both", flag="color_query",
        labels=["colour kya hai", "rang kya hai", "kaunsa colour"],
        present=lambda c: _num(c.color_norm), value=lambda c: c.color_norm),
    "owners": dict(display="Owners", role="attr", flag="ownership_query",
        labels=["kitne owner hain", "kitne malik", "ownership kitni hai"],
        present=lambda c: _num(c.ownership_count), value=lambda c: str(c.ownership_count)),
    "seats": dict(display="Seats", role="both", flag="seats_query",
        labels=["kitne seater hai", "seating capacity kya hai", "kitni seat hai"],
        present=lambda c: _num(c.seats), value=lambda c: str(c.seats)),
    "year": dict(display="Year", role="attr", is_year=True,
        labels=["kaunsa saal hai", "year kya hai", "model year kya hai"],
        present=lambda c: _num(c.year_int), value=lambda c: str(c.year_int)),
}

_NEG = {"none", "no", "n", "nil", "na", "-", "0", "false"}
def _positive(val):
    if val in (None, ""):
        return False
    return str(val).strip().lower() not in _NEG

def _ext_value_str(attr, val):
    return str(val).split(".")[0] if isinstance(val, float) else str(val)


def column_ok(kind, field, label):
    """Does this question phrasing map to `field`'s Excel column?
    `field_intents.detect()` expects ALREADY-normalized text (as the live
    pipeline passes it), so normalize here too. Returns None for price/year,
    which are verified end-to-end instead of via a single flag."""
    if kind == "extended":
        attrs, _f = FI.detect(QP._norm(label))
        return field in attrs
    spec = CORE[field]
    if spec.get("flag"):
        return bool(getattr(QP.parse(label), spec["flag"], None))
    return None


def _all_fields():
    fields = []
    for f in CORE:
        s = CORE[f]
        fields.append(("core", f, s["display"], s["role"], s["labels"], s["present"], s["value"], s))
    for attr, spec in FI.FIELD_SPECS.items():
        present = (lambda a: (lambda c: _num(getattr(c, a, None))))(attr)
        value = (lambda a: (lambda c: _ext_value_str(a, getattr(c, a, None))))(attr)
        fields.append(("extended", attr, spec["display"], spec["role"], spec["labels"], present, value, spec))
    return fields


def run_audit(svc):
    """Return a per-field result dict list for the CURRENTLY loaded inventory."""
    facing = svc.engine.all_facing
    def ask(m, sid):
        return svc.handle(m, session_id=sid)

    rows = []
    for kind, field, display, role, labels, present, value, spec in _all_fields():
        r = {"field": field, "display": display, "kind": kind, "role": role,
             "labels_tested": len(labels), "map_fail": [], "positive": None,
             "missing": None, "filter": None, "wrong_price": False, "data_in_inv": 0}
        # (1) COLUMN MAPPING for every phrasing
        for lab in labels:
            if column_ok(kind, field, lab) is False:
                r["map_fail"].append(lab)
        pos_cars = [c for c in facing if present(c)]
        blank_cars = [c for c in facing if not present(c)]
        r["data_in_inv"] = len(pos_cars)
        # (2) DIRECT RETRIEVAL (positive)
        if pos_cars:
            car = pos_cars[0]; lab = labels[0]
            resp = ask(f"{car.registration_no} {lab}", "pos_" + field).response
            names = (FI.display(field).lower() in resp.lower()) if kind == "extended" \
                else (CORE[field]["display"].lower() in resp.lower() or value(car) in resp)
            val_in = value(car) in resp
            wrongp = (not spec.get("is_price")) and (" lakh" in resp.lower())
            r["positive"] = bool((names or val_in) and not wrongp)
            r["wrong_price"] = bool(wrongp)
        # (3) MISSING DATA
        if blank_cars:
            car = blank_cars[0]; lab = labels[0]
            resp = ask(f"{car.registration_no} {lab}", "mis_" + field).response.lower()
            r["missing"] = bool("not available" in resp or "data" in resp or "confirm" in resp
                                or "visit" in resp or "nahi" in resp or "पता" in resp)
        # (4) FILTER (role both)
        if role == "both" and pos_cars:
            res = ask(f"{labels[0]} wali dikhao", "flt_" + field)
            vids = res.vehicles or []
            if vids:
                def _sat(v):
                    it = svc._reg_lookup.get(v.get("registration_no"))
                    return bool(it and (present(it) if kind == "extended" else CORE[field]["present"](it)))
                r["filter"] = all(_sat(v) for v in vids)
        rows.append(r)
    return rows


def collision_check(svc):
    """The most important guard: field questions must map to the intended column,
    never collapse to price/km/another field. Uses column-mapping (not a pinned
    availability answer, whose card legitimately shows a price)."""
    fails = []
    cases = [("engine cc kitna hai", "engine_cc"), ("mileage kitna hai", "mileage_arai_kmpl"),
             ("boot kitna hai", "boot_litres"), ("km kitna hai", "km"),
             ("kitne owner hain", "owners"), ("kitne airbags hain", "airbags"),
             ("ground clearance kitna hai", "ground_clearance_mm")]
    for q, f in cases:
        kind = "core" if f in CORE else "extended"
        if column_ok(kind, f, q) is False:
            fails.append((q, f, "does not map to intended column"))
    # the deliberately AMBIGUOUS "engine kitna hai" must clarify, never quote price
    r = svc.handle("engine kitna hai", session_id="coll_bare")
    if " lakh" in r.response.lower():
        fails.append(("engine kitna hai", "clarify", "answered a price"))
    return fails


def summarize(rows):
    return dict(
        col_fail=[r for r in rows if r["map_fail"]],
        pos_fail=[r for r in rows if r["positive"] is False],
        mis_fail=[r for r in rows if r["missing"] is False],
        flt_fail=[r for r in rows if r["filter"] is False],
        wrongp=[r for r in rows if r["wrong_price"]],
    )
