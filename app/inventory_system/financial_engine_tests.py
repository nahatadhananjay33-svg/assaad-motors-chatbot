"""
financial_engine_tests.py — unit tests for the Assad Motors Financial engine.

Builds a tiny synthetic DNJ workbook (two header rows, data from row 4, financial
columns AC..AN at indices 28..39) and asserts the deterministic behaviour.
Run:  pytest -q financial_engine_tests.py
"""

import datetime as dt

import openpyxl
import pytest

import financial_engine as FE


# column index -> cell value, for one data row
def _row(car, year, make, model, rate, loc, pdate, days, investor, seller,
         pprice, appid, exp, total, addexp, gp, yld):
    r = [None] * 40
    r[2], r[3], r[4] = make, model, year
    r[12], r[13], r[15] = rate, car, loc
    r[28], r[30] = pdate, days
    r[31], r[32], r[33] = investor, seller, pprice
    r[34], r[35], r[36], r[37], r[38], r[39] = appid, exp, total, addexp, gp, yld
    return r


@pytest.fixture
def workbook(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "DNJ"
    ws.append(["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""])  # row1
    ws.append(["Stock", "Sr", "Make", "Model", "Year"])                          # row2
    ws.append(["code"])                                                          # row3 (example)
    # row4+  (car, year, make, model, rate, loc, pdate, days, inv, seller,
    #         pprice, appid, exp, total, addexp, gp, yield)
    rows = [
        _row("MH01AA1111", 2015, "MARU", "Eeco", 295000, "L",
             dt.datetime(2025, 5, 1), 540, "WD", "CARS 24",
             250000, "APP1", 70000, 359210, 30000, -64210, -0.98),
        _row("MH02BB2222", 2019, "TOYO", "Crysta", 1650000, "Z1",
             dt.datetime(2026, 8, 1), 90, "WD ", "CARS24",
             1100000, "APP2", 100000, 1233670, 0, 416330, 15.58),
        _row("MH03CC3333", 2016, "HOND", "City", 33, "H",
             dt.datetime(2026, 9, 1), 46326, "SW", "DIRECT",   # garbage days -> recompute
             300000, "APP3", 20000, 330000, 0, 70000, 8.0),
        _row("MH04DD4444", 2014, "HYUN", "Verna", 499000, "Z3",
             dt.datetime(2026, 6, 1), 150, "DNJ", "AARTI",
             380000, "APP4", 40000, 420000, 0, 79000, 3.2),
    ]
    for r in rows:
        ws.append(r)
    p = tmp_path / "fin.xlsx"
    wb.save(str(p))
    return str(p)


@pytest.fixture
def eng(workbook):
    return FE.FinancialEngine.load(workbook, today=dt.date(2026, 11, 1))


# ── parsing ──
def test_money_parsing():
    assert FE.parse_money("2,84,180") == 284180
    assert FE.parse_money("₹75000") == 75000
    assert FE.parse_money(419951.0) == 419951
    assert FE.parse_money("") is None
    assert FE.parse_money(None) is None


def test_date_parsing():
    assert FE.parse_date("9/11/25") == dt.date(2025, 11, 9)
    assert FE.parse_date(dt.datetime(2026, 5, 23)) == dt.date(2026, 5, 23)
    assert FE.parse_date("") is None


def test_group_normalisation():
    assert FE._norm_group("WD ") == FE._norm_group("WD") == "WD"
    assert FE._norm_group("CARS 24") == FE._norm_group("CARS24") == "CARS24"


# ── loading / records ──
def test_loads_all_rows(eng):
    assert len(eng.records) == 4


def test_sale_value_is_total_plus_gross(eng):
    car = eng.car("MH01AA1111")
    assert car.total_cost == 359210
    assert car.gross_profit == -64210
    assert car.sale_value == 295000           # 359210 + (-64210)


def test_sold_detection_rate_33(eng):
    assert eng.car("MH03CC3333").sold is True   # rate == 33
    assert eng.car("MH01AA1111").sold is False


def test_garbage_days_recomputed_from_purchase(eng):
    # row had days=46326 (a leaked serial); purchase 2026-09-01, today 2026-11-01
    assert eng.car("MH03CC3333").days_in_house == (dt.date(2026, 11, 1) - dt.date(2026, 9, 1)).days


# ── summary ──
def test_total_summary(eng):
    s = eng.total_summary()
    assert s["total_cars"] == 4
    assert s["sold_undelivered_count"] == 1      # the rate-33 car
    assert s["for_sale_count"] == 3
    # cost of for-sale = 359210 + 1233670 + 420000
    assert s["total_cost_for_sale"] == 359210 + 1233670 + 420000


# ── buyers / sellers grouping ──
def test_buyer_grouping_merges_whitespace(eng):
    buyers = {b["key"]: b for b in eng.buyers()}
    assert buyers["WD"]["count"] == 2            # "WD" + "WD " merged
    bb = eng.by_buyer("WD")
    assert bb["count"] == 2
    assert bb["total_investment"] == 359210 + 1233670
    # costliest first
    assert bb["cars"][0].car_numb == "MH02BB2222"


def test_seller_grouping_merges_whitespace(eng):
    sellers = {s["key"]: s for s in eng.sellers()}
    assert sellers["CARS24"]["count"] == 2       # "CARS 24" + "CARS24"


# ── car days ──
def test_car_days_cutoff_and_sort(eng):
    recs = eng.car_days("31/12/25")              # only cars purchased on/before 2025-12-31
    assert [r.car_numb for r in recs] == ["MH01AA1111"]
    allc = eng.car_days("ALL")
    assert len(allc) == 4
    # ALL sorted days desc: the 540-day car first
    assert allc[0].car_numb == "MH01AA1111"


# ── pey buckets ──
def test_pey_under_includes_negative(eng):
    under1 = eng.pey("under:1")
    regs = {r.car_numb for r in under1}
    assert "MH01AA1111" in regs                  # yield -0.98 < 1
    assert "MH04DD4444" not in regs              # yield 3.2 not < 1


def test_pey_range(eng):
    r = eng.pey("range:6:10")
    assert [c.car_numb for c in r] == ["MH03CC3333"]   # yield 8.0


# ── profit / loss ──
def test_profit_sorted_by_yield_desc(eng):
    p = eng.profit()
    assert p[0].car_numb == "MH02BB2222"         # yield 15.58 highest


def test_loss_only_negative_and_sorted(eng):
    l = eng.loss()
    assert [r.car_numb for r in l] == ["MH01AA1111"]   # only negative gross profit


def test_stock_excludes_sold(eng):
    regs = {r.car_numb for r in eng.stock()}
    assert "MH03CC3333" not in regs              # sold (rate 33)
    assert len(regs) == 3
