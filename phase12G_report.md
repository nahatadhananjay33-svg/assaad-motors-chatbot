# Phase 12G — Final Report

**Deterministic contextual attribute hardening.** Fix exactly three known
ambiguities so that a **single pinned vehicle** answers year / odometer /
transmission attribute questions, while all browse / variant / filter behaviour is
preserved and unpinned questions never fabricate. No LLM. No new engine. Surgical
and reversible.

Companion docs: `phase12G_audit.md`, `phase12G_validation.md`,
`phase12G_regression.md`.

---

## 1. EXACTLY what changed

One deterministic idea: **the attribute-question vs search/variant distinction is
lexical** (it is in the wording, not the conversation state), so the *parser*
emits the right signal and the *existing* pinned-answer / unpinned-clarify
machinery does the rest. Four files, all additive:

**`query_parser.py`**
- New `Query.year_query` flag (mirrors the existing `transmission_query` /
  `seats_query`).
- New deterministic discriminators (small, reused, no giant dictionary):
  `_SEARCH_VARIANT_CUES` (`wali/wale/chahiye/dikhao/cars/sabse/koi hai/mein koi/…`
  + Marathi), `_ATTR_QUESTION_WORDS`, `_ODO_QUESTION_CUES`, `_YEAR_QUESTION_WORDS`,
  and helpers `_has_search_cue` / `_is_attr_question` / `_is_odo_question` /
  `_is_year_question`.
- A single reclassification block at the end of `parse()` — runs **only** when
  there is no search cue and no other model/make/category named:
  - **RULE C** transmission: `automatic hai?` / `manual hai?` /
    `transmission automatic hai?` → clear the `transmission` filter, set
    `transmission_query`.
  - **RULE B** odometer: `kam km chali hai?` (an odometer *reading* question) →
    clear `sort_low_km`, set `km_reading_query`.
  - **RULE A** year: `2019 model hai?` / `model year kya hai?` / `kaunsa year hai?`
    → clear `year_exact`/`year_min`, set `year_query`.
  A specific registration/partial-plate does **not** block this (it pins one car);
  only a model/make/category (a class of cars) keeps the search behaviour.

**`response_formatter.py`** — new `year_query` answer block (mirrors
`seats_query`): single pinned car → "yeh &lt;year&gt; model hai"; unknown →
"exact model year visit pe confirm" (never fabricated).

**`chat_service.py`** — `year_query` added to `_is_attr_followup`,
`_ATTR_QUERY_FLAGS`, and `_ATTR_CLARIFY` ("Kis gaadi ka model year chahiye?"), so
a pinned car is reused and an unpinned question clarifies.

**`conversation_policy.py`** — `year_query` added to `_ATTR_FLAGS` so the turn is
labelled `current_car` (pinned) / `clarify` (unpinned).

### Why
`automatic hai?`, `2019 model hai?`, `kam km chali hai?` were parsed as a
transmission **filter**, a year **filter**, and a low-km **sort** respectively, so
they could never reach the attribute-answer path and instead ran a search — even
when a single car was pinned. See `phase12G_audit.md` for the exact old paths.

### Exact deterministic rules
> **pinned single car + attribute question (no search cue, no other model named)**
> → answer that car.
> **any search/variant wording** (`…wali`, `…chahiye`, `…dikhao`, `…cars`,
> `sabse`, `koi hai`) **or another model/make/category named** → search/filter.
> **unpinned attribute question** → safe "which car?" clarification (never a
> fabricated car).

## 2. EXACTLY what did NOT change
- No LLM, no new NLP framework, no parser rewrite, no second intent engine, no
  vocabulary duplication (reused `_has`/cue style; added only the missing phrases).
- The parser cache/perf path (`_has_pattern` lru_cache) is untouched.
- **Unchanged files/systems:** auth, permissions, audit, media, upload,
  analytics, Supabase, owner/staff panel, Excel schema, retrieval architecture,
  intent_intelligence.
- All existing filter/variant/sort semantics: `automatic cars`, `automatic wali?`,
  `2019 model chahiye`, `sabse kam km wali car`, `2019 nexon` — identical.

## 3. Test results
- New `phase12g_context_tests.py`: **27 / 27 pass** (parser reclassification,
  policy modes, real ChatService behaviour, anti-regression searches, unpinned
  no-fabrication, multi-intent, conversation flows, Marathi).
- Targeted regressions green throughout development
  (12D/12E/11A/11B/retrieval, auth/permissions/audit).

## 4. Regression results
- Full suite: **578 passed, 2 failed** (= 551 from 12F + 27 new; the 2 are the
  identical pre-existing stale tests, unrelated to 12G). **Zero new failures.**
  Details in `phase12G_regression.md`.

## 5. Performance comparison (deterministic, no LLM)
| Layer | 12F baseline | 12G (clean run) |
|-------|--------------|-----------------|
| `query_parser.parse()` | ~2.3 ms | ~1.6 ms |
| `intent_intelligence.analyze()` (delta) | ~4.4 ms | ~0.8 ms |
| `conversation_policy.classify()` | ~4.4 ms | ~2.0 ms |
| `ChatService.handle()` | median ~29 ms · p95 ~47 ms | median ~25 ms · p95 ~33 ms |

No meaningful regression (numbers vary with machine load; the 12G additions are a
handful of substring/`_has` checks at the tail of `parse()`). The parser cache is
intact.

## 6. Remaining ambiguity / limitations
1. **Multi-car model pin** (e.g. `Show me Ertiga` = 2 cars) + `automatic hai?`:
   with no *single* car pinned, this stays a same-model variant search (shows the
   automatic Ertiga) rather than answering one car — correct per the "single
   vehicle pinned" objective, and it never fabricates.
2. **Combined old-flag multi-intent** (`automatic hai aur kitne owners hain?`)
   answers the primary field only — a pre-existing `response_formatter`
   early-return, not introduced here. It correctly answers the pinned car and
   never converts to a search.
3. **Cold (unpinned) `2019 model hai?`** now returns a safe "tell me the model/
   budget" help reply instead of the previous 4-car 2019 list. This is an
   intended, brief-permitted trade-off ("clarification/search behaviour");
   explicit `2019 model chahiye` still lists 2019 cars.

## 7. Is Phase 12G complete?

**✅ COMPLETE.**

All acceptance criteria are met and proven by tests + full regression, not just a
few examples:

- [x] `2019 model hai?` on pinned car → the car's year (2011).
- [x] `kam km chali hai?` on pinned car → the car's km (169,773).
- [x] `automatic hai?` on pinned car → the car's transmission (Manual).
- [x] `automatic wali dikhao` → variant/search behaviour.
- [x] `2019 model chahiye` → inventory search.
- [x] `kam km wali car chahiye` / `sabse kam km wali car` → search/sort.
- [x] Unpinned cases never fabricate (safe clarify/help).
- [x] Multi-intent answers the pinned car (never a search).
- [x] Follow-up memory + fresh browse intact.
- [x] Existing 11A/11B/12D/12E/12F tests green.
- [x] 27 new Phase 12G tests pass.
- [x] No meaningful performance regression.
- [x] Full regression: zero new failures (578/2).
- [x] All four reports written.

No further phase is started. This change is surgical and reversible (delete the
one reclassification block + the four additive `year_query` hooks to fully revert).
