# Phase 12A — Implementation Roadmap (STEP 8)

*Recommendation only. Nothing implemented in 12A.* The safest order to build the
v2 knowledge model into the live, deterministic Assad Motors chatbot, keeping every
phase backward compatible and testable — mirroring how Phases 10/11 were shipped.

---

## Guiding principles
- **Data before features:** filling the empty structured fields (🟡) needs zero
  code and instantly improves answers — do it first.
- **Spec-library over per-car entry:** a `model_specs` reference table (make+model+
  variant+year → specs & standard features) auto-answers most 🔴 fields with minimal
  data-entry burden.
- **Additive, reversible steps:** every phase must leave existing tests green and be
  toggle-able, exactly like Phase 11B's `INTEL_CONFLICT_CLARIFY`.
- **No LLM, ever:** all answers stay deterministic.
- **Full regression after each phase** (the `*_tests.py` suite + new tests).

---

## Phase 12B — Inventory Schema Expansion  *(data + model)*
**Do:**
1. Add Excel columns for the 🟡 fields that already exist in the model (condition,
   service, docs, insurance, warranty, sales) so owners can actually fill them.
2. Add the 🔴 new fields to `InventoryItem` + loader (header-located, like media).
3. Build the **`model_specs` reference library** (a second sheet or JSON) and a
   deterministic merge: per-car value overrides the model-level spec.
**Risk:** low (additive columns; loader is header-driven).
**Exit test:** loader reads new columns; unknown → Unknown (not fabricated);
existing 498-test suite still green.

## Phase 12C — Inventory UI Expansion  *(owner panel)*
**Do:**
1. Group the owner-panel edit form into the v2 sections (collapsible).
2. Tier-1 mandatory, Tier-2 high-value, Tier-3 auto-filled-from-spec-library
   (editable override).
3. Field-scoped editing already exists (Finance/Document staff) — extend scopes.
**Risk:** medium (UI only; no chatbot change).
**Exit test:** owner can fill every v2 field; role scoping enforced; audit logs entries.

## Phase 12D — Intent Engine Upgrade  *(recognition of new fields)*
**Do:**
1. Extend Phase 11A field-intent dictionaries + Phase 11B families for the new
   fields (sunroof, airbags, mileage, camera, boot space, EV, keys, PUC, road tax…).
2. Add answer branches in `response_formatter` for the new attribute questions
   (same pattern as colour/fuel/seats in 11A).
3. Keep the value-vs-question and conflict logic from 11B.
**Risk:** low-medium (additive vocab + formatter branches; proven pattern).
**Exit test:** new "≥50 queries/field" packs (like `phase11a_intent_tests.py`);
100% field resolution; regression green.

## Phase 12E — Conversation Intelligence  *(policy engine)*
**Do:**
1. Implement the deterministic **policy table** (`phase12A_conversation_policy.md`):
   pattern → steps → template keys.
2. Add small deterministic lexicons for emotion / harshness / urgency (the only
   detection gaps).
3. Wire additively into `chat_service` behind a flag (like 11B), meta-first, then
   enable behaviours after regression.
**Risk:** medium (touches conversation flow) — mitigate with flag + meta-only first.
**Exit test:** policy unit tests per pattern; existing memory/browse/variant/FAQ
tests unchanged.

## Phase 12F — Production Testing & Rollout
**Do:**
1. Massive validation (thousands of assertions, all languages) like Phase 11B.
2. Real-data pass: fill 5–10 real cars fully; manual owner UAT (modules-style).
3. Performance benchmark (parser must not regress).
4. Cleanup: remove test cars (e.g. MH99ZZ9999/TEST0001), reset audit.db, refresh
   intent_analytics.json.
5. Restart server, re-login, verify live.
**Exit:** all reports pass; sign-off.

---

## Sequencing rationale

```
12B (fields+data)  →  12C (entry UI)  →  12D (understand new fields)
        →  12E (converse better)  →  12F (validate + ship)
```

- **12B first** because it unlocks the 🟡 quick wins and lays the field foundation.
- **12C before 12D** so there is real data to answer *from* before teaching the bot
  to recognise the questions.
- **12D before 12E** so factual answers are solid before layering persuasion/policy.
- **12F last** as the safety gate.

## Effort vs impact

| Phase | Effort | Answer-quality impact | Risk |
|---|---|---|---|
| 12B | Medium (mostly data + columns) | **High** (unlocks 🟡 + spec library) | Low |
| 12C | Medium (UI) | Medium (enables entry) | Medium |
| 12D | Low-Med (proven pattern) | **High** (specs/features answerable) | Low-Med |
| 12E | Medium | Medium-High (sales quality) | Medium |
| 12F | Medium | Assurance | Low |

## The one big lever
Build the **`model_specs` library** in 12B. It converts ~45 missing spec/feature
fields from "manual entry per car" into "auto-filled by make+model+variant+year",
which is what makes answering Sections D–Q of the question bank feasible without an
LLM and without overloading the owner's data entry.

---

## Final blueprint statement
The engine (parser, intelligence layer, retrieval, formatter, media, roles, audit,
4-language) is production-ready and deterministic. The next generation is a
**data + policy** effort: expand the fields (12B), make them easy to enter (12C),
teach the bot to recognise them (12D), converse like a pro (12E), and validate
(12F) — each step additive, reversible, LLM-free, and regression-gated.
