"""
media_tests.py
=============

Tests for the Phase-3D media delivery layer (deterministic, inventory-backed):
  * media intent detection (photo / video / instagram / youtube)
  * media retrieval per type + photo scope (interior/exterior)
  * missing media -> media_unavailable (never fabricated)
  * invalid / out-of-stock vehicle, multiple matches, unidentified vehicle
  * provider interface (InventoryMediaProvider + SupabaseMediaProvider stub)
  * real-workbook behaviour (no media -> media_unavailable)

Run:  python media_tests.py
"""

import os
import unittest

from inventory_models import (
    InventoryItem, InventoryMedia, MediaType, BodyType, ListingStatus,
)
from retrieval_engine import RetrievalEngine
import media_lookup as ml
from media_service import (
    MediaService, MediaAssets, MediaProvider, InventoryMediaProvider,
    SupabaseMediaProvider,
    STATUS_OK, STATUS_MEDIA_UNAVAILABLE, STATUS_VEHICLE_UNAVAILABLE,
    STATUS_VEHICLE_NOT_IDENTIFIED, STATUS_MULTIPLE_MATCHES, STATUS_NOT_MEDIA_REQUEST,
)
import inventory_loader as L

XLSX = os.path.join(os.path.dirname(__file__), "..", "IVR_Sheet.xlsx")


def media(reg, mtype, n):
    return [InventoryMedia(registration_no=reg, media_type=mtype, slot=i + 1,
                           url=f"https://cdn.example.com/{reg}/{mtype}/{i+1}.bin")
            for i in range(n)]


def item(reg, model, *, make="HYUN", make_full="Hyundai", body=BodyType.COMPACT_SUV,
         year=2018, color="White", media_list=None, status=ListingStatus.AVAILABLE):
    return InventoryItem(
        registration_no=reg, model=model, make=make, make_full=make_full,
        year_int=year, color_norm=color, body_type=body, price_inr=700000,
        price_lakh=7.0, price_quotable=True, is_ivr_eligible=True,
        listing_status=status, media=media_list or [])


def build_service(items):
    return MediaService(RetrievalEngine(items))


# a Creta with every media type
CRETA = item("MH01AA0001", "Creta",
             media_list=(media("MH01AA0001", MediaType.EXTERIOR_PHOTO, 3)
                         + media("MH01AA0001", MediaType.INTERIOR_PHOTO, 2)
                         + media("MH01AA0001", MediaType.VIDEO, 1)
                         + media("MH01AA0001", MediaType.INSTAGRAM, 1)
                         + media("MH01AA0001", MediaType.YOUTUBE, 1)))
FORTUNER = item("MH02BB0002", "Fortuner", make="TOYO", make_full="Toyota",
                body=BodyType.SUV, media_list=media("MH02BB0002", MediaType.VIDEO, 2))
NEXON = item("MH03CC0003", "Nexon", make="TATA", make_full="Tata",
             media_list=media("MH03CC0003", MediaType.EXTERIOR_PHOTO, 4))
POLO_A = item("MH04DD0004", "Polo", make="VOX", make_full="Volkswagen",
              body=BodyType.HATCHBACK, media_list=media("MH04DD0004", MediaType.EXTERIOR_PHOTO, 2))
POLO_B = item("MH05EE0005", "Polo", make="VOX", make_full="Volkswagen",
              body=BodyType.HATCHBACK, media_list=media("MH05EE0005", MediaType.EXTERIOR_PHOTO, 2))
SOLD_ENDEAVOUR = item("MH06FF0006", "Endeavour", make="FORD", make_full="Ford",
                      body=BodyType.SUV, status=ListingStatus.SOLD,
                      media_list=media("MH06FF0006", MediaType.EXTERIOR_PHOTO, 3))

FIXTURE = [CRETA, FORTUNER, NEXON, POLO_A, POLO_B, SOLD_ENDEAVOUR]


