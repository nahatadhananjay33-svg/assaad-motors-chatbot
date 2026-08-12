# Phase 12J — Context & Data Completeness Hardening — Final Report

**Goal.** Fix four remaining items before manual testing, deterministically (NO
LLM), additively and reversibly, on top of 12I: (1) `mileage?` ambiguity,
(2) `automatic aur petrol?` ambiguity, (3) model-only pinning when multiple cars
exist, (4) vehicle-data completeness visibility.

**Result.** All four addressed. Full suite **633 passed / 0 failed** (612 baseline
+ 21 new). No architecture redesign; no auto-population; no fabrication; auth /
security / media / Supabase untouched.

---

## 1. What was fixed

### (1) Mileage — `mileage?`
Bare `mileage?` used to dump 34 cars. It is genuinely ambiguous (running vs km/l),
so it now returns **one deterministic clarify**: *"Aap running (kitne km chali hai)
pooch rahe ho ya mileage (km/l average)?"*. The specific forms are unchanged and
already correct: `mileage kitna/kya hai` → **kmpl** (ARAI field), `kitne km chali`
/ `running kitni` → **odometer**. Never price, never a random search. (Added bare
`"mileage"` to `AMBIGUOUS_FIELDS`.)

### (2) automatic + petrol
`automatic aur petrol hai?` already answered **both** attributes of the pinned car
(12I combiner) and `automatic petrol wali dikhao` / `...chahiye` already
**searched**. The only gap — bare `automatic aur petrol?` (a coordinated
two-attribute FILTER with no `hai` and no search word) — is genuinely ambiguous, so
it now **clarifies**: *ask `automatic petrol hai?` to question, `automatic petrol
wali dikhao` to search*. (New parser flag `attr_pair_ambiguous`, RULE E.)

### (3) Model-only pinning with multiple cars
When the pinned context is a **model with more than one facing car** and the turn
is an attribute question (no new vehicle, no search cue, no filter):
- **all matches share the same value** → answer the **common value**:
  *"Dono Ertiga — 7 seater."*, *"Dono Ertiga — Airbags: 2 airbags."*
- **values differ** → **clarify which variant**: *"Humare paas 2 Ertiga hain —
  2019 Automatic Hybrid ya 2016 Manual Petrol. Aap kaunsi wali pooch rahe hain?"*

No silent pick of `matches[0]`. Single-car model pins (Fortuner) and same-model
variant search (`automatic wali dikhao`) are unchanged. Also fixed a seats-vocab
gap so `kitne seater hai?` is recognised as a seats question. (New
`ChatService._model_multi_followup`, `_attr_intent_signature` in the formatter.)

### (4) Data completeness visibility
**No auto-population** — the Excel / Vehicle Details data stays the source of
truth. The existing Vehicle Details UI already had a full deterministic
completeness system (Required/Recommended/Optional badges, per-section + overall %
bars, "Ready for sale / N required left", "Missing required" list, and a
buyer-facing ✓/✗ feature summary). The only gap was **breadth**: buyer-facing
feature/document fields the chatbot answers (Parking Sensors, Touchscreen,
Speakers, Boot Space, Ground Clearance, Mileage, RC Status, Warranty…) were
Optional (unbadged) and mostly absent from the ✓/✗ summary. A **minimal additive**
widening of the `RECOMMENDED` set and the buyer-facing `SUMMARY` now badges and
shows ✓/✗ for them — nothing made mandatory, no field added, no value invented.

---

## 2. What was intentionally left ambiguous / unchanged
- `mileage kitna/kya hai?` = **kmpl** (the ARAI field, populated 33/45) — not
  treated as odometer.
- `automatic diesel` / `automatic petrol` **without** a coordinator/`hai`/search
  word — a quick two-filter browse (unchanged).
- Devanagari bare `कितने सीटर` collides with the pre-existing MUV category cue
  `सीटर`, so it classifies as a search, not a seats question (Hinglish
  `kitne seater hai?` works). Pre-existing; not touched to avoid category-search
  regressions. Documented limitation.
- Blank owner-entered fields stay **"Data not available"** — never fabricated.

