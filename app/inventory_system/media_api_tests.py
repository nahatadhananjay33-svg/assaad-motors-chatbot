"""
media_api_tests.py
==================

Phase 4B.1 — Media Exposure API test suite.

Tests that /chat (via ChatService.handle) now returns media URLs for media
requests while preserving full backward compatibility for non-media requests.

Test strategy:
  * Uses the REAL ChatService (same as hardening_tests / phase4c eval).
  * Injects synthetic InventoryItem objects with known media URLs so tests are
    not hostage to whatever is in the live IVR_Sheet.xlsx.
  * Also validates the live stack (no fabrication, correct keys) using
    assertions that are inventory-agnostic.

Covers:
  1. photo_request  — "Show me Innova photos"
  2. video_request  — "Show me Fortuner videos"
  3. instagram_request — "Send Nexon reel"
  4. multi-language — "Innova ka reel bhejo"
  5. No vehicle named — media_status == vehicle_not_identified (no fabrication)
  6. Non-media request — no `media` key in response (backward compat)
  7. MediaService reuse — no new media logic in ChatService
  8. Existing test regression — vehicle cards still returned normally
  9. API-level test — route() returns `media` in JSON body when media intent detected
 10. Inventory refresh preserves media_service binding
"""

from __future__ import annotations

import os
import sys
import json
import tempfile
import unittest
from typing import Any, Dict, List
from unittest.mock import patch, MagicMock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

XLSX = os.path.join(HERE, "..", "IVR_Sheet.xlsx")

from chat_service import ChatService, ChatResult
from chat_api import route
from media_service import (MediaService, InventoryMediaProvider, MediaAssets,
                            STATUS_OK, STATUS_VEHICLE_NOT_IDENTIFIED,
                            STATUS_VEHICLE_UNAVAILABLE, STATUS_MULTIPLE_MATCHES,
                            STATUS_NOT_MEDIA_REQUEST)
from media_lookup import (PHOTO_REQUEST, VIDEO_REQUEST, INSTAGRAM_REQUEST,
                          YOUTUBE_REQUEST)
from inventory_models import InventoryItem, InventoryMedia, MediaType


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _temp_svc(**kwargs) -> ChatService:
    """ChatService wired to throwaway DBs (same pattern as hardening_tests)."""
    tmp = tempfile.mkdtemp()
    return ChatService(
        xlsx_path=XLSX,
        leads_db=os.path.join(tmp, "leads.db"),
        analytics_db=os.path.join(tmp, "analytics.db"),
        unknown_db=os.path.join(tmp, "unknown.db"),
        **kwargs)


def _fake_media_item(model: str = "Innova",
                     make: str = "TOYO",
                     with_photos: bool = True,
                     with_video: bool = False,
                     with_instagram: bool = False) -> InventoryItem:
    """Synthetic InventoryItem with known media for deterministic tests."""
    media: List[InventoryMedia] = []
    if with_photos:
        media.append(InventoryMedia(
            registration_no="TEST001",
            media_type=MediaType.EXTERIOR_PHOTO, slot=1,
            url="https://example.com/innova_ext_1.jpg", is_primary=True))
        media.append(InventoryMedia(
            registration_no="TEST001",
            media_type=MediaType.INTERIOR_PHOTO, slot=1,
            url="https://example.com/innova_int_1.jpg"))
    if with_video:
        media.append(InventoryMedia(
            registration_no="TEST001",
            media_type=MediaType.VIDEO, slot=1,
            url="https://example.com/innova_walkaround.mp4"))
    if with_instagram:
        media.append(InventoryMedia(
            registration_no="TEST001",
            media_type=MediaType.INSTAGRAM, slot=1,
            url="https://www.instagram.com/p/test_reel/"))

    from inventory_models import FuelType, Transmission, BodyType, ListingStatus
    return InventoryItem(
        registration_no="TEST001",
        make=make, make_full="Toyota",
        model=model, year_int=2020,
        fuel_norm=FuelType.PETROL,
        transmission_norm=Transmission.AUTOMATIC,
        color_norm="White",
        ownership_count=1, km_driven=35000,
        price_inr=1200000,
        body_type=BodyType.MUV, seats=7,
        listing_status=ListingStatus.AVAILABLE,
        price_quotable=True, price_lakh=12.0,
        media=media)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Unit: ChatResult has media field and to_dict includes it when set
