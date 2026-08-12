"""End-to-end Phase 11A validation via the REAL ChatService (STEP 5/6)."""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.getcwd())

from chat_service import ChatService

svc = ChatService()

# find a model that has exactly ONE available car (clean single-car pin)
from collections import Counter
by_model = Counter(it.model for it in svc.engine.all_facing if it.model)
single = [m for m, c in by_model.items() if c == 1]
pin_reg = None
for it in svc.engine.all_facing:
    if it.model in single:
        pin_reg = it.registration_no
        pin_model = it.model
        break
print(f"Pinning single-car model: {pin_model} ({pin_reg})\n")


def run(msg, sid):
    r = svc.handle(msg, session_id=sid)
    print(f"  [{r.intent}/{r.status}] {msg!r}\n     -> {r.response[:150]}")
    return r


print("=== COLD attribute questions (no pin) -> should CLARIFY 'which car?' ===")
for m in ["RC?", "Color?", "Fuel?", "Transmission?", "kitni seats", "KM?",
          "Claim hua?", "Final?", "Warranty?", "Owner?"]:
    run(m, sid=f"cold-{m}")

print("\n=== PINNED (pin one car by reg, then bare field question) ===")
sid = "pin1"
run(f"{pin_reg} available hai?", sid)  # pin the car
for m in ["RC?", "Color?", "Fuel?", "Transmission?", "kitni seats", "KM?",
          "Running?", "Kitni chali?", "Claim hua?", "Touch-up?", "Final?",
          "Warranty?", "Guarantee?", "Owner?", "Insurance?", "Service history?",
          "Transfer?", "NOC?", "Fitness?", "Original papers?", "EMI?"]:
    run(m, sid)

print("\n=== media / budget quick checks ===")
run("Shorts", "m1")
run("Below 8", "m2")
run("6 lakh ke andar", "m3")
