"""
media_lookup.py
==============

Deterministic parsing of a customer media request — NO LLM / embeddings / vector
DB. Two jobs:

  1. identify the **media intent** (photo / video / instagram / youtube), and
  2. identify the **vehicle** (reusing the inventory query parser).

    "Show me Creta photos"        -> intent=photo_request,   vehicle=Creta
    "Need video of Fortuner"      -> intent=video_request,   vehicle=Fortuner
    "Interior photos available?"  -> intent=photo_request,   scope=interior
    "Any walkaround video?"       -> intent=video_request
    "Send Instagram reel"         -> intent=instagram_request (no vehicle named)

This module only classifies; it never touches inventory data or formats output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from query_parser import parse, Query, _norm, _has

# Indian vehicle registration plate, e.g. "MH01BK9444" / "MH 01 BK 9444".
_REGISTRATION_RE = re.compile(r"\b[A-Za-z]{2}\s?\d{1,2}\s?[A-Za-z]{1,2}\s?\d{3,4}\b")

# ── media intents ──
PHOTO_REQUEST = "photo_request"
VIDEO_REQUEST = "video_request"
INSTAGRAM_REQUEST = "instagram_request"
YOUTUBE_REQUEST = "youtube_request"
LINK_REQUEST = "link_request"          # bare "link bhejo" -> Instagram + YouTube both

# ── photo scope ──
SCOPE_ALL = "all"
SCOPE_INTERIOR = "interior"
SCOPE_EXTERIOR = "exterior"

# keyword tables (checked in this order: youtube > instagram > video > photo,
# so "youtube video" -> youtube and "instagram reel" -> instagram)
_YOUTUBE_WORDS = ["youtube", "you tube", "yt video", "youtube video", "youtube link",
                  "yt link", "shorts", "yt shorts", "youtube shorts", "yt short"]
_INSTAGRAM_WORDS = ["instagram", "insta", "reel", "reels", "ig video", "insta video",
                    "instagram reel", "insta pe", "story",
                    # Devanagari (Hindi + Marathi) — reel/insta references are very
                    # common for this dealership's large Instagram following.
                    "रील", "रील्स", "रीलमध्ये", "रील मध्ये", "इंस्टा", "इंस्टाग्राम",
                    "स्टोरी", "इन्स्टा"]
_VIDEO_WORDS = ["video", "videos", "walkaround", "walk around", "walk-around",
                "walkaraund", "clip", "clips", "chalti gaadi", "video bhejo",
                # Phase 7H.2 ("vidio"→"video" normalized) + Marathi
                "व्हिडिओ", "व्हिडीओ", "विडिओ"]
_PHOTO_WORDS = ["photo", "photos", "image", "images", "pic", "pics", "picture",
                "pictures", "tasveer", "tasveerein", "foto", "photo bhejo",
                "image bhejo", "snaps",
                # Phase 7H.2 + Marathi ("foto"/"fotoo"/"piks"/"tsveer" normalized)
                "फोटो", "फोटू", "चित्र", "चित्रे", "पिक्स", "तस्वीर"]
# Bare "link" (no platform word) -> send BOTH Instagram and YouTube. Checked LAST,
# so "youtube link" -> YouTube and "instagram link"/"reel link" -> Instagram still
# win via their own tables above.
_LINK_WORDS = ["link", "links", "link bhejo", "link do", "social media",
               "social link", "लिंक", "लिंक भेजो"]

_INTERIOR_WORDS = ["interior", "inside", "andar", "andar ki", "cabin", "seats photo",
                   "ander", "ander ka", "आतले", "आतला", "आतील"]
_EXTERIOR_WORDS = ["exterior", "outside", "outer", "bahar", "body photo", "front",
                   "back", "बाहेरचे", "बाहेरचा", "बाहेरून"]


@dataclass
class MediaQuery:
    raw: str
    intent: Optional[str]          # one of the *_REQUEST constants, or None
    scope: str = SCOPE_ALL         # photo scope (interior/exterior/all)
    query: Optional[Query] = None  # parsed inventory query
    identified_vehicle: bool = False
    registration: Optional[str] = None  # normalized registration number, if any


def detect_media_intent(message: str) -> Optional[str]:
    text = _norm(message)
    if any(_has(text, _norm(w)) for w in _YOUTUBE_WORDS):
        return YOUTUBE_REQUEST
    if any(_has(text, _norm(w)) for w in _INSTAGRAM_WORDS):
        return INSTAGRAM_REQUEST
    if any(_has(text, _norm(w)) for w in _VIDEO_WORDS):
        return VIDEO_REQUEST
    if any(_has(text, _norm(w)) for w in _PHOTO_WORDS):
        return PHOTO_REQUEST
    if any(_has(text, _norm(w)) for w in _LINK_WORDS):
        return LINK_REQUEST
    return None


def detect_photo_scope(message: str) -> str:
    text = _norm(message)
    if any(_has(text, _norm(w)) for w in _INTERIOR_WORDS):
        return SCOPE_INTERIOR
    if any(_has(text, _norm(w)) for w in _EXTERIOR_WORDS):
        return SCOPE_EXTERIOR
    return SCOPE_ALL


def _identifies_vehicle(q: Query) -> bool:
    # reg_partial counts: "6687 ki photos bhejo" names a car by its last digits
    # just as surely as naming the model. Without it the media path answered
    # "Kaunsi gaadi ke photos chahiye?" while the inventory path had already
    # resolved the very same car and rendered its card — a self-contradicting
    # reply. The partial is matched by retrieval_engine._matches, which requires
    # the digits to be the plate's COMPLETE trailing group, so this never
    # loosens into a wrong-car answer.
    return bool(q.model or q.make or q.category or q.seats is not None
                or q.reg_partial)


def _extract_registration(message: str) -> Optional[str]:
    m = _REGISTRATION_RE.search(message)
    if not m:
        return None
    return re.sub(r"\s+", "", m.group(0)).upper()


def parse_media_query(message: str) -> MediaQuery:
    intent = detect_media_intent(message)
    q = parse(message)
    registration = _extract_registration(message)
    return MediaQuery(
        raw=message,
        intent=intent,
        scope=detect_photo_scope(message),
        query=q,
        identified_vehicle=_identifies_vehicle(q) or bool(registration),
        registration=registration,
    )


if __name__ == "__main__":
    for m in ["Show me Creta photos", "Need video of Fortuner",
              "Interior photos available?", "Any walkaround video?",
              "Send Instagram reel", "youtube video of Nexon", "hello"]:
        mq = parse_media_query(m)
        veh = mq.query.model or mq.query.category or mq.query.make
        print(f"intent={str(mq.intent):18} scope={mq.scope:8} vehicle={str(veh):10} <- {m}")
