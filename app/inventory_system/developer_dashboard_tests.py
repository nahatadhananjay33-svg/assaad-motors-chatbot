"""
developer_dashboard_tests.py
============================

Validation for the Developer Dashboard (monitoring layer). Everything runs
against throwaway stores (temp audit.db, users.json, and pilot_query_log.db) so
nothing real is touched. Covers the requirements explicitly:

  * authentication  — developer can log in; staff/owner/unauthenticated cannot
                      reach /developer; the Developer role is confined to it;
  * chat logging    — conversations are recorded, ordered, paginated; detail is
                      correct;
  * admin activity  — login / upload / edit / add / sold are counted & listed;
  * inventory        — count / models / sync status are correct & read-only;
  * error logging   — errors are captured; secrets & PII are NOT exposed;
  * persistence     — chat + admin history survive a simulated restart;
  * additive        — the existing /health and /auth routes still work.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone

import audit
import user_management
import developer_auth
import developer_dashboard as dd
from pilot_query_log import PilotQueryLog, QueryLogEntry
from inventory_models import utcnow_iso
from chat_api import route


def _b(o) -> bytes:
    return json.dumps(o).encode("utf-8")


def _item(model, make, reg):
    return types.SimpleNamespace(model=model, make=make, make_full=make,
                                 registration_no=reg, year_int=2021)


class FakeService:
    """Minimal stand-in exposing exactly what the read-only handlers read."""
    def __init__(self, pilot_path, xlsx_path):
        self.pilot_log = PilotQueryLog(pilot_path)
        items = [_item("Creta", "Hyundai", "MH01AB1234"),
                 _item("Nexon", "Tata", "MH02CD5678"),
                 _item("Creta", "Hyundai", "MH03EF9012")]
        self.engine = types.SimpleNamespace(all_facing=items)
        self.inventory_count = len(items)
        self.xlsx_path = xlsx_path
        self._reg_lookup = {i.registration_no: i for i in items}

    def health(self):
        return {"status": "ok", "inventory_count": self.inventory_count}

    def close(self):
        self.pilot_log.close()


class DevDashboardBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="devdash_")
        # isolate audit + users stores
        self._orig_audit_db = audit.DB_PATH
        audit.DB_PATH = os.path.join(self._tmp, "audit.db")
        self._orig_um = (user_management.USERS_PATH, user_management._LOCK,
                         user_management.DATA_DIR)
        user_management.DATA_DIR = self._tmp
        user_management.USERS_PATH = os.path.join(self._tmp, "users.json")
        user_management._LOCK = user_management.USERS_PATH + ".lock"
        # a real (empty) inventory workbook path just needs to exist for mtime
        self._xlsx = os.path.join(self._tmp, "IVR_Sheet.xlsx")
        with open(self._xlsx, "wb") as f:
            f.write(b"x")
        self._pilot = os.path.join(self._tmp, "pilot_query_log.db")
        self.svc = FakeService(self._pilot, self._xlsx)
        # developer env creds
        self._orig_env = {k: os.environ.get(k) for k in
                          ("DEV_DASHBOARD_USER", "DEV_DASHBOARD_PASSWORD")}
        os.environ["DEV_DASHBOARD_USER"] = "devx"
        os.environ["DEV_DASHBOARD_PASSWORD"] = "devx-pass-1"
        developer_auth.seed_developer()
        # clean error ring between tests
        with dd._ERROR_LOCK:
            dd._ERROR_RING.clear()

    def tearDown(self):
        try:
            self.svc.close()
        except Exception:
            pass
        audit.DB_PATH = self._orig_audit_db
        (user_management.USERS_PATH, user_management._LOCK,
         user_management.DATA_DIR) = self._orig_um
        for k, v in self._orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self._tmp, ignore_errors=True)

    # helpers
    def _login(self, username, password):
        st, pl = route("POST", "/auth/login", _b({"username": username,
                                                  "password": password}), self.svc)
        self.assertEqual(st, 200, pl)
        return pl["token"]

    def _seed_turn(self, session, q, a, intent="availability", lang="hinglish",
                   ms=50.0, unknown=False, matched=True, vehicle="2021 Creta"):
        self.svc.pilot_log.record(QueryLogEntry(
            timestamp=utcnow_iso(), conversation_id=session, session_id=session,
            user_query=q, detected_language=lang, detected_intent=intent,
            route=("unknown" if unknown else "inventory"),
            unknown_flag=unknown, matched_inventory=matched,
            response_time_ms=ms, bot_response=a, vehicle_selected=vehicle))


# ─────────────────────────────────────────────────────────────────────────────
class TestAuthentication(DevDashboardBase):
    def test_developer_can_login_and_access(self):
        tok = self._login("devx", "devx-pass-1")
        st, body = route("GET", "/developer/overview", b"", self.svc, session_token=tok)
        self.assertEqual(st, 200)
        self.assertIn("system", body)
        self.assertIn("needs_attention", body)

    def test_unauthenticated_denied(self):
        st, body = route("GET", "/developer/overview", b"", self.svc)
        self.assertEqual(st, 401)

    def test_staff_forbidden(self):
        # create a normal staff user and log in
        user_management.handle_create(_b({"full_name": "Sam", "username": "staff1",
                                          "password": "pass123", "role": "Inventory Staff"}))
        tok = self._login("staff1", "pass123")
        for path in ("/developer/overview", "/developer/chats", "/developer/errors"):
            st, body = route("GET", path, b"", self.svc, session_token=tok)
            self.assertEqual(st, 403, f"{path} should be forbidden for staff")

    def test_owner_forbidden(self):
        tok = self._login("owner", "owner123")   # seeded owner
        st, body = route("GET", "/developer/overview", b"", self.svc, session_token=tok)
        self.assertEqual(st, 403)

    def test_developer_confined_to_dashboard(self):
        # a Developer session must be rejected by the /admin business surface
        tok = self._login("devx", "devx-pass-1")
        st, body = route("GET", "/admin/inventory/vehicles", b"", self.svc,
                         acting_user="devx", session_token=tok)
        self.assertEqual(st, 403)

    def test_developer_post_rejected(self):
        tok = self._login("devx", "devx-pass-1")
        st, body = route("POST", "/developer/overview", b"", self.svc, session_token=tok)
        self.assertEqual(st, 405)

    def test_seed_is_env_required(self):
        # wipe users, unset env → no developer account is created
        os.remove(user_management.USERS_PATH)
        os.environ.pop("DEV_DASHBOARD_USER", None)
        os.environ.pop("DEV_DASHBOARD_PASSWORD", None)
        self.assertFalse(developer_auth.seed_developer())
        data = user_management._load()
        self.assertFalse(any(u.get("role") == "Developer" for u in data["users"]))


class TestDeveloperAccountProtected(DevDashboardBase):
    def test_cannot_disable_or_delete_developer(self):
        st, _ = user_management.handle_set_active(_b({"username": "devx", "active": False}))
        self.assertEqual(st, 400)
        st, _ = user_management.handle_delete(_b({"username": "devx"}))
        self.assertEqual(st, 400)
        st, _ = user_management.handle_update(_b({"username": "devx", "role": "Inventory Staff"}))
        self.assertEqual(st, 400)


# ─────────────────────────────────────────────────────────────────────────────
class TestChatMonitoring(DevDashboardBase):
    def test_conversation_recorded_ordered_and_detailed(self):
        self._seed_turn("sessA", "creta hai kya", "haan Creta available")
        self._seed_turn("sessA", "price kya hai", "7.5 lakh", intent="price")
        self._seed_turn("sessA", "automatic?", "haan automatic", intent="transmission")
        tok = self._login("devx", "devx-pass-1")

        st, chats = route("GET", "/developer/chats", b"", self.svc, session_token=tok)
        self.assertEqual(st, 200)
        self.assertTrue(chats["available"])
        sess = next(s for s in chats["sessions"] if s["session_id"] == "sessA")
        self.assertEqual(sess["messages"], 3)

        st, det = route("GET", "/developer/chats/sessA", b"", self.svc, session_token=tok)
        self.assertEqual(st, 200)
        self.assertEqual(det["messages"], 3)
        # ordered oldest-first
        self.assertEqual(det["turns"][0]["customer"], "creta hai kya")
        self.assertEqual(det["turns"][1]["intent"], "price")
        self.assertEqual(det["turns"][2]["customer"], "automatic?")

    def test_pagination(self):
        for i in range(30):
            self._seed_turn(f"s{i:02d}", "q", "a")
        tok = self._login("devx", "devx-pass-1")
        st, p0 = route("GET", "/developer/chats?page=0&page_size=10", b"", self.svc, session_token=tok)
        self.assertEqual(len(p0["sessions"]), 10)
        self.assertEqual(p0["total"], 30)
        self.assertEqual(p0["pages"], 3)
        st, p2 = route("GET", "/developer/chats?page=2&page_size=10", b"", self.svc, session_token=tok)
        self.assertEqual(len(p2["sessions"]), 10)
        ids0 = {s["session_id"] for s in p0["sessions"]}
        ids2 = {s["session_id"] for s in p2["sessions"]}
        self.assertFalse(ids0 & ids2)          # pages don't overlap

    def test_filters_unanswered_and_slow(self):
        self._seed_turn("good", "creta", "haan")
        self._seed_turn("bad", "zzxx", "samajh nahi aaya", unknown=True, matched=False)
        self._seed_turn("slow", "creta", "haan", ms=3000.0)
        tok = self._login("devx", "devx-pass-1")
        st, un = route("GET", "/developer/chats?errors_only=1", b"", self.svc, session_token=tok)
        self.assertEqual({s["session_id"] for s in un["sessions"]}, {"bad"})
        st, sl = route("GET", "/developer/chats?slow_only=1", b"", self.svc, session_token=tok)
        self.assertEqual({s["session_id"] for s in sl["sessions"]}, {"slow"})

    def test_analytics_intents_and_unanswered(self):
        self._seed_turn("s1", "price", "x", intent="price")
        self._seed_turn("s1", "price2", "x", intent="price")
        self._seed_turn("s2", "avail", "x", intent="availability")
        self._seed_turn("s3", "huh", "?", intent="unknown", unknown=True)
        tok = self._login("devx", "devx-pass-1")
        st, an = route("GET", "/developer/analytics", b"", self.svc, session_token=tok)
        self.assertEqual(st, 200)
        intents = {r["intent"]: r["n"] for r in an["top_intents"]}
        self.assertEqual(intents.get("price"), 2)
        self.assertGreaterEqual(an["unanswered_total"], 1)
        self.assertEqual(len(an["trend_14d"]), 14)


# ─────────────────────────────────────────────────────────────────────────────
class TestAdminActivity(DevDashboardBase):
    def _do(self, method, path, body, status, payload):
        # drive the SAME passive interceptor the server uses
        audit.observe(method, path, "owner", status, body=body, payload=payload,
                      pre_session_user="owner")

    def test_activity_recorded_and_counted(self):
        self._do("POST", "/auth/login", _b({"username": "owner"}), 200,
                 {"user": {"username": "owner", "role": "Owner"}})
        self._do("POST", "/admin/owner/upload", b"{}", 200, {"vehicles_loaded": 187})
        self._do("POST", "/admin/inventory/add_car", _b({"car_number": "MH01AB1234"}), 200,
                 {"car_number": "MH01AB1234"})
        self._do("POST", "/admin/inventory/update_car",
                 _b({"car_number": "MH01AB1234", "values": {"c1": "7.7"}}), 200,
                 {"car_number": "MH01AB1234"})
        self._do("POST", "/admin/media/mark_sold", _b({"car_number": "MH02CD5678"}), 200,
                 {"car_number": "MH02CD5678", "files_deleted": 3})

        tok = self._login("devx", "devx-pass-1")
        st, act = route("GET", "/developer/activity", b"", self.svc, session_token=tok)
        self.assertEqual(st, 200)
        t = act["today"]
        self.assertEqual(t["logins"], 1)
        self.assertEqual(t["excel_uploads"], 1)
        self.assertEqual(t["car_adds"], 1)
        self.assertEqual(t["car_edits"], 1)
        self.assertEqual(t["sold"], 1)
        actions = [e["action"] for e in act["events"]]
        self.assertIn("Add New Car", actions)
        self.assertIn("Mark Vehicle Sold", actions)


# ─────────────────────────────────────────────────────────────────────────────
class TestInventoryMonitoring(DevDashboardBase):
    def test_counts_models_and_sync(self):
        tok = self._login("devx", "devx-pass-1")
        st, inv = route("GET", "/developer/inventory", b"", self.svc, session_token=tok)
        self.assertEqual(st, 200)
        self.assertEqual(inv["count"], 3)
        self.assertEqual(sorted(inv["models"]), ["Creta", "Nexon"])   # deduped
        self.assertEqual(inv["sync"]["status"], "healthy")
        self.assertEqual(inv["sync"]["cars_loaded"], 3)
        self.assertEqual(inv["sync"]["registration_lookup"], "ready")
        self.assertIsNotNone(inv["last_refresh"])                     # workbook mtime

    def test_health_snapshot(self):
        tok = self._login("devx", "devx-pass-1")
        st, h = route("GET", "/developer/health", b"", self.svc, session_token=tok)
        self.assertEqual(st, 200)
        self.assertTrue(h["inventory"]["loaded"])
        self.assertEqual(h["inventory"]["count"], 3)
        self.assertIn("supabase", h)
        self.assertGreaterEqual(h["backend"]["uptime_seconds"], 0)


# ─────────────────────────────────────────────────────────────────────────────
class TestErrorMonitoring(DevDashboardBase):
    def test_errors_captured_without_secrets_or_pii(self):
        dd.install_error_capture("chat")
        lg = logging.getLogger("chat")
        lg.error(json.dumps({
            "event": "unhandled_error", "path": "/chat", "status": 500,
            "error_type": "ValueError",
            "error": "failed for customer 9876543210",
            "api_key": "SUPER_SECRET_KEY", "password": "hunter2",
            "session_id": "sessZ",
        }))
        lg.warning(json.dumps({"event": "permission_denied", "path": "/admin/x", "status": 403}))
        lg.info(json.dumps({"event": "http_access", "path": "/chat", "status": 200}))  # ignored

        tok = self._login("devx", "devx-pass-1")
        st, e = route("GET", "/developer/errors", b"", self.svc, session_token=tok)
        self.assertEqual(st, 200)
        blob = json.dumps(e)
        self.assertNotIn("SUPER_SECRET_KEY", blob)
        self.assertNotIn("hunter2", blob)
        self.assertNotIn("9876543210", blob)      # phone masked
        self.assertNotIn("api_key", blob)
        events = e["errors"]
        self.assertTrue(any(x["event"] == "unhandled_error" and x["severity"] == "HIGH" for x in events))
        self.assertTrue(any(x["event"] == "permission_denied" and x["severity"] == "MEDIUM" for x in events))
        self.assertFalse(any(x["event"] == "http_access" for x in events))   # INFO ignored


# ─────────────────────────────────────────────────────────────────────────────
class TestPersistence(DevDashboardBase):
    def test_chat_and_admin_history_survive_restart(self):
        # write some history
        self._seed_turn("persistA", "creta", "haan")
        self._seed_turn("persistA", "price", "7.5L", intent="price")
        audit.observe("POST", "/auth/login", "owner", 200,
                      body=_b({"username": "owner"}),
                      payload={"user": {"username": "owner", "role": "Owner"}})
        # simulate a restart: close and rebuild the service on the SAME files
        self.svc.close()
        self.svc = FakeService(self._pilot, self._xlsx)

        tok = self._login("devx", "devx-pass-1")
        st, det = route("GET", "/developer/chats/persistA", b"", self.svc, session_token=tok)
        self.assertEqual(st, 200)
        self.assertEqual(det["messages"], 2)          # chat history remains
        st, act = route("GET", "/developer/activity", b"", self.svc, session_token=tok)
        self.assertGreaterEqual(act["today"]["logins"], 1)   # admin history remains


# ─────────────────────────────────────────────────────────────────────────────
class TestAdditiveNoRegression(DevDashboardBase):
    def test_health_and_auth_still_work(self):
        st, h = route("GET", "/health", b"", self.svc)
        self.assertEqual(st, 200)
        self.assertEqual(h["status"], "ok")
        # unknown developer path is a clean 404 for an authorized dev
        tok = self._login("devx", "devx-pass-1")
        st, _ = route("GET", "/developer/nope", b"", self.svc, session_token=tok)
        self.assertEqual(st, 404)


# ─────────────────────────────────────────────────────────────────────────────
class TestActivityDrilldown(DevDashboardBase):
    """Clickable-card drill-down: each card filters the table to today + its type,
    and the card count always equals the filtered row count (one source of truth)."""

    def _obs(self, method, path, user, status, body=b"{}", payload=None):
        audit.observe(method, path, user, status, body=body, payload=payload,
                      pre_session_user=user)

    def _seed(self):
        self._obs("POST", "/auth/login", "owner", 200, body=_b({"username": "owner"}),
                  payload={"user": {"username": "owner", "role": "Owner"}})
        self._obs("POST", "/admin/owner/upload", "owner", 200, payload={"vehicles_loaded": 187})
        self._obs("POST", "/admin/inventory/add_car", "owner", 200,
                  body=_b({"car_number": "MH01AB1234"}), payload={"car_number": "MH01AB1234"})
        self._obs("POST", "/admin/inventory/update_car", "owner", 200,
                  body=_b({"car_number": "MH01AB1234", "values": {"c1": "7"}}),
                  payload={"car_number": "MH01AB1234"})
        self._obs("POST", "/admin/media/mark_sold", "owner", 200,
                  body=_b({"car_number": "MH02CD5678"}),
                  payload={"car_number": "MH02CD5678", "files_deleted": 2})
        self._obs("POST", "/admin/media/upload_photos", "owner", 200, payload={"uploaded": 3})
        self._obs("POST", "/admin/media/upload_videos", "owner", 200, payload={"uploaded": 1})
        self._obs("POST", "/admin/users/create", "owner", 200,
                  body=_b({"username": "newstaff", "role": "Photo Staff"}),
                  payload={"user": {"username": "newstaff", "role": "Photo Staff"}})
        # a genuinely FAILED action (403 edit) — counts under BOTH Car edits and Failed
        self._obs("POST", "/admin/inventory/update_car", "priya", 403,
                  body=_b({"car_number": "MH03EF9012", "values": {"c11": "1"}}),
                  payload={"error": "forbidden", "detail": "denied"})

    def _act(self, type_=None):
        tok = self._login("devx", "devx-pass-1")
        path = "/developer/activity" + ("?type=" + type_ if type_ else "")
        st, body = route("GET", path, b"", self.svc, session_token=tok)
        self.assertEqual(st, 200)
        return body

    # 8) card count == filtered count, for EVERY card
    def test_card_count_equals_filtered(self):
        self._seed()
        today = self._act()["today"]
        pairs = {"login": "logins", "excel": "excel_uploads", "edit": "car_edits",
                 "add": "car_adds", "sold": "sold", "media": "media",
                 "users": "user_mgmt", "failed": "failed"}
        for tid, tkey in pairs.items():
            fb = self._act(tid)
            self.assertEqual(fb["type"], tid)
            self.assertEqual(today[tkey], len(fb["events"]),
                             f"{tid}: card {today[tkey]} != filtered {len(fb['events'])}")

    def test_login_drilldown(self):
        self._seed()
        ev = self._act("login")["events"]
        self.assertTrue(ev)
        self.assertTrue(all(e["action"] == "Login" for e in ev))

    def test_excel_drilldown(self):
        self._seed()
        ev = self._act("excel")["events"]
        self.assertTrue(all((e["category"] or "").lower() == "excel" for e in ev))

    def test_edit_drilldown(self):
        self._seed()
        ev = self._act("edit")["events"]
        self.assertTrue(all(e["action"] == "Edit Car" for e in ev))     # incl. the failed edit

    def test_add_drilldown(self):
        self._seed()
        ev = self._act("add")["events"]
        self.assertTrue(all(e["action"] == "Add New Car" for e in ev))

    def test_sold_drilldown(self):
        self._seed()
        ev = self._act("sold")["events"]
        self.assertTrue(all(e["action"] == "Mark Vehicle Sold" for e in ev))

    def test_media_drilldown_includes_all_media_only(self):
        self._seed()
        ev = self._act("media")["events"]
        self.assertTrue(all((e["category"] or "").lower() == "media" for e in ev))
        actions = {e["action"] for e in ev}
        self.assertIn("Mark Vehicle Sold", actions)      # sold is a media action here
        self.assertNotIn("Edit Car", actions)            # must NOT leak non-media
        self.assertNotIn("Login", actions)

    def test_users_drilldown(self):
        self._seed()
        ev = self._act("users")["events"]
        self.assertTrue(all((e["category"] or "").lower() == "users" for e in ev))

    def test_failed_drilldown(self):
        self._seed()
        ev = self._act("failed")["events"]
        self.assertTrue(ev)
        self.assertTrue(all(e["status"] == "failed" for e in ev))

    def test_clear_filter_returns_all(self):
        self._seed()
        body = self._act()                                # no type
        self.assertEqual(body["type"], "")
        self.assertGreaterEqual(len(body["events"]), 9)   # every seeded event

    def test_switching_replaces_not_stacks(self):
        self._seed()
        a, b = self._act("edit"), self._act("media")
        self.assertEqual(a["type"], "edit")
        self.assertEqual(b["type"], "media")
        self.assertTrue(all(e["action"] == "Edit Car" for e in a["events"]))
        self.assertTrue(all((e["category"] or "").lower() == "media" for e in b["events"]))

    def test_today_only_excludes_older(self):
        self._seed()
        # inject an OLD (2 days ago) edit straight into the audit db
        old_ts = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(timespec="seconds")
        conn = sqlite3.connect(audit.DB_PATH)
        conn.execute("INSERT INTO audit_events (ts,username,role,action,category,status) "
                     "VALUES (?,?,?,?,?,?)",
                     (old_ts, "owner", "Owner", "Edit Car", "Inventory", "success"))
        conn.commit()
        conn.close()
        fb = self._act("edit")
        self.assertTrue(all(e["ts"] != old_ts for e in fb["events"]))   # old one excluded
        # count still agrees with the (today-only) filtered rows
        self.assertEqual(self._act()["today"]["car_edits"], len(fb["events"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
