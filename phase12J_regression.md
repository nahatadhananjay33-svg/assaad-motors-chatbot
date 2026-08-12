# Phase 12J — Regression Report

Run exactly as previous phases:
```bash
cd app/inventory_system
python -m pytest -o python_files="*_tests.py" -q
```

## Results

| Run | Passed | Failed | Wall time |
|-----|--------|--------|-----------|
| Phase 12J baseline (before change) | 612 | 0 | 159–190 s |
| After 12J code, before test update | 611 | **1** | 181.8 s |
| **Phase 12J final (full suite)** | **633** | **0** | 190.2 s |
| New in 12J (`phase12j_tests.py`) | +21 | 0 | 9.2 s (isolated) |

**633 = 612 (baseline) + 21 new Phase 12J tests. Zero failures.**

## The one intermediate failure — caused by 12J, and it was the fix itself
`consultative_sales_tests.py::test_price_followup_untouched` failed after the code
change:

```python
self.svc.handle("Ertiga", session_id="s5")     # Ertiga = 2 cars
r = self.svc.handle("price kya hai", session_id="s5")
self.assertEqual(r.intent, "price")             # expected the OLD silent pick
```

- **Cause:** 12J Item 3. On a **multi-car** model, a price follow-up no longer
  silently answers one car's price (`matches[0]`) — it now **clarifies which
  Ertiga**. The test asserted the exact behaviour 12J corrects.
- **Classification:** 12J-caused, and **intended**. This is not an unrelated test;
  its incidental `intent == "price"` / `count == 1` assertions depended on the
  now-fixed silent-pick.
- **Action (minimal, honest):** the test's real purpose (per its name + the
  `assertIsNone(r.meta.get("consultative"))` assertion) is that a price follow-up
  gets **no consultative intro**. Its fixture was switched from the multi-car
  "Ertiga" to the **single-car "Fortuner"**, so it still validates exactly that,
  without depending on the corrected bug. The multi-car clarify behaviour is now
  covered by `phase12j_tests.py::test_model_multi_no_silent_pick`. No assertion was
  weakened; no unrelated test was touched.

## Why nothing else broke — additive & gated
| Change | Guard |
|--------|-------|
| bare `mileage?` clarify | only when nothing else resolves (same gate as other ambiguous words); `mileage kitna/kya`, `kitne km chali`, `good mileage car` all resolve first. |
| `attr_pair_ambiguous` | requires BOTH a transmission and a fuel FILTER, a coordinator (`aur/and/…`), no `hai`, no search cue, no browse filter. `...hai?` and `...wali/chahiye` excluded. |
| model-multi follow-up | only when ctx is a MODEL with >1 facing car, the turn is an attribute question, and there is no new vehicle / search cue / filter. Single-car pin and variant search untouched. |
| seats vocab additions | new question phrasings only; `N seater` filter search unchanged. |
| Vehicle Details UI | additive `RECOMMENDED`/`SUMMARY` set entries + `renderSummary` else-if branches; JS delimiter balance re-verified. No behaviour removed. |

## Anti-regression evidence (asserted green)
- `parse("mileage kitna hai?")` → `mileage_arai_kmpl`, `ambiguous_field` None.
- `parse("automatic aur petrol hai?")` → `fuel_query` and `transmission_query`
  True, `attr_pair_ambiguous` False.
- `parse("automatic petrol wali dikhao").attr_pair_ambiguous` False.
- Ertiga variant search (`automatic/petrol/kam km wali dikhao`) → still
  `same_model_variant`, never the clarify.
- Single-car Fortuner pin (`automatic hai?`/`price?`/`kitne km chali?`) → still
  answers the one car.
- 12I / 12G / 12E suites (KM, fuel attr, booking, negotiation, multi-intent,
  contextual year/km/transmission) all green.

## Verdict
**633 passed / 0 failed.** The single intermediate red was the intended Item-3
behaviour change; its test fixture was corrected to keep testing its real purpose.
No other regressions.
