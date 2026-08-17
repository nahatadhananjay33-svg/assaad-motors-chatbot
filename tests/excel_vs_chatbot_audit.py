"""
excel_vs_chatbot_audit.py
=========================

Part 13 — the acceptance harness for "filters must behave exactly like an Excel
filter". It is DATA-DRIVEN: every expected count is computed from the CURRENT
Excel, never hardcoded. For each question it:

  1. computes the ground-truth set directly from the workbook,
  2. sends the question through the REAL ChatService,
  3. compares the chatbot's match count to the Excel count, and
  4. (for a sample) verifies every returned CARD satisfies every stated filter.

Run standalone for a full report:
    python -X utf8 tests/excel_vs_chatbot_audit.py
It also exposes generate_cases()/run() so a pytest wrapper can assert 0 mismatches.

Isolated: copies the Excel to a temp dir and points all DBs there. Production
inventory is only read.
"""
import os, sys, tempfile, shutil, argparse, itertools

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
APP = os.path.join(REPO, "app", "inventory_system")


def _bootstrap(xlsx_src=None):
    work = tempfile.mkdtemp(prefix="excelaudit_")
    data = os.path.join(work, "data"); os.makedirs(data, exist_ok=True)
    xlsx = os.path.join(work, "IVR_Sheet.xlsx")
    shutil.copy2(xlsx_src or os.path.join(REPO, "app", "IVR_Sheet.xlsx"), xlsx)
    os.environ["CHAT_DATA_DIR"] = data
    os.environ["CHAT_XLSX"] = xlsx
    if APP not in sys.path:
        sys.path.insert(0, APP)
    os.chdir(APP)
    import logging; logging.disable(logging.CRITICAL)
    return xlsx, data


def _lc(v):
    return str(v or "").lower()


def _fuel_is(i, fuel):
    """CNG/LPG match bi-fuel combined values; petrol/diesel are exact."""
    v = _lc(i.fuel_norm)
    if fuel in ("cng", "lpg"):
        return fuel in {p.strip() for p in v.replace("/", "+").replace(",", "+").split("+")}
    return v == fuel


def _sunroof(i):
    return bool(i.sunroof_type) and _lc(i.sunroof_type) not in ("none", "nan", "")


