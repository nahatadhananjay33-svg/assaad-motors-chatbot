"""
audit_tests.py
==============

Phase 10E — validation for the centralised Audit Log.

Runs against a throwaway audit.db and a throwaway users.json (both
monkeypatched), so nothing real is touched. Verifies the requirements
explicitly: exactly-one-entry per action, timestamps, username, role, vehicle,
filters, search, failure recording, and that the trail is read-only.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import unittest

import user_management
import audit
import permissions
from chat_api import route


def _b(o) -> bytes:
    return json.dumps(o).encode("utf-8")


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="audittest_")
        # isolate the audit DB
        self._orig_db = audit.DB_PATH
        audit.DB_PATH = os.path.join(self._tmp, "audit.db")
        # isolate users.json (for role look-ups)
        self._u = (user_management.USERS_PATH, user_management._LOCK, user_management.DATA_DIR)
        user_management.DATA_DIR = self._tmp
        user_management.USERS_PATH = os.path.join(self._tmp, "users.json")
        user_management._LOCK = user_management.USERS_PATH + ".lock"
        user_management.handle_list()  # seed owner
        user_management.handle_create(_b({"full_name": "Sunita", "username": "sunita",
                                          "password": "photo123", "role": "Photo Staff"}))

    def tearDown(self):
        audit.DB_PATH = self._orig_db
        (user_management.USERS_PATH, user_management._LOCK, user_management.DATA_DIR) = self._u
        shutil.rmtree(self._tmp, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
# 1. store basics + read-only
# ─────────────────────────────────────────────────────────────────────────────
class TestStore(_Base):
    def test_record_one_row(self):
        self.assertEqual(audit.count(), 0)
        rid = audit.record("owner", "Owner", "Login", "Login")
        self.assertIsInstance(rid, int)
        self.assertEqual(audit.count(), 1)
        row = audit.query()[0]
        self.assertEqual(row["username"], "owner")
        self.assertEqual(row["action"], "Login")

    def test_timestamp_iso_utc(self):
        audit.record("owner", "Owner", "Login", "Login")
        ts = audit.query()[0]["ts"]
        self.assertRegex(ts, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")

    def test_newest_first(self):
        for a in ["Login", "Add New Car", "Logout"]:
            audit.record("owner", "Owner", a, "Login")
        actions = [e["action"] for e in audit.query()]
        self.assertEqual(actions, ["Logout", "Add New Car", "Login"])

    def test_read_only_no_mutators(self):
        # There must be NO way to edit or delete logs from this module.
        for banned in ("update", "delete", "remove", "clear", "edit", "purge", "drop"):
            self.assertFalse(hasattr(audit, banned),
                             f"audit must not expose a '{banned}' function")


# ─────────────────────────────────────────────────────────────────────────────
# 2. observe(): exactly one entry per mapped action; none for reads
# ─────────────────────────────────────────────────────────────────────────────
class TestObserve(_Base):
    # (method, path, body, payload, expected_action, expected_category, expected_vehicle)
    CASES = [
        ("POST", "/auth/login", {"username": "owner", "password": "secret"},
         {"status": "ok", "user": {"username": "owner", "role": "Owner"}}, "Login", "Login", None),
        ("POST", "/auth/logout", {}, {"status": "ok"}, "Logout", "Login", None),
        ("POST", "/admin/owner/upload", {}, {"status": "ok", "vehicles_loaded": 44},
         "Upload New Excel", "Excel", None),
        ("POST", "/admin/upload_inventory", {}, {"status": "ok", "vehicles_loaded": 44},
         "Upload New Excel", "Excel", None),
        ("POST", "/admin/owner/rollback", {}, {"status": "ok", "vehicles_loaded": 40, "message": "Restored"},
         "Restore Previous Excel", "Excel", None),
        ("POST", "/admin/owner/delete_backup", {}, {"status": "ok"},
         "Delete Backup Excel", "Excel", None),
        ("POST", "/admin/inventory/add_car", {"values": {}}, {"status": "ok", "car_number": "MH01AB1234"},
         "Add New Car", "Inventory", "MH01AB1234"),
        ("POST", "/admin/inventory/update_car", {"car_number": "MH01AB1234", "values": {"c1": "x"}},
         {"status": "ok", "car_number": "MH01AB1234"}, "Edit Car", "Inventory", "MH01AB1234"),
        ("POST", "/admin/inventory/restore_car", {"car_number": "MH02CD5678"},
         {"status": "ok", "car_number": "MH02CD5678"}, "Restore Vehicle", "Inventory", "MH02CD5678"),
        ("POST", "/admin/media/upload_photos", {}, {"status": "ok", "vehicle": "MH01AB1234", "uploaded": 3},
         "Upload Photos", "Media", "MH01AB1234"),
        ("POST", "/admin/media/upload_videos", {}, {"status": "ok", "vehicle": "MH01AB1234", "uploaded": 1},
         "Upload Videos", "Media", "MH01AB1234"),
        ("POST", "/admin/media/add_link", {"car_number": "MH01AB1234", "platform": "instagram", "url": "u"},
         {"status": "ok", "vehicle": "MH01AB1234", "platform": "instagram", "url": "u"},
         "Add Instagram Link", "Media", "MH01AB1234"),
        ("POST", "/admin/media/add_link", {"car_number": "MH01AB1234", "platform": "youtube", "url": "u"},
         {"status": "ok", "vehicle": "MH01AB1234", "platform": "youtube", "url": "u"},
         "Add YouTube Link", "Media", "MH01AB1234"),
        ("POST", "/admin/media/mark_sold", {"car_number": "MH01AB1234"},
         {"status": "ok", "vehicle": "MH01AB1234", "files_deleted": 5}, "Mark Vehicle Sold", "Media", "MH01AB1234"),
        ("POST", "/admin/users/create", {"username": "raj", "role": "Inventory Staff"},
         {"status": "ok", "user": {"username": "raj", "role": "Inventory Staff"}}, "Create User", "Users", None),
        ("POST", "/admin/users/update", {"username": "raj", "role": "Finance Staff"},
         {"status": "ok", "user": {"username": "raj", "role": "Finance Staff"}}, "Edit User", "Users", None),
        ("POST", "/admin/users/reset_password", {"username": "raj", "new_password": "zzzzzz"},
         {"status": "ok"}, "Reset Password", "Users", None),
        ("POST", "/admin/users/set_active", {"username": "raj", "active": False},
         {"status": "ok"}, "Disable User", "Users", None),
        ("POST", "/admin/users/set_active", {"username": "raj", "active": True},
         {"status": "ok"}, "Enable User", "Users", None),
        ("POST", "/admin/users/delete", {"username": "raj"}, {"status": "ok"}, "Delete User", "Users", None),
    ]

    def test_each_action_exactly_one_entry(self):
        for (m, p, body, payload, act, cat, veh) in self.CASES:
            before = audit.count()
            rid = audit.observe(m, p, "owner", 200, body=_b(body), payload=payload)
            self.assertIsInstance(rid, int, f"{act} should log a row")
            self.assertEqual(audit.count(), before + 1, f"{act} must add exactly ONE row")
            row = audit.query(limit=1)[0]
            self.assertEqual(row["action"], act)
            self.assertEqual(row["category"], cat)
            self.assertEqual(row["vehicle"], veh, f"{act} vehicle")
            self.assertEqual(row["status"], "success")

    def test_reads_and_unmapped_not_logged(self):
        for (m, p) in [("GET", "/health"), ("POST", "/chat"),
                       ("GET", "/admin/users/my_permissions"), ("GET", "/auth/me"),
                       ("GET", "/admin/audit/list"), ("GET", "/admin/inventory/dashboard"),
                       ("GET", "/admin/media/vehicles")]:
            self.assertIsNone(audit.observe(m, p, "owner", 200), f"{m} {p} must NOT log")
        self.assertEqual(audit.count(), 0)

    def test_role_captured(self):
        audit.observe("POST", "/admin/inventory/add_car", "owner", 200,
                      body=_b({"values": {}}), payload={"status": "ok", "car_number": "X1"})
        self.assertEqual(audit.query()[0]["role"], "Owner")
        # a non-owner actor gets their real role
        audit.observe("POST", "/admin/media/upload_photos", "sunita", 200,
                      body=b"", payload={"status": "ok", "vehicle": "X1", "uploaded": 1})
        self.assertEqual(audit.query()[0]["role"], "Photo Staff")

    def test_login_role_from_payload(self):
        audit.observe("POST", "/auth/login", None, 200,
                      body=_b({"username": "sunita", "password": "photo123"}),
                      payload={"status": "ok", "user": {"username": "sunita", "role": "Photo Staff"}})
        row = audit.query()[0]
        self.assertEqual(row["username"], "sunita")
        self.assertEqual(row["role"], "Photo Staff")

    def test_failed_action_recorded(self):
        rid = audit.observe("POST", "/auth/login", None, 401,
                            body=_b({"username": "ghost", "password": "x"}),
                            payload={"status": "error", "detail": "Invalid username or password."})
        self.assertIsInstance(rid, int)
        row = audit.query()[0]
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["username"], "ghost")
        self.assertIn("Invalid", row["detail"])

    def test_password_never_stored(self):
        audit.observe("POST", "/auth/login", None, 200,
                      body=_b({"username": "owner", "password": "TOPSECRET123"}),
                      payload={"status": "ok", "user": {"username": "owner", "role": "Owner"}})
        audit.observe("POST", "/admin/users/reset_password", "owner", 200,
                      body=_b({"username": "sunita", "new_password": "RESETSECRET"}), payload={"status": "ok"})
        blob = json.dumps(audit.query())
        self.assertNotIn("TOPSECRET123", blob)
        self.assertNotIn("RESETSECRET", blob)

    def test_logout_uses_pre_session_user(self):
        audit.observe("POST", "/auth/logout", None, 200, body=b"",
                      payload={"status": "ok"}, pre_session_user="sunita")
        row = audit.query()[0]
        self.assertEqual(row["username"], "sunita")
        self.assertEqual(row["role"], "Photo Staff")

    def test_observe_never_raises(self):
        # garbage body/payload must not crash; observe still records the action
        # best-effort (empty extraction), never raising into the request path.
        rid = audit.observe("POST", "/admin/inventory/add_car", "owner", 200,
                            body=b"\xff\xfe not json", payload="also not a dict")
        self.assertIsInstance(rid, int)
        self.assertEqual(audit.count(), 1)
        self.assertIsNone(audit.query()[0]["vehicle"])   # nothing extractable


# ─────────────────────────────────────────────────────────────────────────────
# 3. filters + search
# ─────────────────────────────────────────────────────────────────────────────
class TestFilterSearch(_Base):
    def setUp(self):
        super().setUp()
        seed = [
            ("POST", "/auth/login", {"username": "owner"}, {"status": "ok", "user": {"username": "owner", "role": "Owner"}}),
            ("POST", "/admin/inventory/add_car", {"values": {}}, {"status": "ok", "car_number": "MH01AB1234"}),
            ("POST", "/admin/media/mark_sold", {"car_number": "MH09ZZ0001"}, {"status": "ok", "vehicle": "MH09ZZ0001"}),
            ("POST", "/admin/users/create", {"username": "raj", "role": "Finance Staff"},
             {"status": "ok", "user": {"username": "raj", "role": "Finance Staff"}}),
            ("POST", "/admin/owner/rollback", {}, {"status": "ok", "vehicles_loaded": 10}),
        ]
        for (m, p, b, pl) in seed:
            audit.observe(m, p, "owner", 200, body=_b(b), payload=pl)

    def test_filter_each_category(self):
        self.assertEqual({e["action"] for e in audit.query(category="Inventory")}, {"Add New Car"})
        self.assertEqual({e["action"] for e in audit.query(category="Media")}, {"Mark Vehicle Sold"})
        self.assertEqual({e["action"] for e in audit.query(category="Users")}, {"Create User"})
        self.assertEqual({e["action"] for e in audit.query(category="Excel")}, {"Restore Previous Excel"})
        self.assertEqual({e["action"] for e in audit.query(category="Login")}, {"Login"})

    def test_filter_all(self):
        self.assertEqual(len(audit.query(category="All")), 5)
        self.assertEqual(len(audit.query()), 5)

    def test_search_by_vehicle(self):
        r = audit.query(search="MH09ZZ0001")
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["action"], "Mark Vehicle Sold")

    def test_search_by_username(self):
        r = audit.query(search="raj")               # appears in detail(target)/username
        self.assertTrue(any(e["action"] == "Create User" for e in r))

    def test_search_by_action(self):
        r = audit.query(search="rollback")           # nothing
        self.assertEqual(r, [])
        r2 = audit.query(search="restore previous")
        self.assertEqual(len(r2), 1)

    def test_search_case_insensitive(self):
        self.assertEqual(len(audit.query(search="mh01ab1234")), 1)


# ─────────────────────────────────────────────────────────────────────────────
# 4. HTTP surface: read handler, route, owner-only, read-only method
# ─────────────────────────────────────────────────────────────────────────────
class TestHttpSurface(_Base):
    def test_handle_list_shape_and_query(self):
        audit.record("owner", "Owner", "Add New Car", "Inventory", vehicle="MH01AB1234")
        audit.record("owner", "Owner", "Login", "Login")
        st, pl = audit.handle_list("category=Inventory")
        self.assertEqual(st, 200)
        self.assertEqual(pl["categories"], ["Inventory", "Media", "Users", "Excel", "Login"])
        self.assertEqual(len(pl["events"]), 1)
        self.assertEqual(pl["events"][0]["action"], "Add New Car")

    def test_route_get_audit(self):
        audit.record("owner", "Owner", "Login", "Login")
        st, pl = route("GET", "/admin/audit/list", b"", None, acting_user="owner")
        self.assertEqual(st, 200)
        self.assertEqual(pl["count"], 1)

    def test_route_get_audit_with_querystring(self):
        audit.record("owner", "Owner", "Add New Car", "Inventory", vehicle="MH01AB1234")
        audit.record("owner", "Owner", "Login", "Login")
        st, pl = route("GET", "/admin/audit/list?category=Login", b"", None, acting_user="owner")
        self.assertEqual(st, 200)
        self.assertEqual([e["action"] for e in pl["events"]], ["Login"])

    def test_audit_is_owner_only(self):
        # Owner allowed, every other role 403 — via the existing unmapped-path rule.
        self.assertIsNone(permissions.enforce("GET", "/admin/audit/list", "owner", None, b""))
        denial = permissions.enforce("GET", "/admin/audit/list", "sunita", None, b"")
        self.assertIsNotNone(denial)
        self.assertEqual(denial[0], 403)

    def test_audit_is_read_only_method(self):
        # No POST/PUT/DELETE surface — POST must be 405, never a write.
        st, _ = route("POST", "/admin/audit/list", b"{}", None, acting_user="owner")
        self.assertEqual(st, 405)


if __name__ == "__main__":
    unittest.main(verbosity=2)
