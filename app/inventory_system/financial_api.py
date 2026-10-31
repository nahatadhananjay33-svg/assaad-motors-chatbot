"""
financial_api.py
================

JSON API for the **Assad Motors Financial** internal console. Thin transport
over ``financial_engine`` (which owns all the rules). Every route is read-only
and GET-only; authorization is enforced by ``financial_auth`` at the call site
in ``chat_api.route``.

Endpoints (all under ``/financial/api``):
  GET /summary                      -> total stock summary
  GET /car_days                     -> cutoff options
  GET /car_days?cutoff=31/3/26      -> cars (cards) older than cutoff
  GET /pey                          -> percent-yield bucket options
  GET /pey?bucket=range:6:10        -> cars in bucket
  GET /buyers                       -> investor groups (label,count)
  GET /buyer?key=WD                 -> {label,count,total_investment,cars[]}
  GET /sellers                      -> seller groups
  GET /seller?key=CARS24            -> {label,count,total_investment,cars[]}
  GET /profit                       -> cars ranked by yield desc
  GET /loss                         -> loss-making cars, biggest loss first
  GET /stock                        -> for-sale cars (exclude Rate=33)
  GET /cars                         -> all cars
  GET /car?reg=MH04GZ0167           -> one car card
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs

import financial_engine as FE

# ── engine cache keyed on workbook mtime (so owner edits reflect live) ──
_CACHE: Dict[str, Any] = {"path": None, "mtime": None, "engine": None}


def _workbook_path() -> str:
    return os.environ.get("CHAT_XLSX", "/data/IVR_Sheet.xlsx")


def get_engine() -> FE.FinancialEngine:
    path = _workbook_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = None
    if (_CACHE["engine"] is None or _CACHE["path"] != path
            or _CACHE["mtime"] != mtime):
        _CACHE["engine"] = FE.FinancialEngine.load(path)
        _CACHE["path"] = path
        _CACHE["mtime"] = mtime
    return _CACHE["engine"]


def _one(qs: Dict[str, list], name: str) -> Optional[str]:
    v = qs.get(name)
    return v[0] if v else None


def handle(method: str, subpath: str, query_string: str
           ) -> Tuple[int, Dict[str, Any]]:
    """Dispatch a ``/financial/api/<subpath>`` request. Never raises."""
    if method != "GET":
        return 405, {"error": "method_not_allowed",
                     "detail": f"{method} not allowed on /financial/api/{subpath}."}
    qs = parse_qs(query_string or "")
    eng = get_engine()

    try:
        if subpath == "summary":
            return 200, eng.total_summary()

        if subpath == "car_days":
            cutoff = _one(qs, "cutoff")
            if not cutoff:
                return 200, {"options": eng.car_days_options()}
            return 200, {"cutoff": cutoff, "cars": FE.cards(eng.car_days(cutoff))}

        if subpath == "pey":
            bucket = _one(qs, "bucket")
            if not bucket:
                return 200, {"options": eng.pey_options()}
            return 200, {"bucket": bucket, "cars": FE.cards(eng.pey(bucket))}

        if subpath == "buyers":
            return 200, {"buyers": eng.buyers()}
        if subpath == "buyer":
            key = _one(qs, "key")
            if not key:
                return 400, {"error": "missing_key", "detail": "buyer key required."}
            r = eng.by_buyer(key)
            return 200, {"label": r["label"], "count": r["count"],
                         "total_investment": r["total_investment"],
                         "cars": FE.cards(r["cars"])}

        if subpath == "sellers":
            return 200, {"sellers": eng.sellers()}
        if subpath == "seller":
            key = _one(qs, "key")
            if not key:
                return 400, {"error": "missing_key", "detail": "seller key required."}
            r = eng.by_seller(key)
            return 200, {"label": r["label"], "count": r["count"],
                         "total_investment": r["total_investment"],
                         "cars": FE.cards(r["cars"])}

        if subpath == "profit":
            return 200, {"cars": FE.cards(eng.profit())}
        if subpath == "loss":
            return 200, {"cars": FE.cards(eng.loss())}
        if subpath == "stock":
            return 200, {"cars": FE.cards(eng.stock())}
        if subpath == "cars":
            return 200, {"cars": FE.cards(eng.all_cars())}

        if subpath == "car":
            reg = _one(qs, "reg")
            if not reg:
                return 400, {"error": "missing_reg", "detail": "reg required."}
            rec = eng.car(reg)
            if rec is None:
                return 404, {"error": "not_found", "detail": f"No car {reg}."}
            return 200, rec.card()

    except Exception as e:                            # last-resort safety net
        return 500, {"error": "financial_failed", "detail": str(e)}

    return 404, {"error": "not_found",
                 "detail": f"No financial route /financial/api/{subpath}."}
