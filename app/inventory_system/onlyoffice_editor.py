"""
ONLYOFFICE Docs integration — REAL XLSX editing of the inventory workbook.

Flow:  Owner Panel "Open Inventory Excel" -> /editor2 page (this module) ->
ONLYOFFICE editor (genuine spreadsheet UI) opens the live workbook via a
download endpoint -> owner edits -> ONLYOFFICE POSTs the saved file to the
callback endpoint -> we validate + back up + atomically replace the workbook ->
existing service.refresh_inventory() -> chatbot sees the new data.

The XLSX (service.xlsx_path, normally /data/IVR_Sheet.xlsx) stays the single
source of truth. We do NOT convert it to any other format.

Security: ONLYOFFICE signs its download/callback requests with a shared JWT
secret (ONLYOFFICE_JWT_SECRET). We reject any unsigned/invalid callback so the
live workbook can only be replaced by a genuine ONLYOFFICE save. The /editor2
PAGE itself is gated upstream (nginx / owner session) — see chat_api wiring.
No external service, no LLM.
"""
import os, json, hmac, hashlib, base64, urllib.request, shutil, logging, datetime

try:
    import inventory_upload           # reuse the upload validator (DNJ sheet, col N, loads)
except Exception:                     # pragma: no cover
    inventory_upload = None

# browser-facing path where nginx proxies the ONLYOFFICE document server
ONLYOFFICE_PUBLIC = os.environ.get("ONLYOFFICE_PUBLIC_PATH", "/onlyoffice")
# internal URL the document server uses to reach THIS app (private docker network)
APP_INTERNAL = os.environ.get("ONLYOFFICE_APP_INTERNAL", "http://app:8000")
JWT_SECRET = os.environ.get("ONLYOFFICE_JWT_SECRET", "")

log = logging.getLogger("chat")


def _wb(service) -> str:
    # EDITOR2_WORKBOOK lets the pre-production isolated test open/save a COPY of
    # the workbook instead of the live file. Unset in production -> live workbook.
    return os.environ.get("EDITOR2_WORKBOOK") or service.xlsx_path


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def jwt_sign(payload: dict) -> str:
    h = _b64u(b'{"alg":"HS256","typ":"JWT"}')
    p = _b64u(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64u(hmac.new(JWT_SECRET.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest())
    return f"{h}.{p}.{sig}"


def jwt_verify(token: str):
    try:
        h, p, s = token.split(".")
        exp = _b64u(hmac.new(JWT_SECRET.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(exp, s):
            return None
        return json.loads(_b64u_dec(p))
    except Exception:
        return None


def _doc_key(path: str) -> str:
    # ONLYOFFICE caches by key — must change whenever the file changes on disk.
    try:
        st = os.stat(path)
        return "ivr%d_%d" % (int(st.st_mtime), st.st_size)
    except OSError:
        return "ivr0"


def editor_page(service) -> str:
    """Full HTML page that embeds the ONLYOFFICE editor on the live workbook."""
    path = _wb(service)
    cfg = {
        "documentType": "cell",
        "document": {
            "fileType": "xlsx", "key": _doc_key(path), "title": "IVR_Sheet.xlsx",
            "url": f"{APP_INTERNAL}/editor2/download",
            "permissions": {"edit": True, "download": True, "print": True},
        },
        "editorConfig": {
            "mode": "edit", "lang": "en",
            "callbackUrl": f"{APP_INTERNAL}/editor2/callback",
            "user": {"id": "owner", "name": "Owner"},
            "customization": {"forcesave": True, "autosave": True, "compactHeader": False},
        },
        "height": "100%", "width": "100%", "type": "desktop",
    }
    if JWT_SECRET:
        cfg["token"] = jwt_sign(cfg)
    return (
        "<!doctype html><html><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>Inventory Excel</title>"
        "<style>html,body,#ph{height:100%;margin:0;padding:0}</style>"
        f'<script src="{ONLYOFFICE_PUBLIC}/web-apps/apps/api/documents/api.js"></script></head>'
        '<body><div id="ph"></div>'
        f'<script>new DocsAPI.DocEditor("ph", {json.dumps(cfg)});</script>'
        "</body></html>"
    )


def _auth_ok(headers: dict) -> bool:
    """ONLYOFFICE signs download/callback with Authorization: Bearer <jwt>."""
    if not JWT_SECRET:
        return True
    auth = headers.get("Authorization") or headers.get("authorization") or ""
    return auth.startswith("Bearer ") and jwt_verify(auth[7:]) is not None


def handle_download(service, headers: dict):
    """Serve the live workbook bytes to ONLYOFFICE (or None -> 403)."""
    if not _auth_ok(headers):
        return None
    with open(_wb(service), "rb") as f:
        return f.read()


def handle_callback(service, body: bytes, headers: dict) -> dict:
    """Handle an ONLYOFFICE save callback. Must always return {"error": N}."""
    try:
        data = json.loads(body or b"{}")
    except Exception:
        return {"error": 1}
    if JWT_SECRET:
        tok = data.get("token")
        if not tok:
            auth = headers.get("Authorization") or headers.get("authorization") or ""
            tok = auth[7:] if auth.startswith("Bearer ") else None
        payload = jwt_verify(tok) if tok else None
        if payload is None:
            log.warning(json.dumps({"event": "editor2_callback_bad_jwt"}))
            return {"error": 1}
        data = payload            # signed body carries the real status/url
    status = data.get("status")
    # 2 = ready to save (all editors closed); 6 = forcesave while editing
    if status in (2, 6):
        url = data.get("url")
        if url:
            _apply_save(service, url)
    return {"error": 0}


def _apply_save(service, url: str) -> None:
    """Download the edited workbook, validate, back up, atomically replace, refresh."""
    try:
        edited = urllib.request.urlopen(url, timeout=90).read()
    except Exception as e:
        log.error(json.dumps({"event": "editor2_fetch_fail", "detail": str(e)}))
        return
    xlsx = _wb(service)
    incoming = xlsx + ".oo_incoming.xlsx"
    try:
        with open(incoming, "wb") as f:
            f.write(edited)
        # validate BEFORE touching the live file — reject anything that isn't a
        # loadable inventory workbook (DNJ sheet, CAR NUMB column, >0 vehicles).
        if inventory_upload is not None:
            v = inventory_upload.validate_workbook(incoming)
            if v["errors"] or int(v.get("vehicles_loaded") or 0) <= 0:
                os.remove(incoming)
                log.error(json.dumps({"event": "editor2_save_rejected",
                                      "errors": v["errors"]}))
                return
        # backup the current live file (keep the panel's backup dir)
        bdir = os.path.join(os.path.dirname(xlsx), "inventory_backups")
        os.makedirs(bdir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(xlsx, os.path.join(bdir, f"IVR_Sheet_{ts}.xlsx"))
        os.replace(incoming, xlsx)         # atomic
    except OSError as e:
        log.error(json.dumps({"event": "editor2_save_io_fail", "detail": str(e)}))
        return
    try:
        rep = service.refresh_inventory()
        log.info(json.dumps({"event": "editor2_saved", "bytes": len(edited),
                             "vehicles": rep.get("inventory_count")}))
    except Exception as e:
        log.error(json.dumps({"event": "editor2_refresh_fail", "detail": str(e)}))
