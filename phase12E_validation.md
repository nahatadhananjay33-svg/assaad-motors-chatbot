# Phase 12E — Validation

Suite: `app/inventory_system/phase12e_conversation_tests.py` — **17 tests, all
passing** (runs under the normal `*_tests.py` sweep). Two layers: the mode
classifier (unit) and real `ChatService` conversation flows (behaviour), on a
workbook copy. Deterministic, no LLM.

## Classifier unit tests
| Test | Covers |
|---|---|
| `test_current_car` | RC/insurance/owners/km/boot/sunroof/music/airbags + pin → current_car |
| `test_current_car_needs_pin_else_clarify` | same questions, no pin → clarify |
| `test_same_model_variant` | automatic/petrol/kam-km/first-owner/white wali → same_model_variant |
| `test_variant_refinement_stays_same_model` | "diesel automatic", "lowest km car" → same_model_variant |
| `test_new_search` | 7-seater / SUV<8L / Creta / sunroof-wali / <5L → new_search |
| `test_multi_intent` | sunroof+airbags, boot+GC, sunroof+alloy, airbags+camera → multi_intent |
| `test_conflict_is_clarify` | petrol diesel / automatic manual / white black → clarify |
| `test_disjunction_not_conflict` | "petrol ya diesel?" is NOT a conflict |
| `test_faq_and_offsheet` | finance/exchange → faq; gibberish → offsheet_unknown |
| `test_languages` | Devanagari attribute Qs (बूट स्पेस/एअरबॅग) + pin → current_car |

## Behaviour tests (real ChatService)
| Test | Proves |
|---|---|
| `test_step9_sequence` | Ertiga → automatic wali (same-model, all Ertiga) → RC (current car, found) → 7 seater (new_search) |
| `test_pinned_answers_pinned_car` | pinned Creta + "boot space kitna?" → found, "433" |
| `test_cold_attribute_clarifies` | "sunroof hai?" cold → clarify |
| `test_conflict_clarifies` | "petrol diesel" → clarify status |
| `test_multi_intent_answers_all` | pinned Creta + "airbags kitne aur boot space?" → "6" and "433" |
| `test_missing_data_not_fabricated` | pinned + "spare key hai?" → "Data not available" |
| `test_fresh_search_not_stuck_on_previous` | pinned Creta + "7 seater chahiye" → new_search, not the pinned car |

## End-to-end mode trace (live)
```
Show me Ertiga            new_search          [multi]
automatic wali?           same_model_variant  [found]
petrol wali?              same_model_variant  [found]
RC?                       current_car         [found]
sunroof aur airbags hain? multi_intent        [found]
7 seater chahiye          new_search          [multi]
SUV under 8 lakh          new_search          [multi]
petrol diesel             clarify             [clarify]
finance milega?           faq                 [faq]
xyz random gibberish      offsheet_unknown    [exhausted]
```

## Notes
- "boot space aur mileage?" resolves fully when mileage is phrased as "mileage
  kitna" — bare "mileage" is deliberately left as a browse term (so "good mileage"
  searches aren't hijacked). Fully-resolving multi pairs are tested instead.
- The classifier is READ-ONLY (`meta["conversation_mode"]`); it changes no answer.
