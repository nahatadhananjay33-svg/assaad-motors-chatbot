# PHASE 7O.5 — STEP 2: Marathi Response Root Cause

**Date:** 2026-06-19
**Audit source:** `data/pilot_query_log.db` (the referenced
`evaluation_results_marathi_v4.xlsx` and `final_conversations_only.txt` are not
present in the repo, so the pilot log was used — same as the 7O.2–7O.4 audits).
Full breakdown in **`marathi_response_audit.xlsx`**.

Scope: **response LANGUAGE only.** Marathi *understanding* (detection) is already
good — `language_detector.detect_language` correctly tags 3,357 Marathi turns.

---

## Measured (pre-fix) — 3,357 Marathi customer turns

| Metric | Count | % |
|---|--:|--:|
| **Pure Marathi reply** | 1,002 | **29.8%** |
| Mixed Hindi/Marathi reply | 0 | 0.0% |
| **Hindi / Hinglish reply (fail)** | 2,341 | **69.7%** |
| Neutral (numeric / proper-noun only) | 14 | 0.4% |
| **Marathi reply % (pure + mixed)** | 1,002 | **29.8%** |

Only ~30% of Marathi customers got a Marathi reply.

---

## Why Marathi replies become Hindi/Hinglish

The bot **detects** Marathi correctly and even passes the language down to the
**FAQ templates** — those are already fully translated, which is exactly the
1,002 replies that pass (finance, location, visit, timing, exchange, warranty,
greeting, etc.). The failures come from the **non-FAQ reply paths, which emit
hard-coded Hinglish regardless of the detected language**:

### Responsible response paths (fail counts)

| Route | Fails | What it is |
|---|--:|---|
| `inventory` | **1,715** | `response_formatter` spoken frames |
| `clarify` | **472** | crisp `chat_service` clarifications |
| `faq` | **154** | the `media_clarify` path (see below) |

### Responsible templates / frames

1. **`response_formatter.py`** — none of its frames take a `language`, so they are
   always Hinglish:
   - single match: `"Haan, … available hai. aap aaj aa ke dekh lo — …"`
   - multi match (G-MULTI): `"Haan, N options hain — jaise …. Konsi dekhni hai — saal ya budget bata do?"`
   - price clause: `" — ₹X lakh"` / coded-price hedge
   - not-found / segment / reel-clarify frames
   - attribute frames (insurance / service / condition / RC / warranty /
     downpayment) and their `Yes/No` + `Data not available.` values
   - `VISIT_PIVOT` / `FRESH_HEDGE` constants
   Intents affected: availability (1,027), budget (270), price (113), fuel (99),
   combination (92), transmission (45), ownership (9).
2. **`chat_service.py` crisp replies** (added in 7O.2–7O.4), all Hinglish:
   - attribute clarify `_ATTR_CLARIFY` ("Kaunsi gaadi ki insurance details chahiye?")
   - price follow-up `_price_line` + "Kis gaadi ki price chahiye?"
   - media `_MEDIA_OK_RESP` / `_MEDIA_UNAVAIL_RESP` / `_MEDIA_CLARIFY_RESP`
     (photo_request 59) — and the 7O.3 media override had **replaced** the
     already-Marathi `media_clarify` template with Hinglish (the 154 `faq`-route
     fails, intent `media_clarify`).
   - `_handle_catalogue` summary.

In short: **FAQ replies were translated; the inventory formatter and the newer
crisp chat_service replies were not.**

---

## Fix direction (STEP 3)

A single response-LANGUAGE post-processor `marathi_response.to_marathi()`, applied
at one chokepoint in `chat_service.handle()` and gated on
`rr.language == "marathi"`. It converts the known Hinglish reply frames to Marathi
by ordered phrase replacement (`Haan → हो`, `available hai → उपलब्ध आहे`,
`₹X lakh → ₹X लाख`, `Insurance type: → विमा प्रकार:`, the media/price/clarify crisp
lines, etc.). Data values (model / colour / fuel / price number / address / RC /
NOC / EMI) and all routing/logic are untouched; no other language is affected.
This re-uses the existing detected language — Marathi *understanding* is not
changed.
