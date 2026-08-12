# Reel / Instagram Discovery Flow — Report

**Why.** The dealership has ~300k Instagram followers, so a large share of chats
open with *"ye reel wali gaadi hai kya?"* / *"is this car available which is in the
reel?"* — the customer saw a car in a reel and wants to **identify it and know if
it's available**. This is a top-volume flow.

## Was it handled before? — Partly, and with real rough edges
Audit (real `ChatService`, `app/inventory_system/phase_reel_trace.py`):

| Utterance | Before |
|-----------|--------|
| `ye reel wali gaadi hai kya?` (no car) | generic *"Kaunsi gaadi ke Instagram photos/reels chahiye?"* — sounds like it will **send photos**, doesn't ask for the car number |
| `reel wali Fortuner available hai?` | **"Instagram photos abhi available nahi — visit pe dikha denge."** ❌ (answered media, not availability) |
| `MH04EX5958 reel wali hai kya?` | same "Instagram photos unavailable" ❌ |
| `9444 wali reel gaadi` (partial plate) | *"Kaunsi gaadi ke Instagram photos chahiye?"* ❌ (ignored the plate) |
| `instagram wali car available hai?` | 34-car dump ❌ |
| reply `Fortuner` / `MH04EX5958` after the clarify | resolved ✅ (this part already worked) |

Root cause: any "reel"/"insta" word was treated as *"send me Instagram media"*, so
the media layer hijacked the answer.

## What was fixed (deterministic, no LLM)
A reel/insta reference is now treated as a **car-discovery signal** — identify +
check availability — **unless** the customer explicitly asks to be sent something
(a send cue like `bhejo`/`send`/`link`, or a `photo`/`video` word).

| Utterance | After |
|-----------|-------|
| `ye reel wali gaadi hai kya?` (no car) | **reel-aware clarify:** *"Reel me jo gaadi dekhi — uska number (jaise MH01AB1234) ya model aur colour bata do, main abhi check karta hoon available hai ya nahi. Ya us reel/post ka link bhej do…"* |
| `reel wali Fortuner available hai?` | **"Haan, 2011 White Fortuner, Diesel available hai…"** ✅ |
| `MH04EX5958 reel wali hai kya?` | availability of that car ✅ |
| `9444 wali reel gaadi` | resolves the partial plate → availability ✅ |
| `reel me jo nexon thi` (2 Nexons) | lists both, asks which ✅ |
| `instagram wali car available hai?` | reel-aware clarify (no 34-car dump) ✅ |
| reply `Fortuner` / a number | availability ✅ (workflow completes) |
| `Fortuner ki reel bhejo` / `Send reel` / `reel ka link` | **unchanged** — media-send behaviour ✅ |

Devanagari reel words (`रील`, `इंस्टा`, `स्टोरी`…) were added so Hindi/Marathi
reel references work too.

## The workflow now
1. Customer: *"reel wali gaadi hai kya?"* → bot asks for the **car number** (often
   on-screen in the reel / caption), or model + colour, or the reel link.
2. Customer replies with a number / model → bot **confirms availability + price +
   visit invite**. A model with several cars → bot lists them and asks which.
3. If the customer instead says *"reel bhejo"* → the existing media flow sends /
   points to the reel (unchanged).

**Why ask for the car number:** a reel link can't be matched to a specific
inventory car deterministically (reels aren't per-car mapped), but the number is
usually visible in the reel and resolves the exact car instantly. Model + colour is
the fallback; the reel link is offered so staff can identify it manually.

## Safety / no-fabrication
- No car is ever invented; when nothing is identified the bot asks, it does not
  guess or dump the inventory.
- Explicit media-send requests are untouched (media tests all green).
- Auth / security / media storage / Supabase untouched.

## Files changed
| File | Change |
|------|--------|
| `chat_service.py` | `_is_reel_source_query` + reel-aware clarify (`_REEL_CLARIFY`); media override suppressed for reel-source queries; wired into `handle()`. |
| `media_lookup.py` | Devanagari reel/insta words added to Instagram detection. |
| `chat_api_tests.py`, `faq_tests.py` | updated the two tests that asserted the old `media_clarify` label for a bare reel query → now `reel_clarify` (improved behaviour); added a photo-clarify test to keep that path covered. |
| **new** `reel_discovery_tests.py` | 12 focused tests (discriminator + end-to-end + workflow + multilingual). |
| **new** `phase_reel_trace.py` | audit trace. |

## Tests & regression
- New: **12** (`reel_discovery_tests.py`) + 1 (`faq_tests`), all green.
- Full suite: **646 passed / 0 failed** (was 633). No regressions.

## Update — a PASTED reel LINK (URL)

Tested what happens when a customer pastes the actual Instagram reel URL and asks
"ye gaadi hai kya?". Found and fixed a subtle but important bug:

- **Before:** a reel URL's random shortcode digits were mis-read as a partial number
  plate — e.g. `instagram.com/reel/DG9444kLm/` → "9444" → the bot confidently replied
  **"Haan, 2014 E 200 available hai"** — a completely **wrong car**.
- **Fix:** URLs/links are stripped before parsing (`query_parser.strip_urls`), so a
  link's shortcode can never become a car filter. A pasted link now always gives the
  reel clarify (ask for number/model/colour). A real model named *alongside* the link
  still resolves (`…/reel/abc/ Fortuner hai kya?` → Fortuner).

**Why a reel link can't identify the car by itself:** the link is just an opaque
shortcode (`/reel/C5xYz1AbCdE/`); there is no data mapping a reel → a specific
inventory car. So the deterministic, safe answer is to ask for the car number
(usually on-screen in the reel), model + colour, or forward the link for staff.

## Car SOLD / not in stock — already handled honestly
If the customer gives a number/model that is sold or not in stock, the bot says
*"Woh abhi available nahi lagti — lekin similar gaadi dikha doon?"* (that one isn't
available — want me to show similar?). A sold car is not in the live inventory, so it
is treated as not-found — never fabricated as available.

## Remaining / manual
- A shared reel **link** is not auto-resolved to a car (no per-reel→car mapping);
  the bot asks for the number/model or offers the link to staff. To automate this you
  would tag each car with its reel/Instagram URL(s) in Vehicle Details; then a pasted
  link could be matched. Optional — say the word and I'll scope it.
- Visual check of the live chat widget is a manual step.
