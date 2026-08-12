"""Phase 12F — performance measurement (deterministic, no LLM)."""
from __future__ import annotations
import os, shutil, tempfile, time, statistics

LIVE = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")

SAMPLES = [
    "SUV under 8 lakh", "Show me Ertiga", "sunroof hai?", "airbags kitne hain?",
    "boot space aur ground clearance?", "automatic wali?", "petrol ya diesel?",
    "camera aur parking sensors hain?", "7 seater chahiye", "kitne owners?",
    "sabse kam km wali car", "insurance?", "finance milega?", "engine kitna cc hai?",
    "किती एअरबॅग आहेत?",
]


def _bench(fn, n=2000):
    fn()  # warm
    t = time.perf_counter()
    for _ in range(n):
        fn()
    return (time.perf_counter() - t) / n * 1000.0  # ms/call


def main():
    tmp = tempfile.mkdtemp(prefix="p12f_perf_")
    xlsx = os.path.join(tmp, "IVR_Sheet.xlsx"); shutil.copy(LIVE, xlsx)
    os.environ["CHAT_DATA_DIR"] = tmp
    try:
        from query_parser import parse
        from intent_intelligence import analyze as intel_analyze
        import conversation_policy as CP
        from chat_service import ChatService

        import itertools
        cyc = itertools.cycle(SAMPLES)

        # 1) parser
        p_parse = _bench(lambda: parse(next(cyc)))
        # 2) intent intelligence (parse + analyze — measure analyze delta)
        def _intel():
            m = next(cyc); q = parse(m); intel_analyze(m, q)
        p_intel_total = _bench(_intel)
        # 3) conversation policy classify (with a pinned ctx)
        ctx = {"reg": None, "model": "Ertiga"}
        p_policy = _bench(lambda: CP.classify(next(cyc), ctx, rr_kind="inventory"))

        # 4) full ChatService.handle overhead (end-to-end, single session)
        svc = ChatService(xlsx_path=xlsx)
        sid = "perf"
        # warm
        for m in SAMPLES:
            svc.handle(m, session_id=sid)
        times = []
        for _ in range(400):
            for m in SAMPLES:
                t = time.perf_counter()
                svc.handle(m, session_id=sid)
                times.append((time.perf_counter() - t) * 1000.0)
        svc.close()

        print("=== Phase 12F performance (ms/call, no LLM) ===")
        print(f"parser.parse()          : {p_parse:.3f} ms")
        print(f"parse()+intel_analyze() : {p_intel_total:.3f} ms  (intel delta ~{p_intel_total-p_parse:.3f} ms)")
        print(f"conversation_policy     : {p_policy:.3f} ms")
        print(f"ChatService.handle()    : mean={statistics.mean(times):.3f}  "
              f"median={statistics.median(times):.3f}  "
              f"p95={sorted(times)[int(len(times)*0.95)]:.3f}  "
              f"max={max(times):.3f}  (n={len(times)})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
