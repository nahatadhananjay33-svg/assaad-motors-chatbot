"""
hardening_tests.py
=================

Verifies the Phase-4A.1 production-hardening fixes:
  * persistence (leads / analytics / unknown survive a restart)
  * runtime inventory refresh (no restart; sessions preserved)
  * API-key auth + rate limiting + CORS
  * PII masking in logs (never log a raw phone number)
  * configuration module

Run:  python hardening_tests.py
"""

import os
import json
import time
import logging
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer

import config
from security import mask_pii, mask_phone, RateLimiter, SecurityGate, extract_api_key
from lead_storage import LeadStore
from lead_capture import Lead, LeadCaptureEngine
from analytics import AnalyticsStore, AnalyticsEvent, AnalyticsEngine
from unknown_query_store import UnknownQueryStore
from chat_service import ChatService
from chat_api import make_handler

XLSX = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")


def tmp(name):
    d = tempfile.mkdtemp()
    return os.path.join(d, name)


# ─────────────────────────────────────────────────────────────────────────────
# 1. PII masking
# ─────────────────────────────────────────────────────────────────────────────
class TestPIIMasking(unittest.TestCase):
    def test_phone_masked(self):
        out = mask_pii("call me on 9876543210 please")
        self.assertNotIn("9876543210", out)
        self.assertIn("[PHONE]", out)

    def test_phone_with_country_code(self):
        self.assertNotIn("9876543210", mask_pii("+91 9876543210"))

    def test_name_masked(self):
        out = mask_pii("my name is Rahul Sharma")
        self.assertIn("[NAME]", out)
        self.assertNotIn("Rahul", out)

    def test_phone_and_name(self):
        out = mask_pii("I am Priya, number 9988776655")
        self.assertNotIn("9988776655", out)
        self.assertIn("[PHONE]", out)
        self.assertIn("[NAME]", out)

    def test_non_pii_unchanged(self):
        self.assertEqual(mask_pii("Creta under 8 lakh"), "Creta under 8 lakh")

    def test_empty(self):
        self.assertEqual(mask_pii(""), "")
        self.assertIsNone(mask_pii(None))

    def test_price_not_masked_as_phone(self):
        self.assertEqual(mask_phone("price 800000"), "price 800000")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Rate limiter
# ─────────────────────────────────────────────────────────────────────────────
class TestRateLimiter(unittest.TestCase):
    def test_allows_then_blocks(self):
        rl = RateLimiter(2, 60, clock=lambda: 100.0)
        self.assertTrue(rl.allow("k"))
        self.assertTrue(rl.allow("k"))
        self.assertFalse(rl.allow("k"))          # 3rd in window blocked

    def test_window_resets(self):
        t = {"now": 100.0}
        rl = RateLimiter(1, 10, clock=lambda: t["now"])
        self.assertTrue(rl.allow("k"))
        self.assertFalse(rl.allow("k"))
        t["now"] = 111.0                          # past the window
        self.assertTrue(rl.allow("k"))

    def test_per_key_isolation(self):
        rl = RateLimiter(1, 60, clock=lambda: 1.0)
        self.assertTrue(rl.allow("a"))
        self.assertTrue(rl.allow("b"))            # different key, own budget

    def test_disabled_when_non_positive(self):
        rl = RateLimiter(0, 60)
        self.assertTrue(all(rl.allow("k") for _ in range(100)))


# ─────────────────────────────────────────────────────────────────────────────
# 3. Security gate (auth + scopes + CORS)
# ─────────────────────────────────────────────────────────────────────────────
class TestSecurityGate(unittest.TestCase):
    def test_open_when_no_keys(self):
        g = SecurityGate()
        self.assertIsNone(g.authorize("POST", "/chat", {}, "ip"))

    def test_chat_requires_key(self):
        g = SecurityGate(api_keys={"k1"}, limiter=RateLimiter(100, 60))
        self.assertEqual(g.authorize("POST", "/chat", {}, "ip")[0], 401)
        self.assertIsNone(g.authorize("POST", "/chat", {"X-API-Key": "k1"}, "ip"))

    def test_bearer_token(self):
        g = SecurityGate(api_keys={"k1"}, limiter=RateLimiter(100, 60))
        self.assertIsNone(
            g.authorize("POST", "/chat", {"Authorization": "Bearer k1"}, "ip"))

    def test_admin_scope(self):
        g = SecurityGate(api_keys={"k1"}, admin_keys={"adm"}, limiter=RateLimiter(100, 60))
        self.assertEqual(
            g.authorize("POST", "/admin/refresh_inventory", {"X-API-Key": "k1"}, "ip")[0],
            401)                                   # chat key is not an admin key
        self.assertIsNone(
            g.authorize("POST", "/admin/refresh_inventory", {"X-API-Key": "adm"}, "ip"))

    def test_health_is_public(self):
        g = SecurityGate(api_keys={"k1"}, limiter=RateLimiter(100, 60))
        self.assertIsNone(g.authorize("GET", "/health", {}, "ip"))

    def test_rate_limit_returns_429(self):
        g = SecurityGate(limiter=RateLimiter(1, 60, clock=lambda: 1.0))
        self.assertIsNone(g.authorize("POST", "/chat", {}, "ip"))
        self.assertEqual(g.authorize("POST", "/chat", {}, "ip")[0], 429)

    def test_cors_wildcard(self):
        g = SecurityGate(allowed_origins=["*"])
        self.assertEqual(g.cors("https://x.com")["Access-Control-Allow-Origin"], "*")

    def test_cors_specific_origin(self):
        g = SecurityGate(allowed_origins=["https://shop.example"])
        self.assertEqual(g.cors("https://shop.example")["Access-Control-Allow-Origin"],
                         "https://shop.example")
        self.assertEqual(g.cors("https://evil.com"), {})   # not allowed

    def test_extract_api_key(self):
        self.assertEqual(extract_api_key({"X-API-Key": "abc"}), "abc")
        self.assertEqual(extract_api_key({"Authorization": "Bearer xyz"}), "xyz")
        self.assertIsNone(extract_api_key({}))


