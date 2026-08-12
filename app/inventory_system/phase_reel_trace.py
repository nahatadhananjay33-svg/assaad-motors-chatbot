"""Audit trace — CURRENT behaviour for 'reel wali gaadi' / Instagram queries."""
from __future__ import annotations
import os, shutil, tempfile
LIVE = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")
tmp = tempfile.mkdtemp(); xlsx = os.path.join(tmp, "IVR_Sheet.xlsx"); shutil.copy(LIVE, xlsx)
os.environ["CHAT_DATA_DIR"] = tmp
from query_parser import parse
from chat_service import ChatService
svc = ChatService(xlsx_path=xlsx)


def run(session, msg, pin=None):
    if pin and session:
        svc.handle(pin, session_id=session)
    q = parse(msg)
    r = svc.handle(msg, session_id=session)
    print(f"  {msg!r}")
    print(f"     parse: reel_stripped={q.reel_stripped} clarify_needed={q.clarify_needed} "
          f"model={q.model} reg={q.registration} reg_partial={q.reg_partial}")
    print(f"     -> intent={r.intent} status={r.status} count={r.count}")
    print(f"        {(r.response or '')[:180]}")
    if r.media:
        print(f"        media_status={r.media.get('status')}")


print("=== BARE REEL QUERIES (no car identified) ===")
for i, m in enumerate([
    "ye reel wali gaadi hai kya?",
    "is this car available which is in the reel",
    "reel wali gaadi",
    "instagram wali car available hai?",
    "jo reel me thi wo gaadi available hai?",
    "reel me dikhi gaadi chahiye",
    "insta pe dekhi thi wo car",
    "ye wali gaadi hai kya jo reel me thi",
    "reel",
]):
    run(f"R{i}", m)

print("\n=== REEL + CAR IDENTIFIER ===")
for i, m in enumerate([
    "reel wali Fortuner available hai?",
    "MH04EX5958 reel wali hai kya?",
    "reel wali white creta",
    "9444 wali reel gaadi",
    "reel me jo nexon thi",
]):
    run(f"RC{i}", m)

print("\n=== FOLLOW-UP AFTER REEL CLARIFY ===")
svc.handle("ye reel wali gaadi hai kya?", session_id="F")
run("F", "Fortuner")
svc.handle("reel wali gaadi", session_id="F2")
run("F2", "MH04EX5958")

svc.close()
shutil.rmtree(tmp, ignore_errors=True)
