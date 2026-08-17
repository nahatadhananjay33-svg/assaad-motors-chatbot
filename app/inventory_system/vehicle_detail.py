"""
vehicle_detail.py
=================

Customer-facing, read-only single-vehicle detail for the "click a card" feature.

    GET /vehicle?reg=<registration_no>
        -> the CURRENT inventory record for that EXACT vehicle (by registration),
           customer-safe fields only, plus that vehicle's own media.

Design guarantees:
  * Identity is the registration number — never the model — so duplicate models
    resolve to the exact car clicked.
  * The record is read LIVE from the running inventory (ChatService._reg_lookup,
    rebuilt on every load/refresh). Nothing trusts the frontend card, so price /
    KM / media / sold-removed all reflect the current Excel.
  * A strict WHITELIST of customer-facing attributes is serialized. Internal /
    system / admin columns (rate codes, custody, stock no, price_inr, IVR flags,
    raw cells, source sheet …) are never read, so they cannot leak.
  * Missing values are hidden (secondary/specs) or shown as "Data not available"
    (primary). Nothing is inferred from another field.

This module does NOT change search, filtering, intent, media architecture, the
admin panel, or the Excel schema. It is additive and read-only.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs


def _norm_reg(reg: str) -> str:
    return "".join(str(reg or "").split()).upper().replace("-", "")


# ── formatters (value -> display string, or None to hide) ────────────────────
def _s(v):                       # plain text
    if v is None:
        return None
    t = str(v).strip()
    if not t or t.lower() in ("none", "unknown", "nan", "data not available"):
        return None
    return t


def _lakh(v):
    return f"₹{v:.2f} Lakh" if isinstance(v, (int, float)) and v else None


def _km(v):
    return f"{int(v):,} km" if isinstance(v, (int, float)) and v is not None else None


def _int(v, suffix=""):
    return f"{int(v)}{suffix}" if isinstance(v, (int, float)) and not isinstance(v, bool) and v is not None else None


def _seats(v):
    return f"{int(v)} Seater" if isinstance(v, (int, float)) and v else None


def _owners(v):
    if not isinstance(v, (int, float)) or v is None:
        return None
    n = int(v)
    return f"{n} owner" + ("s" if n != 1 else "")


def _yesno(v):
    return "Yes" if v is True else ("No" if v is False else None)


def _bool_yn(v):
    return "Yes" if v is True else ("No" if v is False else None)


def _sunroof(v):
    t = _s(v)
    return None if t is None else ("No" if t.lower() == "none" else f"Yes ({t})")


# ── field plans: (attr, label, formatter). Values read LIVE from the item. ────
# PRIMARY is always shown (value or "Data not available"). The rest are shown
# only when a value is present (blank -> hidden, cleaner UX).
_PRIMARY: List[Tuple[str, str, Any]] = [
    ("price_lakh", "Price", _lakh),
    ("km_driven", "KM Driven", _km),
    ("year_int", "Year", lambda v: str(v) if v else None),
    ("fuel_norm", "Fuel", _s),
    ("transmission_norm", "Transmission", _s),
    ("seats", "Seats", _seats),
]
_DETAILS: List[Tuple[str, str, Any]] = [
    ("color_norm", "Colour", _s),
    ("ownership_count", "Owners", _owners),
    ("is_luxury", "Luxury", _yesno),
    ("body_type", "Body Type", _s),
    ("insurance_hint", "Insurance", _s),
    ("rc_status", "RC Status", _s),
    ("rto", "RTO", _s),
]
_SPECS: List[Tuple[str, str, Any]] = [
    ("engine_cc", "Engine", lambda v: _int(v, " cc")),
    ("mileage_arai_kmpl", "Mileage (ARAI)", lambda v: f"{v:g} kmpl" if isinstance(v, (int, float)) and v else None),
    ("airbags", "Airbags", lambda v: _int(v)),
    ("camera_type", "Camera", _s),
    ("sunroof_type", "Sunroof", _sunroof),
    ("parking_sensors", "Parking Sensors", lambda v: _s(v) or _bool_yn(v)),
    ("abs_ebd", "ABS/EBD", _bool_yn),
    ("boot_litres", "Boot Space", lambda v: _int(v, " litres")),
    ("ground_clearance_mm", "Ground Clearance", lambda v: _int(v, " mm")),
    ("fuel_tank_l", "Fuel Tank", lambda v: _int(v, " litres")),
    ("drivetrain", "Drivetrain", _s),
    ("ncap_rating", "NCAP Rating", lambda v: _int(v, "★")),
]


def _rows(item, plan, keep_blank_as_na: bool) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for attr, label, fmt in plan:
        try:
            disp = fmt(getattr(item, attr, None))
        except Exception:
            disp = None
        if disp is None:
            if keep_blank_as_na:
                out.append({"label": label, "value": "Data not available"})
            continue
        out.append({"label": label, "value": disp})
    return out


def build_detail(item, assets) -> Dict[str, Any]:
    """Customer-safe detail dict for one InventoryItem + its MediaAssets."""
    title = " ".join(str(x) for x in (item.year_int, item.color_norm, item.model)
                     if x and str(x).lower() != "unknown").strip() or (item.model or "Vehicle")
    photos = list(assets.all_photos()) if assets else []
    videos = list(assets.videos) if assets else []
    veh_ig = list(assets.instagram) if assets else []
    veh_yt = list(assets.youtube) if assets else []
    return {
        "status": "ok",
        "registration_no": item.registration_no,
        "title": title,
        "make": item.make_full,
        "model": item.model,
        "variant": _s(item.variant),
        "primary": _rows(item, _PRIMARY, keep_blank_as_na=True),
        "details": _rows(item, _DETAILS, keep_blank_as_na=False),
        "specs": _rows(item, _SPECS, keep_blank_as_na=False),
        "media": {"photos": photos, "videos": videos},
        # vehicle-specific links only when the car actually has them; the frontend
        # falls back to clearly-labelled DEALERSHIP links otherwise (never faked).
        "links": {"instagram": veh_ig[0] if veh_ig else None,
                  "youtube": veh_yt[0] if veh_yt else None},
    }


def handle_vehicle_detail(service: Any, query_string: str) -> Tuple[int, Dict[str, Any]]:
    """GET /vehicle?reg=<reg>. Read-only; customer-safe; current inventory."""
    params = parse_qs(query_string or "")
    reg_in = (params.get("reg", [""])[0] or "").strip()
    if not reg_in:
        return 400, {"status": "error", "detail": "Missing 'reg' query parameter."}
    target = _norm_reg(reg_in)
    lookup = getattr(service, "_reg_lookup", {}) or {}
    item = lookup.get(reg_in) or lookup.get(reg_in.upper())
    if item is None:
        for k, it in lookup.items():
            if _norm_reg(k) == target:
                item = it
                break
    if item is None:
        # sold / removed / never existed — never show stale data
        return 404, {"status": "not_available",
                     "message": "This vehicle is no longer available."}
    try:
        assets = service.media_service.provider.fetch(item)
    except Exception:
        assets = None
    return 200, build_detail(item, assets)
