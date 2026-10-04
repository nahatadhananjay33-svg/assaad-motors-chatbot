"""
inventory_normalize.py
======================
Header-aware normalization for owner-uploaded inventory workbooks.

The core loader (`inventory_loader`) reads the 17 core fields by FIXED column
position (A..Q) from a sheet named **DNJ**. Owners, however, build or export
their sheet in many shapes — reordered columns, extra columns, a differently
named sheet, slightly different header spellings. That used to make the upload
fail ("Sheet 'DNJ' not found", "CAR NUMB (N) missing", "0 live cars").

`normalize_to_canonical` reads the uploaded workbook **by HEADER NAME**, remaps
every recognised column to its canonical position, keeps every other column
(appended after, so the header-based loader + panel still pick them up — media,
seats, sunroof, instagram, youtube, and any new owner field), fixes the sheet
names, and writes a clean workbook the loader accepts. Nothing is dropped.

If no recognisable header row (no CAR NUMB column) can be found, it returns
None so the caller keeps the original strict validation (clear error message).
This never raises for ordinary data problems; callers still validate the result.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


def _norm(v: Any) -> str:
    """Normalise a header for matching: lowercase, collapse spaces, trim punctuation."""
    return re.sub(r"\s+", " ", str(v if v is not None else "").strip().lower()).strip(" .:_-")


# (canonical 0-based index, canonical header, canonical row-3 hint, accepted aliases)
_CORE: List[Tuple[int, str, str, List[str]]] = [
    (0,  "Stock No", "", ["stock no", "stock", "stock number", "stockno"]),
    (1,  "Sr No", "", ["sr no", "srno", "sr", "serial", "serial no", "sno", "s no"]),
    (2,  "Company / Make", "code: MARU, TOYO, HOND...",
         ["company / make", "company/make", "company", "make", "brand",
          "company name", "maker", "manufacturer", "company name / make"]),
    (3,  "Model", "e.g. Swift", ["model", "model name"]),
    (4,  "Year", "e.g. 2019",
         ["year", "yr", "mfg year", "manufacturing year", "make year", "reg year"]),
    (5,  "Insurance Valid Till", "",
         ["insurance valid till", "insurance", "ins", "insurance valid", "insurance date"]),
    (6,  "Variant", "e.g. VXI", ["variant", "vari", "trim"]),
    (7,  "Fuel Type", "P / D / C / E", ["fuel type", "fuel", "f", "fueltype"]),
    (8,  "Transmission", "A = Auto, M = Manual",
         ["transmission", "trans", "t", "gearbox", "gear"]),
    (9,  "Owners", "1 / 2 / 3",
         ["owners", "owner", "o", "ownership", "no of owners", "number of owners"]),
    (10, "KM Driven", "e.g. 45000",
         ["km driven", "km", "kms", "kilometers", "kilometres", "kms driven", "odometer"]),
    (11, "Colour", "e.g. White", ["colour", "color", "col"]),
    (12, "Rate (Rs)", "e.g. 550000",
         ["rate (rs)", "rate", "rate rs", "rate(rs)", "price", "rate in rs",
          "amount", "asking price"]),
    (13, "CAR NUMB", "e.g. MH01AB1234 (required)",
         ["car numb", "car number", "car_numb", "carnumb", "car num", "registration",
          "registration no", "reg no", "reg number", "regn no", "car no", "number plate"]),
    (14, "Reg Last 4", "e.g. 1234",
         ["reg last 4", "reg last4", "last 4", "reg_last4", "last four",
          "last 4 digits", "reg last four"]),
    (15, "Location", "e.g. B2", ["location", "loc", "yard", "parking"]),
    (16, "RTO", "", ["rto", "rto code"]),
]
N_CORE = len(_CORE)
CAR_NUMB_IDX = 13
SOLD_SHEET = "DONT TOUCH SOLD"

# alias (normalised) -> canonical index
_ALIAS: Dict[str, int] = {}
for _i, _name, _hint, _aliases in _CORE:
    _ALIAS.setdefault(_norm(_name), _i)
    for _a in _aliases:
        _ALIAS.setdefault(_norm(_a), _i)

_SOLD_NAMES = {"dont touch sold", "don t touch sold", "sold cars", "sold_cars", "sold"}
# a description/legend row (never real data) — our template's row 3 and similar
_HINT_RE = re.compile(r"e\.g\.|yyyy|\(required\)|code:|=\s*auto|/\s*d\s*/|1\s*/\s*2\s*/\s*3")


def _is_hint_row(cells: List[Any]) -> bool:
    blob = " ".join(_norm(c) for c in cells if c is not None)
    return bool(_HINT_RE.search(blob))


def _row_vals(ws, r: int, maxc: int) -> List[Any]:
    return [ws.cell(row=r, column=c).value for c in range(1, maxc + 1)]


def _find_sheet_and_header(wb) -> Optional[Tuple[str, int, Dict[int, int], int]]:
    """Return (sheet_name, header_row, {core_idx: src_col_1based}, max_col) for the
    first sheet whose top rows contain a CAR NUMB column — else None."""
    for sn in wb.sheetnames:
        if _norm(sn) in _SOLD_NAMES:          # never treat the SOLD sheet as inventory
            continue
        ws = wb[sn]
        maxc = ws.max_column or 0
        if not maxc:
            continue
        for hr in range(1, min(6, ws.max_row or 1) + 1):
            colmap: Dict[int, int] = {}
            for c in range(1, maxc + 1):
                h = _norm(ws.cell(row=hr, column=c).value)
                if h and h in _ALIAS and _ALIAS[h] not in colmap:
                    colmap[_ALIAS[h]] = c
            if CAR_NUMB_IDX in colmap:
                return sn, hr, colmap, maxc
    return None


def _build_sold_sheet(src_wb, out_wb) -> None:
    """Create DONT TOUCH SOLD. Copy registrations from a sold-like sheet if present."""
    ws = out_wb.create_sheet(SOLD_SHEET)
    ws.cell(row=2, column=CAR_NUMB_IDX + 1, value="CAR NUMB")
    sold = next((src_wb[sn] for sn in src_wb.sheetnames if _norm(sn) in _SOLD_NAMES), None)
    if sold is None:
        return
    maxc = sold.max_column or 0
    car_c = None
    for hr in range(1, min(4, (sold.max_row or 1)) + 1):
        for c in range(1, maxc + 1):
            if _ALIAS.get(_norm(sold.cell(row=hr, column=c).value)) == CAR_NUMB_IDX:
                car_c = c
                break
        if car_c:
            break
    if car_c is None:
        car_c = CAR_NUMB_IDX + 1
    out_r = 4
    for r in range(1, (sold.max_row or 0) + 1):
        v = sold.cell(row=r, column=car_c).value
        s = "" if v is None else str(v).strip()
        if not s or _norm(s) in _ALIAS:          # skip blanks + a header cell
            continue
        ws.cell(row=out_r, column=CAR_NUMB_IDX + 1, value=v)
        out_r += 1


def normalize_to_canonical(src_path: str, out_path: str) -> Optional[Dict[str, Any]]:
    """Read src workbook by header name, write a canonical DNJ + DONT TOUCH SOLD
    workbook to out_path. Returns a report dict, or None if no CAR NUMB column
    was found anywhere (caller should fall back to strict validation)."""
    import openpyxl

    wb = openpyxl.load_workbook(src_path, data_only=True)
    try:
        found = _find_sheet_and_header(wb)
        if not found:
            return None
        sn, hr, colmap, maxc = found
        ws = wb[sn]
        mapped = set(colmap.values())

        # extra columns = every source column with a non-empty header not used as a
        # core field, in ORIGINAL order (keeps media groups contiguous).
        extras: List[Tuple[int, str]] = []
        for c in range(1, maxc + 1):
            if c in mapped:
                continue
            h = ws.cell(row=hr, column=c).value
            if h is not None and str(h).strip() != "":
                extras.append((c, str(h).strip()))

        # data rows: everything below the header row, skipping blank rows. The
        # description/legend row only ever sits DIRECTLY under the header, so we only
        # hint-check that one position — never later rows (a real car's notes could
        # legitimately contain "e.g." or "=", and must not be dropped).
        data: List[List[Any]] = []
        for r in range(hr + 1, (ws.max_row or hr) + 1):
            cells = _row_vals(ws, r, maxc)
            if all(x is None or str(x).strip() == "" for x in cells):
                continue
            if r == hr + 1 and _is_hint_row(cells):
                continue
            data.append(cells)

        out = openpyxl.Workbook()
        od = out.active
        od.title = "DNJ"
        # header row (2) + hint row (3)
        for i, (idx, name, hint, _al) in enumerate(_CORE, start=1):
            od.cell(row=2, column=i, value=name)
            if hint:
                od.cell(row=3, column=i, value=hint)
        for j, (_src_c, htext) in enumerate(extras):
            od.cell(row=2, column=N_CORE + 1 + j, value=htext)

        # data rows from row 4
        out_r = 4
        for cells in data:
            for idx, _name, _hint, _al in _CORE:
                sc = colmap.get(idx)
                if sc and sc - 1 < len(cells):
                    v = cells[sc - 1]
                    if v is not None and str(v).strip() != "":
                        od.cell(row=out_r, column=idx + 1, value=v)
            for j, (sc, _htext) in enumerate(extras):
                if sc - 1 < len(cells):
                    v = cells[sc - 1]
                    if v is not None and str(v).strip() != "":
                        od.cell(row=out_r, column=N_CORE + 1 + j, value=v)
            out_r += 1

        _build_sold_sheet(wb, out)
        out.save(out_path)

        return {
            "sheet_used": sn,
            "header_row": hr,
            "core_mapped": sorted(nm for ix, nm, _h, _a in _CORE if ix in colmap),
            "core_missing": sorted(nm for ix, nm, _h, _a in _CORE if ix not in colmap),
            "extra_columns": [h for _c, h in extras],
            "data_rows": len(data),
        }
    finally:
        wb.close()
