"""
phase12b_migrate.py
===================

Phase 12B migration / readiness utility.  READ-ONLY — it never modifies the live
Excel (backward compatible).  Because standard specs are merged at LOAD time from
the model_specs library, there is no destructive data migration to run; this tool
instead:

  1. reports model_specs COVERAGE across the live inventory,
  2. shows how many spec fields get auto-filled per car,
  3. audits which new grouped columns are PRESENT vs ABSENT in the Excel (so the
     dealership knows exactly which optional columns to add later, in Phase 12C),
  4. (optional) writes a *separate* blank column-template xlsx — never the live file.

Run:  python phase12b_migrate.py            # report only
      python phase12b_migrate.py --template # also write phase12b_column_template.xlsx
"""

from __future__ import annotations

import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import inventory_loader as L
import model_specs as ms

XLSX = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")


def report() -> dict:
    items = L.load_inventory(XLSX)
    total = len(items)

    # 1–2. spec coverage
    matched, filled_counts, unmatched_models = 0, [], {}
    for it in items:
        cov = ms.coverage_for(it)
        if cov["known"]:
            matched += 1
            filled_counts.append(cov["fillable"])
        else:
            key = f"{it.make_full} {it.model}"
            unmatched_models[key] = unmatched_models.get(key, 0) + 1
    avg_filled = round(sum(filled_counts) / len(filled_counts), 1) if filled_counts else 0

    # 3. column presence audit (header-located)
    present = L._load_ext_col_map(XLSX, L.DNJ_SHEET)   # {field: col_idx}
    new_fields = [f for f, _h, _k in L._NEW_EXT_FIELDS]
    present_new = [f for f in new_fields if f in present]
    absent_new = [f for f in new_fields if f not in present]

    print("=" * 68)
    print("PHASE 12B — MIGRATION / READINESS REPORT")
    print("=" * 68)
    print(f"Inventory rows loaded          : {total}")
    print(f"Matched to model_specs library : {matched} ({100*matched//total}%)")
    print(f"Avg spec fields auto-filled/car: {avg_filled}")
    print(f"Known models in library        : {len(ms.known_models())}")
    print()
    print(f"New grouped columns PRESENT in Excel : {len(present_new)}/{len(new_fields)}")
    print(f"New grouped columns ABSENT  in Excel : {len(absent_new)}")
    print("  (absent = optional; specs still auto-fill, dealership fields stay "
          "'Data not available' until the column is added in Phase 12C)")
    print()
    if unmatched_models:
        print("Models NOT yet in the spec library (add to model_specs.py):")
        for m, n in sorted(unmatched_models.items(), key=lambda x: -x[1]):
            print(f"  {n:2d}  {m}")
    print()
    print("Backward compatibility: live Excel UNCHANGED. Loader is header-located,")
    print("so absent columns are a no-op. Existing columns read exactly as before.")
    return {"total": total, "matched": matched, "avg_filled": avg_filled,
            "present_new": present_new, "absent_new": absent_new,
            "unmatched_models": unmatched_models}


def write_template(path: str = None) -> str:
    """Write a SEPARATE blank xlsx listing every recommended new column header —
    never touches the live sheet. For the dealership to copy columns from."""
    import openpyxl
    path = path or os.path.join(os.path.dirname(__file__), "phase12b_column_template.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "NEW_COLUMNS_TEMPLATE"
    headers = ["Existing key columns → keep as-is (A–Q + media)"] + \
              [h for _f, h, _k in L._NEW_EXT_FIELDS]
    ws.append(headers)
    wb.save(path)
    return path


if __name__ == "__main__":
    report()
    if "--template" in sys.argv:
        p = write_template()
        print(f"\nTemplate written (separate file, live sheet untouched): {p}")