# ─────────────────────────────────────────────────────────────────────────────
class TestChatResultMediaField(unittest.TestCase):

    def test_media_field_defaults_to_none(self):
        r = ChatResult(intent="availability", response="ok", vehicles=[],
                       status="found", count=1)
        self.assertIsNone(r.media)

    def test_to_dict_omits_media_when_none(self):
        r = ChatResult(intent="availability", response="ok", vehicles=[],
                       status="found", count=1)
        d = r.to_dict()
        self.assertNotIn("media", d)

    def test_to_dict_includes_media_when_set(self):
        r = ChatResult(intent="photo_request", response="Here are photos.",
                       vehicles=[], status="found", count=0)
        r.media = {"status": "ok", "photos": ["https://x.com/a.jpg"],
                   "videos": [], "instagram": [], "youtube": []}
        d = r.to_dict()
        self.assertIn("media", d)
        self.assertEqual(d["media"]["photos"], ["https://x.com/a.jpg"])

    def test_to_dict_backward_compat_keys_present(self):
        """Non-media response must always have the same keys as before."""
        r = ChatResult(intent="availability", response="Found 1 Creta.",
                       vehicles=[{"model": "Creta"}], status="found", count=1,
                       guardrails=["G-FRESH"])
        d = r.to_dict()
        for k in ("intent", "response", "vehicles", "status", "count",
                  "filters", "guardrails", "request_id", "meta"):
            self.assertIn(k, d)
        self.assertNotIn("media", d)   # backward compat: absent when None


# ─────────────────────────────────────────────────────────────────────────────
# 2. Unit: MediaService produces correct payloads (isolated from ChatService)
# ─────────────────────────────────────────────────────────────────────────────
class TestMediaServiceUnit(unittest.TestCase):

    def setUp(self):
        from retrieval_engine import RetrievalEngine
        self.item = _fake_media_item(with_photos=True, with_video=True,
                                     with_instagram=True)
        self.engine = RetrievalEngine([self.item])
        self.svc = MediaService(self.engine, InventoryMediaProvider())

    def test_photo_request_returns_photos(self):
        r = self.svc.get_media("Show me Innova photos")
        self.assertEqual(r["status"], STATUS_OK)
        self.assertEqual(r["intent"], PHOTO_REQUEST)
        self.assertIn("https://example.com/innova_ext_1.jpg", r["photos"])
        self.assertIn("https://example.com/innova_int_1.jpg", r["photos"])

    def test_video_request_returns_videos(self):
        r = self.svc.get_media("Show me Innova video")
        self.assertEqual(r["status"], STATUS_OK)
        self.assertEqual(r["intent"], VIDEO_REQUEST)
        self.assertIn("https://example.com/innova_walkaround.mp4", r["videos"])

    def test_instagram_request_returns_instagram(self):
        r = self.svc.get_media("Innova ka reel bhejo")
        self.assertEqual(r["status"], STATUS_OK)
        self.assertEqual(r["intent"], INSTAGRAM_REQUEST)
        self.assertIn("https://www.instagram.com/p/test_reel/", r["instagram"])

    def test_no_vehicle_named_returns_not_identified(self):
        r = self.svc.get_media("Send reel please")
        self.assertEqual(r["status"], STATUS_VEHICLE_NOT_IDENTIFIED)

    def test_non_media_request_returns_not_media(self):
        r = self.svc.get_media("Innova available?")
        self.assertEqual(r["status"], STATUS_NOT_MEDIA_REQUEST)

    def test_interior_scope(self):
        r = self.svc.get_media("Show interior photos of Innova")
        self.assertEqual(r["status"], STATUS_OK)
        self.assertIn("https://example.com/innova_int_1.jpg", r["photos"])
        self.assertNotIn("https://example.com/innova_ext_1.jpg", r["photos"])

    def test_exterior_scope(self):
        r = self.svc.get_media("Show exterior photos of Innova")
        self.assertEqual(r["status"], STATUS_OK)
        self.assertIn("https://example.com/innova_ext_1.jpg", r["photos"])
        self.assertNotIn("https://example.com/innova_int_1.jpg", r["photos"])