# ─────────────────────────────────────────────────────────────────────────────
# 1. Media intent detection
# ─────────────────────────────────────────────────────────────────────────────
class TestMediaIntent(unittest.TestCase):
    def test_photo_words(self):
        for w in ["photos", "images", "pics", "pictures", "picture", "image"]:
            self.assertEqual(ml.detect_media_intent(f"Creta {w}"), ml.PHOTO_REQUEST, w)

    def test_video_words(self):
        for w in ["video", "videos", "walkaround", "clip"]:
            self.assertEqual(ml.detect_media_intent(f"Creta {w}"), ml.VIDEO_REQUEST, w)

    def test_instagram_words(self):
        for w in ["instagram", "reel", "insta"]:
            self.assertEqual(ml.detect_media_intent(f"Creta {w}"), ml.INSTAGRAM_REQUEST, w)

    def test_youtube_words(self):
        self.assertEqual(ml.detect_media_intent("Creta youtube"), ml.YOUTUBE_REQUEST)
        self.assertEqual(ml.detect_media_intent("youtube video of Creta"), ml.YOUTUBE_REQUEST)

    def test_no_media_intent(self):
        self.assertIsNone(ml.detect_media_intent("Creta available?"))
        self.assertIsNone(ml.detect_media_intent("what is the price"))

    def test_photo_scope(self):
        self.assertEqual(ml.detect_photo_scope("interior photos"), ml.SCOPE_INTERIOR)
        self.assertEqual(ml.detect_photo_scope("exterior pics"), ml.SCOPE_EXTERIOR)
        self.assertEqual(ml.detect_photo_scope("photos"), ml.SCOPE_ALL)

    def test_vehicle_identified_flag(self):
        self.assertTrue(ml.parse_media_query("Creta photos").identified_vehicle)
        self.assertFalse(ml.parse_media_query("send a reel").identified_vehicle)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Photos
# ─────────────────────────────────────────────────────────────────────────────
class TestPhotos(unittest.TestCase):
    def setUp(self):
        self.svc = build_service(FIXTURE)

    def test_show_creta_photos(self):
        r = self.svc.get_media("Show me Creta photos")
        self.assertEqual(r["status"], STATUS_OK)
        self.assertEqual(r["intent"], ml.PHOTO_REQUEST)
        self.assertEqual(len(r["photos"]), 5)          # 3 exterior + 2 interior
        self.assertEqual(r["videos"], [])
        self.assertIn("Creta", r["vehicle"])

    def test_need_creta_images(self):
        r = self.svc.get_media("Need Creta images")
        self.assertEqual(r["status"], STATUS_OK)
        self.assertTrue(r["photos"])

    def test_interior_scope(self):
        r = self.svc.get_media("Creta interior photos")
        self.assertEqual(r["status"], STATUS_OK)
        self.assertEqual(len(r["photos"]), 2)

    def test_exterior_scope(self):
        r = self.svc.get_media("Creta exterior photos")
        self.assertEqual(len(r["photos"]), 3)

    def test_photos_are_urls_no_internal_leak(self):
        r = self.svc.get_media("Creta photos")
        for u in r["photos"]:
            self.assertTrue(u.startswith("http"))
        self.assertNotIn("MH01AA0001", r["vehicle"])   # reg never in label


# ─────────────────────────────────────────────────────────────────────────────
# 3. Videos
# ─────────────────────────────────────────────────────────────────────────────
class TestVideos(unittest.TestCase):
    def setUp(self):
        self.svc = build_service(FIXTURE)

    def test_video_of_fortuner(self):
        r = self.svc.get_media("Send video of Fortuner")
        self.assertEqual(r["status"], STATUS_OK)
        self.assertEqual(r["intent"], ml.VIDEO_REQUEST)
        self.assertEqual(len(r["videos"]), 2)
        self.assertEqual(r["photos"], [])

    def test_walkaround_video(self):
        r = self.svc.get_media("Any walkaround video of Fortuner?")
        self.assertEqual(r["status"], STATUS_OK)
        self.assertTrue(r["videos"])


