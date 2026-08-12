"""Phase 12G audit trace — prints the exact current decision path. No code changes."""
from __future__ import annotations
import os, shutil, tempfile
LIVE = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")
tmp = tempfile.mkdtemp(); xlsx = os.path.join(tmp, "IVR_Sheet.xlsx"); shutil.copy(LIVE, xlsx)
os.environ["CHAT_DATA_DIR"] = tmp

from query_parser import parse
import chat_service as CS
from chat_service import ChatService, _is_attr_followup, _is_price_followup, _has_refinement

svc = ChatService(xlsx_path=xlsx)

def show_parse(m):
    q = parse(m)
    fields = {k: getattr(q, k) for k in
              ("year_exact", "year_min", "transmission", "transmission_query",
               "sort_low_km", "km_reading_query", "km_max", "model", "registration",
               "reg_partial", "attr_fields", "feature_filters")
              if getattr(q, k) not in (None, [], {}, False)}
    return q, fields

def run(session, msg):
    q, f = show_parse(msg)
    r = svc.handle(msg, session_id=session)
    print(f"  {msg!r}")
    print(f"     parse: {f}")
    print(f"     is_attr_followup={_is_attr_followup(msg, q)}  has_refinement={_has_refinement(q)}")
    print(f"     -> intent={r.intent} status={r.status} count={r.count} "
          f"mode={r.meta.get('conversation_mode')}")
    print(f"        {(r.response or '')[:120]}")

# what is the pinned Fortuner actually?
import inventory_loader as L
for it in L.load_inventory(xlsx):
    if it.model == "Fortuner":
        print(f"PINNED FORTUNER: year={it.year_int} trans={it.transmission_norm} km={it.km_driven}")
        break

print("\n=== YEAR ===")
svc.handle("Show me Fortuner", session_id="y"); run("y", "2019 model hai?")
svc.handle("Show me Fortuner", session_id="y2"); run("y2", "ye 2019 model hai?")
svc.handle("Show me Fortuner", session_id="y3"); run("y3", "model year kya hai?")
svc.handle("Show me Fortuner", session_id="y4"); run("y4", "kaunsa year hai?")
run("cold_y", "2019 model hai?")            # unpinned
run("cold_y2", "2019 model chahiye")        # unpinned search

print("\n=== KM ===")
svc.handle("Show me Fortuner", session_id="k"); run("k", "kam km chali hai?")
svc.handle("Show me Fortuner", session_id="k2"); run("k2", "kitni km chali hai?")
svc.handle("Show me Fortuner", session_id="k3"); run("k3", "running kitni hai?")
svc.handle("Show me Fortuner", session_id="k4"); run("k4", "odometer kya hai?")
run("cold_k", "kam km wali car chahiye")    # unpinned search
run("cold_k2", "sabse kam km wali car")     # unpinned sort
svc.handle("Show me Fortuner", session_id="k5"); run("k5", "low km wali car dikhao")

print("\n=== TRANSMISSION ===")
svc.handle("Show me Fortuner", session_id="t"); run("t", "automatic hai?")
svc.handle("Show me Fortuner", session_id="t2"); run("t2", "ye automatic hai?")
svc.handle("Show me Fortuner", session_id="t3"); run("t3", "manual hai?")
svc.handle("Show me Fortuner", session_id="t4"); run("t4", "transmission automatic hai?")
svc.handle("Show me Fortuner", session_id="t5"); run("t5", "automatic wali dikhao")
svc.handle("Show me Fortuner", session_id="t6"); run("t6", "automatic wali chahiye")
run("cold_t", "automatic cars dikhao")      # unpinned
run("cold_t2", "automatic mein koi hai?")   # unpinned

svc.close()
shutil.rmtree(tmp, ignore_errors=True)
