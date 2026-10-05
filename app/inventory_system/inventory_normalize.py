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

import os
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


def _url_platform(v: Any) -> Optional[str]:
    """Classify a cell value as an INSTAGRAM or YOUTUBE link, else None."""
    s = str(v if v is not None else "").lower()
    if "instagram.com" in s:
        return "INSTAGRAM"
    if "youtube.com" in s or "youtu.be" in s:
        return "YOUTUBE"
    return None


def _detect_url_media_cols(ws, hr: int, maxc: int, used: set, sample: int = 80) -> Dict[str, List[int]]:
    """Find UNHEADERED columns that hold media links (owner's raw export often drops
    instagram/youtube URLs into blank-header columns). Returns {platform: [cols...]}
    in column order, so they can be preserved instead of dropped. Detected by value:
    a column counts for a platform when its non-empty values are >=50% that platform's
    links. Headered columns are left to the normal extra-column path."""
    last = min(hr + sample, ws.max_row or hr)
    out: Dict[str, List[int]] = {}
    for c in range(1, maxc + 1):
        if c in used:
            continue
        if str(ws.cell(row=hr, column=c).value or "").strip():   # has a header -> handled elsewhere
            continue
        counts: Dict[str, int] = {}
        nonempty = 0
        for r in range(hr + 1, last + 1):
            v = ws.cell(row=r, column=c).value
            if v is None or str(v).strip() == "":
                continue
            nonempty += 1
            p = _url_platform(v)
            if p:
                counts[p] = counts.get(p, 0) + 1
        if not counts:
            continue
        p = max(counts, key=counts.get)
        if counts[p] / max(nonempty, 1) >= 0.5:
            out.setdefault(p, []).append(c)
    return out


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

        # Recover media links that sit in UNHEADERED columns (the owner's raw export
        # often drops instagram/youtube URLs into blank-header columns, which would
        # otherwise be lost). Detect them by value and append them as proper media
        # groups — but only for a platform not already present as a headered group.
        media_recovered: List[str] = []
        present_media = {k for _c, _h in extras if (k := _media_kw(_h))}
        used2 = mapped | {c for c, _h in extras}
        recovered = _detect_url_media_cols(ws, hr, maxc, used2)
        for platform in ("INSTAGRAM", "YOUTUBE"):
            cols = recovered.get(platform) or []
            if not cols or platform in present_media:
                continue
            for n, sc in enumerate(cols, start=1):
                extras.append((sc, platform + " 1" if n == 1 else str(n)))
                media_recovered.append(platform + " " + str(n))

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
            "media_recovered": media_recovered,
            "data_rows": len(data),
        }
    finally:
        wb.close()


# ---------------------------------------------------------------------------
# Media-preserving merge on re-upload
# ---------------------------------------------------------------------------
# When the owner re-uploads a fresh Excel, it replaces the whole live sheet. But
# photos/videos added through the Media panel live ONLY in the live sheet (their
# Supabase URLs are written into the EXTERIOR/VIDEO columns), and the owner's own
# file does not contain them — so a naive replace would wipe every photo for every
# car that is common to both files. `preserve_media_from_previous` carries that
# media forward: for each car matched by CAR NUMB, for each media group, if the NEW
# upload has no links in that group the PREVIOUS links are kept. New links always
# win when the owner provides them.

_MIN_SLOTS = {"INSTAGRAM": 6, "EXTERIOR": 6, "YOUTUBE": 6}   # others: only if data exists
_GROUP_ORDER = ["INSTAGRAM", "EXTERIOR", "INTERIOR", "VIDEO", "YOUTUBE"]


def _is_media_url(v: Any) -> bool:
    return v is not None and str(v).strip().lower().startswith(("http://", "https://"))


def _reg_key(v: Any) -> str:
    return "" if v is None else str(v).strip().upper().replace(" ", "")


def _classify_media_columns(ws) -> Tuple[Dict[str, List[int]], List[int]]:
    """For a canonical sheet (core at cols 1..N_CORE, header row 2), return
    ({group: [cols...]}, [non-media extra cols]) for everything past the core."""
    maxc = ws.max_column or 0
    headers = [(c, ws.cell(row=2, column=c).value) for c in range(1, maxc + 1)]
    media: Dict[str, List[int]] = {}
    nonmedia: List[int] = []
    i = 0
    while i < len(headers):
        c, h = headers[i]
        if c <= N_CORE:
            i += 1
            continue
        kw = _media_kw(h)
        if kw:
            cols = [c]
            j = i + 1
            while j < len(headers) and str(headers[j][1] or "").strip().isdigit():
                cols.append(headers[j][0])
                j += 1
            media.setdefault(kw, []).extend(cols)
            i = j
        else:
            nonmedia.append(c)
            i += 1
    return media, nonmedia


def _reg_media_map(ws, media_cols: Dict[str, List[int]]) -> Dict[str, Dict[str, List[str]]]:
    """{reg: {group: [urls...]}} for every data row (row 4+) with a real CAR NUMB."""
    out: Dict[str, Dict[str, List[str]]] = {}
    for r in range(4, (ws.max_row or 3) + 1):
        reg = _reg_key(ws.cell(row=r, column=CAR_NUMB_IDX + 1).value)
        if len(reg) < 6 or "E.G" in reg:
            continue
        gm: Dict[str, List[str]] = {}
        for group, cols in media_cols.items():
            urls = [str(ws.cell(row=r, column=c).value).strip()
                    for c in cols if _is_media_url(ws.cell(row=r, column=c).value)]
            if urls:
                gm[group] = urls
        out[reg] = gm
    return out


