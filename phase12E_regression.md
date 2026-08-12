# Phase 12E — Regression

Command: `python -m pytest *_tests.py` (full suite, incl. new `phase12e_conversation_tests.py`).

## Result

Two consecutive full runs:

```
run 1: 550 passed, 2 failed + 1 transient (test_chat_requires_key ConnectionError)
run 2: 551 passed, 2 failed   (the transient test passed)
```

- **551 passed** = Phase 12D's 534 + the **17 new Phase 12E tests**.
- **2 failed** = the same pre-existing stale tests. The 3rd failure in run 1 was a
  flaky live-server test that self-hosts a threaded server; it passed in run 2 and
  in isolation (`TestLiveSecurity` → 5 passed), so it is environmental, not a 12E
  regression.
- 12E added **no behavioural change** — the conversation-mode classifier is
  READ-ONLY (`meta["conversation_mode"]` only).

| BEFORE (12D) | AFTER (12E) |
|---|---|
| 534 passed, 2 failed | **551 passed, 2 failed** (zero new) |

## The 2 deterministic failures — pre-existing, NOT 12E
| Test | Cause |
|---|---|
| `hardening_tests::test_refresh_returns_ok_and_count` | asserts count 40; live sheet has 44 (stale). |
| `media_api_tests::test_unknown_still_flagged` | `"…999"` parsed as a partial number-plate (Phase 11A) → `not_found` vs `unknown`. Pre-dates 12B. |

## The 1 transient failure — flaky, NOT a code regression
`hardening_tests::TestLiveSecurity::test_chat_requires_key` failed once with a
**ConnectionError** during the parallel full run. It **self-hosts** an ephemeral
`ThreadingHTTPServer` (127.0.0.1:0) in a background thread and is timing-sensitive
under load. Run in isolation it passes cleanly:

```
pytest hardening_tests.py::TestLiveSecurity  ->  5 passed
```

12E changed only the server's *meta* output (a read-only classifier), nothing at
the connection layer, so this is environmental flakiness, not a 12E regression.

## Regression-safety summary
No auth / permissions / owner-panel / staff-panel / media / Supabase / Excel /
retrieval-behaviour code changed. Additions: new `conversation_policy.py`; one
`_prev_ctx` snapshot + one `meta["conversation_mode"]` line in `chat_service`
(both guarded, meta-only). All 11A/11B/12B/12C/12D suites remain green.