## 3. How multi-car model context now behaves
| Situation | Behaviour |
|-----------|-----------|
| model pinned, 1 car | pin it; answer attribute questions directly (unchanged) |
| model pinned, >1 cars, asked attribute is **identical** across all | "Dono/Saari N `<model>` — `<value>`" (common answer) |
| model pinned, >1 cars, asked attribute **differs** | clarify listing each variant (year + transmission + fuel) |
| model pinned, >1 cars, `...wali dikhao` / filter | same-model variant search (unchanged) |
| model pinned, >1 cars, media / availability | existing media / listing flow (unchanged) |

## 4. Data-completeness improvements
- `RECOMMENDED` widened to the buyer-facing feature/document fields (badge nudge).
- Buyer-facing `SUMMARY` ✓/✗ row extended (Parking Sensors, Touchscreen, Speakers,
  Boot Space, Mileage) with matching render special-cases.
- Underlying system (badges, %, ready-for-sale, missing-required) was already
  sufficient and is unchanged.

## 5. What was NOT changed
- Auth / security / media / Supabase — untouched.
- Retrieval, memory, 11B scoring, 12E modes, all 12D/12G/12I behaviour — unchanged
  (all changes ride on top).
- No LLM. No model-spec auto-population. No new Excel columns. Nothing made
  mandatory in the UI.

## 6. Test results
- New: **21** (`phase12j_tests.py`) — parser flags, mileage, attribute-pair,
  model-only (unique/multi/common/differ/variant), single-car pin, Devanagari, and
  a real **edit → save → refresh → chatbot answers the saved value** data test
  (proving no fabrication and end-to-end persistence).

## 7. Regression result
**633 passed / 0 failed** (612 + 21). One intermediate failure
(`test_price_followup_untouched`) was the *intended* Item-3 change (multi-car price
follow-up now clarifies instead of silently picking); its fixture was switched to a
single-car model so it still tests its real purpose (no consultative intro on a
price follow-up). Details in `phase12J_regression.md`.

## 8. Performance (no meaningful regression)
`app/inventory_system/phase12j_perf.py`, 12J utterances (multi-car pin exercised):

| Metric | 12F baseline | 12J |
|--------|--------------|-----|
| `parse()` | ~2.3 ms | **1.92 ms** |
| `parse()+analyze()` | ~2 ms delta | **0.83 ms delta** |
| `conversation_policy` | ~4.4 ms | **2.07 ms** |
| `handle()` end-to-end | mean ~32 / median ~29 ms | **mean 30.0 / median 28.2 / p95 44 ms** (n=6000) |

## 9. Remaining limitations
1. **Model-only pin, model-only context** requires the pin to be a *model* (from a
   model search). A single registration always pins one car directly.
2. **Devanagari `कितने सीटर`** → MUV search (category-cue collision, pre-existing).
   Use `kitne seater hai?` (Hinglish) or another attribute.
3. Blank buyer-facing fields remain "Data not available" until **staff enter them**
   (the Vehicle Details UI now flags them as Recommended/✗) — by design, never
   auto-filled.
4. A KM/price follow-up's `meta` intent label may read `price` while the **answer**
   is the odometer (cosmetic; carried over from 12I).
5. Vehicle Details UI change verified by JS-syntax/delimiter check; a **visual
   render pass in the browser is a manual step** (no automated HTML tests).

## 10. Ready for manual testing?
**Yes.** All four items are fixed deterministically with no fabrication and no
regression (633/0). Recommended manual passes:
- Multi-turn sessions on **multi-car models** (Ertiga, Nexon, Polo, Alto, City,
  Corolla Altis, KUV100, Mobilio, C Class): confirm common-value answers and
  variant clarifications across EN / Hindi / Hinglish / Marathi.
- `mileage?` vs `mileage kitna?` vs `kitne km chali?`; `automatic aur petrol?` vs
  `...hai?` vs `...wali dikhao`.
- Vehicle Details: open a car, confirm the RECOMMENDED badges + ✓/✗ summary flag
  the blank buyer-facing fields; fill one, save, reload, and confirm the chatbot
  answers it.

---

**FINAL:** Phase 12J is complete — the four hardening items are done, the system is
deterministic, and the suite is green (633/0). **No further phase was started.**
