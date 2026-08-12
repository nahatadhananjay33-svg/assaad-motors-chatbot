# Phase 12D — Deterministic Intent Recognition for New Vehicle Fields (Report)

## Objective
Extend the Phase 11A/11B deterministic engine so the chatbot understands natural
questions about ALL the new vehicle-detail fields added in Phase 12B/12C — no LLM,
reusing the existing engine, no redesign, no changes to auth / permissions / panels
/ media / Supabase / Excel. Excel remains the source of truth; nothing fabricated.

## What was built (additive, modular, reversible)
- **`field_intents.py`** — a data-driven vocabulary (`FIELD_SPECS`) for **67 new
  fields** (EN/HI/Hinglish/Marathi aliases, role = attribute-only / filterable) +
  `detect()` (attribute vs filter, multi-field).
- **`query_parser.py`** — sets `q.attr_fields` / `q.feature_filters`; deconflicts
  the 5 substring collisions; removes sunroof/airbag from off-sheet.
- **`response_formatter.py`** — one generic branch answers the pinned car's
  field(s) (multi-field), no fabrication.
- **`retrieval_engine.py`** — a generic hard feature-filter.
- **`faq_router.py` / `chat_service.py`** — route new-field questions to inventory;
  cold → "Sure — kis gaadi ke details chahiye?"; pinned reuse via existing memory.
- **`intent_intelligence.py`** — new fields fed into scoring/multi-intent (reused vocab).

## Coverage
- **Fields covered (67):** engine, transmission-detail, economy, dimensions,
  exterior & lights, interior & comfort, convenience, infotainment, safety, keys,
  accessories, extra documents, EV. (Already-covered by 11A: km, owners, colour,
  fuel, transmission, seats, price, insurance, RC, service, warranty,
  condition/accident/flood, year, media — unchanged.)
- **Fields NOT covered (no schema field exists):** power steering, central locking,
  heater, USB/AUX as standalone, TPMS, dash-cam, GPS, cylinders, seat-covers,
  memory-seats (standalone), battery-kWh — these have no Phase-12B column, so they
  are honestly out of scope (would need a schema field first).
- **Languages:** English, Hindi, Hinglish, Marathi (Devanagari).
- **Attribute-query coverage:** all 67. **Filter coverage:** 20 `both`-role fields
  (sunroof, airbags, camera, alloy, ABS, ESP, cruise, keyless, push-button,
  android-auto, drivetrain, transmission-subtype, headlamp, DRL, fog, upholstery,
  rear-AC, ventilated, parking-sensors, usage). 47 are attribute-only by design.
- **Multi-intent:** yes (`attr_fields` list — no secondary field lost).
- **Pinned-car:** answers from that car. **No car pinned:** clarifies, never invents.
- **Missing data:** "Data not available" — never fabricated.

## Results
- **Test count:** 5,985 recognition utterances + 13 pytest cases.
- **Accuracy:** **100%** recognition; all 13 pytest pass.
- **Performance:** `parse()` **1.80 ms/query** (+0.44 ms vs pre-12D; within target;
  no regex-cache regression). `parse()+analyze()` 2.50 ms.
- **Regression:** **534 passed, 2 failed** — same 2 pre-existing/stale failures,
  zero new (3 sunroof off-sheet tests intentionally updated — see regression doc).

## Remaining gaps
- Fields with no schema column (list above) — need a Phase-12B column before
  recognition is meaningful.
- Typo tolerance for new fields is curated (aliases) + the 11B Levenshtein layer;
  not every misspelling of every field is enumerated.
- Feature filters return results only where the field has data (spec-auto-filled or
  dealership-entered); sparse dealership fields will match few cars until filled.

## Deliverables
`phase12D_intent_audit.md`, `phase12D_intent_dictionary.md`,
`phase12D_validation.md`, `phase12D_regression.md`, `phase12D_report.md`;
code: `field_intents.py`, `phase12d_field_tests.py`, and additive edits to
`query_parser.py`, `response_formatter.py`, `retrieval_engine.py`, `faq_router.py`,
`chat_service.py`, `intent_intelligence.py`.

---

## FINAL VERDICT

**PHASE 12D: ✅ COMPLETE**

All 67 new vehicle fields are recognised deterministically (100% on 5,985
utterances across 4 languages), answered from the pinned car (or clarified when no
car is pinned), filterable where it makes business sense, multi-intent aware, and
never fabricated. Parser stays fast (1.80 ms) with no regex-cache regression, and
the full suite shows zero new failures (534 pass; the 2 fails are pre-existing
stale tests). The only behavioural change — sunroof/airbags moving from "off-sheet"
to answerable — was required by the spec, is documented, and its 3 tests were
updated. No LLM, no redesign, and no auth/permissions/panel/media/Supabase/Excel
systems were modified.
