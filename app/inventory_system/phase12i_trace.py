"""Phase 12I audit trace — prints the exact CURRENT decision path. No code changes.

Run from app/inventory_system:  python phase12i_trace.py
Covers every Step-1 case group: bare fields, KM, fuel, Devanagari, booking,
multi-intent, negotiation — pinned and cold.
"""
from __future__ import annotations
import os, shutil, tempfile

LIVE = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")
tmp = tempfile.mkdtemp(); xlsx = os.path.join(tmp, "IVR_Sheet.xlsx"); shutil.copy(LIVE, xlsx)
os.environ["CHAT_DATA_DIR"] = tmp

from query_parser import parse
import chat_service as CS
from chat_service import ChatService

svc = ChatService(xlsx_path=xlsx)

PIN = "Fortuner"     # MH04EX5958: 2011 Diesel, 169773 km, 7 airbags, 2 owners


def show_parse(m):
    q = parse(m)
    keys = ("model", "make", "category", "fuel", "fuel_query", "transmission",
            "transmission_query", "year_exact", "year_query", "sort_low_km",
            "km_reading_query", "km_max", "condition_query", "ownership_query",
            "insurance_query", "attr_fields", "feature_filters", "price_max",
            "sort_cheapest", "off_sheet", "reg_partial")
    f = {k: getattr(q, k) for k in keys if getattr(q, k) not in (None, [], {}, False)}
    f["intents"] = sorted(q.intents)
    return q, f


def run(session, msg, pin=True):
    if pin and session:
        svc.handle(f"Show me {PIN}", session_id=session)
    q, f = show_parse(msg)
    r = svc.handle(msg, session_id=session)
    print(f"  {msg!r}")
    print(f"     parse: {f}")
    print(f"     -> intent={r.intent} status={r.status} count={r.count} "
          f"mode={r.meta.get('conversation_mode')}")
    print(f"        {(r.response or '')[:150]}")


def group(name, cases, pin=True):
    print(f"\n=== {name} ===")
    key = "".join(ch for ch in name if ch.isalnum())
    for i, m in enumerate(cases):
        run(f"{key}_{i}", m, pin=pin)


print("PIN =", PIN, "(2011 Diesel, 169773 km, 7 airbags, 2 owners)")

group("BARE FIELDS (pinned)", [
    "engine?", "battery?", "mileage?", "camera?", "sunroof?", "airbags?",
    "owners?", "insurance?", "boot?", "touchscreen?", "abs?", "power steering?",
    "safety features?",
])

group("KM (pinned)", [
    "km kitna hai?", "kitna km hai?", "kitne km chali hai?", "kitna chala hai?",
    "running kitni hai?", "odometer?", "odometer reading?",
])

group("KM SEARCH (should stay search)", [
    "kam km wali dikhao", "lowest km", "20000 km se kam wali",
    "sabse kam km wali car",
], pin=False)

group("FUEL ATTR (pinned)", [
    "petrol hai?", "diesel hai?", "fuel kya hai?", "ye petrol hai?",
    "ye diesel hai?",
])

group("FUEL SEARCH (should stay search)", [
    "petrol wali dikhao", "diesel wali dikhao", "petrol chahiye",
    "diesel wali under 8 lakh",
], pin=False)

group("DEVANAGARI (pinned)", [
    "कितने एयरबैग हैं?", "एयरबैग कितने हैं?", "कितने किलोमीटर चली है?",
    "कितने km है?", "पेट्रोल है?", "डीजल है?", "सनरूफ है?", "कैमरा है?",
    "कितने मालिक हैं?", "किती km चालली आहे?",
])

group("BOOKING", [
    "booking?", "booking kaise karni hai?", "car book kar sakte hain?",
    "booking amount?", "reserve kar sakte hain?", "token amount?",
], pin=False)

group("FINANCE (should stay finance/EMI)", [
    "loan?", "finance?", "EMI?", "down payment?",
], pin=False)

group("MULTI-INTENT (pinned)", [
    "price aur insurance?", "km aur owners?", "sunroof aur airbags?",
    "camera aur parking sensors?", "automatic aur petrol?",
    "RC aur insurance batao", "price aur km batao",
])

group("NEGOTIATION", [
    "final price?", "discount?", "bhai mehengi hai", "bahut expensive hai",
    "kuch kam karo", "last kya karoge?", "dusri jagah sasti mil rahi hai",
    "itne mein nahi lunga", "why so expensive?", "itna mehenga kyun?",
], pin=False)

svc.close()
shutil.rmtree(tmp, ignore_errors=True)