# ─────────────────────────────────────────────────────────────────────────────
# 4. Instagram & YouTube
# ─────────────────────────────────────────────────────────────────────────────
class TestSocial(unittest.TestCase):
    def setUp(self):
        self.svc = build_service(FIXTURE)

    def test_instagram(self):
        r = self.svc.get_media("Creta instagram reel")
        self.assertEqual(r["status"], STATUS_OK)
        self.assertEqual(r["intent"], ml.INSTAGRAM_REQUEST)
        self.assertEqual(len(r["instagram"]), 1)

    def test_youtube(self):
        r = self.svc.get_media("Creta youtube video")
        self.assertEqual(r["status"], STATUS_OK)
        self.assertEqual(r["intent"], ml.YOUTUBE_REQUEST)
        self.assertEqual(len(r["youtube"]), 1)

    def test_instagram_with_context_model(self):
        # "Send Instagram reel" has no vehicle; conversation context supplies it
        r = self.svc.get_media("Send Instagram reel", context_model="Creta")
        self.assertEqual(r["status"], STATUS_OK)
        self.assertEqual(len(r["instagram"]), 1)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Missing media / edge statuses
# ─────────────────────────────────────────────────────────────────────────────
class TestEdgeStatuses(unittest.TestCase):
    def setUp(self):
        self.svc = build_service(FIXTURE)

    def test_media_unavailable_when_type_missing(self):
        # Fortuner has videos only -> asking for photos -> media_unavailable
        r = self.svc.get_media("Fortuner photos")
        self.assertEqual(r["status"], STATUS_MEDIA_UNAVAILABLE)
        self.assertEqual(r["photos"], [])

    def test_no_fabrication_on_missing(self):
        r = self.svc.get_media("Fortuner instagram")
        self.assertEqual(r["status"], STATUS_MEDIA_UNAVAILABLE)
        self.assertEqual(r["instagram"], [])

    def test_invalid_vehicle(self):
        # a recognized model that is not in this inventory -> vehicle_unavailable
        r = self.svc.get_media("Swift photos")
        self.assertEqual(r["status"], STATUS_VEHICLE_UNAVAILABLE)

    def test_unrecognized_vehicle_token(self):
        # a token the parser cannot recognize as a vehicle at all
        # (Baleno is a known model alias, so use a true non-vehicle token)
        r = self.svc.get_media("Xyzmobile photos")
        self.assertEqual(r["status"], STATUS_VEHICLE_NOT_IDENTIFIED)

    def test_out_of_stock_vehicle(self):
        r = self.svc.get_media("Endeavour photos")       # exists but SOLD
        self.assertEqual(r["status"], STATUS_VEHICLE_UNAVAILABLE)
        self.assertEqual(r["photos"], [])

    def test_multiple_matching_vehicles(self):
        r = self.svc.get_media("Polo photos")            # two Polos
        self.assertEqual(r["status"], STATUS_MULTIPLE_MATCHES)
        self.assertEqual(len(r["candidates"]), 2)

    def test_vehicle_not_identified(self):
        r = self.svc.get_media("send me a reel")         # no vehicle, no context
        self.assertEqual(r["status"], STATUS_VEHICLE_NOT_IDENTIFIED)

    def test_not_a_media_request(self):
        r = self.svc.get_media("Creta available?")
        self.assertEqual(r["status"], STATUS_NOT_MEDIA_REQUEST)
        self.assertIsNone(r["intent"])


