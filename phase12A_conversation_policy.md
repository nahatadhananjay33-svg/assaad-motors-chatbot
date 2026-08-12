# Phase 12A — Conversation Policy Design (STEP 7)

*Design only. No prompts, no LLM.* Deterministic response **policies** — fixed
step sequences the engine can execute for each conversation pattern. Each policy
is a state flow the bot follows; wording stays in the existing template layer.

**Global invariants (apply to every policy):**
- Never fabricate a fact — Unknown field → "our team will confirm at your visit".
- Never promise a discount, guarantee finance approval, or quote a number not on file.
- Always keep the customer moving toward **visit / booking / contact capture**.
- Never leak internal fields (reg-slot/stock#). Reply in the customer's language.
- One clarifying question at a time; never guess on conflict/low-confidence.

---

## 1. Negotiation / last price
```
Detect negotiation → Acknowledge ("samajh sakta hoon")
   → Build value (this car's real strengths from DATA)
   → State prices are fixed (transparent, one price for all)
   → Invite showroom visit / best-price-in-person-with-team
   → Capture contact
NEVER: quote a discount, imply price will drop.
```

## 2. Price objection ("too expensive")
```
Acknowledge budget concern
   → Justify with facts (ownership, low km, condition, features)
   → Offer alternative in stated budget (retrieval)
   → Invite inspection to judge value
```

## 3. Trust objection
```
Acknowledge
   → Business credibility (years in business, transparent data)
   → Offer to verify documents/condition in person
   → Invite visit
NEVER: fake reviews or claims.
```

## 4. Finance objection
```
Acknowledge affordability goal
   → Confirm finance availability (eligibility rule: e.g. 2014+)
   → Give ESTIMATE only (deterministic 20% DP / EMI ballpark)
   → Route exact terms to team; state approval not guaranteed
   → Capture contact
```

## 5. Comparison
```
Identify the two options (models in stock)
   → Compare on DATA facts only (price/year/km/owners/fuel/key features)
   → Recommend based on stated need (family/city/mileage)
   → Invite to see both
NEVER: subjective "X is bad".
```

## 6. Confused / vague
```
Detect low-confidence / general intent
   → Ask ONE question (budget OR use-case)
   → On answer: recommend 1–2 (consultative layer)
   → Proceed to details/visit
(Conflict variant: ask which value — "petrol ya diesel?")
```

## 7. Emotional / anxious
```
Empathise briefly
   → Reassure with transparency (accident/owner/condition DATA)
   → Invite to verify in person, no pressure
   → Offer human contact
```

## 8. Harsh / rude
```
Stay professional (never mirror)
   → Answer the underlying question factually
   → Offer human handoff
   → Do not escalate; do not refuse service
```

## 9. Urgent
```
Confirm availability now
   → Give timing + location immediately
   → Offer to hold/booking + capture contact NOW
   → Fast path to visit
```

## 10. Lead qualification
```
Passively capture budget/use/contact as they appear (lead engine)
   → When enough signal: recommend best-fit
   → Move to visit/booking
   → Mark lead level (High/Med/Low) for the team
```

## 11. Appointment / booking
```
Give timing + location + booking amount + refund policy (FAQ)
   → Capture contact + preferred slot
   → Confirm + set expectation (team will reconfirm)
```

## 12. Test drive
```
Confirm TD availability/policy
   → Invite to showroom (TD in person)
   → Capture contact + preferred time
```

## 13. Visit confirmation
```
Timing + address + maps link + parking (FAQ)
   → Confirm slot
   → Capture contact
```

## 14. Repeat / returning
```
Reuse remembered vehicle/context (Phase 11 memory)
   → Acknowledge return
   → Continue where left off / fast-track to visit
```

## 15. Exchange
```
Confirm exchange accepted
   → Explain valuation happens at visit (condition-dependent)
   → Capture old-car basics (model/year/km)
   → Invite visit
NEVER: quote an exchange price online.
```

## 16. Contact / human handoff
```
Acknowledge + capture number (lead engine, PII-masked in logs)
   → Promise callback + give WhatsApp/location
   → Continue helping meanwhile
```

## 17. Greeting / small-talk
```
Short warm reply → "how can I help — budget or model?"
```

## 18. Out-of-scope / unknown
```
Honest scope statement ("I can help with our cars, price, visit")
   → Offer human contact
NEVER: fabricate an answer.
```

---

## Policy engine shape (recommendation for 12E)

A tiny deterministic **policy table**: `pattern → ordered steps → template keys`.
The detector (FAQ intent + Phase 11B band/conflict + small lexicons) picks the
pattern; the policy runner emits the step sequence using existing templates. This
keeps conversation behaviour **auditable, testable, and LLM-free**, and easy to
extend by adding rows — consistent with the current architecture.

**Precedence (when multiple patterns match):** safety/scope (18) > conflict-clarify
(6) > contact/human (16) > booking/visit/urgent (9,11,12,13) > negotiation/finance/
comparison (1,4,5) > info answer > greeting (17). This mirrors the existing
router's "detail/clarify beats generic" ordering.
