# Phase 12F — Regression Report

Full existing test suite, run twice: once against the codebase as-inherited
(baseline), and again after the one small Phase 12F fix (a synonym-dictionary
addition in `field_intents.py`). NO LLM. Deterministic.

## How the suite was run
```bash
cd app/inventory_system
python -m pytest -o python_files="*_tests.py" -q
```
(The project's tests are `unittest`-based in `*_tests.py` files; pytest's default
`test_*.py` glob does not pick them up, so the `python_files` override is required.
This matches how the 12E regression was measured.)

## Results

| Run | Passed | Failed | Wall time |
|-----|--------|--------|-----------|
| Baseline (before 12F edit) | **551** | 2 | 165 s |
| After 12F edit (`field_intents.py` synonyms) | **551** | 2 | 231 s* |

\* second run shared the machine with the perf benchmark; timing is not comparable,
pass/fail is.

**Zero new failures introduced by Phase 12F.** The pass count is identical before
and after the edit.

## The 2 failures — pre-existing & stale, NOT caused by 12A–12F

| Test | Why it fails | Caused by 12A–12F? |
|------|--------------|--------------------|
| `hardening_tests::TestInventoryRefresh::test_refresh_returns_ok_and_count` | Asserts inventory count **40**; the live sheet now has **44** available cars (1 placeholder quarantined out of 45). Stale hard-coded expectation. | ❌ No |
| `media_api_tests::TestMediaAPIRegression::test_unknown_still_flagged` | `"zzz random gobbledygook 999"` — the trailing `999` is parsed as a **partial number-plate** (a Phase 11A/11C feature), so the query routes to inventory → `not_found` instead of the expected `unknown`. | ❌ No |

Both are documented as the identical pre-existing failures in the Phase 12B, 12C,
12C.5, 12D and 12E regression reports. They are stale test expectations, not
product defects, and existed before the Phase 12 series began.

### Transient note
In the Phase 12E run, a third failure (`hardening_tests::TestLiveSecurity::
test_chat_requires_key`, a `ConnectionError` from a self-hosted threaded test
server) appeared once and passed on re-run / in isolation. It did **not** appear
in either Phase 12F run (both were a clean 551/2).

## Targeted suites (run individually, all green)
| Suite | Result |
|-------|--------|
| `phase12d_field_tests.py` + `phase12e_conversation_tests.py` + `phase11a_intent_tests.py` + `phase11b_intelligence_tests.py` + `inventory_retrieval_tests.py` | **103 passed** |
| `auth_tests.py` + `permissions.py` + `audit_tests.py` + `owner_panel.py` | **52 passed** |

## Verdict
Regression is clean. 551 pass, the only 2 red tests are long-standing stale
expectations unrelated to the vehicle-knowledge / conversation work, and the
Phase 12F synonym fix changed the count by zero.
