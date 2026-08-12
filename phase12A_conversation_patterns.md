# Phase 12A — Conversation Patterns (STEP 6)

*Research only.* Every recurring conversational situation a dealership chatbot
faces, the **deterministic signals** that identify it (no LLM), and the desired
outcome. These map to the policies in `phase12A_conversation_policy.md`.

Signals are things the existing deterministic stack can already detect: FAQ
intents, Phase 11B intent scores/bands, conflict flags, lead-capture cues,
keyword sets, and turn history.

---

## 1. Negotiation / "last price"
- **Signals:** FAQ `_NEGOTIATION` ("last price", "final", "kam karo", "mol-bhav"), `_DISCOUNT`.
- **Customer wants:** a lower number.
- **Outcome:** hold price, build value, invite visit. Never quote a discount.

## 2. Price objection ("too expensive")
- **Signals:** "mehenga", "too costly", "zyada hai", price word + negative.
- **Customer wants:** justification / reassurance of value.
- **Outcome:** explain value (condition, ownership, features), offer comparison in budget, invite inspection.

## 3. Trust objection ("can I trust you / genuine?")
- **Signals:** FAQ `_TRUST_REVIEWS`, `_BUSINESS_AGE`, "genuine", "fraud", "reviews", "kitne saal se".
- **Customer wants:** proof of credibility.
- **Outcome:** business age, transparent condition data, invite visit, offer papers verification.

## 4. Finance objection ("EMI too high / no finance")
- **Signals:** FAQ `_FINANCE`, `_LOAN`, `_FINANCE_DETAILS`, "EMI", "down payment", "interest".
- **Customer wants:** affordability path.
- **Outcome:** explain finance availability + estimate (deterministic 20% DP), route to team for exact terms; never guarantee approval.

## 5. Comparison ("X vs Y / which is better")
- **Signals:** FAQ `_COMPARISON`, "vs", "better", "ya", two models named, "petrol vs diesel".
- **Customer wants:** a recommendation.
- **Outcome:** compare on **data facts** (price/km/owners/fuel/features), recommend based on stated need, avoid subjective claims.

## 6. Confused customer (vague / broad)
- **Signals:** Phase 11B **low band** / no primary, general-intent words ("gaadi chahiye", "suggest karo"), or a same-dimension **conflict**.
- **Customer wants:** guidance.
- **Outcome:** ask ONE clarifying question (budget or use-case), then recommend 1–2. (Conflict → ask which value.)

## 7. Emotional / anxious customer
- **Signals:** worry words ("scared", "cheated before", "tension", "safe hai na").
- **Customer wants:** reassurance.
- **Outcome:** empathetic acknowledgement + factual transparency + invite to verify in person.

## 8. Harsh / rude customer
- **Signals:** profanity / aggressive tokens / all-caps demands.
- **Customer wants:** to be taken seriously (often).
- **Outcome:** stay calm + professional, answer the underlying question, never mirror tone, offer human handoff.

## 9. Urgent customer ("need today / immediately")
- **Signals:** "urgent", "today", "abhi", "jaldi", "immediately".
- **Customer wants:** speed.
- **Outcome:** confirm availability, give timing/location, push to visit/booking now, capture contact.

## 10. Lead qualification
- **Signals:** budget stated, use-case stated, contact shared, repeated interest in one car.
- **Customer wants:** the right car.
- **Outcome:** capture budget/use/contact (lead engine already scores), recommend, move to visit.

## 11. Appointment / booking
- **Signals:** FAQ `_BOOKING`, `_VISIT`, "book", "visit karna hai", "appointment".
- **Customer wants:** to reserve/see the car.
- **Outcome:** give timing/location/booking info, capture contact + preferred slot, confirm.

## 12. Test drive
- **Signals:** "test drive", "TD", "chala ke dekh sakta hoon".
- **Customer wants:** to drive it.
- **Outcome:** confirm TD availability/policy, invite to showroom, capture contact.

## 13. Visit confirmation
- **Signals:** FAQ `_TIMING`, `_LOCATION`, `_ADDRESS`, `_DISTANCE_ROUTE`, "open today", "kaha ho".
- **Customer wants:** to come.
- **Outcome:** timing + address + maps + parking; confirm slot; capture contact.

## 14. Repeat / returning customer
- **Signals:** session memory (prior vehicle context), "again", "last time".
- **Customer wants:** continuity.
- **Outcome:** reuse remembered vehicle/context (Phase 11 memory), acknowledge return, fast-track.

## 15. Exchange
- **Signals:** FAQ `_EXCHANGE`, "purani gaadi", "exchange", "old car".
- **Customer wants:** to trade in.
- **Outcome:** confirm exchange accepted, explain valuation-at-visit, capture old-car details.

## 16. Contact / human handoff
- **Signals:** phone number shared, "call me", "human", "WhatsApp".
- **Customer wants:** a person.
- **Outcome:** acknowledge + capture (lead engine), promise callback, give WhatsApp/location.

## 17. Small-talk / greeting / thanks
- **Signals:** FAQ greeting set, "hi/namaste", "thanks".
- **Outcome:** warm short reply, steer to how-can-I-help.

## 18. Out-of-scope / unknown
- **Signals:** Phase 11B **low band**, no FAQ/inventory match.
- **Outcome:** honest "I can help with our cars / visit"; never fabricate; offer human.

---

## Detection coverage today

| Pattern | Detectable now? | With what |
|---|---|---|
| 1–5, 11–17 | ✅ | FAQ intents + lead engine |
| 6, 18 | ✅ | Phase 11B bands + general-intent + conflict |
| 7, 8, 9 | 🟡 partial | Need small keyword sets (tone/urgency/emotion) |
| 10, 14 | ✅ | Lead scoring + Phase 11 memory |

**Gap:** emotion / harshness / urgency detection need small deterministic keyword
lexicons (Phase 12E). Everything else is already detectable.
