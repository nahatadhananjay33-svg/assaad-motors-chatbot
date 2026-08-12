# PHASE 7O.3 — Photo / Video Experience Improvement Report

**Date:** 2026-06-19
**Scope:** Photo / Video reply experience ONLY. No LLM, no new dependencies, no
DB / schema changes. **No Astor-fix change, no Marathi, no Low-KM, no website, no
Excel structure, no inventory-loader change.**

---

## Problem

When a vehicle was already selected, a media request still produced a **generic
response** (the long availability boilerplate) instead of a direct, crisp media
answer:

```
Customer: Innova
Customer: photo bhejo
Bot (before): Haan, 2017 White Innova available hai. aap aaj aa ke dekh lo —
              Vasant Oasis Car Parking, Andheri East …            ❌ (generic)
Bot (after) : 2017 White Innova ke photos available hain.          ✅ (crisp, direct)
```
```
Customer: video bhejo
Bot (after) : 2017 White Innova ka video available hai.            ✅
```

The media payload (URLs) was already attached — only the **reply text** was
generic, creating friction.

---

## Fix (minimal)

All changes are in `chat_service.py`, inside the existing media block; the media
resolution (`media_service.get_media`) and inventory logic were **not** touched.

- Three short, deterministic reply maps (`_MEDIA_OK_RESP`,
  `_MEDIA_UNAVAIL_RESP`, `_MEDIA_CLARIFY_RESP`) keyed by media intent
  (photo / video / instagram / youtube).
- When a media request resolves to a **single identified vehicle**
  (`status == ok`) the bot now answers directly — `"<vehicle> ke photos available
  hain."` / `"<vehicle> ka video available hai."` — and **never re-asks** the
  vehicle name. The single vehicle is supplied by the existing Phase-7I.2
  follow-up memory, which already appends the selected car to the message.
- Identified single vehicle but no asset on file (`status == media_unavailable`)
  → a crisp `"<vehicle> ke photos abhi available nahi — visit pe dikha denge."`
  (still no re-ask).
- No vehicle in context (`status == vehicle_not_identified`) → a crisp,
  media-aware clarification `"Kaunsi gaadi ke photos chahiye?"` /
  `"Kaunsi gaadi ka video chahiye?"`.
- Multiple cars match the context (`status == multiple_matches`) → the existing
  numbered candidate list is kept (a clarification that also lets the customer
  pick by number / year / reg).

A module flag `MEDIA_CRISP_REPLIES` (default **True**) gates the new wording; it
is flipped to `False` only by the A/B validation harness to reproduce the exact
pre-7O.3 responses. Nothing else depends on it.

### The four required cases

| Case | Situation | Example | Result |
|---|---|---|---|
| **1** | One vehicle selected | `Innova` → `photo bhejo` | `2017 White Innova ke photos available hain.` (direct) ✓ |
| **2** | One vehicle selected | `video bhejo` | `2017 White Innova ka video available hai.` (direct) ✓ |
| **3** | Multiple vehicles in context | `Nexon` (2 cars) → `photo bhejo` | numbered clarification ("…Number, year, ya reg number bata do.") ✓ |
| **4** | No vehicle selected | `photo bhejo` | `Kaunsi gaadi ke photos chahiye?` ✓ |

---

## VALIDATION

Replayed the **real pilot conversation log** (`data/pilot_query_log.db`) — every
conversation containing at least one photo or video request — **in order**, with
conversation context preserved (one session per conversation). Before vs after is
the `MEDIA_CRISP_REPLIES` toggle; nothing else differs. Read-only on the pilot
log; isolated temp DBs.

**Dataset: 1,965 media conversations — 1,810 photo requests + 576 video
requests** (well above the 100 + 100 minimum).

Classification per request turn:
- **direct** — vehicle identified, no re-ask (`status` ok / media_unavailable).
- **crisp direct** — direct **and** the reply is the short, vehicle-named media
  line (not the long generic boilerplate).
- **clarification** — bot re-asked the vehicle (`status` multiple_matches /
  vehicle_not_identified).

### Photo requests

| Metric | Before | After |
|---|--:|--:|
| Photo Requests (total) | 1,810 | 1,810 |
| Served directly (vehicle identified, no re-ask) | 626 | 626 |
| **Crisp direct reply** | **0** | **626** |
| **Clarification Count** | **1,108** | **1,108** |

### Video requests

| Metric | Before | After |
|---|--:|--:|
| Video Requests (total) | 576 | 576 |
| Served directly (vehicle identified, no re-ask) | 171 | 171 |
| **Crisp direct reply** | **0** | **171** |
| **Clarification Count** | **371** | **371** |

### Reading the numbers

- **Crisp direct replies: 0 → 797** (626 photo + 171 video). Every media request
  where a single vehicle was selected now gets a short, direct, vehicle-named
  answer instead of the generic availability boilerplate. **This is the fix.**
- **Clarification Count is unchanged** (photo 1,108 = 1,108; video 371 = 371).
  The fix did **not** introduce any new clarifications and did **not** remove any
  legitimate one — the requests that clarify are exactly the ambiguous (multiple
  cars in context) and no-vehicle cases (Cases 3 & 4), which *should* clarify.
  Their wording is now crisper and media-aware, but the count is identical.
- **Media delivery is unchanged** — "served directly" is identical before/after
  (626 photo, 171 video); only the reply text became crisp.

---

## REGRESSION TESTS

Command: `python -m pytest *_tests.py -q`

| Run | Result |
|---|---|
| **tests_before** (post-Astor baseline, this session) | **380 passed, 1 failed** |
| **tests_after** (Phase 7O.3) | **380 passed, 1 failed** |

**Any Regressions: None (0 new failures).**

The single failure is **pre-existing and unrelated**:
`hardening_tests.py::TestInventoryRefresh::test_refresh_returns_ok_and_count`
asserts a hard-coded inventory count of 40 while the current `IVR_Sheet.xlsx`
holds 44 cars (data drift) — identical before and after this change, and the same
failure documented in the Phase-7L.2 and Phase-7O.2 reports.

---

## SUCCESS CRITERIA

| Criterion | Result |
|---|---|
| Vehicle selected → photo/video works immediately | ✓ 797/797 single-vehicle requests answered directly & crisply |
| No unnecessary clarification | ✓ clarification count unchanged; only genuinely ambiguous / no-vehicle cases clarify |
| Responses short and crisp | ✓ one-line, vehicle-named replies |
| No regressions | ✓ 0 new test failures |
| Only Photo / Video improved | ✓ Astor fix, Marathi, Low-KM, website, Excel, inventory-loader untouched |

---

## Files changed / added

- **Changed:** `app/inventory_system/chat_service.py` — three media reply maps,
  the `MEDIA_CRISP_REPLIES` flag, and the crisp-reply branches in the media block
  (one `STATUS_MEDIA_UNAVAILABLE` import added).
- **Added (validation harness, not shipped to the bot):**
  `app/inventory_system/media_experience_audit.py`,
  `app/inventory_system/media_experience_audit_result.json`.
- **Added (this report):** `media_experience_report.md`.

No changes to the Astor fix, Marathi logic, Low-KM logic, website, Excel
structure, or the inventory loader.
