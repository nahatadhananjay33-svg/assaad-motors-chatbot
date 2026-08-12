# Phase 7P.1 — Consultative Selling Layer

**Goal:** make the bot sound like a salesperson, not an inventory search engine —
ONE recommendation + ONE question on broad entry intents — **without changing**
retrieval, memory, inventory matching, price, media, Marathi, low-KM, the Astor
fix, or lead capture.

```
Customer: family car batao
BEFORE  : Haan, 8 options hain — jaise 2019 Blue Ertiga, 2019 ...   (inventory dump)
AFTER   : Family ke liye Ertiga aur Marazzo achi rahengi.
          Kitne members hain family mein?                          (consultative)
```

The vehicle cards are **never removed** — only the spoken intro changes. Every
recommendation is drawn from **current inventory** (the live match set of that
very search), so nothing unavailable is ever named.

---

## STEP 1 — Audit (`consultative_sales_audit.xlsx`)

Replayed the real pilot conversation log (`data/pilot_query_log.db`,
**11,301 conversations / 33,740 turns**) with the consultative layer **disabled**
to capture the pre-fix behaviour. A *dump* = a multi-car listing with no
recommendation and no follow-up question.

| Entry Intent | Turns | Inventory Dumps | Dump % | Consultative Qs |
|---|---:|---:|---:|---:|
| Family Car | 521 | 431 | 83% | 0 |
| Budget Only | 827 | 537 | 65% | 28* |
| SUV | 842 | 738 | 88% | 0 |
| Sedan | 649 | 525 | 81% | 0 |
| Hatchback | 428 | 355 | 83% | 0 |
| CNG | 164 | 156 | 95% | 0 |
| Automatic | 574 | 332 | 58% | 0 |
| Finance | 1,194 | 0 | 0% | 0 |
| First Car / City / Office | 20 | 12 | — | — |
| **TOTAL** | **5,221** | **3,086** | **59%** | **38 (1%)** |

\* the handful of "consultative" pre-fix hits are the existing budget-clarify /
attr-clarify prompts, not real recommendations.

**Finding:** broad entry intents were answered as inventory dumps **59%** of the
time, with **~1%** ever asking a consultative question. Finance is fully handled
by the Finance FAQ (no dump), so it is intentionally left untouched.

Workbook sheets: `Summary · Family Car · Budget Only · SUV · Sedan · Hatchback ·
Finance · CNG · Recommendations`.

---

## STEP 2 — Design (recommendation layer)

A tiny module, [`consultative_sales.py`](app/inventory_system/consultative_sales.py).
Each intent has a *preference list* of models to headline; only those that appear
in **this search's live matches** are named (so they are guaranteed available and
within every active filter, including price). Up to **2** cars, never more.

| Entry Intent | Recommends (from current stock) | Question |
|---|---|---|
| Family | **Ertiga, Marazzo** | Kitne members hain family mein? |
| Budget (<5L) | **Polo, Grand i10** | Budget flexible hai ya strict? |
| SUV | **Nexon, Sonet** | City use ya highway use? |
| Sedan | **City, Ciaz** | Zyada city use ya highway? |
| Hatchback | **Polo, Grand i10** | Daily city use ke liye chahiye? |
| CNG | **Tigor, WagonR** | Daily running zyada hai? |
| Automatic | **Ertiga, Nexon** | Daily traffic use ke liye chahiye? |
| City use | **Grand i10, WagonR** | Roz kitne km chalana hota hai? |
| First car | **Grand i10, WagonR** | Budget kitna soch rahe hain? |

Recommendations are computed from the ranked match models, never hardcoded — if a
model leaves stock, it simply stops being recommended.

---

## STEP 3 / 4 — One question, one recommendation, response rules

* Exactly **one** recommendation sentence (≤ 2 vehicles) + **one** question.
* Response is **≤ 3 lines**.
* The inventory cards are **kept** (additive); only the intro text is replaced.
* Wiring: [`chat_service.py`](app/inventory_system/chat_service.py) `handle()` —
  after retrieval, a guarded block rewrites `out.response` and tags
  `meta["consultative"]` + guardrail `G-CONSULT`. It fires only on a broad entry
  listing (`match_models` present, a detected entry intent, no media, no appended
  follow-up token), so specific-model / price / media / low-KM / attribute /
  continuation turns are never touched.

---

## STEP 5 — Validation (`consultative_sales_validate_result.json`)

Replayed BEFORE vs AFTER via the `CONSULTATIVE_LAYER` toggle (nothing else
differs). Coverage denominator = *broad entry inventory turns* (message is an
entry intent **and** a listing was returned) — measured identically in both runs.

### 500-conversation benchmark