def _looks_canonical(ws) -> bool:
    return _ALIAS.get(_norm(ws.cell(row=2, column=CAR_NUMB_IDX + 1).value)) == CAR_NUMB_IDX


def preserve_media_from_previous(new_path: str, prev_path: str) -> Optional[Dict[str, Any]]:
    """Carry media forward from the previous live canonical workbook (`prev_path`)
    into the freshly-normalised new workbook (`new_path`), matched by CAR NUMB, and
    rewrite `new_path` in place. New media wins when present; otherwise the previous
    media is kept so Media-panel photos survive a re-upload. Returns a small report,
    or None (new file left untouched) if either file is missing/not canonical."""
    import openpyxl

    if not prev_path or not os.path.exists(prev_path):
        return None
    try:
        nwb = openpyxl.load_workbook(new_path, data_only=True)
    except Exception:
        return None
    pwb = None
    try:
        if "DNJ" not in nwb.sheetnames:
            return None
        nds = nwb["DNJ"]
        if not _looks_canonical(nds):
            return None
        try:
            pwb = openpyxl.load_workbook(prev_path, data_only=True)
        except Exception:
            return None
        if "DNJ" not in pwb.sheetnames:
            return None
        pds = pwb["DNJ"]
        if not _looks_canonical(pds):
            return None

        new_media_cols, nonmedia = _classify_media_columns(nds)
        prev_media_cols, _ = _classify_media_columns(pds)
        new_media = _reg_media_map(nds, new_media_cols)
        prev_media = _reg_media_map(pds, prev_media_cols)

        new_regs = list(new_media.keys())

        # groups to emit: the standard ones + any present in the new file + any that
        # a matched car carries forward from the previous file (e.g. VIDEO photos).
        groups = set(_MIN_SLOTS) | set(new_media_cols)
        for reg in new_regs:
            groups |= set(prev_media.get(reg, {}))
        final_groups = [g for g in _GROUP_ORDER if g in groups]

        # merged media per reg, and the slot count each group needs (no truncation).
        merged: Dict[str, Dict[str, List[str]]] = {}
        slots: Dict[str, int] = {g: _MIN_SLOTS.get(g, 0) for g in final_groups}
        carried = 0
        for reg in new_regs:
            nm = new_media.get(reg, {})
            pm = prev_media.get(reg, {})
            m: Dict[str, List[str]] = {}
            for g in final_groups:
                if nm.get(g):
                    m[g] = nm[g]
                elif pm.get(g):
                    m[g] = pm[g]
                    carried += 1
                else:
                    m[g] = []
                if len(m[g]) > slots[g]:
                    slots[g] = len(m[g])
            merged[reg] = m

        # column plan: core (1..N_CORE), non-media extras, then media groups
        col_specs: List[Tuple] = [("copy", c) for c in range(1, N_CORE + 1)]
        col_specs += [("copy", c) for c in nonmedia]
        for g in final_groups:
            for k in range(slots[g]):
                col_specs.append(("media", g, k))

        out = openpyxl.Workbook()
        od = out.active
        od.title = "DNJ"
        for oc, spec in enumerate(col_specs, start=1):
            if spec[0] == "copy":
                od.cell(row=2, column=oc, value=nds.cell(row=2, column=spec[1]).value)
                hint = nds.cell(row=3, column=spec[1]).value
                if hint is not None and str(hint).strip() != "":
                    od.cell(row=3, column=oc, value=hint)
            else:
                _, g, k = spec
                od.cell(row=2, column=oc, value=(g + " 1" if k == 0 else str(k + 1)))

        out_r = 4
        rows_out = 0
        for r in range(4, (nds.max_row or 3) + 1):
            core_vals = [nds.cell(row=r, column=c).value for c in range(1, N_CORE + 1)]
            reg = _reg_key(nds.cell(row=r, column=CAR_NUMB_IDX + 1).value)
            if all(v is None or str(v).strip() == "" for v in core_vals) and not reg:
                continue
            m = merged.get(reg, {})
            for oc, spec in enumerate(col_specs, start=1):
                if spec[0] == "copy":
                    v = nds.cell(row=r, column=spec[1]).value
                    if v is not None and str(v).strip() != "":
                        od.cell(row=out_r, column=oc, value=v)
                else:
                    _, g, k = spec
                    urls = m.get(g, [])
                    if k < len(urls):
                        od.cell(row=out_r, column=oc, value=urls[k])
            out_r += 1
            rows_out += 1

        # carry the DONT TOUCH SOLD sheet from the new workbook untouched
        if SOLD_SHEET in nwb.sheetnames:
            src = nwb[SOLD_SHEET]
            dst = out.create_sheet(SOLD_SHEET)
            for row in src.iter_rows():
                for cell in row:
                    if cell.value is not None:
                        dst.cell(row=cell.row, column=cell.column, value=cell.value)

        tmp = new_path + ".merge.xlsx"
        out.save(tmp)
        os.replace(tmp, new_path)
        matched = sum(1 for reg in new_regs if reg in prev_media)
        return {
            "rows_out": rows_out,
            "cars_matched_with_previous": matched,
            "media_groups_carried": carried,
            "slots": {g: slots[g] for g in final_groups},
        }
    finally:
        nwb.close()
        if pwb is not None:
            pwb.close()
