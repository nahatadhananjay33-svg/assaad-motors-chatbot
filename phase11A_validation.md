# Phase 11A — Validation

No LLM. All results are deterministic and reproducible.

## STEP 7 — Per-field intent tests (≥ 50 utterances / field)

Test suite: `app/inventory_system/phase11a_intent_tests.py` (runs under pytest as
part of the normal `*_tests.py` sweep). Each field generates `TERMS × neutral
question FRAMES` utterances spanning English / Hindi / Hinglish / Marathi, short
& long forms, spoken variants and spelling mistakes, then asserts the parser
resolves each to the intended field (threshold 96 %; actual 100 %).

```
[OK ] rc            209/209
[OK ] insurance     133/133
[OK ] ownership     133/133
[OK ] km            161/161
[OK ] condition     182/182
[OK ] color         146/146
[OK ] fuel           91/91
[OK ] transmission  119/119
[OK ] seats         112/112
[OK ] warranty      111/111
[OK ] service        98/98
[OK ] finance       112/112
[OK ] price         125/125
[OK ] video          70/70
[OK ] instagram      63/63
[OK ] youtube        63/63
[OK ] budget         54/54

TOTAL 1982/1982 (100.0%)
```

Every field is well above the 50-utterance floor; smallest is fuel at 91.

## STEP 5 / STEP 6 — End-to-end behaviour (real `ChatService`)

Harness: `app/inventory_system/phase11a_e2e.py`. A single-car model was pinned by registration,
then bare field questions were asked; separately, the same questions were asked
cold (no pin).

**Pinned car → answers from that car's field:**

| Ask | Reply (abridged) |
|---|---|
| `Color?` | 2015 White Litiva — colour **White** hai. |
| `Fuel?` | … fuel **Petrol** hai. |
| `Transmission?` | … **Automatic** (gear) hai. |
| `KM?` / `Running?` / `Kitni chali?` | … **14,000 km** chali hai. |
| `Owner?` | … yeh **3 owners** wali gaadi hai. |
| `Final?` | 2015 White Litiva **₹5.15 lakh**. |
| `EMI?` | … downpayment **~₹1.03 lakh** (20%) … |
| `Transfer?` / `NOC?` / `Fitness?` / `Original papers?` | RC / documents answer |
| `Claim hua?` / `Insurance?` | insurance answer (type/validity/claim history) |
| `Touch-up?` | condition answer (accident-free/flood/repaint/…) |
| `Warranty?` / `Guarantee?` | warranty answer |
| `Service history?` | service answer |

Empty spreadsheet columns render **"Data not available" / "visit pe confirm"** —
never a fabricated value (no-fabrication guardrails intact).

**Cold (no vehicle pinned) → clarify, not a wrong answer (STEP 6):**

```
RC?            -> RC / documents kis gaadi ke chahiye?
Color?         -> Kis gaadi ka colour poochh rahe hain?
Fuel?          -> Kis gaadi ka fuel type chahiye?
Transmission?  -> Kis gaadi ka transmission chahiye?
kitni seats    -> Kis gaadi ki seating chahiye?
KM?            -> Kis gaadi ki km reading chahiye?
Claim hua?     -> Kaunsi gaadi ki insurance details chahiye?
Final?         -> Kis gaadi ki price chahiye?
Warranty?      -> Warranty kis gaadi ki dekhni hai?
Owner?         -> Owner details kis gaadi ke chahiye?
```

## STEP 8 — Regression (nothing broken)

Full suite `python -m pytest *_tests.py`:

| Run | Result | Wall time |
|---|---|---|
| Baseline (before Phase 11A) | **464 passed, 5 failed** | 353 s |
| After Phase 11A (+17 new tests) | **481 passed, 5 failed** | **99 s** |

The **5 failures are identical and pre-existing** — all caused by the leftover
manual-test car `MH99ZZ9999` (a fake Swift) plus one stale count assertion, none
introduced by Phase 11A:

- `hardening_tests … test_refresh_returns_ok_and_count` (expects 40, live count 45)
- `inventory_retrieval_tests … test_swift_available_hai` (test Swift now in stock)
- `inventory_retrieval_tests … test_swift_not_in_stock_offers_segment` (same)
- `media_api_tests … test_unknown_still_flagged` ("999" trailing-matches the reg)
- `media_tests … test_real_unknown_vehicle` ("Swift photos" now resolves)

Memory / browse / variant / follow-up / budget / search / media / owner /
inventory paths all remain green.

## Performance note

`_has()` recompiled a boundary regex on every call (~1,200 calls/parse). Once the
field vocabularies grew, the stdlib `re` cache (512 entries) thrashed and parse
took **~300 ms**. Caching the compiled pattern per phrase (`_has_pattern`, plus an
`lru_cache` on `_norm`) — a pure, behaviour-preserving optimisation — brought parse
to **~1.5 ms** (≈200×), which is also why the suite dropped from 353 s to 99 s.