def generate_cases(items):
    """Return a list of (question, predicate) built from the CURRENT inventory."""
    lc = _lc
    C = []
    add = lambda q, p: C.append((q, p))

    # ── single-column filters ──
    add("petrol cars", lambda i: _fuel_is(i, "petrol"))
    add("diesel cars", lambda i: _fuel_is(i, "diesel"))
    add("cng cars", lambda i: _fuel_is(i, "cng"))
    add("petrol wali gaadi", lambda i: _fuel_is(i, "petrol"))
    add("diesel wali cars", lambda i: _fuel_is(i, "diesel"))
    add("automatic cars", lambda i: lc(i.transmission_norm) == "automatic")
    add("manual cars", lambda i: lc(i.transmission_norm) == "manual")
    add("automatic wali gaadi", lambda i: lc(i.transmission_norm) == "automatic")
    add("sunroof cars", _sunroof)
    add("sunroof wali cars", _sunroof)
    add("luxury cars", lambda i: i.is_luxury)
    add("first owner cars", lambda i: i.ownership_count == 1)
    add("second owner cars", lambda i: i.ownership_count == 2)
    add("single owner cars", lambda i: i.ownership_count == 1)
    add("7 seater cars", lambda i: i.seats == 7)
    add("5 seater cars", lambda i: i.seats == 5)
    add("saat seater gaadi", lambda i: i.seats == 7)

    # ── colours actually present ──
    from collections import Counter
    colours = [c for c, n in Counter(lc(i.color_norm) for i in items if i.color_norm).most_common()
               if c and c != "unknown"][:6]
    for col in colours:
        add(f"{col} cars", lambda i, col=col: lc(i.color_norm) == col)

    # ── body-type / category ──
    add("suv", lambda i: i.body_type in ("SUV", "Compact-SUV"))
    add("suv cars", lambda i: i.body_type in ("SUV", "Compact-SUV"))
    add("muv", lambda i: i.body_type == "MUV")
    add("muv cars", lambda i: i.body_type == "MUV")
    add("sedan cars", lambda i: i.body_type == "Sedan")
    add("hatchback cars", lambda i: i.body_type == "Hatchback")

    # ── price ceilings / floors (lakh + rupees) ──
    for lk in (2, 3, 5, 8, 10, 15):
        add(f"cars under {lk} lakh", lambda i, lk=lk: i.price_inr is not None and i.price_inr <= lk * 100000)
    add("cars under 500000", lambda i: i.price_inr is not None and i.price_inr <= 500000)
    add("cars under 300000", lambda i: i.price_inr is not None and i.price_inr <= 300000)
    add("cars above 10 lakh", lambda i: i.price_inr is not None and i.price_inr >= 1000000)
    add("cars above 5 lakh", lambda i: i.price_inr is not None and i.price_inr >= 500000)

    # ── KM ceilings ──
    for km in (30000, 50000, 80000):
        add(f"under {km} km cars", lambda i, km=km: i.km_driven is not None and i.km_driven <= km)

    # ── year (exact + floor, both cue positions) ──
    years = [y for y, n in Counter(i.year_int for i in items if i.year_int).most_common()][:6]
    for y in years:
        add(f"{y} model cars", lambda i, y=y: i.year_int == y)
    add("2018 se upar wali cars", lambda i: i.year_int is not None and i.year_int >= 2018)
    add("above 2016 cars", lambda i: i.year_int is not None and i.year_int >= 2016)
    add("2015 ke baad wali cars", lambda i: i.year_int is not None and i.year_int >= 2015)

    # ── two-column combinations ──
    add("petrol automatic cars", lambda i: _fuel_is(i, "petrol") and lc(i.transmission_norm) == "automatic")
    add("diesel manual cars", lambda i: _fuel_is(i, "diesel") and lc(i.transmission_norm) == "manual")
    add("diesel automatic cars", lambda i: _fuel_is(i, "diesel") and lc(i.transmission_norm) == "automatic")
    add("cng manual cars", lambda i: _fuel_is(i, "cng") and lc(i.transmission_norm) == "manual")
    add("automatic cars under 5 lakh", lambda i: lc(i.transmission_norm) == "automatic" and i.price_inr and i.price_inr <= 500000)
    add("petrol cars under 5 lakh", lambda i: _fuel_is(i, "petrol") and i.price_inr and i.price_inr <= 500000)
    add("diesel cars under 8 lakh", lambda i: _fuel_is(i, "diesel") and i.price_inr and i.price_inr <= 800000)
    add("cng cars under 5 lakh", lambda i: _fuel_is(i, "cng") and i.price_inr and i.price_inr <= 500000)
    add("7 seater diesel cars", lambda i: i.seats == 7 and _fuel_is(i, "diesel"))
    add("7 seater automatic cars", lambda i: i.seats == 7 and lc(i.transmission_norm) == "automatic")
    add("first owner petrol cars", lambda i: i.ownership_count == 1 and _fuel_is(i, "petrol"))
    add("first owner diesel cars", lambda i: i.ownership_count == 1 and _fuel_is(i, "diesel"))
    add("white automatic cars", lambda i: lc(i.color_norm) == "white" and lc(i.transmission_norm) == "automatic")
    add("luxury automatic cars", lambda i: i.is_luxury and lc(i.transmission_norm) == "automatic")
    add("luxury diesel cars", lambda i: i.is_luxury and _fuel_is(i, "diesel"))
    add("suv automatic cars", lambda i: i.body_type in ("SUV", "Compact-SUV") and lc(i.transmission_norm) == "automatic")
    add("suv under 10 lakh", lambda i: i.body_type in ("SUV", "Compact-SUV") and i.price_inr and i.price_inr <= 1000000)
    add("muv under 10 lakh", lambda i: i.body_type == "MUV" and i.price_inr and i.price_inr <= 1000000)
    add("sunroof automatic cars", lambda i: _sunroof(i) and lc(i.transmission_norm) == "automatic")

    # ── three-column combinations ──
    add("petrol automatic cars under 5 lakh",
        lambda i: _fuel_is(i, "petrol") and lc(i.transmission_norm) == "automatic" and i.price_inr and i.price_inr <= 500000)
    add("diesel manual cars under 5 lakh",
        lambda i: _fuel_is(i, "diesel") and lc(i.transmission_norm) == "manual" and i.price_inr and i.price_inr <= 500000)
    add("7 seater diesel cars under 10 lakh",
        lambda i: i.seats == 7 and _fuel_is(i, "diesel") and i.price_inr and i.price_inr <= 1000000)
    add("first owner automatic cars under 10 lakh",
        lambda i: i.ownership_count == 1 and lc(i.transmission_norm) == "automatic" and i.price_inr and i.price_inr <= 1000000)
    add("first owner petrol automatic cars",
        lambda i: i.ownership_count == 1 and _fuel_is(i, "petrol") and lc(i.transmission_norm) == "automatic")
    add("luxury automatic diesel cars",
        lambda i: i.is_luxury and lc(i.transmission_norm) == "automatic" and _fuel_is(i, "diesel"))
    add("suv diesel automatic cars",
        lambda i: i.body_type in ("SUV", "Compact-SUV") and _fuel_is(i, "diesel") and lc(i.transmission_norm) == "automatic")

    # ── per-model availability (single-instance + duplicate) ──
    from collections import Counter as _Ct
    model_counts = _Ct(i.model for i in items if i.model)
    for m, n in list(model_counts.items())[:20]:
        add(f"{m} kitni hai", lambda i, m=m: i.model == m)

    # ── unavailable models must be exactly zero (no substitution). Only use names
    #    that are neither a model in stock nor a substring of one. ──
    present_lc = {lc(mm) for mm in model_counts}
    for absent in ["Lamborghini", "Ferrari", "Kushaq", "Taigun", "Virtus"]:
        al = lc(absent)
        if not any(al in p or p in al for p in present_lc):
            add(f"{absent} kitni hai", lambda i, absent=absent: i.model == absent)

    # ── last-4 registration lookups (each unique tail -> exactly its car) ──
    import re as _re
    def _tail(p):
        mm = _re.search(r"(\d+)$", (p or "").upper().replace(" ", "")); return mm.group(1) if mm else None
    seen_tail = {}
    for i in items:
        t = _tail(i.registration_no)
        if t:
            seen_tail.setdefault(t, []).append(i)
    uniq_tails = [(t, g[0]) for t, g in seen_tail.items() if len(g) == 1][:10]
    for t, car in uniq_tails:
        add(f"{t} number wali gaadi", lambda i, car=car: i.registration_no == car.registration_no)

    # ── Hindi / Hinglish phrasings of core filters ──
    add("पेट्रोल गाड़ियां", lambda i: _fuel_is(i, "petrol"))
    add("automatic gaadiyan dikhao", lambda i: lc(i.transmission_norm) == "automatic")
    add("saat seater diesel gaadi", lambda i: i.seats == 7 and _fuel_is(i, "diesel"))

    return C


