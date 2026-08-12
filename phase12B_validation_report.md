# Phase 12B — Validation Report

Suite: `app/inventory_system/phase12b_specs_tests.py` — **14 tests, all passing**
(runs under the normal `*_tests.py` sweep). Deterministic; no LLM.

## What was validated

| Area | Assertion | Result |
|---|---|---|
| Field separation | `SPEC_FIELDS` and `DEALERSHIP_FIELDS` are disjoint | ✅ |
| Model completeness | every SPEC + DEALERSHIP field exists on `InventoryItem` | ✅ |
| Resolve — known | `resolve_specs("Hyundai","Creta").engine_cc == 1497` | ✅ |
| Resolve — unknown | unknown/None make+model → `{}` (no fabrication) | ✅ |
| Resolve — accents | "Škoda Rapid" matches the `skoda` key | ✅ |
| Resolve — whitelist | only `SPEC_FIELDS` are ever returned | ✅ |
| Apply — fill empty | empty spec fields auto-filled (engine 1497, boot 433) | ✅ |
| Apply — **owner wins** | owner `airbags=2`/`boot=400` NOT overwritten (lib 6/433) | ✅ |
| Apply — unknown | unknown model left fully untouched | ✅ |
| Apply — never dealership | apply_specs changes no `DEALERSHIP_FIELDS` | ✅ |
| Apply — deterministic | same model → identical spec fields across items | ✅ |
| Backward compat | `InventoryItem(reg)` constructs with no new args | ✅ |
| Live load | sheet loads, existing fields unchanged, known model auto-fills, ≥50% matched | ✅ |
| Excel override | every spec field is wired to a header (owner CAN override) | ✅ |

## Behavioural proof points

- **No fabrication:** unseeded models (C Class, A4, plain Corolla) keep every spec
  `None` → "Data not available".
- **Owner authority:** a value present in Excel or set on the item always beats the
  library.
- **Determinism:** identical input → identical output, every run.
- **Live coverage:** 37/45 cars (82%) enriched, ~12.8 specs/car, e.g. Creta →
  engine 1497cc, boot 433L, tank 50L, ARAI 16.8, 6 airbags, ABS, FWD.

## Scope honoured
No chatbot, intent engine, conversation policy, media, or auth code was modified.
Only the inventory data layer (model + loader + spec library + utility + tests).
