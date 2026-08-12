# Phase 12H — Manual Integrated Validation Report

**Type:** testing only. No product/chatbot/parser/Excel/auth code was changed
(all `app/` source files still date to Phase 12G; verified by mtime). Automated
baseline **580 passed / 0 failed** is preserved.

**How it was run:** the real app was started via the normal procedure
(`chat_api.py`) but pointed at an **isolated copy** of `IVR_Sheet.xlsx` and a temp
data dir, so production data was never at risk. Live Excel md5 is unchanged
(`16f121f4…`) before and after. Auth, roles, the Owner-UI edit endpoints, the
loader, the chatbot, and the FAQ engine were all exercised through the running
HTTP server (localhost:8000). ~140 messages were sent.

---

## 1. Tests attempted / passed / failed
- **Attempted:** ~140 across Steps 1–9 (auth/roles, Owner-UI edit→persist→chain,
  13 intent groups × multiple phrasings, conversation flow, multi-intent, 4
  languages, safety/honesty, conflict/ambiguity).
- **Passed:** the large majority — including every safety/honesty and
  conflict/ambiguity case.
- **Failed (recognition/quality gaps, none blocking):** ~11 phrasings, listed below.

## 2. Genuine BUGS found
**None that are blocking, crash, corrupt data, or fabricate.** Nothing here
requires a stop-and-fix. The one item closest to a functional bug:
- **`km kitna hai?` returns the price**, not the odometer (the loose `price`
  intent from "kitna" wins over the km reading). `kitne km chali?` / `running?`
  work correctly. → classify **intent gap**.

## 3. Missing-data cases (correct behaviour — needs owner data entry, not code)
The test car (Fortuner) and most cars have **blank feature/document columns**, so
the bot correctly answered **"Data not available"** for: sunroof, camera,
music/speakers, parking sensors, touchscreen, Android Auto/CarPlay, cruise,
keyless, push-button, fog lamps, EV range, battery, RC, insurance, service,
warranty, accident. **No value was ever invented.** Fix = owner fills these in via
the Vehicle Details UI (which was proven to persist end-to-end).

## 4. Intent / understanding gaps (recognition only — never fabrication)
| # | Message (pinned car) | Got | Expected | Class |
|---|----------------------|-----|----------|-------|
| a | `which car is this?`, `model?`, `kaunsa model hai?`, bare `year?` | "here are more options" / exhausted | name the pinned car / model / year | no identity/model attribute handler |
| b | `km kitna hai?` | price ₹8.75 L | odometer | price intent wins over km |
| c | `petrol hai?` / `diesel hai?` (pinned) | fuel **search** | answer the pinned car's fuel | fuel yes/no not treated as attribute (the fuel analog of the 12G transmission fix — fuel was out of 12G scope) |
| d | bare `engine`, `battery`, `mileage`, `power steering`, `safety features` | exhausted / search | pinned car's value | bare-keyword synonym gaps (fuller forms `engine capacity`, `battery health`, `mileage kitna` work) |
| e | `इसमें कितने एयरबैग हैं?` (Hindi Devanagari) | exhausted | 7 airbags | Hindi Devanagari "kitne airbags" phrasing gap (Marathi + Hinglish work) |
| f | `booking?` | finance/EMI answer | booking/visit info | FAQ mis-route |

## 5. Conversation-quality issues
- **Negotiation objections without the word "discount"** are handled weakly:
  `bhai expensive hai` → "that's all I have…"; `itna mehenga kyun?` → exhausted;
  `dusri jagah sasti mil rahi hai` → a 34-car budget dump. Explicit
  `discount karo` / `10,000 kam karo` / `discount nahi doge?` are handled well and
  consistently ("prices are fixed…"). → tone-deaf on indirect objections.
- Multi-intent that mixes **old-style** flags answers the primary field only
  (`RC aur insurance batao` → insurance only; `price aur km batao` → price only).
  12D-field pairs answer both (`airbags aur sunroof`, `camera aur parking`,
  `boot aur ground clearance` all answer both). → pre-existing formatter
  early-return limitation, documented since 12F.

## 6. What PASSED notably (evidence)
- **Auth/roles:** Owner login OK; wrong password rejected; Inventory Staff → 403
  on Owner-only endpoints (`users/list`, `users/create`); no-token → 401.
- **Owner UI → chatbot full chain:** edited Sunroof, Camera, Music/Speakers,
  Parking, ABS, Airbags, Alloy, Touchscreen, Engine, Boot, Ground-clearance →
  **partial save works**, **full save persists on reload**, refresh →
  **chatbot answered with the saved values** (e.g. Sunroof "haan (Electric)",
  Camera "Reverse camera", Speakers "6", Touchscreen "9.0 inch", Boot "296 L").
  Transmission/Fuel are dropdowns that send codes (`A`/`M`, `P`/`D`) and map
  correctly ("Automatic (gear) hai", "fuel Petrol hai").
- **12G contextual fixes confirmed live:** `automatic hai?`, `manual hai?`,
  `gearbox kya hai?`, `kaunsa year hai?`, `2019 model hai?`, `kitne km chali?`,
  `running?` all answer the **pinned car**; `automatic wali dikhao` /
  `2019 wali dikhao` / `kam km wali dikhao` still **search**.
- **Conversation context:** Ertiga → price → RC → km → insurance → sunroof →
  airbags → automatic variant → petrol variant → 7-seater (fresh) → SUV — pin
  stayed correct, variants stayed in-model, new requirements started fresh search.
- **Safety/honesty:** every blank field → "Data not available" (incl. Marathi
  "माहिती उपलब्ध नाही"); no media links, RC, insurance, or specs invented.
- **Conflict vs question:** `petrol diesel`/`automatic manual` → clarify;
  `petrol ya diesel?`/`automatic ya manual?` → normal question (not a conflict).
- **FAQ:** finance, loan, exchange, test drive, location, visit, timing, discount
  all answered sensibly and stayed sales-oriented.

## 7. UI issues
None found in behaviour. The Vehicle Details dropdowns (Fuel/Transmission) use the
correct value/label mapping. (Visual/rendering pass is the user's manual step.)

## 8. Security issues
None. RBAC enforced correctly (Owner vs Staff vs anonymous). `/chat` open only
because `CHAT_API_KEYS` is intentionally unset in local/dev (documented warning).

## 9. Data-integrity result
**Intact.** Live `IVR_Sheet.xlsx` md5 unchanged; all tests ran on a copy; the one
edited test car (Fortuner) was fully restored (trans M, fuel D, features blank,
owners 2); the temporary test staff user was deleted; no live users/audit touched.

## 10. Readiness for next phase
**Ready.** No blocking bug, no fabrication, no security or data-integrity problem.
The remaining items are (a) owner data entry for blank feature columns and
(b) a set of small, optional recognition/quality gaps (§4–5). None require product
changes to proceed to real-user manual testing.

## 11. Suggested follow-ups (NOT done — your call)
1. Add a pinned-car **identity/model** answer (`which car / model? / kaunsa model`).
2. Fix `km kitna hai?` losing to price; add bare `engine`/`battery`/`mileage`
   keyword resolution.
3. Extend the 12G attribute treatment to **fuel** (`petrol hai?` → pinned car).
4. Add Hindi Devanagari airbags phrasing; route `booking?` to booking/visit.
5. Soften indirect negotiation objections ("expensive hai", "mehenga kyun").

These are enhancements, not blockers — tell me which (if any) to implement and I
will keep each change small and covered by tests.