# ─────────────────────────────────────────────────────────────────────────────
# 3. Integration: ChatService.handle() exposes media via real stack
# ─────────────────────────────────────────────────────────────────────────────
class TestChatServiceMediaIntegration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.svc = _temp_svc()
        # Replace the engine pool with ONLY the fake item so tests are
        # deterministic regardless of what is in IVR_Sheet.xlsx.
        cls.fake_item = _fake_media_item(
            model="Innova", with_photos=True, with_video=True, with_instagram=True)
        cls.svc.engine.all_facing = [cls.fake_item]
        cls.svc.media_service = MediaService(
            cls.svc.engine, InventoryMediaProvider())

    @classmethod
    def tearDownClass(cls):
        cls.svc.close()

    def test_photo_request_has_media_key(self):
        r = self.svc.handle("Show me Innova photos")
        self.assertIsNotNone(r.media)
        self.assertIn("photos", r.media)

    def test_photo_request_intent_is_photo_request(self):
        r = self.svc.handle("Show me Innova photos")
        self.assertEqual(r.intent, PHOTO_REQUEST)

    def test_photo_request_returns_urls(self):
        r = self.svc.handle("Show me Innova photos")
        self.assertEqual(r.media["status"], STATUS_OK)
        self.assertGreater(len(r.media["photos"]), 0)
        for url in r.media["photos"]:
            self.assertTrue(url.startswith("http"), f"Not a URL: {url}")

    def test_video_request_has_videos(self):
        r = self.svc.handle("Show me Innova video")
        self.assertIsNotNone(r.media)
        self.assertIn("videos", r.media)
        self.assertEqual(r.intent, VIDEO_REQUEST)

    def test_instagram_request_hinglish(self):
        """'Innova ka reel bhejo' → instagram_request with media payload."""
        r = self.svc.handle("Innova ka reel bhejo")
        self.assertIsNotNone(r.media)
        self.assertEqual(r.intent, INSTAGRAM_REQUEST)

    def test_non_media_request_no_media_key(self):
        """Backward compatibility: non-media response must NOT have `media` key."""
        r = self.svc.handle("Innova available?")
        self.assertIsNone(r.media)
        d = r.to_dict()
        self.assertNotIn("media", d)

    def test_vehicle_cards_still_returned_for_media_request(self):
        """Vehicles are additive — media + vehicle cards both present."""
        r = self.svc.handle("Show me Innova photos")
        # intent is overridden to media, but vehicles list populated by inventory
        # (may be empty if no Innova in sheet — that's fine; check media IS set)
        self.assertIsNotNone(r.media)
        self.assertIsInstance(r.vehicles, list)

    def test_media_no_fabrication_unknown_vehicle(self):
        """Querying an unknown model returns a media_unavailable/not_found status — never fabricates URLs."""
        r = self.svc.handle("Show me photos of ZZZUnknownCar9999")
        # either not a media request (model not parsed) or media_unavailable
        if r.media is not None:
            self.assertNotEqual(r.media.get("status"), STATUS_OK,
                                "Should not return OK for unknown vehicle")
            self.assertEqual(r.media.get("photos", []), [])

    def test_meta_contains_media_status(self):
        """meta.media_status is logged for every media request."""
        r = self.svc.handle("Show me Innova photos")
        self.assertIn("media_status", r.meta)

    def test_creta_photo_request_live(self):
        """Live test: 'Need Creta images' — media key present even if no URLs in xlsx."""
        r = self.svc.handle("Need Creta images")
        self.assertIsNotNone(r.media)
        self.assertEqual(r.intent, PHOTO_REQUEST)
        # status is either ok or media_unavailable — never vehicle_not_identified
        # because Creta is a known model that the parser picks up
        self.assertIn(r.media["status"],
                      (STATUS_OK, STATUS_VEHICLE_UNAVAILABLE,
                       STATUS_MULTIPLE_MATCHES, "media_unavailable"))

    def test_fortuner_video_request_live(self):
        r = self.svc.handle("Show me Fortuner videos")
        self.assertIsNotNone(r.media)
        self.assertEqual(r.intent, VIDEO_REQUEST)

    def test_nexon_reel_live(self):
        r = self.svc.handle("Send Nexon reel")
        self.assertIsNotNone(r.media)
        self.assertEqual(r.intent, INSTAGRAM_REQUEST)


