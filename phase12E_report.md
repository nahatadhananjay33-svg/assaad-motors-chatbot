# Phase 12E — Deterministic Conversation Policy (Report)

## Objective
Improve the chatbot's conversation behaviour using the existing Phase 11A/11B/12D
intent engine — decide WHAT the bot does after the intent is detected — with no
LLM, no redesign, and no auth/media/panel/Excel/Supabase changes.

## Approach
The per-mode behaviours already existed across earlier phases. Phase 12E adds a
thin, **read-only** deterministic classifier (`conversation_policy.py`) that names
each turn's mode from signals the parser already produced, exposes it as
`meta["conversation_mode"]`, and — most importantly — **verifies** the flows with a
focused conversation test suite. No routing/retrieval/memory/answer logic changed.

## Conversation modes (7)
`current_car` · `same_model_variant` · `new_search` · `multi_intent` · `clarify`
(incl. conflicts) · `faq` · `offsheet_unknown`.

## Behaviour (verified)
- **Pinned car** → `insurance/sunroof/airbags/boot space/RC/owners/km/music` answer
  about that car; no unnecessary fresh search.
- **Same-model variant** → `automatic/petrol/kam-km/first-owner/white wali` stay
  within the pinned model; if none match, retrieval returns 0 and other options are
  offered.
- **Fresh search** → 7-seater / SUV<8L / new model / feature-filter → fresh browse,
  not stuck on the previous car.
- **Multi-intent** → all requested fields answered (12D `attr_fields`); no secondary
  intent lost.
- **Clarification** → attribute question with no pinned car → "Sure — kis gaadi ke
  details chahiye?"; never a random car.
- **Conflicts** → "petrol diesel" clarifies; "petrol ya diesel?" stays a question
  (11B behaviour unchanged).
- **Follow-up memory** → the STEP 9 sequence (Ertiga → automatic wali → petrol wali
  → RC → 7 seater) works; context retained for attribute/variant turns and replaced
  on a new class of search.

## Results
- **Tests:** `phase12e_conversation_tests.py` — **17 tests, all pass** (classifier
  units + real ChatService flows across EN/HI/Hinglish/Marathi).
- **Performance:** `classify()` **1.86 ms/call** (meta-only, guarded; minor on a
  ~20 ms handle). No parser latency change (parser untouched by 12E).
- **Regression:** **551 passed, 2 failed** (re-run; the 2 are the same pre-existing
  stale tests). A 3rd failure appeared once (`test_chat_requires_key`,
  ConnectionError) but passed on re-run and in isolation — environmental flakiness,
  not a code regression. Zero behavioural regressions.

## Deliverables
`phase12E_conversation_policy.md`, `phase12E_validation.md`,
`phase12E_regression.md`, `phase12E_report.md`; code: `conversation_policy.py`,
`phase12e_conversation_tests.py`, and two additive lines in `chat_service.py`
(prior-context snapshot + meta label).

---

## FINAL VERDICT

**PHASE 12E: ✅ COMPLETE**

All seven conversation modes are classified deterministically from existing signals
and, crucially, the important flows are **actually tested and working** (17/17):
pinned-car answers stay on the pinned car, same-model variants stay in the model,
different requirements start a fresh browse, multi-intent answers every field,
cold attribute questions clarify (never a random car), conflicts clarify while
disjunction questions don't, and the full follow-up sequence behaves correctly
across four languages. It is read-only (no answer/routing change), fast (1.86 ms),
uses no LLM, and introduces no behavioural regressions — the only non-green tests
are two pre-existing stale cases and one flaky live-server test that passes in
isolation.
