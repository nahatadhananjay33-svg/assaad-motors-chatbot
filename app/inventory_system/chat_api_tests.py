"""
chat_api_tests.py
================

Tests for the Phase-3A chatbot backend:
  * ChatService orchestration (intent, response, vehicles, safety)
  * route() pure routing (health, chat, errors) without sockets
  * a live end-to-end HTTP round-trip over a real socket

Run:  python chat_api_tests.py
"""

import os
import json
import time
import threading
import unittest
import urllib.request
import urllib.error

from http.server import ThreadingHTTPServer

from chat_service import ChatService, ChatInputError, public_vehicle, classify_intent
from chat_api import route, make_handler
import inventory_loader as L
from query_parser import parse

XLSX = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")


@unittest.skipUnless(os.path.exists(XLSX), "IVR_Sheet.xlsx not found")
class ServiceBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svc = ChatService(XLSX)


# ─────────────────────────────────────────────────────────────────────────────
# 1. ChatService
# ─────────────────────────────────────────────────────────────────────────────
class TestChatService(ServiceBase):
    def test_primary_example_suv_under_8_lakh(self):
        r = self.svc.handle("SUV under 8 lakh")
        self.assertEqual(r.intent, "budget")
        self.assertTrue(r.response)
        self.assertTrue(len(r.vehicles) > 0)
        for v in r.vehicles:
            self.assertIn(v["body_type"], ("SUV", "Compact-SUV"))
            self.assertLessEqual(v["price_lakh"], 8.0)

    def test_response_shape(self):
        r = self.svc.handle("Creta available?").to_dict()
        for key in ("intent", "response", "vehicles", "status", "count",
                    "filters", "guardrails", "request_id", "meta"):
            self.assertIn(key, r)

    def test_vehicles_never_expose_internal_fields(self):
        # Phase 6B: registration_no is intentionally shown ("Reg: <number>").
        r = self.svc.handle("Creta available?")
        for v in r.vehicles:
            self.assertIn("registration_no", v)
            self.assertNotIn("location_code", v)
            self.assertNotIn("stock_no", v)

    def test_price_quotable_flag_and_no_fake_price(self):
        # an off-the-shelf coded price must serialize price_lakh=None
        items = L.load_inventory(XLSX)
        from inventory_models import InventoryItem, BodyType
        coded = InventoryItem(registration_no="MH00CODE9999", model="Endeavour",
                              make="FORD", make_full="Ford", year_int=2018,
                              price_quotable=False, body_type=BodyType.SUV,
                              is_ivr_eligible=True)
        v = public_vehicle(coded)
        self.assertFalse(v["price_quotable"])
        self.assertIsNone(v["price_lakh"])

    def test_empty_message_raises(self):
        with self.assertRaises(ChatInputError):
            self.svc.handle("")
        with self.assertRaises(ChatInputError):
            self.svc.handle(None)

    def test_too_long_message_raises(self):
        with self.assertRaises(ChatInputError):
            self.svc.handle("x" * 1000)

    def test_intent_classification(self):
        cases = {
            "Creta available?": "availability",
            "Fortuner price?": "price",
            "SUV under 8 lakh": "budget",
            "diesel cars": "fuel",
            "automatic cars": "transmission",
            "first owner cars": "ownership",
            "white cars": "color",
            "white automatic Honda": "combination",
            # Phase 12D: sunroof is now an answerable field (not off_sheet) — a
            # named-model attribute question resolves to the model's car.
            "Creta mein sunroof hai?": "availability",
            # A reel reference with no identifiable vehicle asks for the car
            # number / model / reel link (reel-discovery clarify). A reel is how the
            # customer found the car — an identification+availability question, not
            # a request to be sent media.
            "jo reel mein thi woh gaadi": "reel_clarify",
        }
        for msg, expected in cases.items():
            self.assertEqual(self.svc.handle(msg).intent, expected, msg)

    def test_health(self):
        h = self.svc.health()
        self.assertEqual(h["status"], "ok")
        self.assertEqual(h["inventory_count"], self.svc.inventory_count)


# ─────────────────────────────────────────────────────────────────────────────
# 2. route() — socket-free
# ─────────────────────────────────────────────────────────────────────────────
class TestRouting(ServiceBase):
    def test_health_route(self):
        status, body = route("GET", "/health", b"", self.svc)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_chat_route_ok(self):
        status, body = route("POST", "/chat",
                             json.dumps({"message": "SUV under 8 lakh"}).encode(), self.svc)
        self.assertEqual(status, 200)
        self.assertEqual(body["intent"], "budget")
        self.assertTrue(body["vehicles"])

    def test_chat_invalid_json(self):
        status, body = route("POST", "/chat", b"{not json", self.svc)
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_json")

    def test_chat_empty_message(self):
        status, body = route("POST", "/chat", json.dumps({"message": ""}).encode(), self.svc)
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "bad_request")

    def test_chat_missing_message_key(self):
        status, body = route("POST", "/chat", json.dumps({"foo": "bar"}).encode(), self.svc)
        self.assertEqual(status, 400)

    def test_method_not_allowed(self):
        status, body = route("GET", "/chat", b"", self.svc)
        self.assertEqual(status, 405)

    def test_not_found(self):
        status, body = route("GET", "/nope", b"", self.svc)
        self.assertEqual(status, 404)

    def test_trailing_slash_and_query_normalized(self):
        status, _ = route("GET", "/health/?x=1", b"", self.svc)
        self.assertEqual(status, 200)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Live HTTP round-trip (real socket)
# ─────────────────────────────────────────────────────────────────────────────
@unittest.skipUnless(os.path.exists(XLSX), "IVR_Sheet.xlsx not found")
class TestLiveServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svc = ChatService(XLSX)
        handler = make_handler(cls.svc)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)  # ephemeral port
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def test_health_endpoint(self):
        with urllib.request.urlopen(self._url("/health"), timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read())
        self.assertEqual(data["status"], "ok")

    def test_chat_endpoint(self):
        body = json.dumps({"message": "SUV under 8 lakh"}).encode()
        req = urllib.request.Request(self._url("/chat"), data=body,
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read())
        self.assertEqual(data["intent"], "budget")
        self.assertIn("response", data)
        self.assertTrue(data["vehicles"])
        # registration_no is intentionally present on each vehicle (Phase 6B)
        for v in data["vehicles"]:
            self.assertIn("registration_no", v)

    def test_chat_bad_request_over_http(self):
        body = json.dumps({"message": ""}).encode()
        req = urllib.request.Request(self._url("/chat"), data=body,
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