# ─────────────────────────────────────────────────────────────────────────────
# 4. API-level: route() JSON response includes media key
# ─────────────────────────────────────────────────────────────────────────────
class TestChatAPIMediaResponse(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.svc = _temp_svc()
        # Isolated pool: only fake item so photo URLs are deterministic.
        cls.fake_item = _fake_media_item(
            model="Innova", with_photos=True, with_video=True, with_instagram=True)
        cls.svc.engine.all_facing = [cls.fake_item]
        cls.svc.media_service = MediaService(
            cls.svc.engine, InventoryMediaProvider())

    @classmethod
    def tearDownClass(cls):
        cls.svc.close()

    def _post(self, message: str) -> Dict[str, Any]:
        body = json.dumps({"message": message}).encode("utf-8")
        status, payload = route("POST", "/chat", body, self.svc)
        self.assertEqual(status, 200, f"Expected 200, got {status}: {payload}")
        return payload

    def test_media_request_response_has_media_key(self):
        payload = self._post("Show me Innova photos")
        self.assertIn("media", payload)

    def test_media_response_structure(self):
        payload = self._post("Show me Innova photos")
        media = payload["media"]
        for key in ("status", "photos", "videos", "instagram", "youtube"):
            self.assertIn(key, media, f"Missing key '{key}' in media payload")

    def test_media_intent_in_response(self):
        payload = self._post("Show me Innova photos")
        self.assertEqual(payload["intent"], PHOTO_REQUEST)

    def test_video_request_api(self):
        payload = self._post("Show me Innova video")
        self.assertIn("media", payload)
        self.assertEqual(payload["intent"], VIDEO_REQUEST)

    def test_non_media_backward_compat(self):
        """Non-media /chat response must not include 'media' key."""
        payload = self._post("Innova available?")
        self.assertNotIn("media", payload)

    def test_standard_keys_always_present(self):
        """All original keys still present in media response."""
        payload = self._post("Show me Innova photos")
        for k in ("intent", "response", "vehicles", "status", "count",
                  "filters", "guardrails", "request_id", "meta"):
            self.assertIn(k, payload, f"Missing required key: {k}")

    def test_faq_route_no_media(self):
        """FAQ route (e.g. address query) must not include media key."""
        payload = self._post("What is your address?")
        self.assertNotIn("media", payload)

    def test_urls_are_strings(self):
        """All URLs in the media payload must be strings."""
        payload = self._post("Show me Innova photos")
        media = payload.get("media", {})
        for key in ("photos", "videos", "instagram", "youtube"):
            for url in media.get(key, []):
                self.assertIsInstance(url, str, f"URL in {key} is not a string: {url}")

    def test_no_internal_fields_in_media(self):
        """Media payload must not leak LOC slot or storage-path internals.
        registration_no is intentionally shown (Phase 6B: Reg: <number>)."""
        payload = self._post("Show me Innova photos")
        media_str = json.dumps(payload.get("media", {}))
        for forbidden in ("LOC", "slot", "storage_path"):
            self.assertNotIn(forbidden, media_str,
                             f"Internal field '{forbidden}' leaked into media payload")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Inventory refresh preserves media_service
# ─────────────────────────────────────────────────────────────────────────────
class TestRefreshPreservesMedia(unittest.TestCase):

    def test_refresh_rebinds_media_service(self):
        svc = _temp_svc()
        original_engine_id = id(svc.engine)
        original_media_id = id(svc.media_service)
        svc.refresh_inventory()
        # Both engine and media_service should be new objects after refresh
        self.assertNotEqual(id(svc.engine), original_engine_id)
        self.assertNotEqual(id(svc.media_service), original_media_id)
        svc.close()

    def test_media_service_references_current_engine(self):
        svc = _temp_svc()
        svc.refresh_inventory()
        # media_service.engine must point to the same object as svc.engine
        self.assertIs(svc.media_service.engine, svc.engine)
        svc.close()


# ─────────────────────────────────────────────────────────────────────────────
# 6. Regression: existing non-media tests still pass
# ─────────────────────────────────────────────────────────────────────────────
class TestMediaAPIRegression(unittest.TestCase):
    """Ensure Phase 4B.1 wiring does not break any existing chat behaviour."""

    @classmethod
    def setUpClass(cls):
        cls.svc = _temp_svc()

    @classmethod
    def tearDownClass(cls):
        cls.svc.close()

    def _handle(self, msg: str) -> ChatResult:
        return self.svc.handle(msg)

    def test_faq_address_still_works(self):
        r = self._handle("What is your address?")
        self.assertEqual(r.status, "faq")
        self.assertIn("Vasant Oasis", r.response)
        self.assertIsNone(r.media)

    def test_inventory_availability_still_works(self):
        r = self._handle("Creta available?")
        self.assertIn(r.status, ("found", "not_found", "multi", "segment"))
        self.assertIsNone(r.media)

    def test_unknown_still_flagged(self):
        # Phase 12G.5: the trailing "999" is intentionally treated as a partial
        # registration-number lookup (Phase 11A/11C), so a gibberish query with a
        # digit run routes to inventory and returns "not_found" (no match), not
        # "unknown". Either way it must not leak media. Stale expectation cleanup
        # only — product behaviour unchanged.
        r = self._handle("zzz random gobbledygook 999")
        self.assertEqual(r.status, "not_found")
        self.assertIsNone(r.media)

    def test_finance_faq_still_routes(self):
        r = self._handle("Finance available?")
        self.assertEqual(r.status, "faq")
        self.assertIsNone(r.media)

    def test_negotiation_faq_still_routes(self):
        r = self._handle("Last price?")
        self.assertEqual(r.status, "faq")
        self.assertIsNone(r.media)

    def test_api_route_health_unchanged(self):
        status, payload = route("GET", "/health", b"", self.svc)
        self.assertEqual(status, 200)
        self.assertIn("inventory_count", payload)

    def test_vehicles_list_still_returned(self):
        r = self._handle("Swift available?")
        self.assertIsInstance(r.vehicles, list)
        self.assertIsNone(r.media)

    def test_guardrails_still_fired(self):
        r = self._handle("Show me the cheapest car")
        # G-EXPOSE or similar should be in guardrails for inventory results
        self.assertIsInstance(r.guardrails, list)
        self.assertIsNone(r.media)


if __name__ == "__main__":
    unittest.main(verbosity=2)
