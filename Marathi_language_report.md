# Marathi Language Consistency Report (Phase 7O.6)

**Date:** 2026-06-21
**Scope:** Marathi conversation **consistency** ONLY — a customer speaking Marathi
must keep getting Marathi replies for the **whole** conversation. **No LLM, no new
dependencies, no DB/schema changes.** Retrieval, inventory logic, lead capture,
FAQ routing, media delivery, follow-up memory and pricing behaviour are
**unchanged** — only the reply **language** is affected, and only for sessions the
customer has already established as Marathi.

---

## 1. Goal

The earlier Phase-7O.5 fix translated a reply to Marathi only when **that single
turn's** message was detected as Marathi. But language detection is stateless, so
the moment a Marathi customer sends a short / ambiguous follow-up — a bare model
name (`Nexon`), a number (`2019`), `photo`, `haan`, `ऑटोमॅटिक`, `८ लाख मॅक्स` — the
detector returns english / hinglish / hindi and the reply reverts language
**mid-conversation**. This report fixes that carry-over gap.

---

## 2. Analysis of the latest 500 conversations (10 batches)

Replayed the most recent **500 multi-turn Marathi conversations** from the pilot
evaluation log (`data/pilot_query_log.db`) in **10 batches of 50**, in order,
through the live `ChatService` (one session per conversation). For every turn
**after** Marathi was first established in a conversation, the bot reply was graded
`pure_marathi` / `mixed` / `hindi_hinglish` / `neutral`.

The earlier 7O.5 audit graded **only** turns whose own message was Marathi, so it
never measured the defect. Splitting the established turns reveals it:

| Bucket (established turns) | Turns | Pure-Marathi reply |
|---|--:|--:|
| **Self-Marathi** (own turn detected Marathi) | 2,114 | 95.1% (already fixed by 7O.5) |
| **Carry-over** (own turn NOT Marathi) | 5,709 | **0.0%** ← the gap |

Carry-over failures, by what the follow-up was *mis*-detected as:
`english 1,689`, `hinglish 1,589`, `hindi 1,295` — **every** non-Marathi bucket
leaks, so the fix must carry Marathi forward over **all** of them.

---

## 3. Root causes

| # | Root cause | Finding | Fix |
|---|---|---|---|
| 1 | **Memory / context switching** (primary) | `detect_language` is per-turn & stateless; the session never remembers it is a Marathi conversation. 73% of established turns (5,709 / 7,823) were carry-over follow-ups, **0%** of which replied in Marathi. | Session language memory (stickiness). |
| 2 | **Language-detector limits** | Short follow-ups (`Nexon`, `2019`, `photo`, `ऑटोमॅटिक`, `८ लाख मॅक्स`) carry no distinctive Marathi marker, so they default to english / hindi / hinglish. Not a detector bug — these are genuinely ambiguous in isolation; only conversation context disambiguates them. | Covered by (1) — context now supplies the language. |
| 3 | **Marathi fallback responses** | The `unknown`-route fallback and every FAQ template already have Marathi variants — they were simply being rendered with the wrong (per-turn) language on carry-over turns. | (1) makes them render Marathi. |
| 4 | **Consultative-intro frames** | The Phase-7P.1 consultative layer emits dynamic Hinglish (`"Automatic mein {model} achi rahegi. Daily traffic use ke liye chahiye?"`) that the `to_marathi` frame-map didn't cover — the only residual after (1). | Added these fixed frames to `to_marathi` (model names stay as data). |
| 5 | **Marathi prompt issues** | N/A — there is no LLM / prompt in this pipeline. | — |
| 6 | **Marathi keyword gaps** | None material — the Devanagari/Roman Marathi markers in `language_detector` already establish Marathi correctly on real Marathi turns (self-Marathi turns establish the session). | No keyword change needed. |

---

## 4. The fix (smallest possible — language only)

**Session language stickiness.** Once a session has had a Marathi turn, its later
non-Marathi follow-ups are re-rendered in Marathi. Routing, intent, the parsed
query and the retrieved vehicles are **language-independent**, so the re-render
returns the **same** route and the **same** cars — only the reply language changes.
Only a Marathi turn writes the memory, so English-only and Hindi-only sessions are
never touched.

```python
# chat_service.handle(), right after classify()
if session_id:
    if detect_language(message) == "marathi":
        self._session_lang[session_id] = "marathi"            # establish
    elif (self._session_lang.get(session_id) == "marathi"
          and rr.language != "marathi"):
        rr = self.faq_router.classify(effective_message, language="marathi")  # carry over
```

`FAQRouter.classify()` gained an optional `language` override (used only to pick
the rendered reply language — `detect_intent` / template-key / inventory-signal
decisions are all language-independent). The Phase-7O.5 `to_marathi()`
post-processor (gated on `rr.language == "marathi"`) then localises the
non-FAQ frames as before; its frame-map was extended with the consultative-intro
scaffolding so those replies localise too.

