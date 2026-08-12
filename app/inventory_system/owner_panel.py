"""
owner_panel.py
==============

Phase 10A — Owner Panel backend (Excel management for the dealership owner).

The owner works in Excel; Excel stays the single source of truth. This module
manages exactly TWO files:

    LIVE    app/IVR_Sheet.xlsx            (the file the chatbot reads — path
                                           unchanged, loader untouched)
    BACKUP  app/IVR_Sheet_OWNER_BACKUP.xlsx  (exactly one previous version)

Upload flow:   validate new file -> old backup deleted -> live becomes backup
               -> new file becomes live -> refresh_inventory() (no restart).
Rollback:      backup and live swap -> refresh_inventory().
Delete backup: removes ONLY the backup. The live file can never be deleted.

Reused, not rewritten: inventory_upload.validate_workbook (DNJ sheet, columns,
readability, vehicle count), media_admin.parse_multipart, service.refresh_
inventory(), and the media_sync FileLock/atomic helpers. The chatbot keeps
reading the same live path automatically.

Metadata (upload name/date/count per slot) lives in owner_panel_meta.json next
to the Excel. It is a plain dict so later phases can add users/permissions/
audit fields without changing this file's API.

Endpoints (admin-key gated by the existing /admin rule):
    GET  /admin/owner/status
    POST /admin/owner/upload          (multipart, field "file")
    POST /admin/owner/rollback        {confirm: true}
    POST /admin/owner/delete_backup   {confirm: true}
"""

from __future__ import annotations

import base64
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from inventory_upload import validate_workbook
from media_admin import parse_multipart

_MS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "media_sync")
if _MS_DIR not in sys.path:
    sys.path.insert(0, _MS_DIR)
from _util import FileLock  # noqa: E402

BACKUP_BASENAME = "IVR_Sheet_OWNER_BACKUP.xlsx"
META_BASENAME = "owner_panel_meta.json"


