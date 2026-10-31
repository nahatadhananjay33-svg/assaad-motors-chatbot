"""
financial_engine.py
===================

Deterministic data engine for the **Assad Motors Financial** internal console
(the /financial/ page — team only, NOT the customer chatbot). It reads the SAME
live workbook the customer bot uses (``/data/IVR_Sheet.xlsx``, sheet ``DNJ``) but
exposes the *financial* columns the owner walked through in his recording.

NO LLM / embeddings / vector DB here — pure, testable rules over the Excel rows.
(A semantic / vector column-matcher may be layered on later for free-text owner
queries; the button actions below stay deterministic so the money numbers are
always exact.)

Column map (0-based index in the DNJ row tuple; Excel letter in comment),
VERIFIED against the live sheet 2026-11-01:

    2  C   make (code)        3  D  model          4  E  year
    12 M   rate (Rs)          13 N  car number     15 P  location
    28 AC  purchase date      29 AD sale date      30 AE no. of days in house
    31 AF  investor name      32 AG seller company 33 AH price of purchase
    34 AI  app id             35 AJ expenses       36 AK total (cost)
    37 AL  estimate/add exp   38 AM gross profit    39 AN percent yield ("P")

Owner decisions (confirmed):
  * The "P" value = percent-yield column AN (read directly, not recomputed).
  * Sold / undelivered car = Rate (M) is the code ``33``.
  * Sale value per car = Total cost (AK) + Gross profit (AM).
  * Bank balances: out of scope for v1 (data not in the sheet yet).
"""

from __future__ import annotations

import os
import datetime as _dt
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

import openpyxl

try:
    from inventory_loader import MAKE_MAP
except Exception:                     # standalone / test fallback
    MAKE_MAP = {}

DNJ_SHEET = "DNJ"
DATA_START_ROW = 4                    # rows 1-3 are headers / examples (1-based)
SOLD_RATE_CODE = 33                   # Rate == 33 => sold but not yet delivered

# column indices (0-based) into the raw row tuple
IDX = {
    "make": 2, "model": 3, "year": 4,
    "rate": 12, "car_numb": 13, "location": 15,
    "purchase_date": 28, "sale_date": 29, "days": 30,
    "investor": 31, "seller": 32, "purchase_price": 33,
    "app_id": 34, "expenses": 35, "total": 36, "add_expenses": 37,
    "gross_profit": 38, "percent_yield": 39,
}

# Car-Days purchase-date cutoffs the owner listed (label -> last day of quarter).
# Selecting a cutoff shows cars purchased ON OR BEFORE it (the older / aged stock),
# sorted most-days-in-house first.
CAR_DAYS_CUTOFFS: List[Tuple[str, _dt.date]] = [
    ("31/12/25", _dt.date(2025, 12, 31)),
    ("31/3/26",  _dt.date(2026, 3, 31)),
    ("31/6/26",  _dt.date(2026, 6, 30)),
    ("31/9/26",  _dt.date(2026, 9, 30)),
    ("31/12/26", _dt.date(2026, 12, 31)),
    ("31/3/27",  _dt.date(2027, 3, 31)),
    ("31/6/27",  _dt.date(2027, 6, 30)),
    ("31/9/27",  _dt.date(2027, 9, 30)),
    ("31/12/27", _dt.date(2027, 12, 31)),
]

# PEY (percent-yield / "P") buckets. "under:N" is cumulative (everything below N,
# so negatives land in under-1); the ranges are inclusive lower, inclusive upper.
PEY_BUCKETS: List[Dict[str, Any]] = [
    {"key": "under:1",     "label": "Under 1"},
    {"key": "under:2",     "label": "Under 2"},
    {"key": "under:3",     "label": "Under 3"},
    {"key": "under:4",     "label": "Under 4"},
    {"key": "under:5",     "label": "Under 5"},
    {"key": "range:6:10",  "label": "6 – 10"},
    {"key": "range:11:15", "label": "11 – 15"},
    {"key": "range:16:20", "label": "16 – 20"},
    {"key": "range:20:40", "label": "20 – 40"},
    {"key": "range:40:100","label": "40 – 100"},
    {"key": "range:100:1000","label": "100 – 1000"},
]