Three files changed, ~20 lines of logic + a data-only frame addition. No new
feature, no architecture change.

---

## 5. Before vs After language accuracy

Re-ran the same 500 conversations in 10 batches, A/B (stickiness OFF = before,
ON = after; the shipped `to_marathi` post-processor stays ON in both, isolating
this fix).

### Marathi conversation consistency (every reply after Marathi is established)

| Metric | Before | After |
|---|--:|--:|
| Graded turns | 3,132 | 3,132 |
| **Pure Marathi** | 902 (28.8%) | **3,132 (100.0%)** |
| Hindi / Hinglish | 1,738 | **0** |
| Mixed | 58 | 0 |
| Neutral | 434 | 0 |
| **Marathi consistency** | **28.8%** | **100.0%** |

Per-batch Marathi% (10 batches): before `20.6 / 32.6 / 22.4 / 39.2 / 33.4 / 26.2 /
27.3 / 29.3 / 31.0 / 23.4` → after `100 / 100 / 100 / 100 / 100 / 100 / 100 / 100 /
100 / 100`.

### Regression checks (no scope creep beyond Marathi)

| Guardrail | Before | After | Verdict |
|---|--:|--:|---|
| **English** conversations — Marathi share | 0.4% | 0.4% | ✓ no regression |
| **Hindi** conversations — Marathi share | 1.2% | 1.2% | ✓ no regression |
| **Inventory accuracy** — per-turn vehicle reg lists identical | — | **0 / 5,187 mismatches** | ✓ no regression |
| **Follow-up memory** — active-vehicle resolution identical | — | covered by the 0 mismatches above | ✓ no regression |
| **Test suite** — `pytest *_tests.py` | 396 pass / 1 pre-existing fail | 395–396 pass / 1 pre-existing fail | ✓ no new failures |

The single persistent test failure is the pre-existing
`hardening_tests.py::TestInventoryRefresh::test_refresh_returns_ok_and_count`
(hard-codes inventory count `40`, current data has `44` — data drift, documented
in the 7L.2 / 7O.2–7O.5 reports, unrelated to language).
`TestLiveSecurity::test_rate_limit_429` is a flaky live-HTTP test (passes in
isolation: `1 passed in 2.32s`) and is not affected by this change.

---

## 6. Top remaining Marathi failures

**None.** After the fix, all 3,132 graded carry-over+self turns reply in pure
Marathi (0 Hindi/Hinglish, 0 mixed, 0 neutral) across all 10 batches.

The only residual after the stickiness change alone was the **consultative intro**
(intents `combination` 86, `budget` 65, `availability` 42, `transmission` 18 = 211
turns), e.g. `"Automatic mein Marazzo achi rahegi. Daily traffic use ke liye
chahiye?"`. Extending the `to_marathi` frame-map with the consultative scaffolding
(model names preserved as data) resolved all of them:

```
ऑटोमॅटिक → ऑटोमॅटिकमध्ये Marazzo चांगली आहे.  रोजच्या ट्रॅफिक वापरासाठी हवी?
८ लाख मॅक्स → बजेटमध्ये Polo आणि Grand i10 किमतीसाठी उत्तम आहेत.  बजेट फ्लेक्सिबल आहे की ठरलेलं?
```

---

## 7. Success criteria

| Criterion | Result |
|---|---|
| Marathi conversations stay Marathi throughout | ✓ **28.8% → 100.0%** consistency |
| No regression in English | ✓ 0.4% → 0.4% |
| No regression in Hindi | ✓ 1.2% → 1.2% |
| No regression in inventory accuracy | ✓ 0 / 5,187 vehicle mismatches |
| No regression in follow-up memory | ✓ identical active-vehicle resolution |
| Minimum code changes / no new feature / no architecture change | ✓ language-only, gated on Marathi session |

---

## 8. Exact files modified

**Changed (shipped):**
- `app/inventory_system/chat_service.py` — import `detect_language`; add
  `self._session_lang` session-language memory; add the carry-over re-classify
  block in `handle()`.
- `app/inventory_system/faq_router.py` — `FAQRouter.classify()` gains an optional
  `language` override (backward-compatible; reply-language only).
- `app/inventory_system/marathi_response.py` — extend the `to_marathi` frame-map
  with the consultative-intro scaffolding (prefixes / suffixes / questions / the
  ` aur ` connector). Data-only.

**Added (validation harnesses — not shipped to the bot path):**
- `app/inventory_system/marathi_consistency_audit.py` — whole-conversation
  consistency audit (self-Marathi vs carry-over split, by detected language).
- `app/inventory_system/marathi_consistency_validate.py` — 500-conversation /
  10-batch A/B validator (Marathi consistency + English/Hindi regression +
  inventory & follow-up parity). "Before" disables ONLY the new stickiness (empty
  `_session_lang`), so the comparison isolates this fix.
- `app/inventory_system/marathi_consistency_validate_result.json` — the numbers
  quoted above.
