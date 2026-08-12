"""
phase12f_e2e.py
===============
Phase 12F — FINAL end-to-end conversation validation (read-only; no writes to the
live workbook). Runs realistic buyer conversations through the REAL ChatService
and prints intent / conversation_mode / response so behaviour can be judged.

Covers STEP 2..8 of the Phase 12F brief:
  2  vehicle questions (pinned vs unpinned)
  3  filter vs attribute
  4  conversation flows (STEP 9 sequence + conflicts)
  5  multi-intent
  6  language coverage (EN / HI / Hinglish / Marathi, natural variations)
  7  missing data
  8  unknown / off-sheet

NO LLM. Deterministic. Uses a COPY of the workbook.
"""
from __future__ import annotations
import os, shutil, tempfile

os.environ.setdefault("CHAT_XLSX", "")  # will be overridden below

LIVE = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")


def _mk_service():
    tmp = tempfile.mkdtemp(prefix="p12f_")
    xlsx = os.path.join(tmp, "IVR_Sheet.xlsx")
    shutil.copy(LIVE, xlsx)
    # isolate persistence dbs
    os.environ["CHAT_DATA_DIR"] = tmp
    from chat_service import ChatService
    return ChatService(xlsx_path=xlsx), tmp


def _line(tag, msg, r):
    mode = r.meta.get("conversation_mode")
    resp = (r.response or "").replace("\n", " / ")
    if len(resp) > 140:
        resp = resp[:137] + "..."
    print(f"[{tag}] {msg!r}")
    print(f"     -> intent={r.intent} status={r.status} count={r.count} mode={mode}")
    print(f"        {resp}")


def main():
    svc, tmp = _mk_service()
    try:
        # pick a clean single-car model and a two-car model
        SINGLE = "Fortuner"   # 1 car
        DUAL = "Ertiga"       # 2 cars

        print("\n########## STEP 2 — VEHICLE QUESTIONS (pinned single car) ##########")
        s = "seg2"
        r = svc.handle(f"Show me {SINGLE}", session_id=s); _line("pin", f"Show me {SINGLE}", r)
        for q in ["sunroof hai?", "airbags kitne hain?", "boot space?",
                  "ground clearance?", "music system hai?", "camera hai?",
                  "alloy wheels?", "automatic hai?", "kitne owners?",
                  "insurance?", "RC?", "service history?", "engine kitna cc hai?"]:
            _line("Q", q, svc.handle(q, session_id=s))

        print("\n########## STEP 2b — SAME QUESTIONS, NO PINNED CAR (must clarify) ##########")
        for i, q in enumerate(["sunroof hai?", "airbags kitne hain?", "boot space?",
                               "music system hai?", "kitne owners?", "insurance?",
                               "engine kitna cc hai?"]):
            r = svc.handle(q, session_id=f"cold{i}")  # fresh session each -> no pin
            _line("COLD", q, r)

        print("\n########## STEP 3 — FILTER vs ATTRIBUTE ##########")
        # attribute (pinned)
        sp = "seg3pin"
        svc.handle(f"Show me {SINGLE}", session_id=sp)
        for q in ["sunroof hai?", "6 airbags hain?", "2019 model hai?", "kam km chali hai?"]:
            _line("ATTR", q, svc.handle(q, session_id=sp))
        # filter (fresh sessions)
        for i, q in enumerate(["sunroof wali car chahiye", "6 airbags wali car chahiye",
                               "2019 model chahiye", "sabse kam km wali car"]):
            _line("FILTER", q, svc.handle(q, session_id=f"seg3f{i}"))

        print("\n########## STEP 4 — CONVERSATION FLOW (STEP 9 sequence) ##########")
        f = "seg4"
        for q in ["Show me Ertiga", "automatic wali?", "petrol wali?", "RC?",
                  "sunroof?", "7 seater chahiye"]:
            _line("FLOW", q, svc.handle(q, session_id=f))
        print("  -- conflict vs disjunction --")
        _line("CONFLICT", "petrol diesel", svc.handle("petrol diesel", session_id="seg4b"))
        _line("DISJ", "petrol ya diesel?", svc.handle("petrol ya diesel?", session_id="seg4c"))

        print("\n########## STEP 5 — MULTI-INTENT (pinned) ##########")
        m = "seg5"
        svc.handle(f"Show me {SINGLE}", session_id=m)
        for q in ["sunroof aur airbags hain?", "automatic hai aur kitne owners hain?",
                  "boot space aur ground clearance?", "camera aur parking sensors hain?"]:
            _line("MULTI", q, svc.handle(q, session_id=m))

        print("\n########## STEP 6 — LANGUAGE COVERAGE (pinned) ##########")
        lg = "seg6"
        svc.handle(f"Show me {SINGLE}", session_id=lg)
        for q in ["sunroof hai kya?", "sunroof milta hai?", "roof khulti hai?",
                  "isme kitne airbags hai?", "kitne malik rahe?", "gaadi kitna chali?",
                  "running kitni hai?", "camera laga hai?", "music system hai?",
                  # Marathi
                  "sunroof aahe ka?", "किती एअरबॅग आहेत?", "बूट स्पेस किती?"]:
            _line("LANG", q, svc.handle(q, session_id=lg))

        print("\n########## STEP 7 — MISSING DATA (fields empty in sheet) ##########")
        md = "seg7"
        svc.handle(f"Show me {SINGLE}", session_id=md)
        for q in ["music system hai?", "camera hai?", "parking sensors hain?",
                  "touchscreen kitna inch?", "battery health kitni?", "range kitna?"]:
            _line("MISS", q, svc.handle(q, session_id=md))

        print("\n########## STEP 8 — UNKNOWN / OFF-SHEET ##########")
        for i, q in enumerate(["is it a good car for astrology?",
                               "kya ye car chand par ja sakti hai?",
                               "iska horoscope kya hai?",
                               "engine oil kaunsa brand daalu?",
                               "resale value 2030 mein kya hogi?"]):
            _line("OFF", q, svc.handle(q, session_id=f"seg8_{i}"))

        svc.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
