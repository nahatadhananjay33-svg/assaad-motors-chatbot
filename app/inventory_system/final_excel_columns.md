# Final Excel Schema — IVR_Sheet.xlsx (DNJ sheet)
# Phase 7C — Schema Expansion
# Generated: 2026-06-17

---

## CURRENT COLUMNS (A–Q, as-is)

| Col | Header in sheet | Internal key    | Notes                                       |
|-----|-----------------|-----------------|---------------------------------------------|
| A   | (blank)         | stock_no        | Sequential stock number                     |
| B   | (blank)         | sr_no           | Serial number — duplicate of stock_no; WEAK |
| C   | Company Name    | make            | Code: MARU / HYUN / HOND etc.              |
| D   | MODEL           | model           | Dirty free text — normalised by loader      |
| E   | (blank)         | year            | Manufacture year — sometimes has month suffix |
| F   | INS             | insurance       | Free-text advisory blob — WEAK              |
| G   | VARI            | variant         | Raw variant code — cryptic, not shown to buyer |
| H   | F               | fuel            | Single-letter code: P/D/C/PC/E etc.        |
| I   | T               | transmission    | A / M only                                  |
| J   | O               | ownership       | Owner count integer                         |
| K   | KM              | km              | Kilometres driven                           |
| L   | COL             | color           | 3–5 letter code: WHI/BLA/SIL etc.          |
| M   | RATE            | rate            | Price OR status code (4/33/44/DDD/DDDD)    |
| N   | CAR NUMB        | car_numb        | Full registration number — primary key      |
| O   | (blank)         | reg_last4       | Last 4 digits of reg — redundant; WEAK     |
| P   | LOC             | location        | Slot (Y5) or custody word (POLI/IMM)       |
| Q   | RTO             | rto             | RTO code (MH01 etc.)                       |

### Media columns already present (header-located, not hard-coded)
| Range   | Type              | Slots |
|---------|-------------------|-------|
| R–AA    | EXTERIOR 1–10     | 10    |
| AB–AK   | INTERIOR 1–10     | 10    |
| AL–AP   | VIDEO 1–5         | 5     |
| AQ–AU   | INSTAGRAM 1–5     | 5     |
| AV–AZ   | YOUTUBE 1–5       | 5     |

---

## PROBLEMS WITH CURRENT SCHEMA

| Column | Problem |
|--------|---------|
| F (INS) | Free-text blob — could be a date, "THIRD PARTY", "COMP", or blank. Cannot be queried deterministically. |
| B (sr_no) | Duplicate of A; no value. Can be repurposed. |
| O (reg_last4) | Redundant — derivable from N. Can be repurposed. |
| G (variant) | Cryptic code never shown to buyer. OK to keep but add human-readable `best_features` alongside. |
| M (rate) | Dual-use: price OR status code. Loader already handles this; keep as-is but add `price_range_low` / `price_range_high` for non-quotable cars. |

---

## FINAL SCHEMA — ORDERED COLUMN LIST

Columns are ordered: Identity → Pricing → Usage → Insurance → Condition → Service → Documents → Warranty → Sales → Media (existing).

New columns are inserted BEFORE the media block (currently starting at col R).
Existing columns A–Q are left in-place to avoid breaking the loader.
New columns occupy R onward; media shifts right accordingly.

### GROUP A — Identity (existing, A–G + partial)

| Excel Col | Field name       | Type         | Allowed values / notes                        |
|-----------|------------------|--------------|-----------------------------------------------|
| A         | stock_no         | Integer      | Existing — keep                               |
| B         | sr_no            | —            | REPURPOSE → `finance_eligible` (see Group G)  |
| C         | make             | Code         | Existing — keep                               |
| D         | model            | Text         | Existing — keep                               |
| E         | year             | Integer      | Existing — keep                               |
| F         | insurance        | —            | SPLIT into structured cols below (keep for audit trail) |
| G         | variant          | Text         | Existing — keep                               |
| H         | fuel             | Code         | Existing — keep                               |
| I         | transmission     | Code         | Existing — keep                               |
| J         | ownership        | Integer      | Existing — keep                               |
| K         | km               | Integer      | Existing — keep                               |
| L         | color            | Code         | Existing — keep                               |
| M         | rate             | Integer/Code | Existing — keep                               |
| N         | car_numb         | Text         | Existing — primary key                        |
| O         | reg_last4        | —            | REPURPOSE → `claimed_mileage_kmpl` (see Group C) |
| P         | location         | Code         | Existing — keep (internal only)               |
| Q         | rto              | Code         | Existing — keep                               |

---

### NEW COLUMNS (insert at R onward, before media)

#### GROUP B — Pricing

| New Col | Field name         | Type    | Allowed values          | Notes                                       |
|---------|--------------------|---------|-------------------------|---------------------------------------------|
| R       | price_range_low    | Integer | ≥ 10000 or blank        | Soft floor for non-quotable cars (₹)       |
| S       | price_range_high   | Integer | ≥ 10000 or blank        | Soft ceiling for non-quotable cars (₹)     |
| T       | negotiable         | Y/N     | Y / N / blank           | Is price open to negotiation?               |

