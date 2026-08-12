# Phase 11A — Intent Coverage Audit

**Goal:** improve the chatbot's *deterministic* understanding of every inventory
field. No LLM, no redesign, no retrieval / ranking / memory / follow-up rewrite —
only inventory-field intent recognition.

**Method:** the task's example phrases (plus close variants) were run through the
**real** parser (`query_parser.parse` + `media_lookup.detect_media_intent`) and
mapped to the field the current system would answer from. This is a grounded
audit — not a guess about what "should" work.

Harness: `app/inventory_system/phase11a_audit.py`. Field set (STEP 1) auto-detected by
introspecting the `InventoryItem` dataclass (no hardcoded field names).

---

## STEP 1 — Fields auto-detected from the schema

`InventoryItem` has **69** dataclass fields; **48** are customer-relevant after
dropping internal/identity/audit columns (id, registration_no, stock_no, raw,
timestamps, location_code, listing_status, …). The intent engine groups them into
the customer-facing **intent families** below (many schema columns share one
answer, e.g. `rc_status` + `hypothecation_bank` + `loan_closed` + `noc_available`
+ `finance_eligible` all answer an "RC / documents" question).

| Intent family | Backing schema fields |
|---|---|
| RC / documents / transfer / fitness | rc_status, hypothecation_bank, loan_closed, noc_available, finance_eligible, rto |
| Insurance | insurance_type, insurance_expiry, zero_dep, insurance_claim_history, insurance_hint |
| Ownership | ownership_count |
| KM / odometer | km_driven |
| Condition / accident | accident_free, flood_damage, repainted, body_condition, engine_condition, interior_condition, tyre/brake/clutch/battery_condition |
| Colour | color_norm |
| Fuel | fuel_norm |
| Transmission | transmission_norm |
| Seats | seats |
| Price / budget | price_lakh, price_quotable, negotiable, price_range_* |
| Warranty | warranty_available, warranty_expiry, warranty_provider |
| Service | service_history_available, last_service_date, service_center_type |
| Finance / EMI | finance_eligible (+ 20% downpayment estimate on price) |
| Mileage (kmpl) | claimed_mileage_kmpl |
| Media | photo_count, video_count, InventoryMedia (photos/videos/instagram/youtube) |

---

## STEP 3 — Coverage BEFORE (baseline)

**Overall: 70 / 112 = 62 %.** Fields fully covered: ownership, video, instagram,
service. Everything else had gaps.

| Field | Before | Notable failures |
|---|---|---|
| rc | 2/9 | bare `RC`, `RC hai?`, `RC ka kya scene hai`, `Registration hai?`, `rc kaisa hai`, `rc transfer` |
| insurance | 7/9 | `Claim hua?`, `no claim bonus` |
| ownership | 7/7 | — |
| km | 3/10 | `Running?`, `Kilometer?`, `KM?`, `km reading`, `odo kya hai`, `kms?` |
| condition | 8/9 | `Touch-up?` |
| video | 5/5 | — |
| instagram | 4/4 | — |
| youtube | 3/4 | `Shorts` |
| color | 0/5 | `Color?`, `kaunsa rang`, `which colour`, `rang kya hai` (all treated as availability) |
| fuel | 1/4 | `Fuel?`, `kaunsa fuel`, `fuel type kya hai` |
| transmission | 5/7 | `Transmission?`, `gear kaisa hai` |
| seats | 3/5 | `kitni seats`, `how many seats` |
| budget | 3/4 | `Below 8` (bare number after ceiling word) |
| price | 5/6 | `Final?` |
| finance | 4/5 | `kitni kist` |
| warranty | 3/4 | `Guarantee?` |
| service | 3/3 | — |
| rc_transfer | 1/4 | `Transfer?`, `NOC?`, `rc transfer` |
| fitness | 2/4 | `Fitness?`, `RTO?` |
| documents | 1/4 | `Original papers?` (mis-routed to **insurance**), `Paper complete?`, `documents?` |

**Root causes**

1. **Interrogative field-name questions had no intent.** "kaunsa rang?", "fuel?",
   "transmission?", "how many seats" were only recognised when they carried a
   *value* ("white", "petrol", "7 seater"). A bare *question* fell through to the
   default availability path.
2. **Only multi-word phrasings were listed** for RC / KM. Bare "rc", "km",
   "running", "odometer", "transfer", "noc", "fitness", "rto" were missing.
3. **`papers` was wired to insurance**, so "Original papers?" answered insurance
   instead of documents/RC.
4. **Missing synonyms/typos:** `claim`, `ncb`, `touch-up`, `shorts`, `guarantee`,
   `kist`.
5. **Bare English budget** ("below 8", "under 6") set no ceiling.

---

## Coverage AFTER

**Overall: 110 / 112 = 98 %** at the parser level; **100 %** end-to-end once the
two follow-up-layer cases are included.

The two residual parser "misses" are **not** defects:

* `kितनी चली` — a malformed test string (Latin `k` + Devanagari `ितनी चली`); the
  real Devanagari `कितनी चली` resolves correctly.
* `Final?` — deliberately handled at the conversation layer (`_is_price_followup`),
  not `parse()`. Cold `Final?` → "Kis gaadi ki price chahiye?"; pinned `Final?` →
  that car's price (verified end-to-end, `app/inventory_system/phase11a_e2e.py`).

See `phase11A_intent_dictionary.md` for the full alias sets and
`phase11A_validation.md` for the 50-per-field test results and regression.
