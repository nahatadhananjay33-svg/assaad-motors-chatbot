# Phase 8H — Step 1: Inventory & Media Schema Audit

**Generated:** 2026-06-23
**Source of truth audited:** `app/IVR_Sheet.xlsx`
**Inventory sheet:** `DNJ` (header row 2, descriptions row 3, **data from row 4**)

This document audits the inventory workbook **exactly as it is today** — the
columns the chatbot already reads, the media columns already present, and the
columns the Phase 8H management layer still needs. It does **not** change any
behaviour; it is the grounding for Step 2 (final schema).

---

## 1. Workbook sheets (as-is)

| Sheet              | Rows | Cols | Role |
|--------------------|------|------|------|
| `CTRL F`           | 196  | 51   | Working/scratch sheet |
| `DONT TOUCH SOLD`  | 237  | 23   | Legacy sold archive — **loader reads this** for sold reconciliation |
| `SALE `            | 160  | 22   | Working sheet |
| `IVR`              | 116  | 18   | IVR working sheet |
| `LOCATION`         | 202  | 16   | Parking-grid reference |
| `KEY`              | 199  | 16   | Code key reference |
| `Sheet1`           | 23   | 2    | Misc |
| **`DNJ`**          | 193  | 88   | **Inventory source of truth** — the only sheet the chatbot loads as live stock |

> The chatbot loads live cars from **`DNJ`** and treats a registration as *sold*
> if it appears in **`DONT TOUCH SOLD`** (or carries a `DDD`/`DDDD` rate code).
> See `app/inventory_system/inventory_loader.py`.

---

## 2. Core inventory columns — DNJ (A–Q, read by the chatbot)

These are normalized by `inventory_loader.py` and **must not change**.

| Col | Header (row 2) | Internal key   | Meaning |
|-----|----------------|----------------|---------|
| A   | (blank)        | stock_no       | Sequential stock number |
| B   | (blank)        | sr_no          | Serial number (weak duplicate of A) |
| C   | Company Name   | make           | Make code: `MARU`/`HYUN`/`HOND`/`MERCEDES`… |
| D   | MODEL          | model          | Dirty free text, normalized by loader |
| E   | (blank)        | year           | Manufacture year |
| F   | INS            | insurance      | Free-text insurance blob |
| G   | VARI           | variant        | Raw variant code |
| H   | F              | fuel           | `P`/`D`/`C`/`PC`/`E`… |
| I   | T              | transmission   | `A` / `M` |
| J   | O              | ownership      | Owner count |
| K   | KM             | km             | Kilometres driven |
| L   | COL            | color          | Colour code/word |
| M   | RATE           | rate           | Price **or** status code (`4`/`33`/`44`/`DDD`/`DDDD`) |
| N   | **CAR NUMB**   | car_numb       | **Full registration — the primary key** for inventory *and* media |
| O   | (blank)        | reg_last4      | Last 4 digits (redundant) |
| P   | LOC            | location       | Parking slot / custody word (internal only) |
| Q   | RTO            | rto            | RTO code |

---

## 3. Media columns — DNJ (already present, R–AZ)

Media URL slots already exist and are **already populated with live Supabase
public URLs** (31 URLs present at audit time). They are located by **header
text**, not fixed letters, by `media_loader_mapping.py` /
`app/media_sync/_poc.py:read_layout`.

| Range  | Header pattern        | Slots | Maps to `MediaType`     |
|--------|-----------------------|-------|-------------------------|
| R–AA   | `EXTERIOR 1` … `10`   | 10    | `EXTERIOR_PHOTO`        |
| AB–AK  | `INTERIOR 1` … `10`   | 10    | `INTERIOR_PHOTO`        |
| AL–AP  | `VIDEO 1` … `5`       | 5     | `VIDEO`                 |
| AQ–AU  | `INSTAGRAM 1` … `5`   | 5     | `INSTAGRAM`             |
| AV–AZ  | `YOUTUBE 1` … `5`     | 5     | `YOUTUBE`               |

**Observed live URL shape** (from row 5, `MH02EZ6001`):

```
https://hxjxqdufquowvpmucqmf.supabase.co/storage/v1/object/public/
        car-photos/MH02EZ6001/exterior/8408ad5abbe9d81ba457da92d0e4167f93101c9f.jpeg
        └── bucket ──┘ └── REG ──┘ └─type─┘ └──────── sha1 content hash ────────┘
```

So the **production bucket is `car-photos`** and the **per-vehicle folder key is
the registration (CAR NUMB)** — exactly the convention Phase 8H standardizes in
Step 3.

