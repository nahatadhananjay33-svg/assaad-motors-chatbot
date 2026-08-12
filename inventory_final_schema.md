# Phase 8H — Step 2: Final Excel Schema

**Generated:** 2026-06-23
**Sheet:** `DNJ` (header row 2, data from row 4) + new `SOLD_CARS` archive sheet
**Principle:** Excel stays the **source of truth**. Supabase is **media storage
only**. The chatbot's existing read path is **frozen** — all new columns are
**appended to the right** of the existing layout, located by header text.

---

## 1. Design rules

1. **Additive only.** Existing columns A–CJ keep their meaning, order, and the
   per-slot media columns the chatbot already reads. Nothing is moved or removed.
2. **Header-located.** New columns are found by header text (like the media
   columns), never by hard-coded letters — so future edits never silently shift.
3. **Per-slot columns remain the chatbot's media source.** The new consolidated
   `*_URLS` columns are an **owner-facing mirror** maintained automatically; the
   loader/MediaService are not changed and do not read them.
4. **`STATUS` becomes the single lifecycle field** driving the sold workflow and
   `media_cleanup.py`.

---

## 2. New management columns (appended after the existing block)

Existing data ends at `CJ` (col 88). The seven Phase 8H columns are appended at
`CK`–`CQ` (cols 89–95). They are discovered by exact header text.

| Col | Header           | Type      | Allowed values / format                         | Written by |
|-----|------------------|-----------|-------------------------------------------------|------------|
| CK  | `STATUS`         | Enum      | `AVAILABLE` · `RESERVED` · `SOLD`               | Owner (Excel) **or** Admin Panel (Mark Sold) |
| CL  | `PHOTO_URLS`     | Text      | Newline-joined photo public URLs (mirror)       | Media upload service (auto) |
| CM  | `VIDEO_URLS`     | Text      | Newline-joined video public URLs (mirror)       | Media upload service (auto) |
| CN  | `YOUTUBE_URL`    | Text      | Newline-joined YouTube links                    | Admin Panel (Add YouTube) |
| CO  | `INSTAGRAM_URL`  | Text      | Newline-joined Instagram links                  | Admin Panel (Add Instagram) |
| CP  | `MEDIA_FOLDER_ID`| Text      | Supabase folder key = the registration (CAR NUMB) | Media service (auto) |
| CQ  | `LAST_UPDATED`   | Timestamp | ISO-8601 UTC, set on every media/status change  | All write paths (auto) |

### Field semantics

- **`STATUS`** — default `AVAILABLE`. The owner can set `RESERVED` directly in
  Excel (chatbot still shows it; reserved cars are a soft hold). `SOLD` is set by
  the Mark-Sold workflow, which then **moves the row to `SOLD_CARS`** so the
  chatbot stops showing it. A blank `STATUS` is treated as `AVAILABLE`.
- **`PHOTO_URLS` / `VIDEO_URLS`** — a denormalized, newline-joined mirror of the
  per-slot `EXTERIOR/INTERIOR` and `VIDEO` columns, so the owner can see/copy a
  car's media from one cell. **The chatbot does not read these** — it reads the
  per-slot columns, which the service writes in lockstep.
- **`YOUTUBE_URL` / `INSTAGRAM_URL`** — owner-supplied links. Written to both the
  per-slot `YOUTUBE 1..5` / `INSTAGRAM 1..5` columns (chatbot source) **and**
  mirrored here for readability.
- **`MEDIA_FOLDER_ID`** — equals the registration (e.g. `MH02EZ6001`). Makes the
  Supabase folder explicit so the owner never has to think about storage paths.
- **`LAST_UPDATED`** — bumped on any media add or status change; powers the admin
  panel "Last updated" display and audit.

---

## 3. The `SOLD_CARS` archive sheet (new)

When a car is marked sold, its **entire DNJ row is moved** to a new `SOLD_CARS`
sheet (created on first use). This is distinct from the legacy
`DONT TOUCH SOLD` sheet (left untouched for back-compat).

`SOLD_CARS` layout:

- **Row 1:** a copy of the DNJ header row (same columns A–CQ) + two extra audit
  columns appended: `SOLD_AT` (ISO timestamp) and `SOLD_BY` (admin user).
- **Row 2+:** one moved row per sold car. `STATUS` is forced to `SOLD`; media
  URL cells are cleared (the files are deleted from Supabase by the workflow).

Because the row **leaves DNJ**, `load_inventory()` no longer sees it at all and
the vehicle disappears from the chatbot — no loader change required.

---

## 4. Full column map (final)

```
A   stock_no            (existing)
B   sr_no               (existing)
C   make                (existing)
D   model               (existing)
E   year                (existing)
F   insurance           (existing)
G   variant             (existing)
H   fuel                (existing)
I   transmission        (existing)
J   ownership           (existing)
K   km                  (existing)
L   color               (existing)
M   rate                (existing)
N   car_numb  ← KEY     (existing, primary key for inventory + media)
O   reg_last4           (existing)
P   location            (existing)
Q   rto                 (existing)
R–AA   EXTERIOR 1..10   (existing media — chatbot source)
AB–AK  INTERIOR 1..10   (existing media — chatbot source)
AL–AP  VIDEO 1..5       (existing media — chatbot source)
AQ–AU  INSTAGRAM 1..5   (existing media — chatbot source)
AV–AZ  YOUTUBE 1..5     (existing media — chatbot source)
BA      (free/spare)
BB–CJ  Phase 7C/7D detail columns (existing)
────────────────────────  Phase 8H additions  ────────────────────────
CK  STATUS              ★ new — lifecycle (AVAILABLE/RESERVED/SOLD)
CL  PHOTO_URLS          ★ new — consolidated photo mirror
CM  VIDEO_URLS          ★ new — consolidated video mirror
CN  YOUTUBE_URL         ★ new — YouTube links
CO  INSTAGRAM_URL       ★ new — Instagram links
CP  MEDIA_FOLDER_ID     ★ new — Supabase folder = registration
CQ  LAST_UPDATED        ★ new — ISO timestamp of last media/status change
```

---

## 5. Backward-compatibility guarantees

| Concern | Guarantee |
|---------|-----------|
| Chatbot inventory read | Unchanged — loads A–Q + detail columns exactly as today. |
| Chatbot media read | Unchanged — reads per-slot `EXTERIOR/INTERIOR/VIDEO/INSTAGRAM/YOUTUBE` columns. |
| Column drift | New columns are header-located; existing media detection already tolerates rightward shifts. |
| Old files (no new columns) | The management layer treats missing columns as blank and **creates them on first write** — never errors. |
| `media_cleanup.py` | Now finds the real `STATUS` column it was already coded to look for. |

---

## 6. Owner mental model (what changes for the owner)

Before: open Excel, edit cars; media is uploaded by a separate folder-sync; sold
cars are hand-moved to `DONT TOUCH SOLD`.

After: open Excel and edit cars **the same way**, but now there is a clear
`STATUS` column, a one-cell view of each car's media, and a Last-Updated stamp.
For media and sold actions the owner uses the **Admin Panel** (Step 6) — never
Supabase, never URL copy-paste.

➡ Storage layout: `supabase_media_architecture.md` (Step 3).
