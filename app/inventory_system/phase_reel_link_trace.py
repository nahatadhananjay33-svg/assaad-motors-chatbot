"""Trace: a pasted Instagram reel LINK, and the sold / not-available case."""
from __future__ import annotations
import os, shutil, tempfile
LIVE = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")
tmp = tempfile.mkdtemp(); xlsx = os.path.join(tmp, "IVR_Sheet.xlsx"); shutil.copy(LIVE, xlsx)
os.environ["CHAT_DATA_DIR"] = tmp
from query_parser import parse
from chat_service import ChatService
svc = ChatService(xlsx_path=xlsx)


_n = [0]
def run(msg, sid=None):
    _n[0] += 1
    sid = sid or f"s{_n[0]}"       # unique session per call (no context leak)
    q = parse(msg)
    r = svc.handle(msg, session_id=sid)
    print(f"  {msg!r}")
    print(f"     parse: model={q.model} reg={q.registration} reg_partial={q.reg_partial}")
    print(f"     -> intent={r.intent} status={r.status} count={r.count}")
    print(f"        {(r.response or '')[:160]}")


print("=== PASTED REEL LINKS (shortcode must NOT resolve a random car) ===")
for m in [
    "https://www.instagram.com/reel/C5xYz1AbCdE/",
    "https://www.instagram.com/reel/C5xYz1AbCdE/ ye gaadi hai kya?",
    "https://instagram.com/reel/DG9444kLm/",          # contains 9444 (a real plate tail)
    "https://www.instagram.com/reel/i20City99/",      # contains 'i20' + digits
    "instagram.com/p/Cabc123def/ is this available?",
    "ye gaadi available hai? https://www.instagram.com/reel/Reel8000xy/",
    "https://www.instagram.com/reel/CkiaSonet1/",     # contains 'kia'/'sonet'
]:
    run(m)

print("\n=== SOLD / NOT AVAILABLE (customer gives an id that isn't in stock) ===")
for m in [
    "XUV700 hai kya?",              # model not in inventory
    "MH99XX0000 hai kya?",          # registration not in inventory
    "0001 wali gaadi hai kya?",     # partial plate not matching
    "Ferrari available hai?",       # unknown model
]:
    run(m)

svc.close()
shutil.rmtree(tmp, ignore_errors=True)