> **How the chatbot consumes media today:** `inventory_loader.load_inventory()`
> calls `media_loader_mapping.attach_media()`, which reads these per-slot columns
> into `InventoryItem.media`; `MediaService` then serves them. **This read path
> is frozen for Phase 8H — the management layer writes the same per-slot columns,
> so the chatbot keeps working with zero loader changes.**

---

## 4. Extended detail columns — DNJ (BB–CJ, Phase 7C/7D)

Already present and read by the loader (header-located). Not media; listed for
completeness so Step 2 inserts new columns without colliding.

`Price Range Low` (BB) · `Price Range High` (BC) · `Negotiable` (BD) ·
`Claimed Mileage` (BE) · `Insurance Type` (BF) · `Insurance Expiry` (BG) ·
`Zero Dep` (BH) · `Insurance Claim History` (BI) · `Accident Free` (BJ) ·
`Flood Damage` (BK) · `Repainted` (BL) · `Repaint Panels` (BM) ·
`Body Condition` (BN) · `Engine Condition` (BO) · `Interior Condition` (BP) ·
`Tyre Condition` (BQ) · `Brake Condition` (BR) · `Clutch Condition` (BS) ·
`Battery Condition` (BT) · `Service History Available` (BU) ·
`Last Service Date` (BV) · `Service Center Type` (BW) · `RC Status` (BX) ·
`Hypothecation Bank` (BY) · `Loan Closed` (BZ) · `NOC Available` (CA) ·
`Finance Eligible` (CB) · `Warranty Available` (CC) · `Warranty Expiry` (CD) ·
`Warranty Provider` (CE) · `Reason for Sale` (CF) · `Best Features` (CG) ·
`Known Issues` (CH) · `Photo Count` (CI) · `Video Count` (CJ)

**Free column:** `BA` (53) is empty — a gap between `YOUTUBE 5` (AZ/52) and
`Price Range Low` (BB/54). Available for a new management column if appended
inline is undesirable.

---

## 5. Gap analysis — what Phase 8H still needs

| Requested column (Step 2) | Present today? | Notes |
|---------------------------|:--------------:|-------|
| `STATUS`                  | ❌ **Missing** | No explicit AVAILABLE/RESERVED/SOLD column. Sold state is inferred only from the `DONT TOUCH SOLD` sheet / `DDD` codes. `media_cleanup.py` already *looks for* a `STATUS` column (`_STATUS_HEADERS`) but the sheet has none yet. |
| `PHOTO_URLS`              | ⚠️ Partial     | Photo URLs exist but spread across `EXTERIOR 1..10` / `INTERIOR 1..10` slots. No single consolidated cell. |
| `VIDEO_URLS`              | ⚠️ Partial     | URLs exist across `VIDEO 1..5`. No consolidated cell. |
| `YOUTUBE_URL`             | ⚠️ Partial     | URLs exist across `YOUTUBE 1..5`. No consolidated cell. |
| `INSTAGRAM_URL`           | ⚠️ Partial     | URLs exist across `INSTAGRAM 1..5`. No consolidated cell. |
| `MEDIA_FOLDER_ID`         | ❌ **Missing** | Implicitly the registration (CAR NUMB), but not written as an explicit, owner-visible cell. |
| `LAST_UPDATED`            | ❌ **Missing** | No per-row "media last changed" timestamp. |

### Other findings
- **No data loss risk in reading:** media columns are header-located, so adding
  new columns to the right does not shift the existing read logic.
- **Sold today is implicit**, not a first-class field. Phase 8H makes it explicit
  via `STATUS`, which also lets `media_cleanup.py` work as designed.
- **The owner currently has no single place** to see a car's media at a glance —
  it is fragmented across 30 slot columns. The consolidated `*_URLS` columns fix
  this for human readability (the chatbot keeps using the per-slot columns).

---

## 6. Conclusion

The workbook already has a rich, working media layer keyed by **CAR NUMB** and a
live Supabase bucket (`car-photos`) with one folder per vehicle. Phase 8H does
**not** redesign this. It adds **seven management columns** (`STATUS`,
`PHOTO_URLS`, `VIDEO_URLS`, `YOUTUBE_URL`, `INSTAGRAM_URL`, `MEDIA_FOLDER_ID`,
`LAST_UPDATED`) so the owner gets an explicit lifecycle field, a single-glance
media view, and an audit timestamp — while the chatbot's existing per-slot read
path stays byte-for-byte unchanged.

➡ Final schema design: `inventory_final_schema.md` (Step 2).