| Metric | Before | After |
|---|---:|---:|
| Broad entry inventory turns | 93 | 93 |
| **Recommendation coverage** | 0.0% | **95.7%** |
| **Consultative question coverage** | 0.0% | **95.7%** |
| Dump-text turns | 93 | 4 |
| Inventory accuracy | — | **100.00%** |
| Follow-up memory | — | **100.00%** |
| Price accuracy | — | **100.00%** |
| Media accuracy | — | **100.00%** |
| Lead capture | — | **100.00%** |
| Regressions (inventory/media/lead/price) | — | **0 / 0 / 0 / 0** |

### Full pilot log (11,301 conversations / 33,740 turns)

| Metric | Before | After |
|---|---:|---:|
| Broad entry inventory turns | 4,034 | 4,034 |
| **Recommendation coverage** | 0.0% | **92.0%** |
| **Consultative question coverage** | 0.0% | **92.0%** |
| Dump-text turns | 4,034 | 324 |
| Inventory accuracy | — | **100.00%** |
| Follow-up memory (8,897 resolved turns) | — | **100.00%** |
| Price accuracy | — | **100.00%** |
| Media accuracy | — | **100.00%** |
| Lead capture | — | **100.00%** |
| Regressions (inventory/media/lead/price) | — | **0 / 0 / 0 / 0** |

The ~8% of entry turns that stay as listings are edge cases where the production
detector defers (e.g. a "city" phrase the parser reads as the *City* model, or a
budget phrase that resolved a specific model) — by design, never a wrong
recommendation.

**No regression:** the vehicles returned, media payloads, price-follow-up answers,
follow-up-memory resolutions and lead levels are **byte-identical** before vs
after on every turn. The layer changes wording only.

---

## STEP 6 — Examples & conversation improvements

| Customer | Before (dump) | After (consultative) |
|---|---|---|
| family car batao | Haan, 8 options hain — jaise 2019 Blue Ertiga … | **Family ke liye Ertiga aur Marazzo achi rahengi.** / Kitne members hain family mein? |
| SUV chahiye | Haan, 11 options hain — jaise 2022 Black Astor … | **SUV mein Nexon aur Sonet achi options hain.** / City use ya highway use? |
| car under 5 lakh | Haan, 23 options hain — jaise 2021 Tigor … | **Budget mein Polo aur Grand i10 value ke liye best hain.** / Budget flexible hai ya strict? |
| CNG car | Haan, 4 options hain — jaise 2021 Tigor … | **CNG mein Tigor aur WagonR best rahengi.** / Daily running zyada hai? |
| automatic car chahiye | Haan, 8 options hain — jaise 2021 Tigor … | **Automatic mein Ertiga aur Nexon achi rahengi.** / Daily traffic use ke liye chahiye? |

**Protected flows — verified untouched (`meta.consultative` stays empty):**

| Flow | Input | Reply (unchanged) |
|---|---|---|
| Astor fix | insurance kya hai | Kaunsi gaadi ki insurance details chahiye? |
| Low-KM | low km car | Haan, 34 options hain — jaise … (low-km sort) |
| Price follow-up | Ertiga → price kya hai | 2019 Blue Ertiga ₹7.99 lakh. |
| Media | family car → photo bhejo | Kaunsi gaadi ke photos chahiye? |
| Specific model | Swift available hai | Swift abhi available nahi, lekin … |

---

## Regression results — summary

| Guarantee | Result |
|---|---|
| Inventory matching / retrieval | ✅ identical (100%) |
| Follow-up memory | ✅ identical (100%) |
| Price logic / price follow-up | ✅ identical (100%) |
| Media logic | ✅ identical (100%) |
| Marathi logic | ✅ `to_marathi` runs on the intro exactly as before |
| Low-KM sort | ✅ never consultative |
| Astor fix (attr-guard) | ✅ never consultative |
| Lead capture | ✅ identical |
| Unit + integration tests | ✅ `consultative_sales_tests.py` (16) + 242 existing pass† |

† The one pre-existing failure (`test_refresh_returns_ok_and_count`, expects
inventory_count 40 vs current 44) is unrelated data drift — present before this
phase.

## Success criteria

- ✅ More salesperson-like — one recommendation + one question
- ✅ Less inventory-dump feeling — dump-text on entry intents 100% → ~4%
- ✅ Recommendations only from current inventory
- ✅ No impact on Astor fix / Price follow-up / Marathi / Photo-Video / Low-KM
- ✅ Vehicle cards and all retrieval untouched (additive wording only)

## Files

| File | Purpose |
|---|---|
| [`consultative_sales.py`](app/inventory_system/consultative_sales.py) | recommendation + question layer |
| [`chat_service.py`](app/inventory_system/chat_service.py) | wiring (guarded `G-CONSULT` block) |
| [`consultative_sales_audit.py`](app/inventory_system/consultative_sales_audit.py) | STEP 1 audit → `consultative_sales_audit.xlsx` |
| [`consultative_sales_validate.py`](app/inventory_system/consultative_sales_validate.py) | STEP 5 A/B validation → `consultative_sales_validate_result.json` |
| [`consultative_sales_tests.py`](app/inventory_system/consultative_sales_tests.py) | unit + integration tests |
