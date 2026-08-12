# Go-Live Decision

Use this **after** completing `LOCAL_TESTING_CHECKLIST.md`.

The rule is simple.

---

## The rule

### ✅ If EVERY box is ticked
```
READY FOR VPS
```
The system passed all local tests. It is safe to move to the next phase
(deployment on the VPS / internet).

### ❌ If ANY box is NOT ticked
```
DO NOT DEPLOY
```
Even one failing test means **stop**. Do not put it on the internet. Send the
unticked item(s) to the technical person to fix, then test again from the start.

---

## How to decide (30 seconds)

1. Open `LOCAL_TESTING_CHECKLIST.md`.
2. Look at the bottom: **"Any box unticked? YES / NO"**.
   - **NO** (all 18 ticked) → **READY FOR VPS**.
   - **YES** (one or more empty) → **DO NOT DEPLOY**.

---

## Write your decision here

- Date tested: ____________
- Boxes ticked: ______ / 18
- All boxes ticked? **YES / NO**

**Decision (circle one):**

```
   READY FOR VPS            DO NOT DEPLOY
```

- If DO NOT DEPLOY, list what failed:
  1. ______________________________________________
  2. ______________________________________________
  3. ______________________________________________

- Signed: ____________________

---

> Reminder: never deploy on a "mostly works". The checklist is the gate —
> **all green, or no go.**
