"""
auth_tests.py
=============

Phase 10D — validation for authentication & sessions.

Covers, without opening a socket or touching the real users.json:
  * SessionStore lifecycle: create / resolve / destroy / EXPIRY / purge
  * handle_login: success, wrong password, unknown user, disabled account,
    missing fields, malformed body
  * handle_logout (idempotent) and handle_me (valid / expired / disabled)
  * route() integration for /auth/login, /auth/me, /auth/logout
  * SecurityGate: /auth is public, a session authorises /admin, and the legacy
    admin-key path is unchanged (regression)
  * end-to-end: a logged-in non-Owner is blocked by the Phase 10C permission
    engine on an Owner-only endpoint but allowed on their own surface

Each test runs against a throwaway users.json (monkeypatched) so it is
isolated and never mutates real data.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest

import user_management
import auth
import permissions
from auth import SessionStore
from chat_api import route


def _b(obj) -> bytes:
    return json.dumps(obj).encode("utf-8")


class _TempUsers(unittest.TestCase):
    """Base: point user_management at a temp users.json for the duration."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="authtest_")
        self._orig_path = user_management.USERS_PATH
        self._orig_lock = user_management._LOCK
        self._orig_dir = user_management.DATA_DIR
        user_management.DATA_DIR = self._tmp
        user_management.USERS_PATH = os.path.join(self._tmp, "users.json")
        user_management._LOCK = user_management.USERS_PATH + ".lock"
        # seed the first-run owner into the temp store
        user_management.handle_list()

    def tearDown(self):
        user_management.USERS_PATH = self._orig_path
        user_management._LOCK = self._orig_lock
        user_management.DATA_DIR = self._orig_dir
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make(self, full_name, username, password, role):
        st, pl = user_management.handle_create(
            _b({"full_name": full_name, "username": username,
                "password": password, "role": role}))
        self.assertEqual(st, 200, pl)


# ─────────────────────────────────────────────────────────────────────────────
# 1. SessionStore
# ─────────────────────────────────────────────────────────────────────────────
class TestSessionStore(unittest.TestCase):
    def test_create_and_resolve(self):
        s = SessionStore(ttl=100, clock=lambda: 1000.0)
        tok = s.create("ramesh", "Inventory Staff")
        self.assertTrue(tok)
        self.assertEqual(s.username_for(tok), "ramesh")
        self.assertEqual(s.get(tok)["role"], "Inventory Staff")

    def test_unknown_token(self):
        s = SessionStore()
        self.assertIsNone(s.get("nope"))
        self.assertIsNone(s.username_for(None))

    def test_expiry(self):
        now = [1000.0]
        s = SessionStore(ttl=100, clock=lambda: now[0])
        tok = s.create("owner", "Owner")
        now[0] = 1099.0
        self.assertEqual(s.username_for(tok), "owner")   # still valid
        now[0] = 1100.0
        self.assertIsNone(s.username_for(tok))           # boundary = expired
        self.assertIsNone(s.get(tok))

    def test_destroy_and_idempotent(self):
        s = SessionStore()
        tok = s.create("owner", "Owner")
        self.assertTrue(s.destroy(tok))
        self.assertFalse(s.destroy(tok))                 # already gone
        self.assertIsNone(s.username_for(tok))

    def test_purge_expired(self):
        now = [0.0]
        s = SessionStore(ttl=10, clock=lambda: now[0])
        s.create("a", "Owner"); s.create("b", "Owner")
        now[0] = 50.0
        self.assertEqual(s.purge_expired(), 2)
        self.assertEqual(s.active_count(), 0)

    def test_tokens_unique(self):
        s = SessionStore()
        toks = {s.create("owner", "Owner") for _ in range(50)}
        self.assertEqual(len(toks), 50)