#### GROUP C — Usage

| New Col | Field name            | Type    | Allowed values | Notes                                     |
|---------|-----------------------|---------|----------------|-------------------------------------------|
| U       | claimed_mileage_kmpl  | Decimal | e.g. 18.5      | Manufacturer claimed kmpl for this variant |

#### GROUP D — Insurance (replaces free-text INS in col F)

| New Col | Field name              | Type    | Allowed values                         | Notes                              |
|---------|-------------------------|---------|----------------------------------------|------------------------------------|
| V       | insurance_type          | Enum    | Comprehensive / Third-Party / Expired / blank | Structured type                |
| W       | insurance_expiry        | Date    | YYYY-MM-DD or blank                    | Exact expiry date                  |
| X       | zero_dep                | Y/N     | Y / N / blank                          | Zero depreciation add-on?          |
| Y       | insurance_claim_history | Y/N     | Y / N / blank                          | Any claim made on this policy?     |

#### GROUP E — Vehicle Condition

| New Col | Field name       | Type | Allowed values              | Notes                               |
|---------|------------------|------|-----------------------------|-------------------------------------|
| Z       | accident_free    | Y/N  | Y / N / blank               | Y = no accident ever recorded       |
| AA      | flood_damage     | Y/N  | Y / N / blank               | Y = flood/water damage history      |
| AB      | repainted        | Y/N  | Y / N / blank               | Y = any panel repainted             |
| AC      | repaint_panels   | Text | e.g. "Front bumper, hood"   | Which panels — free text (brief)    |
| AD      | body_condition   | Enum | Excellent / Good / Fair / Poor | Overall body/exterior rating    |
| AE      | engine_condition | Enum | Excellent / Good / Fair / Poor | Engine health rating            |
| AF      | interior_condition | Enum | Excellent / Good / Fair / Poor | Interior rating                 |
| AG      | tyre_condition   | Enum | Good / Fair / Replace        | All 4 tyres assessed together       |
| AH      | brake_condition  | Enum | Good / Fair / Replace        | Brake pad / disc condition          |
| AI      | clutch_condition | Enum | Good / Fair / Replace / NA  | NA for automatics                   |
| AJ      | battery_condition | Enum | Good / Fair / Replace / NA | NA for petrol/diesel without aux   |

#### GROUP F — Service History

| New Col | Field name               | Type | Allowed values                    | Notes                              |
|---------|--------------------------|------|-----------------------------------|------------------------------------|
| AK      | service_history_available | Y/N | Y / N / blank                     | Service records available?         |
| AL      | last_service_date        | Date | YYYY-MM-DD or blank               | Date of most recent service        |
| AM      | service_center_type      | Enum | Authorised / Multi-brand / Local / blank | Where last serviced         |

#### GROUP G — Documents

| New Col | Field name        | Type | Allowed values                     | Notes                               |
|---------|-------------------|------|------------------------------------|-------------------------------------|
| AN      | rc_status         | Enum | Clear / Hypothecated / Pending / blank | Loan/hypothecation status      |
| AO      | hypothecation_bank | Text | Bank name or blank                 | Only fill if rc_status=Hypothecated |
| AP      | loan_closed       | Y/N  | Y / N / blank                      | NOC obtained from bank?             |
| AQ      | noc_available     | Y/N  | Y / N / blank                      | NOC document in hand?               |
| AR      | finance_eligible  | Y/N  | Y / N / blank                      | Eligible for bank finance?          |

#### GROUP H — Warranty

| New Col | Field name        | Type | Allowed values           | Notes                                   |
|---------|-------------------|------|--------------------------|------------------------------------------|
| AS      | warranty_available | Y/N | Y / N / blank            | Any warranty/assurance on this car?      |
| AT      | warranty_expiry   | Date | YYYY-MM-DD or blank      | Expiry of warranty                       |
| AU      | warranty_provider | Text | e.g. "Maruti True Value" | Who provides the warranty                |

#### GROUP I — Sales Intelligence

| New Col | Field name      | Type | Allowed values                         | Notes                              |
|---------|-----------------|------|----------------------------------------|------------------------------------|
| AV      | reason_for_sale | Enum | Upgrade / Relocation / Fleet / Other / blank | Seller's stated reason      |
| AW      | best_features   | Text | e.g. "Sunroof, camera, new tyres"     | 2–4 selling points (brief)         |
| AX      | known_issues    | Text | e.g. "Minor dent on rear bumper"      | Honest disclosure (brief)          |

#### GROUP J — Media count (summary; actual URLs stay in existing media cols)

| New Col | Field name  | Type    | Notes                        |
|---------|-------------|---------|------------------------------|
| AY      | photo_count | Integer | Auto-filled by media_sync    |
| AZ      | video_count | Integer | Auto-filled by media_sync    |

