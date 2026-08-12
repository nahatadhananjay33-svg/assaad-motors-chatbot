"""
_poc.py — bridge to the validated POC (Phase 4A.3-PoC).

We REUSE the POC's proven primitives (scan, registration normalization, workbook
layout/row indexing, extension/content-type validation, storage upload pattern)
rather than rewriting working logic. This module makes them importable from the
production package.
"""

from __future__ import annotations

import os
import sys

_POC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "media_sync_poc")
if _POC_DIR not in sys.path:
    sys.path.insert(0, _POC_DIR)

import media_sync_poc as poc   # noqa: E402

# ── Phase 4A.5.1 reconciliation ──────────────────────────────────────────────
# The POC's `read_layout` scans header ROW 1 (its test workbooks put headers
# there). The real DNJ workbook keeps media headers on ROW 2 ("EXTERIOR 1",
# "INTERIOR 1", "VIDEO 1", "INSTAGRAM 1", "YOUTUBE 1") with numbered continuation
# columns, so the row-1 scan finds nothing and NO media URLs get written into the
# live IVR_Sheet.xlsx.
#
# Fix (write-side only): locate the header row automatically and delegate the
# grouping to the already-tested `detect_media_layout()` from the loader side
# (inventory_system/media_loader_mapping.py). We REUSE that logic verbatim and
# translate its output into the POC's `SheetLayout` so every existing media_sync
# consumer (service, reconciliation, cleanup) keeps working unchanged. This is
# backward compatible with the POC's row-1 "Exterior_Photo_N" fixtures.
_INV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "inventory_system")
if _INV_DIR not in sys.path:
    sys.path.insert(0, _INV_DIR)

from media_loader_mapping import detect_media_layout, MediaType  # noqa: E402

# how many leading rows to probe for the header row (row 1 covers POC fixtures,
# row 2 covers the real DNJ sheet; a small bound keeps it cheap and safe).
_HEADER_SCAN_ROWS = 5

# loader-side MediaType -> media_sync slot vocabulary
_TYPE_TO_KEY = {
    MediaType.EXTERIOR_PHOTO: "exterior",
    MediaType.INTERIOR_PHOTO: "interior",
    MediaType.VIDEO: "video",
    MediaType.INSTAGRAM: "instagram",
    MediaType.YOUTUBE: "youtube",
}


def read_layout(ws):
    """Header-row-aware layout detection (replaces the POC's row-1-only scan).

    Probes the first few rows for the one carrying CAR NUMB + media headers,
    runs the shared `detect_media_layout()`, and returns a POC `SheetLayout`
    whose `slots` are keyed by the media_sync vocabulary
    (exterior/interior/video/instagram/youtube)."""
    max_col = ws.max_column or 0
    max_scan = min(ws.max_row or 1, _HEADER_SCAN_ROWS)

    chosen = None
    for r in range(1, max_scan + 1):
        header = [ws.cell(r, c).value for c in range(1, max_col + 1)]
        ml = detect_media_layout(header)
        if ml.car_col is not None and any(ml.groups.values()):
            chosen = ml
            break
    if chosen is None:                       # nothing found: keep legacy row-1 view
        header = [ws.cell(1, c).value for c in range(1, max_col + 1)]
        chosen = detect_media_layout(header)

    slots = {"exterior": [], "interior": [], "video": [], "instagram": [], "youtube": []}
    for mtype, entries in chosen.groups.items():
        key = _TYPE_TO_KEY.get(mtype)
        if key is not None:
            slots[key] = [col for _slot, col in entries]
    return poc.SheetLayout(chosen.car_col, slots)


# re-export the reused primitives
scan_uploads = poc.scan_uploads
normalize_registration = poc.normalize_registration
index_rows = poc.index_rows
content_type = poc.content_type
create_test_workbook = poc.create_test_workbook
UploadItem = poc.UploadItem
SheetLayout = poc.SheetLayout
MEDIA_TYPES = poc.MEDIA_TYPES
PHOTO_EXT = poc.PHOTO_EXT
VIDEO_EXT = poc.VIDEO_EXT
_ext = poc._ext
_valid_ext_for_type = poc._valid_ext_for_type
InMemoryStorageUploader = poc.InMemoryStorageUploader
SupabaseStorageUploader = poc.SupabaseStorageUploader
