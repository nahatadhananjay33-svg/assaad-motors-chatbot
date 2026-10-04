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


# Make-name tokens (built from the loader's MAKE_MAP) — used to spot a Make column
# BY ITS VALUES when it has no header (the owner's terse sheet puts AUDI/MARU/HOND…
# in a column with a blank header).
_MAKE_TOKENS: Optional[set] = None


def _make_tokens() -> set:
    global _MAKE_TOKENS
    if _MAKE_TOKENS is None:
        toks: set = set()
        try:
            from inventory_loader import MAKE_MAP
            for k, val in MAKE_MAP.items():
                toks.add(str(k).upper())
                for w in re.split(r"[\s\-/]+", str(val).upper()):
                    if len(w) >= 2:
                        toks.add(w)
        except Exception:
            pass
        toks |= {"MARUTI", "SUZUKI", "HYUNDAI", "HONDA", "TOYOTA", "MAHINDRA", "TATA",
                 "FORD", "RENAULT", "NISSAN", "VOLKSWAGEN", "SKODA", "CHEVROLET",
                 "FIAT", "DATSUN", "MITSUBISHI", "JEEP", "KIA", "MG", "AUDI", "BMW",
                 "MERCEDES", "BENZ", "JAGUAR", "RANGE", "ROVER", "VOLVO", "MINI",
                 "LEXUS", "PORSCHE", "ISUZU", "FORCE", "HINDUSTAN", "HIND"}
        _MAKE_TOKENS = toks
    return _MAKE_TOKENS


def _detect_make_col(ws, hr: int, maxc: int, used: set, sample: int = 50) -> Optional[int]:
    """Return the 1-based column whose data values are mostly car-make names, or None.
    Only used when no 'Make' HEADER was found."""
    toks = _make_tokens()
    best_frac, best_c = 0.0, None
    last = min(hr + sample, ws.max_row or hr)
    for c in range(1, maxc + 1):
        if c in used:
            continue
        hits = total = 0
        for r in range(hr + 1, last + 1):
            v = ws.cell(row=r, column=c).value
            if v is None or str(v).strip() == "":
                continue
            total += 1
            su = str(v).strip().upper()
            if su in toks or any(w in toks for w in re.split(r"[\s\-/]+", su)):
                hits += 1
        if total >= 5 and hits / total > best_frac:
            best_frac, best_c = hits / total, c
    return best_c if best_frac >= 0.5 else None


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


# Standard media groups we GUARANTEE on every normalised sheet, with the minimum
# number of slots each must have. Photos live in the EXTERIOR group. Videos are
# intentionally NOT guaranteed (the owner uses YouTube links instead), though any
# VIDEO / INTERIOR group the uploaded sheet already has is always preserved.
_STD_MEDIA: List[Tuple[str, int]] = [("INSTAGRAM", 6), ("EXTERIOR", 6), ("YOUTUBE", 6)]
_MEDIA_KEYWORDS = ("INSTAGRAM", "EXTERIOR", "INTERIOR", "VIDEO", "YOUTUBE")


def _media_kw(header: Any) -> Optional[str]:
    """Return the media-group keyword a header belongs to (EXTERIOR 1 -> EXTERIOR), else None.
    Matches only a group header ("EXTERIOR", "EXTERIOR 1", "EXTERIOR 1 (…)") — NOT legacy
    single fields like YOUTUBE_URL / INSTAGRAM_URL / VIDEO_URLS that merely start with the word."""
    hu = str(header if header is not None else "").strip().upper()
    for kw in _MEDIA_KEYWORDS:
        if hu == kw or hu.startswith(kw + " "):
            return kw
    return None


def _is_cont_header(header: Any) -> bool:
    """True for a bare slot-continuation header like '2' or '3'."""
    return str(header if header is not None else "").strip().isdigit()


def _plan_media_columns(
    extras: List[Tuple[int, str]]
) -> Tuple[List[Tuple[Optional[int], str]], List[str]]:
    """Plan the output's non-core columns so every standard media group has enough
    slots. Returns (plan, added):
      * plan  — ordered [(src_col | None, header)] for EVERY output extra column
                (real preserved columns + synthesised empty slots).
      * added — synthesised header texts, for the report.
    Standard groups (INSTAGRAM/EXTERIOR/YOUTUBE) are topped up to their minimum slot
    count and any wholly missing standard group is appended. Existing groups are
    NEVER shrunk (no data loss) and non-standard groups (VIDEO/INTERIOR) are kept
    exactly as uploaded but never synthesised."""
    targets = dict(_STD_MEDIA)
    plan: List[Tuple[Optional[int], str]] = []
    added: List[str] = []
    seen: set = set()
    i, n = 0, len(extras)
    while i < n:
        src_c, htext = extras[i]
        kw = _media_kw(htext)
        if kw is None:                                   # ordinary owner column — keep as-is
            plan.append((src_c, htext))
            i += 1
            continue
        group = [(src_c, htext)]                          # a media group: keyword + numeric runs
        j = i + 1
        while j < n and _is_cont_header(extras[j][1]):
            group.append(extras[j])
            j += 1
        for gc, gh in group:
            plan.append((gc, gh))
        if kw in targets:                                 # top up a short standard group
            seen.add(kw)
            for k in range(len(group), targets[kw]):
                h = str(k + 1)
                plan.append((None, h))
                added.append(kw + " " + h)
        i = j
    for kw, target in _STD_MEDIA:                         # append wholly-missing standard groups
        if kw in seen:
            continue
        plan.append((None, kw + " 1"))
        added.append(kw + " 1")
        for k in range(1, target):
            plan.append((None, str(k + 1)))
            added.append(kw + " " + str(k + 1))
    return plan, added


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

        # Value-based fallback for Make/Model when their HEADERS are missing (the
        # owner's terse sheet holds make/model data in unlabeled columns). Safe: only
        # runs when the header map did not already locate them.
        if 2 not in colmap:
            mc = _detect_make_col(ws, hr, maxc, set(colmap.values()))
            if mc:
                colmap[2] = mc
                nxt = mc + 1                      # model usually sits right after make
                if (3 not in colmap and nxt <= maxc and nxt not in colmap.values()
                        and not str(ws.cell(row=hr, column=nxt).value or "").strip()):
                    colmap[3] = nxt

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

        # Guarantee the standard media groups ALWAYS have enough slots, so photo /
        # instagram / youtube uploads always have somewhere to go — even if the
        # uploaded sheet had none, or had FEWER slots than we want. Standard sizes:
        # INSTAGRAM 6, EXTERIOR (photos) 6, YOUTUBE 6. Existing groups (with their
        # data) are kept and topped up; only truly missing groups are added empty.
        media_plan, media_groups_added = _plan_media_columns(extras)

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
        for j, (_src_c, htext) in enumerate(media_plan):
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
            for j, (sc, _htext) in enumerate(media_plan):
                if sc is not None and sc - 1 < len(cells):
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
            "media_groups_added": media_groups_added,
            "data_rows": len(data),
        }
    finally:
        wb.close()