# ─────────────────────────────────────────────────────────────────────────────
# 4. Persistence (survives restart)
# ─────────────────────────────────────────────────────────────────────────────
class TestStorePersistence(unittest.TestCase):
    def test_lead_store_persists(self):
        path = tmp("leads.db")
        s = LeadStore(path)
        s.upsert(Lead(session_id="s1", phone="9876543210", score_level="High").to_record())
        s.close()
        s2 = LeadStore(path)                       # "restart"
        self.assertEqual(s2.get("s1")["phone"], "9876543210")
        s2.close()

    def test_analytics_store_persists(self):
        path = tmp("analytics.db")
        s = AnalyticsStore(path)
        s.record(AnalyticsEvent(session_id="s1", query="q", route="inventory",
                                vehicle="Creta", timestamp="2026-06-10T10:00:00+00:00"))
        s.close()
        s2 = AnalyticsStore(path)
        self.assertEqual(s2.count(), 1)
        self.assertEqual(s2.all()[0]["vehicle"], "Creta")
        s2.close()

    def test_unknown_store_persists(self):
        path = tmp("unknown.db")
        s = UnknownQueryStore(path)
        s.record("family car?", session_id="s1", language="english")
        s.close()
        s2 = UnknownQueryStore(path)
        self.assertEqual(s2.count(), 1)
        s2.close()

    @unittest.skipUnless(os.path.exists(XLSX), "no workbook")
    def test_chat_service_persists_across_restart(self):
        leads, analytics, unknown = tmp("l.db"), tmp("a.db"), tmp("u.db")
        svc = ChatService(XLSX, leads_db=leads, analytics_db=analytics, unknown_db=unknown)
        svc.handle("what's your address? my number 9876543210", session_id="sP")
        svc.handle("zzz unknown qqq", session_id="sQ")
        svc.close()
        # "restart" — new service, same files
        svc2 = ChatService(XLSX, leads_db=leads, analytics_db=analytics, unknown_db=unknown)
        self.assertEqual(svc2.lead_engine.get("sP").score_level, "High")
        self.assertGreaterEqual(svc2.analytics.store.count(), 2)
        self.assertGreaterEqual(svc2.analytics.unknown_store.count(), 1)
        svc2.close()

    def test_files_are_created_on_disk(self):
        path = tmp("leads.db")
        LeadStore(path).close()
        self.assertTrue(os.path.exists(path))


# ─────────────────────────────────────────────────────────────────────────────
# 5. Inventory refresh
# ─────────────────────────────────────────────────────────────────────────────
@unittest.skipUnless(os.path.exists(XLSX), "no workbook")
class TestInventoryRefresh(unittest.TestCase):
    def setUp(self):
        self.svc = ChatService(XLSX, leads_db=tmp("l.db"),
                               analytics_db=tmp("a.db"), unknown_db=tmp("u.db"))

    def tearDown(self):
        self.svc.close()

    def test_refresh_returns_ok_and_count(self):
        r = self.svc.refresh_inventory()
        self.assertEqual(r["status"], "ok")
        # data-driven: refresh must load a non-empty fleet (exact count tracks the
        # live sheet and changes as the owner updates inventory — don't hard-code it).
        self.assertGreater(r["inventory_count"], 0)
        self.assertIn("sync", r)

    def test_sessions_preserved_across_refresh(self):
        self.svc.handle("address bhejo, my number 9876543210", session_id="keep")
        self.svc.refresh_inventory()
        self.assertIsNotNone(self.svc.lead_engine.get("keep"))   # lead survives
        self.assertEqual(self.svc.lead_engine.get("keep").phone, "9876543210")

    def test_engine_works_after_refresh(self):
        self.svc.refresh_inventory()
        r = self.svc.handle("Creta available?")
        self.assertEqual(r.intent, "availability")

    def test_refresh_is_idempotent(self):
        self.svc.refresh_inventory()
        r2 = self.svc.refresh_inventory()
        self.assertEqual(r2["sync"]["updated"], 0)               # nothing changed


# ─────────────────────────────────────────────────────────────────────────────
# 6. Log masking integration (chat_service never logs a raw phone)
# ─────────────────────────────────────────────────────────────────────────────
class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


