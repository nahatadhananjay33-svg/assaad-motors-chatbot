"""Phase 12J audit trace — CURRENT behaviour for mileage / multi-attr / model-only.
Run from app/inventory_system:  PYTHONIOENCODING=utf-8 python phase12j_trace.py
No code changes."""
from __future__ import annotations
import os, shutil, tempfile

LIVE = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")
tmp = tempfile.mkdtemp(); xlsx = os.path.join(tmp, "IVR_Sheet.xlsx"); shutil.copy(LIVE, xlsx)
os.environ["CHAT_DATA_DIR"] = tmp

from query_parser import parse
from chat_service import ChatService

svc = ChatService(xlsx_path=xlsx)


def show_parse(m):
    q = parse(m)
    keys = ("model", "make", "category", "fuel", "fuel_query", "transmission",
            "transmission_query", "km_reading_query", "km_max", "sort_low_km",
            "attr_fields", "feature_filters", "ambiguous_field", "price_max",
            "sort_cheapest", "condition_query", "insurance_query", "rc_query",
            "ownership_query", "seats_query")
    f = {k: getattr(q, k) for k in keys if getattr(q, k) not in (None, [], {}, False)}
    f["intents"] = sorted(q.intents)
    return q, f


def run(session, msg, pin_msg=None):
    if pin_msg and session:
        svc.handle(pin_msg, session_id=session)
    q, f = show_parse(msg)
    r = svc.handle(msg, session_id=session)
    print(f"  {msg!r}")
    print(f"     parse: {f}")
    print(f"     -> intent={r.intent} status={r.status} count={r.count} "
          f"mode={r.meta.get('conversation_mode')}")
    print(f"        {(r.response or '')[:150]}")


print("=== A. MILEAGE / KM (pinned Fortuner) ===")
for i, m in enumerate(["mileage?", "mileage kitna hai?", "kitne km chali?",
                       "running kitni hai?", "average kitna hai?",
                       "mileage kya hai?", "kitna average deti hai?"]):
    run(f"A{i}", m, pin_msg="MH04EX5958 available hai?")

print("\n=== A2. MILEAGE cold (no pin) ===")
for i, m in enumerate(["mileage?", "good mileage car", "mileage kitna hai?"]):
    run(f"A2{i}", m)

print("\n=== B. MULTI-ATTRIBUTE (pinned Fortuner) ===")
for i, m in enumerate(["automatic aur petrol?", "automatic aur petrol hai?",
                       "automatic petrol wali dikhao", "automatic petrol chahiye",
                       "automatic diesel", "diesel aur manual hai?"]):
    run(f"B{i}", m, pin_msg="MH04EX5958 available hai?")

print("\n=== B2. MULTI-ATTR cold (no pin) ===")
for i, m in enumerate(["automatic aur petrol?", "automatic petrol wali dikhao"]):
    run(f"B2{i}", m)

print("\n=== C. MODEL-ONLY: MULTIPLE (Ertiga = 2 cars) ===")
print("   Ertiga A: 2019 Hybrid Automatic 7-seat 2ab km80000")
print("   Ertiga B: 2016 Petrol Manual 7-seat 2ab km39000")
for i, m in enumerate(["automatic hai?", "petrol hai?", "price?", "RC?",
                       "kitne km chali?", "kitne seater hai?", "airbags kitne?",
                       "kaunsa year hai?"]):
    run(f"C{i}", m, pin_msg="show me Ertiga")

print("\n=== C2. MODEL-ONLY: variant search should still search ===")
for i, m in enumerate(["automatic wali dikhao", "petrol wali dikhao",
                       "kam km wali dikhao"]):
    run(f"C2{i}", m, pin_msg="show me Ertiga")

print("\n=== C3. MODEL-ONLY: SINGLE (Fortuner) still pins ===")
for i, m in enumerate(["automatic hai?", "price?", "kitne km chali?"]):
    run(f"C3{i}", m, pin_msg="show me Fortuner")

svc.close()
shutil.rmtree(tmp, ignore_errors=True)
