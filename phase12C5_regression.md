# Phase 12C.5 — Regression Report

Command: `python -m pytest *_tests.py` (full suite).

## Result

```
521 passed, 2 failed  (150s)
```

**Identical to the Phase 12C baseline** (521 passed / 2 failed). Phase 12C.5
changed **only `vehicle_details.html`** (client HTML/CSS/JS) — no Python, no Excel,
no API — so the test suite is, by construction, unaffected. The run confirms it.

## The 2 remaining failures — pre-existing, NOT caused by 12C.5

| Test | Cause | 12C.5-related? |
|---|---|---|
| `hardening_tests::test_refresh_returns_ok_and_count` | asserts count 40; live sheet has 44 (stale) | ❌ No |
| `media_api_tests::test_unknown_still_flagged` | `"…999"` parsed as a partial number-plate (Phase 11A) → `not_found` vs expected `unknown` | ❌ No |

Both predate Phase 12B and are tracked for the pending cleanup step.

## Why this phase is regression-safe
- No backend/API/loader/model_specs/Excel change — the only artifact modified is a
  static page the pytest suite does not exercise.
- Memory, browse, variant, follow-up, budget, search, media, owner, inventory,
  intent (11A/11B), schema (12B) and data-entry (12C) suites all remain green.

## Cross-check
| Run | Result |
|---|---|
| Phase 12C final | 521 passed, 2 failed |
| Phase 12C.5 | **521 passed, 2 failed** |