@unittest.skipUnless(os.path.exists(XLSX), "no workbook")
class TestLogMaskingIntegration(unittest.TestCase):
    def test_chat_log_has_no_raw_phone(self):
        cap = _Capture()
        logger = logging.getLogger("hardening-test")
        logger.handlers = [cap]
        logger.setLevel(logging.INFO)
        svc = ChatService(XLSX, logger=logger, leads_db=tmp("l.db"),
                          analytics_db=tmp("a.db"), unknown_db=tmp("u.db"))
        svc.handle("my name is Rahul, call 9876543210", session_id="m1")
        joined = "\n".join(cap.lines)
        self.assertIn('"event": "chat"', joined)
        self.assertNotIn("9876543210", joined)        # raw phone never logged
        self.assertIn("[PHONE]", joined)
        svc.close()


# ─────────────────────────────────────────────────────────────────────────────
# 7. Config
# ─────────────────────────────────────────────────────────────────────────────
class TestConfig(unittest.TestCase):
    def test_snapshot_has_no_secrets(self):
        snap = config.snapshot()
        self.assertNotIn("API_KEYS", snap)
        self.assertNotIn("api_keys", snap)
        self.assertIn("auth_required", snap)
        self.assertIn("rate_limit_max", snap)

    def test_ensure_data_dir(self):
        d = tempfile.mkdtemp()
        sub = os.path.join(d, "data2")
        config.ensure_data_dir(sub)
        self.assertTrue(os.path.isdir(sub))

    def test_db_paths_under_data_dir(self):
        self.assertTrue(config.LEADS_DB.endswith("leads.db"))
        self.assertTrue(config.ANALYTICS_DB.endswith("analytics.db"))
        self.assertTrue(config.UNKNOWN_DB.endswith("unknown_queries.db"))


# ─────────────────────────────────────────────────────────────────────────────
# 8. Live API — auth, rate limit, CORS, admin (real socket)
# ─────────────────────────────────────────────────────────────────────────────
def _start(service, gate):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, gate))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.05)
    return httpd, port


def _req(port, path, *, method="GET", body=None, headers=None):
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read() or "{}"), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, None, dict(e.headers)


@unittest.skipUnless(os.path.exists(XLSX), "no workbook")
class TestLiveSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svc = ChatService(XLSX, leads_db=tmp("l.db"),
                              analytics_db=tmp("a.db"), unknown_db=tmp("u.db"))

    @classmethod
    def tearDownClass(cls):
        cls.svc.close()

    def test_health_is_public(self):
        gate = SecurityGate(api_keys={"k1"}, limiter=RateLimiter(100, 60))
        httpd, port = _start(self.svc, gate)
        try:
            status, _, _ = _req(port, "/health")
            self.assertEqual(status, 200)
        finally:
            httpd.shutdown()

    def test_chat_requires_key(self):
        gate = SecurityGate(api_keys={"k1"}, limiter=RateLimiter(100, 60))
        httpd, port = _start(self.svc, gate)
        try:
            s1, _, _ = _req(port, "/chat", method="POST", body={"message": "Creta?"})
            self.assertEqual(s1, 401)
            s2, body, _ = _req(port, "/chat", method="POST",
                               body={"message": "Creta available?"},
                               headers={"X-API-Key": "k1", "Content-Type": "application/json"})
            self.assertEqual(s2, 200)
            self.assertIn("intent", body)
        finally:
            httpd.shutdown()

    def test_rate_limit_429(self):
        gate = SecurityGate(api_keys={"k1"}, limiter=RateLimiter(2, 60))
        httpd, port = _start(self.svc, gate)
        try:
            h = {"X-API-Key": "k1", "Content-Type": "application/json"}
            codes = [_req(port, "/chat", method="POST", body={"message": "Creta?"},
                          headers=h)[0] for _ in range(3)]
            self.assertEqual(codes[:2], [200, 200])
            self.assertEqual(codes[2], 429)
        finally:
            httpd.shutdown()

    def test_cors_preflight(self):
        gate = SecurityGate(allowed_origins=["*"])
        httpd, port = _start(self.svc, gate)
        try:
            status, _, headers = _req(port, "/chat", method="OPTIONS",
                                      headers={"Origin": "https://shop.example"})
            self.assertEqual(status, 204)
            self.assertEqual(headers.get("Access-Control-Allow-Origin"), "*")
        finally:
            httpd.shutdown()

    def test_admin_refresh_requires_admin_key(self):
        gate = SecurityGate(api_keys={"k1"}, admin_keys={"adm"},
                            limiter=RateLimiter(100, 60))
        httpd, port = _start(self.svc, gate)
        try:
            s1, _, _ = _req(port, "/admin/refresh_inventory", method="POST", body={})
            self.assertEqual(s1, 401)
            s2, body, _ = _req(port, "/admin/refresh_inventory", method="POST",
                               body={}, headers={"X-API-Key": "adm"})
            self.assertEqual(s2, 200)
            self.assertEqual(body["status"], "ok")
        finally:
            httpd.shutdown()


if __name__ == "__main__":
    unittest.main(verbosity=2)
