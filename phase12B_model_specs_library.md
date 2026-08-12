# Phase 12B — Model Specifications Library

`app/inventory_system/model_specs.py` — a deterministic reference library that
maps **make → model → (variant) → (year)** to standard factory specifications, so
the same facts are not re-typed for every car of a model.

## Two hard rules

1. **Owner data always wins.** `apply_specs(item)` fills a field **only** when the
   car's own value is still `None`. Anything the dealership typed (Excel/panel) is
   never overwritten.
2. **No fabrication.** Only KNOWN models return specs. Unknown make/model → `{}` →
   field stays `None` → chatbot says *"Data not available."* Nothing is invented
   from a segment default.

## What it fills vs never touches

- **Auto-fills (`SPEC_FIELDS`, factory-standard):** engine, transmission detail,
  mileage/tank, dimensions, exterior/lights, interior/comfort, convenience,
  infotainment, safety.
- **Never touches (`DEALERSHIP_FIELDS`, per car):** price, km, owners, insurance,
  RC, condition, service, accident, warranty, remarks, keys, EV battery health,
  road tax, PUC, fitness, usage type, media. (The two sets are provably disjoint —
  enforced by a test.)

## Resolution (most-specific-wins, deterministic)

```
resolve_specs(make, model, variant, year):
   base            = SPECS[make][model]["base"]
   + year-range overrides   (if year in range)
   + variant overrides      (highest precedence)
   → keep only whitelisted SPEC_FIELDS
```

- Make/model keys are **accent-folded + lowercased** (`_norm_key`), so "Škoda"
  matches the `skoda` entry.
- Variant matching is substring-tolerant (dealer variant codes are messy).

## Seed coverage (today)

- **30 models** seeded across Hyundai, Maruti Suzuki, Honda, Tata, Volkswagen,
  Škoda, Toyota, Mahindra, Kia, Ford, MG, Chevrolet.
- On the live sheet: **37 / 45 cars (82%)** match, **~12.8 spec fields auto-filled
  per matched car**.
- Values are generation-typical (dimensions, tank, mileage-ARAI, engine, core
  safety/comfort). Extend/verify per dealership records — **adding a model is a
  one-line dict entry**.

## Extending the library

```python
SPECS["kia"]["seltos"] = {"base": {"engine_cc": 1497, "boot_litres": 433, ...},
                          "variants": {"gtx": {"sunroof_type": "Single", "airbags": 6}},
                          "years": [(2019, 2022, {"ncap_rating": 5})]}
```

Unmatched models on the current sheet (candidates to add): Mercedes-Benz C Class,
E 200; Audi A4; Jeep "Litiva"; Toyota Corolla (plain); rows with a missing make.
These simply return "Data not available" until seeded — safe and honest.

## Public API
- `resolve_specs(make, model, variant=None, year=None) -> dict`
- `apply_specs(item) -> item`  (owner-wins, exception-safe)
- `coverage_for(item) -> {known, fillable}`
- `known_models() -> list[str]`
- constants `SPEC_FIELDS`, `DEALERSHIP_FIELDS`
