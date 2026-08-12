# Phase 12A — Used-Car Buyer Journey (STEP 2)

*Research only.* How a real customer buys a used car at a dealership like Assad
Motors, and what the chatbot must support at each stage. Mapped to Indian
used-car market practice (Mumbai / Andheri).

---

## Journey overview

```
Discovery → Shortlist → Enquiry → Inspection → Evaluation → Negotiation
   → Booking → Documentation → Delivery → Post-sale
```

The chatbot's job shifts stage by stage: **inform** early, **qualify + invite**
in the middle, **reassure + convert** near booking, **support** after.

---

## 1. BEFORE PURCHASE (Discovery → Enquiry)

**Buyer mindset:** "What do you have, in my budget, that fits my needs?"

- Browses by budget, body type, fuel, seats, brand, mileage, "family car", "first car".
- Asks availability, price, year, km, owners, colour, transmission.
- Compares 2–3 models; checks resale reputation and running cost.
- Wants photos/videos/Instagram/YouTube to shortlist without visiting.
- Checks location, timing, distance, whether test drive/finance/exchange is possible.

**Chatbot must:** answer inventory + spec + feature questions, surface media,
recommend 1–2 options with a follow-up question (consultative), capture the lead,
and invite a visit. *(Discovery is where breadth of answerable fields matters most.)*

## 2. DURING INSPECTION (at the showroom, or pre-visit deep questions)

**Buyer mindset:** "Is this specific car genuinely good?"

- Condition: accident-free? flood? repaint? panel/body/engine/interior/tyre/clutch condition?
- Documents: RC clear? loan closed? NOC? hypothecation? fitness? PUC? road tax?
- Service history, last service, authorised vs local.
- Insurance type/validity, zero-dep, claim history, NCB.
- Keys (how many), spare tyre, toolkit, accessories.
- Feature verification: sunroof works? camera? sensors? airbags? music?
- Test drive request; asks staff to demonstrate features.

**Chatbot must:** answer per-car condition/document/service/warranty from data
(never fabricate), and for anything not on file, pivot honestly to "our team will
confirm at your visit." This is exactly where empty fields hurt today.

## 3. AFTER INSPECTION (Evaluation)

**Buyer mindset:** "Is it worth the price? Any red flags?"

- Reason for sale, known issues, any pending work.
- Running cost, expected mileage, tyre life left, upcoming service cost.
- Resale value, brand reliability, comparison with an alternative in stock.
- Warranty available? provider? duration?
- Price justification vs market.

**Chatbot must:** present `reason_for_sale`, `known_issues`, `best_features`,
warranty, and comparisons deterministically; build value without over-promising.

## 4. BEFORE BOOKING (Negotiation → Decision)

**Buyer mindset:** "Give me your best price and terms."

- Negotiation / discount / "last price".
- Finance: eligibility, EMI, down payment, tenure, interest, documents needed.
- Exchange: will you take my old car? valuation?
- Price inclusions: RC transfer cost, insurance, what's included in the price.
- Booking amount, refund policy, how to hold the car.

**Chatbot must:** follow a fixed **negotiation policy** (acknowledge → build value →
invite visit → never promise a discount), explain finance/exchange deterministically,
and move toward a booking/visit. *(Prices are fixed — see conversation policy.)*

## 5. AFTER BOOKING (Documentation → Delivery)

**Buyer mindset:** "Make the paperwork and handover smooth."

- Documents required from buyer (ID, address, photos, cheque/UPI).
- RC transfer process, time, cost; NOC/loan-closure if financed.
- Insurance transfer/new policy.
- Delivery timeline, what's handed over (keys, papers, accessories), delivery/home-delivery.
- Payment methods, invoice.

**Chatbot must:** explain the documentation + delivery checklist deterministically,
set expectations on timelines, and route to the team for execution.

## 6. POST-SALE (Ownership support)

**Buyer mindset:** "I've bought it — now help me run it."

- First service, warranty claims, where to service.
- RC transfer status follow-up.
- Referral / repeat purchase / exchange later.

**Chatbot must:** answer service/warranty/transfer-status, capture referrals, and
keep the relationship warm.

---

## Stage → capability map (for later phases)

| Stage | Primary capability needed | Mostly exists? |
|---|---|---|
| Discovery | inventory + spec + feature answers, media, recommend, lead capture | Inventory ✅ / specs+features ❌ |
| Inspection | per-car condition/docs/service/warranty from data | Model ✅ / data ❌ |
| Evaluation | reason-for-sale, known issues, comparison, running cost | Partial |
| Negotiation | fixed-price + finance/exchange policy | ✅ (FAQ) |
| Booking/Docs | documentation + delivery checklist policy | Partial (FAQ) |
| Post-sale | service/warranty/transfer status, referral | Partial |

**Takeaway:** the journey is well covered by the *engine*; the two thin spots are
**specs/features** (no fields) and **per-car condition/docs data** (empty fields).
