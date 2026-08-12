# Phase 12B — Migration Report

Utility: `app/inventory_system/phase12b_migrate.py` (READ-ONLY — never modifies the
live Excel). Because standard specs are merged at **load time**, there is **no
destructive data migration**: existing data is untouched and specs are layered on
in-memory where fields are empty.

## Live inventory readiness (IVR_Sheet.xlsx / DNJ)

| Metric | Value |
|---|---|
| Inventory rows loaded | **45** |
| Matched to model_specs library | **37 (82%)** |
| Avg standard-spec fields auto-filled / matched car | **12.8** |
| Known models in library | **30** |
| New grouped columns present in Excel | 0 / 68 (optional) |
| New grouped columns absent | 68 (no-op until added) |

## What "migration" means here

1. **Specs:** no migration needed — auto-filled at load from `model_specs`.
2. **New dealership columns (docs-extra, keys, EV, usage, condition-extra):**
   optional. The loader locates them by header text; until the dealership adds a
   column, that field reads "Data not available". Adding a column later requires
   **no code change** (header-located).
3. **Existing columns (A–Q + media):** read exactly as before — **unchanged**.

## Models not yet in the spec library (safe to add later)

| Count | Model |
|---|---|
| 2 | Mercedes-Benz C Class |
| 1 | Jeep "Litiva" (likely a data typo) |
| 1 | (missing make) Innova |
| 1 | Audi A4 |
| 1 | Toyota Corolla (plain) |
| 1 | Mercedes-Benz E 200 |
| 1 | (blank row / no make+model) |

These return "Data not available" (no fabrication) until seeded.

## Optional column template

`python phase12b_migrate.py --template` writes a **separate** `phase12b_column_template.xlsx`
listing every recommended new header — the live sheet is never touched. The
dealership can copy the columns it wants into the DNJ sheet (Phase 12C surfaces
them in the owner panel).

## Backward compatibility statement

- Live `IVR_Sheet.xlsx` **not modified**.
- Loader remains header-located; absent columns are no-ops.
- Existing 500-test suite behaviour preserved (see regression report).