# ─────────────────────────────────────────────────────────────────────────────
# 2. handle_login
# ─────────────────────────────────────────────────────────────────────────────
class TestLogin(_TempUsers):
    def test_login_success_seeded_owner(self):
        store = SessionStore()
        st, pl = auth.handle_login(_b({"username": "owner", "password": "owner123"}), store)
        self.assertEqual(st, 200)
        self.assertTrue(pl["token"])
        self.assertEqual(pl["user"]["username"], "owner")
        self.assertEqual(pl["user"]["role"], "Owner")
        self.assertEqual(store.username_for(pl["token"]), "owner")

    def test_login_wrong_password(self):
        st, pl = auth.handle_login(_b({"username": "owner", "password": "bad"}), SessionStore())
        self.assertEqual(st, 401)
        self.assertNotIn("token", pl)

    def test_login_unknown_user(self):
        st, pl = auth.handle_login(_b({"username": "ghost", "password": "x"}), SessionStore())
        self.assertEqual(st, 401)

    def test_login_same_message_user_or_pass(self):
        # must not reveal which field was wrong
        _, p1 = auth.handle_login(_b({"username": "ghost", "password": "x"}), SessionStore())
        _, p2 = auth.handle_login(_b({"username": "owner", "password": "x"}), SessionStore())
        self.assertEqual(p1["detail"], p2["detail"])

    def test_login_disabled_account(self):
        self._make("Sunita", "sunita", "photo123", "Photo Staff")
        user_management.handle_set_active(_b({"username": "sunita", "active": False}))
        st, pl = auth.handle_login(_b({"username": "sunita", "password": "photo123"}), SessionStore())
        self.assertEqual(st, 401)
        self.assertIn("disabled", pl["detail"].lower())

    def test_login_missing_fields(self):
        st, _ = auth.handle_login(_b({"username": "owner"}), SessionStore())
        self.assertEqual(st, 400)

    def test_login_bad_body(self):
        st, _ = auth.handle_login(b"{not json", SessionStore())
        self.assertEqual(st, 400)

    def test_login_case_insensitive_username(self):
        st, pl = auth.handle_login(_b({"username": "OWNER", "password": "owner123"}), SessionStore())
        self.assertEqual(st, 200)


# ─────────────────────────────────────────────────────────────────────────────
# 3. logout + me
# ─────────────────────────────────────────────────────────────────────────────
class TestLogoutMe(_TempUsers):
    def _login(self, store, u="owner", p="owner123"):
        _, pl = auth.handle_login(_b({"username": u, "password": p}), store)
        return pl["token"]

    def test_me_valid(self):
        store = SessionStore()
        tok = self._login(store)
        st, pl = auth.handle_me(tok, store)
        self.assertEqual(st, 200)
        self.assertEqual(pl["user"]["username"], "owner")

    def test_me_no_token(self):
        st, _ = auth.handle_me(None, SessionStore())
        self.assertEqual(st, 401)

    def test_logout_then_me(self):
        store = SessionStore()
        tok = self._login(store)
        st, _ = auth.handle_logout(tok, store)
        self.assertEqual(st, 200)
        st2, _ = auth.handle_me(tok, store)
        self.assertEqual(st2, 401)

    def test_logout_idempotent(self):
        store = SessionStore()
        tok = self._login(store)
        auth.handle_logout(tok, store)
        st, _ = auth.handle_logout(tok, store)          # again
        self.assertEqual(st, 200)

    def test_me_after_expiry(self):
        now = [1000.0]
        store = SessionStore(ttl=10, clock=lambda: now[0])
        tok = self._login(store)
        now[0] = 2000.0
        st, _ = auth.handle_me(tok, store)
        self.assertEqual(st, 401)

    def test_me_disabled_mid_session(self):
        self._make("Sunita", "sunita", "photo123", "Photo Staff")
        store = SessionStore()
        tok = self._login(store, "sunita", "photo123")
        user_management.handle_set_active(_b({"username": "sunita", "active": False}))
        st, _ = auth.handle_me(tok, store)
        self.assertEqual(st, 401)                        # revoked live


