# Phase 12G — Regression Report

Run exactly as previous phases:
```bash
cd app/inventory_system
python -m pytest -o python_files="*_tests.py" -q
```

## Results

| Run | Passed | Failed | Wall time |
|-----|--------|--------|-----------|
| Phase 12F baseline | 551 | 2 | ~165 s |
| **Phase 12G (post-change)** | **578** | **2** | 163.75 s |
| New in 12G | +27 (`phase12g_context_tests.py`) | 0 | — |

**578 = 551 (12F) + 27 new Phase 12G tests.** Zero new failures.

## The 2 failures — pre-existing & stale, NOT caused by 12G

| Test | Why | New? |
|------|-----|------|
| `hardening_tests::TestInventoryRefresh::test_refresh_returns_ok_and_count` | asserts inventory count **40**; live sheet has **44** | ❌ pre-existing (since 11B) |
| `media_api_tests::TestMediaAPIRegression::test_unknown_still_flagged` | `"…999"` parses as a partial plate → `not_found` vs expected `unknown` | ❌ pre-existing (since 11B) |

Both are the identical stale tests documented in every regression report from
Phase 11B through 12F. Neither touches year / km / transmission logic.

## Failure classification
- **Genuine new failures:** 0
- **Pre-existing stale:** 2 (unchanged)
- **Transient/environment:** 0 (the occasionally-flaky `TestLiveSecurity::
  test_chat_requires_key` did not appear this run)

## Anti-regression evidence (the phrasings most at risk)
These parser-level assertions are covered by `TestParserReclassification` and by
existing suites (`inventory_retrieval_tests`, `chat_api_tests`, `phase12e`):
- `parse("automatic cars").transmission == AUTOMATIC` → still true (unchanged).
- `"automatic wali?"` → still `same_model_variant` (phase12e green).
- `"2019 model chahiye"` / `"sabse kam km wali car"` → still searches.
- `normalize_numbers("2019 model")["year"] == 2019` (phase11b) → unaffected
  (separate function; parser change does not touch it).

## Verdict
Zero new regressions. The only red tests are the two long-standing stale
expectations unrelated to this phase.
