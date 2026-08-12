# PHASE 7O.5 — Marathi Response Quality Report

**Date:** 2026-06-19
**Scope:** Marathi RESPONSE language ONLY. No LLM, no new dependencies, no DB /
schema changes. **No change to the Astor fix, Photo/Video fix, Price-Follow-up
fix, Low-KM, website, Excel, or inventory loader. Marathi understanding
(detection) is NOT changed.**

---

## Goal

A customer clearly speaking Marathi should get Marathi replies — greeting, price,
insurance, warranty, service, finance, photo/video, visit/location.

```
Customer: विमा आहे का?       Bot (before): Haan, insurance available hai.
                             Bot (after) : (vehicle in context) 2021 Tigor … विमा प्रकार: …
                                           (no vehicle)         कोणत्या गाडीची विमा माहिती हवी?
Customer: किंमत किती आहे?     Bot (after) : 2022 White Nexon ₹6.89 लाख.
Customer: फोटो पाठवा          Bot (after) : 2017 White Innova चे फोटो उपलब्ध आहेत.
```

---

## STEP 1 — Audit (`marathi_response_audit.xlsx`)

Replayed every conversation containing a Marathi customer turn from the pilot log
(`data/pilot_query_log.db`; the referenced `evaluation_results_marathi_v4.xlsx` /
`final_conversations_only.txt` are not in the repo). Classified each bot reply to
a Marathi turn.

| Metric | Count | % |
|---|--:|--:|
| Marathi customer turns measured | 3,357 | 100% |
| **Pure Marathi reply** | 1,002 | **29.8%** |
| Mixed Hindi/Marathi | 0 | 0.0% |
| **Hindi / Hinglish reply (fail)** | 2,355 | **70.2%** |

**Current Marathi Reply % = 29.8%** (pure). Failures by route: `inventory` 1,729
(formatter), `clarify` 472 (crisp chat_service replies), `faq` 154
(`media_clarify`).

---

## STEP 2 — Root cause (`marathi_response_summary.md`)

The bot detects Marathi correctly and the **FAQ templates are already fully
Marathi** (the 1,002 passing replies). The failures come from the **non-FAQ reply
paths that emit hard-coded Hinglish regardless of language**:
- `response_formatter.py` — single / multi / not-found / segment / price /
  attribute frames + `VISIT_PIVOT` / `FRESH_HEDGE` (no `language` param).
- `chat_service.py` crisp replies (7O.2–7O.4): attribute-clarify, price-clarify
  & price line, media OK / unavailable / clarify, catalogue — and the 7O.3 media
  override had replaced the already-Marathi `media_clarify` template with
  Hinglish.

---

## STEP 3 — Fix (surgical)

A single response-LANGUAGE post-processor, `marathi_response.to_marathi()`,
applied at ONE chokepoint in `chat_service.handle()` and gated on
`rr.language == "marathi"`:

```python
if rr.language == "marathi" and out.response:
    out.response = to_marathi(out.response)
```

`to_marathi` converts the known Hinglish reply frames to Marathi by ordered
(longest-first) phrase replacement — e.g. `Haan → हो`, `available hai → उपलब्ध
आहे`, `₹X lakh → ₹X लाख`, `Insurance type: → विमा प्रकार:`, `Konsi dekhni hai …
→ कोणती बघायची आहे …`, the media / price / clarify crisp lines, the catalogue
summary, and the multi-match list trailer. Data values (model / colour / fuel /
price number / address / RC / NOC / EMI proper nouns) and **all routing and
logic are untouched**; no other language is affected. Replies stay short and
sales-oriented.

The four target examples now reply in Marathi (the no-context insurance case
clarifies in Marathi — `कोणत्या गाडीची विमा माहिती हवी?` — because the existing
Astor logic is preserved; with a vehicle in context it answers the vehicle).

---

## STEP 4 — Validation

Replayed **1,901 Marathi conversations (3,357 Marathi turns)** — far above the
500 minimum — A/B via the post-processor (disabled = pre-fix, enabled = shipped).
Read-only on the pilot log; isolated temp DBs.

| Metric | Before | After |
|---|--:|--:|
| Marathi turns measured | 3,357 | 3,357 |
| **Pure Marathi reply** | 1,002 (29.8%) | 3,357 (100%) |
| Hindi / Hinglish reply | 2,355 (70.2%) | 0 (0.0%) |
| **Marathi Reply %** | **29.8%** | **100.0%** |

- **Marathi reply quality: 29.8% → 100%** (> 90% target).
- All formatter, media, price, attribute-clarify and catalogue replies now render
  in Marathi for Marathi customers; FAQ replies remain Marathi.

---

## STEP 5 — Regression

Command: `python -m pytest *_tests.py -q`

| Run | Result |
|---|---|
| **tests_before** (post-7O.4 baseline, this session) | **380 passed, 1 failed** |
| **tests_after** (Phase 7O.5) | **380 passed, 1 failed** |

**No new regressions (0).** The single failure is the pre-existing
`hardening_tests.py::TestInventoryRefresh::test_refresh_returns_ok_and_count`
(hard-coded inventory count 40 vs current 44 — data drift), identical before and
after, documented in the 7L.2 / 7O.2 / 7O.3 / 7O.4 reports.

---

## Success criteria

| Criterion | Result |
|---|---|
| Marathi reply quality > 90% | ✓ **100%** |
| No regressions | ✓ 0 new failures |
| No logic changes | ✓ (only response text translated, gated on language) |
| No impact on Astor fix | ✓ (only fires for Marathi; logic unchanged) |
| No impact on Photo/Video fix | ✓ |
| No impact on Price Follow-up fix | ✓ |
| No impact on Low-KM | ✓ |
| Marathi understanding unchanged | ✓ (detector untouched) |

---

## Outputs / files

- **Outputs:** `marathi_response_audit.xlsx`, `marathi_response_summary.md`,
  `marathi_response_report.md`.
- **Changed:** `app/inventory_system/chat_service.py` (import + one gated call).
- **Added (shipped):** `app/inventory_system/marathi_response.py` (the converter).
- **Added (validation harnesses, not shipped):**
  `app/inventory_system/marathi_response_audit.py`,
  `app/inventory_system/marathi_response_validate.py`,
  `app/inventory_system/marathi_response_validate_result.json`.