# ─────────────────────────────────────────────────────────────────────────────
# Parsing helpers (defensive — the sheet is hand-maintained and messy)
# ─────────────────────────────────────────────────────────────────────────────
def _s(v: Any) -> str:
    return "" if v is None else str(v).strip()


def parse_money(v: Any) -> Optional[int]:
    """'2,84,180' / 284180 / '₹75000' / 419951.0 -> int ; blank -> None."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        try:
            return int(round(v))
        except Exception:
            return None
    s = str(v).replace(",", "").replace("₹", "").replace("Rs", "").replace("rs", "").strip()
    if s in ("", "-"):
        return None
    try:
        return int(round(float(s)))
    except Exception:
        return None


def parse_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("%", "").replace(",", "").strip()
    try:
        return float(s)
    except Exception:
        return None


def parse_date(v: Any) -> Optional[_dt.date]:
    """Accept a datetime (openpyxl) or a d/m/yy(yy) string."""
    if v is None or v == "":
        return None
    if isinstance(v, _dt.datetime):
        return v.date()
    if isinstance(v, _dt.date):
        return v
    s = str(v).strip()
    for sep in ("/", "-", "."):
        if sep in s:
            parts = [p for p in s.split(sep) if p != ""]
            if len(parts) == 3:
                try:
                    d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                    if y < 100:
                        y += 2000
                    return _dt.date(y, m, d)
                except Exception:
                    return None
    return None


def _norm_group(v: Any) -> str:
    """Normalise an investor / seller label for grouping: upper-case and
    collapse all internal whitespace (so 'CARS 24' == 'CARS24', 'WD ' == 'WD')."""
    return " ".join(_s(v).upper().split()).replace(" ", "")


def rate_is_sold(rate_raw: Any) -> bool:
    m = parse_money(rate_raw)
    return m == SOLD_RATE_CODE


def make_name(code: Any) -> str:
    c = _s(code).upper()
    return MAKE_MAP.get(c, _s(code).title() or "—")


# ─────────────────────────────────────────────────────────────────────────────
# Record
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class FinRecord:
    car_numb: str
    year: str
    make: str
    model: str
    rate_raw: Any
    location: str
    purchase_date: Optional[_dt.date]
    sale_date: Optional[_dt.date]
    days_in_house: Optional[int]
    investor: str                     # display (cleaned)
    investor_key: str                 # grouping key
    seller: str
    seller_key: str
    app_id: str
    purchase_price: Optional[int]
    expenses: Optional[int]
    add_expenses: Optional[int]
    total_cost: Optional[int]
    gross_profit: Optional[int]
    percent_yield: Optional[float]
    sold: bool

    @property
    def sale_value(self) -> Optional[int]:
        """Owner rule: sale value = total cost + gross profit."""
        if self.total_cost is None or self.gross_profit is None:
            return None
        return self.total_cost + self.gross_profit

    @property
    def title(self) -> str:
        yr = _s(self.year)
        return " ".join(x for x in (yr, self.make, self.model) if x) or self.car_numb

    def card(self) -> Dict[str, Any]:
        """Full financial detail card, in the owner's stated field order."""
        return {
            "car_numb": self.car_numb,
            "title": self.title,
            "year": _s(self.year), "make": self.make, "model": self.model,
            "purchase_date": _fmt_date(self.purchase_date),
            "days_in_house": self.days_in_house,
            "investor": self.investor,
            "bought_from": self.seller,
            "app_id": self.app_id or None,
            "purchase_price": self.purchase_price,
            "expenses": self.expenses,
            "add_expenses": self.add_expenses if self.add_expenses is not None else 0,
            "total_cost": self.total_cost,
            "sale_value": self.sale_value,
            "profit_loss": self.gross_profit,
            "percent_yield": _round(self.percent_yield),
            "sold": self.sold,
            "location": self.location or None,
        }


def _fmt_date(d: Optional[_dt.date]) -> Optional[str]:
    return d.strftime("%d/%m/%Y") if d else None


def _round(v: Optional[float]) -> Optional[float]:
    return round(v, 2) if isinstance(v, (int, float)) else None


# ─────────────────────────────────────────────────────────────────────────────
# Loading
# ─────────────────────────────────────────────────────────────────────────────
def _cell(row: Tuple, key: str) -> Any:
    i = IDX[key]
    return row[i] if i < len(row) else None