# ─────────────────────────────────────────────────────────────────────────────
# paths + metadata
# ─────────────────────────────────────────────────────────────────────────────
def _paths(service: Any) -> Dict[str, str]:
    live = os.path.abspath(service.xlsx_path)
    d = os.path.dirname(live)
    return {"live": live,
            "backup": os.path.join(d, BACKUP_BASENAME),
            "meta": os.path.join(d, META_BASENAME),
            "lock": live + ".lock"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_meta(meta_path: str) -> Dict[str, Any]:
    try:
        with open(meta_path, encoding="utf-8") as f:
            m = json.load(f)
            return m if isinstance(m, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_meta(meta_path: str, meta: Dict[str, Any]) -> None:
    tmp = meta_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    os.replace(tmp, meta_path)


def _slot_info(meta: Dict[str, Any], slot: str, path: str,
               live_count: Optional[int] = None) -> Optional[Dict[str, Any]]:
    if not os.path.exists(path):
        return None
    info = dict(meta.get(slot) or {})
    info.setdefault("file_name", os.path.basename(path))
    info.setdefault("uploaded_at",
                    datetime.fromtimestamp(os.path.getmtime(path),
                                           timezone.utc).isoformat(timespec="seconds"))
    if slot == "live":
        # Phase 12K (F2): the LIVE slot must reflect the ACTUAL file on disk, not a
        # stale name left in metadata by an earlier upload/restore. (vehicle_count
        # is already treated as live truth below.)
        info["file_name"] = os.path.basename(path)
        if live_count is not None:
            info["vehicle_count"] = live_count   # live slot: always current truth
    info["status"] = "LIVE" if slot == "live" else "BACKUP"
    return info


# ─────────────────────────────────────────────────────────────────────────────
# handlers
# ─────────────────────────────────────────────────────────────────────────────
def handle_status(service: Any) -> Tuple[int, Dict[str, Any]]:
    p = _paths(service)
    meta = _load_meta(p["meta"])
    live = _slot_info(meta, "live", p["live"],
                      live_count=getattr(service, "inventory_count", None))
    backup = _slot_info(meta, "backup", p["backup"])
    return 200, {"live": live, "backup": backup}


def handle_download(service: Any, slot: str = "live") -> Tuple[int, Dict[str, Any]]:
    """Return the LIVE (or BACKUP) Excel for download, base64-encoded in JSON so
    the existing JSON response path can carry it (the browser decodes it to a real
    .xlsx download). Owner-only via the permission gate."""
    slot = "backup" if slot == "backup" else "live"
    p = _paths(service)
    path = p[slot]
    if not os.path.exists(path):
        label = "backup" if slot == "backup" else "live"
        return 404, {"status": "error",
                     "detail": f"No {label} Excel available to download."}
    with open(path, "rb") as f:
        data = f.read()
    meta = _load_meta(p["meta"])
    if slot == "backup":
        name = (meta.get("backup") or {}).get("file_name") or "IVR_Sheet_previous.xlsx"
    else:
        name = os.path.basename(path)
    if not str(name).lower().endswith(".xlsx"):
        name = f"{name}.xlsx"
    return 200, {"status": "ok", "slot": slot, "file_name": name, "size": len(data),
                 "content_b64": base64.b64encode(data).decode("ascii")}


def handle_upload(service: Any, body: bytes, content_type: str
                  ) -> Tuple[int, Dict[str, Any]]:
    try:
        fields, files = parse_multipart(body, content_type)
    except ValueError as e:
        return 400, {"status": "rejected",
                     "detail": f"Upload must be multipart/form-data ({e})."}
    if not files:
        return 400, {"status": "rejected", "detail": "No file in upload."}
    upload_name, content = files[0]
    if not content:
        return 400, {"status": "rejected", "detail": "The file is empty."}

    p = _paths(service)
    with FileLock(p["lock"]):
        # 1) stage + validate — live inventory untouched on any failure
        incoming = p["live"] + ".owner_incoming.xlsx"
        try:
            with open(incoming, "wb") as f:
                f.write(content)
        except OSError as e:
            return 500, {"status": "error", "detail": f"Could not save upload ({e})."}
        v = validate_workbook(incoming)
        if v["errors"] or int(v.get("vehicles_loaded") or 0) <= 0:
            try:
                os.remove(incoming)
            except OSError:
                pass
            errs = v["errors"] or ["The Excel contains no vehicles."]
            return 400, {"status": "rejected", "errors": errs,
                         "warnings": v.get("warnings", []),
                         "detail": "File rejected — your live inventory was NOT changed."}

        meta = _load_meta(p["meta"])
        # 2) old backup (if any) is deleted — never more than two files
        if os.path.exists(p["backup"]):
            try:
                os.remove(p["backup"])
            except OSError as e:
                try:
                    os.remove(incoming)
                except OSError:
                    pass
                return 500, {"status": "error",
                             "detail": f"Could not clear the old backup ({e})."}
        # 3) current live becomes the backup
        if os.path.exists(p["live"]):
            try:
                os.replace(p["live"], p["backup"])
            except OSError as e:
                try:
                    os.remove(incoming)
                except OSError:
                    pass
                return 500, {"status": "error",
                             "detail": f"Could not back up the current Excel ({e}). "
                                       "Close it in Excel and retry."}
            meta["backup"] = dict(meta.get("live") or {})
            meta["backup"]["file_name"] = meta["backup"].get("file_name", "IVR_Sheet.xlsx")
            # bootstrap: the pre-panel live file has no stored meta — take the
            # count from the running service (it IS that file's count)
            if meta["backup"].get("vehicle_count") is None:
                meta["backup"]["vehicle_count"] = getattr(service, "inventory_count", None)
        # 4) new file becomes live
        try:
            os.replace(incoming, p["live"])
        except OSError as e:
            # restore: put the backup straight back as live
            if os.path.exists(p["backup"]):
                os.replace(p["backup"], p["live"])
            return 500, {"status": "error",
                         "detail": f"Could not activate the new Excel ({e}). "
                                   "Previous inventory restored."}
        meta["live"] = {"file_name": upload_name or "IVR_Sheet.xlsx",
                        "uploaded_at": _now(),
                        "vehicle_count": int(v.get("vehicles_loaded") or 0)}
        _save_meta(p["meta"], meta)

    # 5) live refresh — existing engine, no restart
    refresh = service.refresh_inventory()
    return 200, {"status": "ok",
                 "message": "Inventory Updated Successfully",
                 "vehicles_loaded": refresh.get("inventory_count",
                                                v.get("vehicles_loaded")),
                 "warnings": v.get("warnings", []),
                 "refresh": refresh}


def handle_rollback(service: Any, body: bytes) -> Tuple[int, Dict[str, Any]]:
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except ValueError:
        payload = {}
    if not payload.get("confirm"):
        return 400, {"status": "rejected",
                     "detail": "Confirmation required (confirm: true)."}
    p = _paths(service)
    if not os.path.exists(p["backup"]):
        return 404, {"status": "error", "detail": "There is no backup Excel to restore."}

    with FileLock(p["lock"]):
        swap = p["live"] + ".owner_swap.xlsx"
        try:
            os.replace(p["live"], swap)          # live -> aside
            os.replace(p["backup"], p["live"])   # backup -> live
            os.replace(swap, p["backup"])        # old live -> backup
        except OSError as e:
            if os.path.exists(swap) and not os.path.exists(p["live"]):
                os.replace(swap, p["live"])      # never leave the live slot empty
            return 500, {"status": "error",
                         "detail": f"Could not restore ({e}). Close the file in "
                                   "Excel and retry."}
        meta = _load_meta(p["meta"])
        meta["live"], meta["backup"] = (dict(meta.get("backup") or {}),
                                        dict(meta.get("live") or {}))
        meta.setdefault("live", {})["restored_at"] = _now()
        _save_meta(p["meta"], meta)

    refresh = service.refresh_inventory()
    return 200, {"status": "ok",
                 "message": "Previous Excel restored — it is LIVE again.",
                 "vehicles_loaded": refresh.get("inventory_count"),
                 "refresh": refresh}


def handle_delete_backup(service: Any, body: bytes) -> Tuple[int, Dict[str, Any]]:
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except ValueError:
        payload = {}
    if not payload.get("confirm"):
        return 400, {"status": "rejected",
                     "detail": "Confirmation required (confirm: true)."}
    p = _paths(service)
    if not os.path.exists(p["backup"]):
        return 404, {"status": "error", "detail": "There is no backup Excel to delete."}
    # only ever the backup file — the live Excel cannot be deleted here
    with FileLock(p["lock"]):
        try:
            os.remove(p["backup"])
        except OSError as e:
            return 500, {"status": "error", "detail": f"Could not delete backup ({e})."}
        meta = _load_meta(p["meta"])
        meta.pop("backup", None)
        _save_meta(p["meta"], meta)
    return 200, {"status": "ok", "message": "Backup Excel deleted."}