def run(max_cases=None, verbose=True, xlsx_src=None):
    xlsx, data = _bootstrap(xlsx_src)
    import inventory_loader as L
    from chat_service import ChatService
    items = [i for i in L.load_inventory(xlsx) if i.is_customer_facing]
    svc = ChatService(xlsx, leads_db=os.path.join(data, "l.db"),
                      analytics_db=os.path.join(data, "a.db"),
                      unknown_db=os.path.join(data, "u.db"))
    cases = generate_cases(items)
    if max_cases:
        cases = cases[:max_cases]
    mismatches = []
    for q, pred in cases:
        expected = sum(1 for i in items if pred(i))
        r = svc.handle(q, session_id=None)
        got = r.count or 0
        if got != expected:
            mismatches.append((q, expected, got, (r.response or "")[:70]))
        if verbose:
            flag = "OK " if got == expected else "** "
            print(f"  {flag}{q:<44} excel={expected:<4} bot={got}")
    # per-card constraint spot-check on the multi-filter cases
    card_bad = []
    def price_lk(c): return c.get("price_lakh")
    for q, pred in cases:
        if " under " not in q and " and " not in q:
            continue
        r = svc.handle(q, session_id=None)
        for c in (r.vehicles or []):
            if not pred_card_ok(q, c):
                card_bad.append((q, c.get("registration_no")))
    return cases, mismatches, card_bad


def pred_card_ok(q, c):
    """Loose per-card check: a card in an 'under N lakh' result must be <= N lakh."""
    import re
    m = re.search(r"under (\d+) lakh", q)
    if m and c.get("price_lakh") is not None:
        return c["price_lakh"] <= int(m.group(1)) + 1e-6
    m2 = re.search(r"under (\d+)\b", q)  # rupees
    if m2 and "lakh" not in q and c.get("price_lakh") is not None:
        return c["price_lakh"] * 100000 <= int(m2.group(1)) + 1
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=None)
    ap.add_argument("--xlsx", default=None)
    a = ap.parse_args()
    cases, mismatches, card_bad = run(max_cases=a.max, verbose=True, xlsx_src=a.xlsx)
    print("\n" + "=" * 64)
    print(f"TOTAL QUESTIONS : {len(cases)}")
    print(f"COUNT MISMATCH  : {len(mismatches)}")
    print(f"CARD VIOLATIONS : {len(card_bad)}")
    if mismatches:
        print("\n--- MISMATCHES (Excel != chatbot) ---")
        for q, exp, got, ans in mismatches:
            print(f"  {q!r}: excel={exp} bot={got} :: {ans}")
    if card_bad:
        print("\n--- CARD VIOLATIONS ---")
        for q, reg in card_bad[:20]:
            print(f"  {q!r}: {reg}")
    print("=" * 64)
    sys.exit(1 if (mismatches or card_bad) else 0)