def load_records(path: Optional[str] = None, *, today: Optional[_dt.date] = None) -> List[FinRecord]:
    path = path or os.environ.get("CHAT_XLSX", "/data/IVR_Sheet.xlsx")
    today = today or _dt.date.today()
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[DNJ_SHEET]
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()

    out: List[FinRecord] = []
    for row in rows[DATA_START_ROW - 1:]:
        car = _s(_cell(row, "car_numb"))
        if not car:
            continue
        pdate = parse_date(_cell(row, "purchase_date"))
        days = _sanitize_days(_cell(row, "days"), pdate, today)
        investor_disp = " ".join(_s(_cell(row, "investor")).upper().split())
        seller_disp = " ".join(_s(_cell(row, "seller")).upper().split())
        rec = FinRecord(
            car_numb=car.upper(),
            year=_s(_cell(row, "year")),
            make=make_name(_cell(row, "make")),
            model=_s(_cell(row, "model")).title(),
            rate_raw=_cell(row, "rate"),
            location=_s(_cell(row, "location")).upper(),
            purchase_date=pdate,
            sale_date=parse_date(_cell(row, "sale_date")),
            days_in_house=days,
            investor=investor_disp or "—",
            investor_key=_norm_group(_cell(row, "investor")),
            seller=seller_disp or "—",
            seller_key=_norm_group(_cell(row, "seller")),
            app_id=_s(_cell(row, "app_id")),
            purchase_price=parse_money(_cell(row, "purchase_price")),
            expenses=parse_money(_cell(row, "expenses")),
            add_expenses=parse_money(_cell(row, "add_expenses")),
            total_cost=parse_money(_cell(row, "total")),
            gross_profit=parse_money(_cell(row, "gross_profit")),
            percent_yield=parse_float(_cell(row, "percent_yield")),
            sold=rate_is_sold(_cell(row, "rate")),
        )
        out.append(rec)
    return out


