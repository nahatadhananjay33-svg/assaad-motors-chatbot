"""
media_service.py
===============

Deterministic media delivery over inventory records — NO LLM / embeddings /
vector DB. Reuses the inventory models, the query parser, and the retrieval
engine's exact-match predicate; it does NOT duplicate inventory logic.

    Inventory ──► Media Lookup ──► Media Service ──► (structured response)

Media is fetched through a pluggable **MediaProvider** so the source can later
move to Supabase Storage WITHOUT changing this business logic:

    MediaProvider (interface)
      ├── InventoryMediaProvider   (implemented — reads InventoryItem.media)
      └── SupabaseMediaProvider    (designed only — not implemented this phase)

Returns structured data only — no formatting/templating here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from inventory_models import InventoryItem, MediaType
from retrieval_engine import RetrievalEngine, _matches
import media_lookup as ml


# ─────────────────────────────────────────────────────────────────────────────
# Media assets bundle
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class MediaAssets:
    exterior_photos: List[str] = field(default_factory=list)
    interior_photos: List[str] = field(default_factory=list)
    videos: List[str] = field(default_factory=list)
    instagram: List[str] = field(default_factory=list)
    youtube: List[str] = field(default_factory=list)

    def all_photos(self) -> List[str]:
        return list(self.exterior_photos) + list(self.interior_photos)

    def is_empty(self) -> bool:
        return not (self.exterior_photos or self.interior_photos or self.videos
                    or self.instagram or self.youtube)


# ─────────────────────────────────────────────────────────────────────────────
# Provider interface + implementations
# ─────────────────────────────────────────────────────────────────────────────
class MediaProvider(ABC):
    """Source of media assets for a vehicle. Swap the implementation to change
    where media comes from (inventory rows today, Supabase Storage later)."""

    @abstractmethod
    def fetch(self, item: InventoryItem) -> MediaAssets:
        ...


class InventoryMediaProvider(MediaProvider):
    """Reads media straight off the inventory record (`InventoryItem.media`)."""

    def fetch(self, item: InventoryItem) -> MediaAssets:
        a = MediaAssets()
        for m in (item.media or []):
            url = getattr(m, "url", None)
            if not url:
                continue
            if m.media_type == MediaType.EXTERIOR_PHOTO:
                a.exterior_photos.append(url)
            elif m.media_type == MediaType.INTERIOR_PHOTO:
                a.interior_photos.append(url)
            elif m.media_type == MediaType.VIDEO:
                a.videos.append(url)
            elif m.media_type == MediaType.INSTAGRAM:
                a.instagram.append(url)
            elif m.media_type == MediaType.YOUTUBE:
                a.youtube.append(url)
        return a


class SupabaseMediaProvider(MediaProvider):
    """
    FUTURE provider — fetches media URLs from Supabase Storage / a media table,
    keyed by `registration_no`. Designed here as an interface only; NOT
    implemented in this phase. Wiring it in requires no change to MediaService.
    """

    def __init__(self, *args, **kwargs):
        self._args = (args, kwargs)

    def fetch(self, item: InventoryItem) -> MediaAssets:  # pragma: no cover
        raise NotImplementedError(
            "SupabaseMediaProvider is a designed interface only (Phase 3D). "
            "Implement Storage lookup by registration_no in a later phase.")


# ─────────────────────────────────────────────────────────────────────────────
# Response statuses
# ─────────────────────────────────────────────────────────────────────────────
STATUS_OK = "ok"
STATUS_MEDIA_UNAVAILABLE = "media_unavailable"
STATUS_VEHICLE_UNAVAILABLE = "vehicle_unavailable"     # named but not in stock
STATUS_VEHICLE_NOT_IDENTIFIED = "vehicle_not_identified"
STATUS_MULTIPLE_MATCHES = "multiple_matches"
STATUS_NOT_MEDIA_REQUEST = "not_media_request"


def _label(item: InventoryItem) -> str:
    """Customer-safe vehicle label — never reg/LOC/stock."""
    bits = [str(item.year_int) if item.year_int else "",
            item.color_norm or "", item.model or ""]
    return " ".join(b for b in bits if b).strip() or (item.make_full or "vehicle")


# ─────────────────────────────────────────────────────────────────────────────
# Media service
# ─────────────────────────────────────────────────────────────────────────────
class MediaService:
    def __init__(self, engine: RetrievalEngine,
                 provider: Optional[MediaProvider] = None):
        self.engine = engine
        self.provider = provider or InventoryMediaProvider()

    def _find_matches(self, mq: ml.MediaQuery,
                      context_model: Optional[str]) -> Optional[List[InventoryItem]]:
        """Exact match over customer-facing inventory (no relaxation/segment).
        Returns None when no vehicle could be identified at all."""
        pool = self.engine.all_facing
        if mq.registration:
            reg = mq.registration.replace(" ", "").upper()
            return [i for i in pool
                    if (i.registration_no or "").replace(" ", "").upper() == reg]
        if mq.identified_vehicle:
            return [i for i in pool if _matches(i, mq.query)]
        if context_model:                     # vehicle supplied by conversation
            cm = context_model.lower()
            return [i for i in pool if (i.model or "").lower() == cm]
        return None

    def get_media(self, message: str, *,
                  context_model: Optional[str] = None) -> Dict[str, Any]:
        mq = ml.parse_media_query(message)
        resp: Dict[str, Any] = {
            "intent": mq.intent, "vehicle": None,
            "photos": [], "videos": [], "instagram": [], "youtube": [],
            "status": None,
        }

        if mq.intent is None:
            resp["status"] = STATUS_NOT_MEDIA_REQUEST
            return resp

        matches = self._find_matches(mq, context_model)
        if matches is None:
            resp["status"] = STATUS_VEHICLE_NOT_IDENTIFIED
            return resp
        if not matches:
            resp["status"] = STATUS_VEHICLE_UNAVAILABLE      # invalid / out-of-stock
            return resp
        if len(matches) > 1:
            resp["status"] = STATUS_MULTIPLE_MATCHES
            resp["candidates"] = [{"label": _label(i), "registration_no": i.registration_no}
                                   for i in matches]
            resp["_candidate_items"] = matches   # internal: for follow-up selection
            return resp

        item = matches[0]
        resp["vehicle"] = _label(item)
        resp["registration_no"] = item.registration_no
        assets = self.provider.fetch(item)
        bucket = self._select(mq, assets, resp)

        resp["status"] = STATUS_OK if bucket else STATUS_MEDIA_UNAVAILABLE
        return resp

    @staticmethod
    def _select(mq: ml.MediaQuery, assets: MediaAssets,
                resp: Dict[str, Any]) -> List[str]:
        """Fill the requested bucket; return it (for ok/unavailable decision)."""
        if mq.intent == ml.PHOTO_REQUEST:
            if mq.scope == ml.SCOPE_INTERIOR:
                photos = list(assets.interior_photos)
            elif mq.scope == ml.SCOPE_EXTERIOR:
                photos = list(assets.exterior_photos)
            else:
                photos = assets.all_photos()
            resp["photos"] = photos
            return photos
        if mq.intent == ml.VIDEO_REQUEST:
            resp["videos"] = list(assets.videos)
            return resp["videos"]
        if mq.intent == ml.INSTAGRAM_REQUEST:
            resp["instagram"] = list(assets.instagram)
            return resp["instagram"]
        if mq.intent == ml.YOUTUBE_REQUEST:
            resp["youtube"] = list(assets.youtube)
            return resp["youtube"]
        if mq.intent == ml.LINK_REQUEST:          # bare "link" -> both platforms
            resp["instagram"] = list(assets.instagram)
            resp["youtube"] = list(assets.youtube)
            return resp["instagram"] + resp["youtube"]
        return []
