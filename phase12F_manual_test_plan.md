# Phase 12F — Owner's Manual Test Plan

A short, real-world checklist. Do these once before going live. Each step says
what to do and what a **pass** looks like. ~20 minutes total.

> Setup: start the server, open the Owner Panel and the chatbot widget in a browser.
> Keep the live `IVR_Sheet.xlsx` backed up before you upload anything.

---

### 1. Owner login
- Log in with the owner account.
- **Pass:** you reach the Owner Panel; a wrong password is rejected.

### 2. Excel upload
- Upload your `IVR_Sheet.xlsx`.
- **Pass:** it reports the number of cars loaded (currently ~44) with no error.

### 3. Vehicle details editing
- Open one car in **Vehicle Details**, tick/enter a few features (e.g. **Sunroof**,
  **Camera**, **Music system / speakers**, **Parking sensors**), save.
- Reopen the same car.
- **Pass:** your values are still there; completion % went up.

### 4. Staff role access
- Log in as a **Staff** user.
- **Pass:** Staff can do their allowed tasks but **cannot** reach owner-only
  actions (user management / delete). Owner-only controls are hidden or blocked.

### 5. Chatbot basic search
- Ask: **"SUV under 8 lakh"**, then **"Show me Ertiga"**.
- **Pass:** relevant cars are listed; prices only shown when quotable.

### 6. Pinned-car questions
- After "Show me Fortuner" (or any single car), ask **"RC?"**, **"kitne owners?"**,
  **"insurance?"**.
- **Pass:** answers are about **that** car. If a detail isn't filled in, it says
  **"Data not available"** — it never makes up a value.

### 7. Vehicle feature questions
- On a pinned car ask **"sunroof hai?"**, **"airbags kitne hain?"**,
  **"boot space?"**, **"camera hai?"**.
- **Pass:** filled fields give the value (e.g. "Airbags: 7"); empty fields say
  "Data not available". (Fill features in step 3 to see real answers.)

### 8. Same-model variants
- "Show me Ertiga" → **"automatic wali?"** → **"petrol wali?"**.
- **Pass:** it stays on **Ertiga** and narrows down; it does not jump to a random model.

### 9. Fresh search
- In the same chat, now ask **"7 seater chahiye"**.
- **Pass:** it starts a **new** search (not stuck on the previous car).

### 10. Multi-intent
- Ask **"sunroof aur airbags hain?"** on a pinned car.
- **Pass:** **both** are answered in one reply.

### 11. Hindi / Hinglish / Marathi
- Ask **"gaadi kitna chali?"** (Hinglish), **"किती एअरबॅग आहेत?"** (Marathi).
- **Pass:** correct answer; Marathi replies come back in Marathi, and a missing
  value reads **"माहिती उपलब्ध नाही"**.

### 12. Missing-data behaviour
- Ask about a feature you know is blank (e.g. **"touchscreen kitna inch?"** if not entered).
- **Pass:** "Data not available" — never a made-up number.

### 13. Audit logs
- As owner, open the audit log.
- **Pass:** your login and the Excel upload / edits from steps 1–3 appear with
  user and timestamp.

---

**If every step passes, the system is ready for real-user testing.**
If any step fails, note the exact message you typed and what came back, and share it.