---

### Media URL columns shift right
After the 28 new columns (R–AZ), existing EXTERIOR/INTERIOR/VIDEO/INSTAGRAM/YOUTUBE URL columns shift to BA onward. The `media_loader_mapping.py` already locates these by HEADER TEXT (not column letter), so no code change is required.

---

## QUESTION → COLUMN MAPPING

| Buyer question                          | Column(s) required                          |
|-----------------------------------------|---------------------------------------------|
| Has this car had an accident?           | accident_free                               |
| Any flood/water damage?                 | flood_damage                                |
| Has it been repainted?                  | repainted, repaint_panels                   |
| What is the body condition?             | body_condition                              |
| How is the engine?                      | engine_condition                            |
| How are the tyres?                      | tyre_condition                              |
| Brakes OK?                              | brake_condition                             |
| Clutch condition?                       | clutch_condition                            |
| Battery OK?                             | battery_condition                           |
| What is the interior condition?         | interior_condition                          |
| Insurance valid till when?              | insurance_expiry                            |
| Comprehensive or third-party insurance? | insurance_type                              |
| Zero dep insurance?                     | zero_dep                                    |
| Any insurance claim made?               | insurance_claim_history                     |
| Service history available?              | service_history_available                   |
| When was it last serviced?              | last_service_date                           |
| Authorised service centre?              | service_center_type                         |
| RC clear / any loan on car?             | rc_status, hypothecation_bank, loan_closed  |
| NOC available?                          | noc_available                               |
| Can I get finance/loan for this car?    | finance_eligible                            |
| Down payment / EMI?                     | price_lakh + finance_eligible               |
| Any warranty?                           | warranty_available, warranty_expiry         |
| What is the mileage / fuel efficiency?  | claimed_mileage_kmpl                        |
| Why is owner selling?                   | reason_for_sale                             |
| What are the best features?             | best_features                               |
| Any known issues?                       | known_issues                                |
| Price range? (non-quotable cars)        | price_range_low, price_range_high           |
| Is price negotiable?                    | negotiable                                  |
| How many photos available?              | photo_count                                 |

---

## COVERAGE IMPROVEMENT ESTIMATE

| Metric                      | Current | After schema expansion |
|-----------------------------|---------|------------------------|
| Buyer questions (20 audited) | 4 YES / 6 PARTIAL / 10 NO | 16 YES / 3 PARTIAL / 1 NO |
| Coverage %                  | ~25%    | ~82%                   |
| Off-sheet deflections       | ~10     | ~2 (engine detail, mechanical noise) |

Questions currently impossible → enabled by new columns:
- accident_free → "Has it had an accident?"
- flood_damage → "Any flood damage?"
- repainted → "Has it been repainted?"
- body_condition, engine_condition, interior_condition → "What is the condition?"
- tyre_condition, brake_condition, clutch_condition → Mechanical readiness
- insurance_expiry, insurance_type → "Insurance details?"
- service_history_available, last_service_date → "Service history?"
- rc_status, loan_closed, noc_available → "RC clear? Any loan?"
- finance_eligible → "Can I get finance?"
- warranty_available, warranty_expiry → "Any warranty?"
- claimed_mileage_kmpl → "What mileage does it give?"
- price_range_low/high → Price band for non-quotable cars
- reason_for_sale → "Why is owner selling?"
- best_features → "What is special about this car?"

Questions still requiring visit (intentionally):
- Mechanical noise / unusual sounds
- Test drive experience

---

## TIER PRIORITIZATION

### Tier 1 — Implement immediately (highest buyer anxiety, trust-blockers)
1. accident_free
2. flood_damage
3. repainted
4. body_condition
5. engine_condition
6. insurance_expiry
7. insurance_type
8. rc_status
9. loan_closed
10. service_history_available

### Tier 2 — Implement in next cycle (conversion helpers)
11. tyre_condition
12. brake_condition
13. clutch_condition
14. interior_condition
15. last_service_date
16. service_center_type
17. finance_eligible
18. warranty_available
19. warranty_expiry
20. price_range_low / price_range_high

### Tier 3 — Implement when Tier 1+2 are stable (nice-to-have)
21. zero_dep
22. insurance_claim_history
23. hypothecation_bank
24. noc_available
25. battery_condition
26. claimed_mileage_kmpl
27. warranty_provider
28. reason_for_sale
29. best_features
30. known_issues
31. repaint_panels
32. negotiable
33. photo_count / video_count

---

## GO / NO-GO

**GO** — Schema is well-defined, all new columns have:
- Exact header name
- Data type (Y/N / Enum / Date / Integer / Text)
- Explicit allowed values
- Excel column letter assigned
- Buyer question mapped

No code changes required in Phase 7C.
The loader's header-based media detection means media columns shift right safely.
Loader and model changes (to read new columns) are Phase 7D scope.
