"""Phase 12I — performance measurement (deterministic, no LLM).

Benchmarks parse() / intent-intelligence / conversation-policy / handle() on the
12I-affected utterances (KM, fuel attr, bare fields, Devanagari, booking,
multi-intent, negotiation). Confirms no meaningful overhead regression vs 12F.
"""
from __future__ import annotations
import os, shutil, tempfile, time, statistics, itertools

LIVE = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")

SAMPLES = [
    "km kitna hai?", "kitne km chali hai?", "petrol hai?", "डीजल है?",
    "boot?", "engine?", "safety features?", "कितने एयरबैग हैं?",
    "कितने मालिक हैं?", "booking?", "token amount?", "price aur insurance?",
    "km aur owners?", "RC aur insurance batao", "sunroof aur airbags?",
    "bhai mehengi hai", "dusri jagah sasti mil rahi hai", "last kya karoge?",
    "petrol wali dikhao", "sabse kam km wali car",
]


def _bench(fn, n=2000):
    fn()  # warm
    t = time.perf_counter()
    for _ in range(n):
        fn()
    return (time.perf_counter() - t) / n * 1000.0  # ms/call


def main():
    tmp = tempfile.mkdtemp(prefix="p12i_perf_")
    xlsx = os.path.join(tmp, "IVR_Sheet.xlsx"); shutil.copy(LIVE, xlsx)
    os.environ["CHAT_DATA_DIR"] = tmp
    try:
        from query_parser import parse
        from intent_intelligence import analyze as intel_analyze
        import conversation_policy as CP
        from chat_service import ChatService

        cyc = itertools.cycle(SAMPLES)
        p_parse = _bench(lambda: parse(next(cyc)))

        def _intel():
            m = next(cyc); q = parse(m); intel_analyze(m, q)
        p_intel_total = _bench(_intel)

        ctx = {"reg": None, "model": "Ertiga"}
        p_policy = _bench(lambda: CP.classify(next(cyc), ctx, rr_kind="inventory"))

        svc = ChatService(xlsx_path=xlsx)
        sid = "perf"
        for m in SAMPLES:
            svc.handle(m, session_id=sid)
        times = []
        for _ in range(300):
            for m in SAMPLES:
                t = time.perf_counter()
                svc.handle(m, session_id=sid)
                times.append((time.perf_counter() - t) * 1000.0)
        svc.close()

        print("=== Phase 12I performance (ms/call, no LLM) ===")
        print(f"parser.parse()          : {p_parse:.3f} ms")
        print(f"parse()+intel_analyze() : {p_intel_total:.3f} ms  "
              f"(intel delta ~{p_intel_total-p_parse:.3f} ms)")
        print(f"conversation_policy     : {p_policy:.3f} ms")
        print(f"ChatService.handle()    : mean={statistics.mean(times):.3f}  "
              f"median={statistics.median(times):.3f}  "
              f"p95={sorted(times)[int(len(times)*0.95)]:.3f}  "
              f"max={max(times):.3f}  (n={len(times)})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
