# Phase 12G — Validation

Focused deterministic tests in `phase12g_context_tests.py` — **27 tests, all pass**
— plus an instrumented end-to-end trace (`phase12g_trace.py`) on a copy of the
live workbook. Pinned probe car: single **Fortuner** (year **2011**, transmission
**Manual**, odometer **169,773 km**). NO LLM.

## Test groups (27)
| Group | Tests | What it proves |
|-------|-------|----------------|
| `TestParserReclassification` | 7 | Lexical discriminator: year/km/transmission attribute questions → `*_query`; every search/variant phrasing keeps its filter/sort. |
| `TestModes` | 3 | Pinned attribute → `current_car`; unpinned attribute → `clarify`; search language → not `current_car`. |
| `TestBehaviour` | 17 | Real `ChatService` answers the pinned car, preserves searches, never fabricates when unpinned, multi-intent + fresh browse intact. |

## The three fixes — before → after (pinned Fortuner)

| Utterance | Before (12F) | After (12G) |
|-----------|--------------|-------------|
| `2019 model hai?` | fresh 2019 search (4 cars) | **"yeh 2011 model hai"** |
| `ye 2019 model hai?` | fresh 2019 search | **"yeh 2011 model hai"** |
| `model year kya hai?` / `kaunsa year hai?` | `exhausted`/offsheet | **"yeh 2011 model hai"** |
| `kam km chali hai?` | low-km sort (no km stated) | **"169,773 km chali hai"** |
| `automatic hai?` | "Automatic mein Fortuner achi rahegi" (wrong) | **"Manual (gear) hai"** (the car's real value) |
| `manual hai?` / `transmission automatic hai?` | variant search | **"Manual (gear) hai"** |

## Preserved search / variant behaviour (anti-regression — Step 8)

| Utterance | Result | Verified |
|-----------|--------|----------|
| `automatic wali dikhao` / `automatic wali chahiye` | same-model variant search | ✅ |
| `automatic cars dikhao` / `automatic mein koi hai?` | inventory search (8 cars) | ✅ |
| `automatic wali?` | same-model variant (12E unchanged) | ✅ |
| `2019 model chahiye` / `2019 model wali car chahiye` / `2019 ki car dikhao` | 2019 inventory search | ✅ |
| `kam km wali car chahiye` / `sabse kam km wali car` / `low km wali car dikhao` | low-km sort search (34 cars) | ✅ |
| `2019 nexon` | `year_exact=2019` + model=Nexon search | ✅ |
| `automatic Ertiga hai?` / `automatic wali Ertiga chahiye` | model named → search, not pinned attribute | ✅ |

## Context matters (Step 4)
- `Show me Ertiga` (2 cars, model-only pin) → `automatic hai?` → stays scoped to
  Ertiga (variant), because no **single** car is pinned.
- `Show me Ertiga` → `petrol wali?` (narrows to ONE 2016 Petrol Ertiga) →
  `automatic hai?` → **"2016 Blue Ertiga — Manual (gear) hai"** (that exact car);
  `2019 model hai?` → **"yeh 2016 model hai"**; `kam km chali hai?` →
  **"39,000 km chali hai"**. The single pin is answered.
- `Show me Fortuner` → `RC?` → `2019 model hai?` → **"yeh 2011 model hai"** →
  `kam km chali hai?` → **"169,773 km chali hai"**.

## No fabrication when unpinned (Step 4)
| Utterance (cold session) | Response | Safe? |
|--------------------------|----------|-------|
| `automatic hai?` / `manual hai?` | "Kis gaadi ka transmission chahiye?" | ✅ clarify |
| `kam km chali hai?` | "Kis gaadi ki km reading chahiye?" | ✅ clarify |
| `2019 model hai?` / `kaunsa year hai?` | "…gaadi ka model ya budget bata do" | ✅ safe help, no car invented |

## Multi-intent safety (Step 7) — every one answers the pinned car, none becomes a search
| Utterance (pinned) | Answered |
|--------------------|----------|
| `automatic hai aur kitne owners hain?` | owners (2) — pinned car |
| `2019 model hai aur kitne owners hain?` | owners (2) — pinned car |
| `kitni km chali hai aur insurance?` | 169,773 km — pinned car |
| `automatic hai aur sunroof hai?` | Sunroof: Data not available — pinned car |

(Combined **old-flag** questions answer the primary field only — a pre-existing
`response_formatter` early-return, unchanged by 12G. The requirement "answer the
pinned car, do not convert to a search" is met in every case.)

## Fresh browse still works
`Show me Fortuner` → `7 seater chahiye` → `new_search`, 8 options.

## Language
Marathi `कोणते वर्ष आहे?` on the pinned car → `current_car`, answers the year.