def _sanitize_days(raw: Any, pdate: Optional[_dt.date], today: _dt.date) -> Optional[int]:
    """Use the sheet's AE value when it is sane; otherwise derive from the
    purchase date. Guards against leaked date-serials (e.g. 46326)."""
    v = parse_money(raw)
    if v is not None and 0 <= v <= 3650:
        return v
    if pdate:
        delta = (today - pdate).days
        return delta if delta >= 0 else 0
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────────────────────
class FinancialEngine:
    def __init__(self, records: List[FinRecord]):
        self.records = records

    @classmethod
    def load(cls, path: Optional[str] = None, *, today: Optional[_dt.date] = None) -> "FinancialEngine":
        return cls(load_records(path, today=today))

    # ---- Car Days ----------------------------------------------------------
    def car_days_options(self) -> List[Dict[str, Any]]:
        opts = [{"key": lbl, "label": "Older than " + lbl} for lbl, _ in CAR_DAYS_CUTOFFS]
        opts.append({"key": "ALL", "label": "All cars"})
        return opts

    def car_days(self, cutoff_key: str) -> List[FinRecord]:
        if cutoff_key == "ALL":
            recs = list(self.records)
        else:
            cutoff = dict(CAR_DAYS_CUTOFFS).get(cutoff_key)
            if cutoff is None:
                return []
            recs = [r for r in self.records if r.purchase_date and r.purchase_date <= cutoff]
        return sorted(recs, key=lambda r: (r.days_in_house is None, -(r.days_in_house or 0)))

    # ---- PEY (percent yield) ----------------------------------------------
    def pey_options(self) -> List[Dict[str, Any]]:
        return list(PEY_BUCKETS)

    def pey(self, bucket_key: str) -> List[FinRecord]:
        recs = [r for r in self.records if r.percent_yield is not None]
        if bucket_key.startswith("under:"):
            n = float(bucket_key.split(":")[1])
            sel = [r for r in recs if r.percent_yield < n]
        elif bucket_key.startswith("range:"):
            _, lo, hi = bucket_key.split(":")
            lo, hi = float(lo), float(hi)
            sel = [r for r in recs if lo <= r.percent_yield <= hi]
        else:
            sel = []
        return sorted(sel, key=lambda r: -(r.percent_yield or 0))

    # ---- Buyer (investor) --------------------------------------------------
    def buyers(self) -> List[Dict[str, Any]]:
        groups: Dict[str, Dict[str, Any]] = {}
        for r in self.records:
            if not r.investor_key:
                continue
            g = groups.setdefault(r.investor_key, {"key": r.investor_key, "label": r.investor, "count": 0})
            g["count"] += 1
        return sorted(groups.values(), key=lambda g: -g["count"])

    def by_buyer(self, key: str) -> Dict[str, Any]:
        recs = [r for r in self.records if r.investor_key == _norm_group(key)]
        recs.sort(key=lambda r: (r.total_cost is None, -(r.total_cost or 0)))   # costliest first
        total_inv = sum(r.total_cost for r in recs if r.total_cost is not None)
        label = recs[0].investor if recs else key
        return {"label": label, "count": len(recs),
                "total_investment": total_inv, "cars": recs}

    # ---- Seller ------------------------------------------------------------
    def sellers(self) -> List[Dict[str, Any]]:
        groups: Dict[str, Dict[str, Any]] = {}
        for r in self.records:
            if not r.seller_key:
                continue
            g = groups.setdefault(r.seller_key, {"key": r.seller_key, "label": r.seller, "count": 0})
            g["count"] += 1
        return sorted(groups.values(), key=lambda g: -g["count"])

    def by_seller(self, key: str) -> Dict[str, Any]:
        recs = [r for r in self.records if r.seller_key == _norm_group(key)]
        recs.sort(key=lambda r: (r.days_in_house is None, -(r.days_in_house or 0)))  # oldest first
        total_inv = sum(r.total_cost for r in recs if r.total_cost is not None)
        label = recs[0].seller if recs else key
        return {"label": label, "count": len(recs),
                "total_investment": total_inv, "cars": recs}

    # ---- Profit / Loss -----------------------------------------------------
    def profit(self) -> List[FinRecord]:
        recs = [r for r in self.records if r.percent_yield is not None]
        return sorted(recs, key=lambda r: -(r.percent_yield or 0))          # highest P first

    def loss(self) -> List[FinRecord]:
        recs = [r for r in self.records if r.gross_profit is not None and r.gross_profit < 0]
        return sorted(recs, key=lambda r: (r.gross_profit or 0))            # biggest loss first

    # ---- Stock / Cars ------------------------------------------------------
    def stock(self) -> List[FinRecord]:
        """Cars currently for sale (exclude sold/undelivered code 33)."""
        return [r for r in self.records if not r.sold]

    def all_cars(self) -> List[FinRecord]:
        return list(self.records)

    # ---- Total stock summary ----------------------------------------------
    def total_summary(self) -> Dict[str, Any]:
        total = len(self.records)
        sold = [r for r in self.records if r.sold]
        for_sale = [r for r in self.records if not r.sold]
        cost_for_sale = sum(r.total_cost for r in for_sale if r.total_cost is not None)
        cost_sold = sum(r.total_cost for r in sold if r.total_cost is not None)
        loc: Dict[str, int] = {}
        for r in self.records:
            k = r.location or "—"
            loc[k] = loc.get(k, 0) + 1
        loc_sorted = sorted(loc.items(), key=lambda kv: -kv[1])
        return {
            "total_cars": total,
            "for_sale_count": len(for_sale),
            "sold_undelivered_count": len(sold),
            "total_cost_for_sale": cost_for_sale,
            "total_cost_sold": cost_sold,
            "locations": [{"location": k, "count": v} for k, v in loc_sorted],
            "bank_balances": None,     # v1: not in the sheet yet
        }

    # ---- Single car --------------------------------------------------------
    def car(self, reg: str) -> Optional[FinRecord]:
        reg = _s(reg).upper().replace(" ", "")
        for r in self.records:
            if r.car_numb.replace(" ", "") == reg:
                return r
        return None


def cards(recs: List[FinRecord]) -> List[Dict[str, Any]]:
    return [r.card() for r in recs]


if __name__ == "__main__":       # quick smoke test
    eng = FinancialEngine.load()
    print("records:", len(eng.records))
    print("summary:", eng.total_summary())