# ─────────────────────────────────────────────────────────────────────────────
# 4. route() integration
# ─────────────────────────────────────────────────────────────────────────────
class TestRouteAuth(_TempUsers):
    def test_route_login_logout_me(self):
        st, pl = route("POST", "/auth/login",
                       _b({"username": "owner", "password": "owner123"}), None)
        self.assertEqual(st, 200)
        tok = pl["token"]
        # me
        st, pl = route("GET", "/auth/me", b"", None, session_token=tok)
        self.assertEqual(st, 200)
        self.assertEqual(pl["user"]["username"], "owner")
        # logout
        st, _ = route("POST", "/auth/logout", b"", None, session_token=tok)
        self.assertEqual(st, 200)
        st, _ = route("GET", "/auth/me", b"", None, session_token=tok)
        self.assertEqual(st, 401)

    def test_route_login_bad_credentials(self):
        st, _ = route("POST", "/auth/login",
                      _b({"username": "owner", "password": "nope"}), None)
        self.assertEqual(st, 401)

    def test_route_auth_method_not_allowed(self):
        st, _ = route("GET", "/auth/login", b"", None)
        self.assertEqual(st, 405)


# ─────────────────────────────────────────────────────────────────────────────
# 5. SecurityGate — session authorises admin; legacy path unchanged
# ─────────────────────────────────────────────────────────────────────────────
class TestGateSessions(unittest.TestCase):
    def setUp(self):
        from security import SecurityGate, RateLimiter
        self.SecurityGate = SecurityGate
        self.RateLimiter = RateLimiter

    def test_auth_endpoints_public(self):
        g = self.SecurityGate(admin_keys={"adm"})
        self.assertIsNone(g.authorize("POST", "/auth/login", {}, "ip"))

    def test_admin_open_with_session(self):
        g = self.SecurityGate(admin_keys=set())          # no key => normally closed
        self.assertEqual(g.authorize("GET", "/admin/users/list", {}, "ip")[0], 403)
        self.assertIsNone(g.authorize("GET", "/admin/users/list", {}, "ip",
                                      session_user="owner"))

    def test_admin_key_path_unchanged(self):
        # regression: behaviour with NO session must match Phase 10C exactly
        g = self.SecurityGate(api_keys={"k1"}, admin_keys={"adm"},
                              limiter=self.RateLimiter(100, 60))
        self.assertEqual(
            g.authorize("POST", "/admin/refresh_inventory", {"X-API-Key": "k1"}, "ip")[0], 401)
        self.assertIsNone(
            g.authorize("POST", "/admin/refresh_inventory", {"X-API-Key": "adm"}, "ip"))

    def test_health_still_public(self):
        g = self.SecurityGate(api_keys={"k1"})
        self.assertIsNone(g.authorize("GET", "/health", {}, "ip"))


# ─────────────────────────────────────────────────────────────────────────────
# 6. End-to-end: session identity drives Phase 10C permissions
# ─────────────────────────────────────────────────────────────────────────────
class TestSessionPermissions(_TempUsers):
    def test_non_owner_blocked_and_allowed(self):
        self._make("Sunita", "sunita", "photo123", "Photo Staff")
        store = SessionStore()
        _, pl = auth.handle_login(_b({"username": "sunita", "password": "photo123"}), store)
        acting = store.username_for(pl["token"])
        self.assertEqual(acting, "sunita")

        # blocked on an Owner-only endpoint (excel.rollback)
        denial = permissions.enforce("POST", "/admin/owner/rollback", acting, None, b"{}")
        self.assertIsNotNone(denial)
        self.assertEqual(denial[0], 403)

        # allowed on their own surface (media.view)
        ok = permissions.enforce("GET", "/admin/media/vehicles", acting, None, b"")
        self.assertIsNone(ok)

    def test_owner_full_access(self):
        store = SessionStore()
        _, pl = auth.handle_login(_b({"username": "owner", "password": "owner123"}), store)
        acting = store.username_for(pl["token"])
        # Owner passes every admin endpoint
        for path in ("/admin/owner/rollback", "/admin/users/list",
                     "/admin/media/vehicles", "/admin/inventory/update_car"):
            self.assertIsNone(
                permissions.enforce("POST", path, acting, None, b"{}"),
                f"Owner should be allowed on {path}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
