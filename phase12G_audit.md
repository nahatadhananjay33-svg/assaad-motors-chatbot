# Phase 12G — Audit (Step 1, before any code change)

Traced against the real code and confirmed by an instrumented run
(`phase12g_trace.py`) on a copy of the live workbook. The pinned probe car is the
single **Fortuner** (year **2011**, transmission **Manual**, odometer **169,773 km**).

## A. How YEAR is parsed
- `query_parser.parse()` line ~792: a bare 4-digit year (`_YEAR_EXACT_RE`) sets
  `q.year_exact` (a FILTER). There is **no** year attribute/question concept.
- `"2019 model hai?"` → `year_exact=2019` (filter). `"model year kya hai?"` /
  `"kaunsa year hai?"` → parse to **nothing** (no signal at all).

## B. How ODOMETER / KM is parsed
- `LOW_KM_WORDS` (line 261) contains `"kam km"`, `"low km"`, `"sabse kam km"`, …
  → sets `q.sort_low_km=True` (a SORT).
- `_KM_READING_WORDS` (line 476) → `q.km_reading_query=True`, **but only when
  `not q.sort_low_km`** (line 492). So `"kam km chali hai?"` trips `sort_low_km`
  first and the odometer question is suppressed.
- `"kitni km chali hai?"` / `"running kitni hai?"` / `"odometer kya hai?"` →
  `km_reading_query=True` (already correct).

## C. How TRANSMISSION / AUTOMATIC is parsed
- `_auto_terms` / `_manual_terms` (line 643) → `q.transmission = AUTOMATIC|MANUAL`
  (a FILTER value).
- `TRANSMISSION_QUERY_WORDS` → `q.transmission_query=True`, **only when
  `q.transmission is None`** (line 697). So `"automatic hai?"` sets the filter
  value and never becomes a question. `"transmission kya hai?"` (no value) →
  `transmission_query`.

## D. How pinned-car context is represented
- `ChatService._followup_ctx[session_id] = {"reg": <reg|None>, "model": <model|None>}`.
  A single resolved car → `reg` set; a named-model multi-match → `model` only.
- `_followup_token()` returns `reg` (single car) else `model`.
- `_is_attr_followup(message, q)` decides whether to append that token so the
  existing parser/retrieval resolves the pinned car. It currently keys off the
  11A/12D attribute flags (`insurance_query`, `km_reading_query`, `color_query`,
  `transmission_query`, `attr_fields`, …). **`sort_low_km` short-circuits it to
  False; year has no flag; `transmission` filter value is not an attribute flag.**

## E. How same-model variant detection works
- `chat_service._conversation_override()` → `_has_refinement(q)` (a non-model
  filter such as `transmission`, `sort_low_km`, `year_exact`) merges onto the
  session's last search / pinned model. `conversation_policy._is_variant_refine()`
  labels the mode `same_model_variant`.

## F. How fresh-search detection works
- `conversation_policy._BROWSE_FIELDS` (model/make/category/seats/km_max/price/
  year_min/year_exact) or `feature_filters`/`sort_cheapest`/registration → mode
  `new_search`; retrieval runs a fresh browse.

## G. Where attribute-answer vs variant/filter-search is decided
1. **Parser** decides whether the utterance carries a FILTER value
   (`transmission`, `year_exact`, `sort_low_km`) or an attribute QUERY flag
   (`transmission_query`, `km_reading_query`, …). **This is the root cause** — the
   three problem phrasings are parsed as filters/sorts, so they can never reach
   the attribute-answer path.
2. `ChatService.handle` → `_is_attr_followup` (append pinned token) → routing.
3. `_conversation_override` merges refinements into a search.
4. `response_formatter.format_response` answers a single pinned car for
   `km_reading_query` / `*_query` / `attr_fields` (early-return blocks,
   `result.count == 1`); missing value → "Data not available" (never fabricated).

## Exact current decision path for the three examples (pinned Fortuner)

| Utterance | Parse | `_is_attr_followup` | Route / result | Correct? |
|-----------|-------|---------------------|----------------|----------|
| `2019 model hai?` | `year_exact=2019` | False | refinement merge → fresh **2019 search** (4 cars), mode `new_search` | ❌ should answer 2011 |
| `model year kya hai?` | *(nothing)* | False | falls to continuation → `exhausted`/offsheet | ❌ should answer 2011 |
| `kam km chali hai?` | `sort_low_km=True` | False (`sort_low_km` short-circuit) | low-km sort merged onto model → availability line, **no km** | ❌ should answer 169,773 km |
| `automatic hai?` | `transmission=Automatic` | False | variant search → consultative "Automatic mein Fortuner…" (Fortuner is **Manual**) | ❌ should answer "Manual" |

## Anti-regression baselines to preserve (verified in the trace)
| Utterance | Parse | Must stay |
|-----------|-------|-----------|
| `automatic wali?` / `automatic wali dikhao` / `automatic wali chahiye` | `transmission=Automatic` | variant/search |
| `automatic cars` / `automatic cars dikhao` / `automatic mein koi hai?` | `transmission=Automatic` | inventory search |
| `2019 model chahiye` / `2019 model wali car chahiye` / `2019 ki car dikhao` | `year_exact=2019` | inventory search |
| `kam km wali car chahiye` / `sabse kam km wali car` / `low km wali car dikhao` | `sort_low_km=True` | search/sort |
| `2019 nexon` | `year_exact=2019`,`model=Nexon` | search |

## Conclusion
The fix belongs at the **parser** (point G-1): distinguish an attribute QUESTION
from a SEARCH/VARIANT request **lexically** (search cues: `wali/chahiye/dikhao/
cars/sabse/koi hai/mein koi`; other model/make/category named), and when it is a
question, emit the attribute flag (`transmission_query` / `km_reading_query` /
new `year_query`) instead of the filter/sort. The existing pinned-answer path then
answers the car; the existing unpinned path safely clarifies. No new engine, no
context threading into the parser, no vocabulary duplication.