# ─────────────────────────────────────────────────────────────────────────────
# 6. Response contract
# ─────────────────────────────────────────────────────────────────────────────
class TestResponseContract(unittest.TestCase):
    def setUp(self):
        self.svc = build_service(FIXTURE)

    def test_contract_keys_present(self):
        r = self.svc.get_media("Creta photos")
        for k in ("intent", "vehicle", "photos", "videos", "instagram", "youtube", "status"):
            self.assertIn(k, r)

    def test_only_requested_bucket_filled(self):
        r = self.svc.get_media("Creta youtube")
        self.assertTrue(r["youtube"])
        self.assertEqual(r["photos"], [])
        self.assertEqual(r["videos"], [])
        self.assertEqual(r["instagram"], [])


# ─────────────────────────────────────────────────────────────────────────────
# 7. Provider interface
# ─────────────────────────────────────────────────────────────────────────────
class TestProviders(unittest.TestCase):
    def test_inventory_provider_buckets(self):
        a = InventoryMediaProvider().fetch(CRETA)
        self.assertEqual(len(a.exterior_photos), 3)
        self.assertEqual(len(a.interior_photos), 2)
        self.assertEqual(len(a.videos), 1)
        self.assertEqual(len(a.instagram), 1)
        self.assertEqual(len(a.youtube), 1)
        self.assertEqual(len(a.all_photos()), 5)

    def test_empty_provider_for_no_media(self):
        a = InventoryMediaProvider().fetch(item("MH09ZZ0009", "WagonR", media_list=[]))
        self.assertTrue(a.is_empty())

    def test_provider_is_swappable(self):
        self.assertIsInstance(InventoryMediaProvider(), MediaProvider)

    def test_supabase_provider_is_designed_not_implemented(self):
        p = SupabaseMediaProvider(url="x", key="y")
        self.assertIsInstance(p, MediaProvider)
        with self.assertRaises(NotImplementedError):
            p.fetch(CRETA)

    def test_custom_provider_injection(self):
        class FakeProvider(MediaProvider):
            def fetch(self, item):
                return MediaAssets(videos=["https://x/v1.mp4"])
        svc = MediaService(RetrievalEngine(FIXTURE), provider=FakeProvider())
        r = svc.get_media("Creta video")
        self.assertEqual(r["videos"], ["https://x/v1.mp4"])


# ─────────────────────────────────────────────────────────────────────────────
# 8. Real workbook — no media populated -> media_unavailable (no fabrication)
# ─────────────────────────────────────────────────────────────────────────────
@unittest.skipUnless(os.path.exists(XLSX), "IVR_Sheet.xlsx not found")
class TestRealWorkbook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svc = MediaService(RetrievalEngine(L.load_inventory(XLSX)))

    def test_real_car_has_no_media(self):
        # a single-instance model that exists in the sheet but with empty media
        # columns -> media unavailable (never fabricated). Astor = one car.
        r = self.svc.get_media("Show me Astor photos")
        self.assertEqual(r["status"], STATUS_MEDIA_UNAVAILABLE)
        self.assertEqual(r["photos"], [])

    def test_real_unknown_vehicle(self):
        # Swift is a recognized model but not in the real sheet -> vehicle_unavailable
        r = self.svc.get_media("Swift photos")
        self.assertEqual(r["status"], STATUS_VEHICLE_UNAVAILABLE)


# ─────────────────────────────────────────────────────────────────────────────
# 9. Success criteria
# ─────────────────────────────────────────────────────────────────────────────
class TestSuccessCriteria(unittest.TestCase):
    def setUp(self):
        self.svc = build_service(FIXTURE)

    def test_show_me_creta_photos(self):
        r = self.svc.get_media("Show me Creta photos")
        self.assertEqual(r["status"], STATUS_OK)
        self.assertTrue(r["photos"])

    def test_need_videos_of_fortuner(self):
        r = self.svc.get_media("Need videos of Fortuner")
        self.assertEqual(r["status"], STATUS_OK)
        self.assertTrue(r["videos"])

    def test_send_instagram_reel_with_context(self):
        r = self.svc.get_media("Send Instagram reel", context_model="Creta")
        self.assertEqual(r["status"], STATUS_OK)
        self.assertTrue(r["instagram"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
