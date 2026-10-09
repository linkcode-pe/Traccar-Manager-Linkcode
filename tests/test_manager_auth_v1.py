"""Temporary-fixture tests for Manager authentication and HTTP session routes."""
from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch

from api.audit_bridge_contract_v1 import AUDIT_BRIDGE_PLAN
from manager.auth.audit import write_auth_audit
from manager.auth.auth_store import (
    AuthStore, AuthStoreError, AuthenticatedUser, SERVICE_GROUP, derive_password_hash,
    make_password_record,
)
from manager.auth.session_store import SessionStore
from manager.web_app import ManagerHTTPServer

_TEST_PASSWORD = "fixture-only-never-installed"
_TEST_USERNAME = "fixture-admin"


def _stat_with_owner(info, uid: int, gid: int):
    return os.stat_result((info.st_mode, info.st_ino, info.st_dev, info.st_nlink,
                           uid, gid, info.st_size, info.st_atime, info.st_mtime,
                           info.st_ctime))


@contextmanager
def root_owned_store_fixture(path: Path):
    # Synthesize root ownership only in stat results for this temporary fixture.
    import grp

    path = Path(path)
    parent = path.parent
    service_gid = grp.getgrnam(SERVICE_GROUP).gr_gid
    real_file = os.stat(path, follow_symlinks=False)
    original_lstat = Path.lstat
    original_fstat = os.fstat
    file_inode = (real_file.st_dev, real_file.st_ino)

    if real_file.st_uid == 0:
        raise AssertionError("temporary auth fixture must not be actually root-owned")

    def fixture_lstat(candidate):
        info = original_lstat(candidate)
        if candidate == parent:
            return _stat_with_owner(info, 0, service_gid)
        return info

    def fixture_fstat(fd):
        info = original_fstat(fd)
        if (info.st_dev, info.st_ino) == file_inode:
            return _stat_with_owner(info, 0, service_gid)
        return info

    with patch.object(Path, "lstat", new=fixture_lstat), \
            patch.object(os, "fstat", new=fixture_fstat):
        yield


def make_protected_store(root: str) -> Path:
    directory = Path(root) / "auth-data"
    directory.mkdir(mode=0o750)
    os.chmod(directory, 0o750)
    record = {
        "username": _TEST_USERNAME,
        "subject_id": "1234567890abcdef1234567890abcdef",
        **make_password_record(_TEST_PASSWORD),
        "roles": ["dashboard.read"],
        "enabled": True,
    }
    path = directory / "auth-store.json"
    path.write_text(json.dumps({"version": 1, "users": [record]}, separators=(",", ":")) + "\n")
    os.chmod(path, 0o640)
    return path

class AuthStoreTests(unittest.TestCase):
    def test_pbkdf2_record_verifies_and_contains_no_plaintext(self):
        with tempfile.TemporaryDirectory() as root:
            path = make_protected_store(root)
            raw = path.read_bytes()
            self.assertNotIn(_TEST_PASSWORD.encode(), raw)
            with root_owned_store_fixture(path):
                user = AuthStore(path).authenticate(_TEST_USERNAME, _TEST_PASSWORD)
                self.assertIsNotNone(user)
                self.assertEqual(user.roles, ("dashboard.read",))
                self.assertIsNone(AuthStore(path).authenticate(_TEST_USERNAME, "wrong-fixture-value"))

    def test_missing_auth_store_fails_closed_without_account(self):
        with tempfile.TemporaryDirectory() as root:
            store = AuthStore(Path(root) / "missing" / "auth-store.json")
            self.assertIsNone(store.authenticate(_TEST_USERNAME, _TEST_PASSWORD))

    def test_unsafe_auth_store_mode_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path = make_protected_store(root)
            os.chmod(path, 0o644)
            with root_owned_store_fixture(path):
                with self.assertRaises(AuthStoreError):
                    AuthStore(path).authenticate(_TEST_USERNAME, _TEST_PASSWORD)

    def test_disabled_account_and_roles_are_server_owned(self):
        with tempfile.TemporaryDirectory() as root:
            path = make_protected_store(root)
            payload = json.loads(path.read_text())
            payload["users"][0]["enabled"] = False
            path.write_text(json.dumps(payload))
            os.chmod(path, 0o640)
            with root_owned_store_fixture(path):
                self.assertIsNone(AuthStore(path).authenticate(_TEST_USERNAME, _TEST_PASSWORD))


class ProvisionerTests(unittest.TestCase):
    def test_provisioner_refuses_nonroot_before_prompt_or_filesystem_change(self):
        from manager.auth import provision_admin
        capture = io.StringIO()
        with patch("manager.auth.provision_admin.os.geteuid", return_value=996), \
             patch("builtins.input") as prompt, patch("sys.stderr", capture):
            self.assertEqual(provision_admin.main(), 1)
        prompt.assert_not_called()
        self.assertIn("STAGE=root_check", capture.getvalue())

    @unittest.skipUnless(os.geteuid() == 0, "root required for ownership test")
    def test_new_auth_directory_is_created_with_service_group_and_restrictive_mode(self):
        import grp
        from pathlib import Path
        from manager.auth.provision_admin import _prepare_directory
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "auth"
            gid = grp.getgrnam("traccar-manager-web").gr_gid
            _prepare_directory(directory, gid)
            info = directory.stat()
            self.assertEqual(info.st_uid, 0)
            self.assertEqual(info.st_gid, gid)
            self.assertEqual(stat.S_IMODE(info.st_mode), 0o750)


class SessionStoreTests(unittest.TestCase):
    def test_opaque_session_rbac_and_revocation(self):
        store = SessionStore()
        user = AuthenticatedUser("a" * 32, "fixture-user", ("dashboard.read",))
        token, principal = store.create(user)
        self.assertNotEqual(token, principal.subject_id)
        self.assertTrue(store.has_role(token, "dashboard.read"))
        self.assertFalse(store.has_role(token, "manager.admin"))
        self.assertEqual(store.revoke(token), True)
        self.assertIsNone(store.get(token))

    def test_idle_expiry_is_fail_closed(self):
        now = [100.0]
        store = SessionStore(idle_timeout=10, absolute_timeout=20, clock=lambda: now[0])
        token, _principal = store.create(AuthenticatedUser("b" * 32, "fixture", ("dashboard.read",)))
        now[0] += 11
        self.assertIsNone(store.get(token))
        self.assertEqual(len(store), 0)


class ManagerAuthHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.audit_events = []
        self.auth_store_path = make_protected_store(self.tmp.name)
        self._auth_owner_fixture = root_owned_store_fixture(self.auth_store_path)
        self._auth_owner_fixture.__enter__()
        self.auth_store = AuthStore(self.auth_store_path)
        self.sessions = SessionStore()
        self.server = ManagerHTTPServer(
            0, auth_store=self.auth_store, session_store=self.sessions,
            audit_writer=lambda *event: self.audit_events.append(event) or True,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)

    def tearDown(self):
        self.connection.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self._auth_owner_fixture.__exit__(None, None, None)
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        self.connection.request(method, path, body=body, headers=headers or {})
        response = self.connection.getresponse()
        payload = response.read()
        return response.status, dict(response.getheaders()), payload

    def test_me_without_session_is_401(self):
        status, _headers, _body = self.request("GET", "/api/auth/me")
        self.assertEqual(status, 401)

    def test_login_me_logout_cycle_and_cookie_flags(self):
        body = json.dumps({"username": _TEST_USERNAME, "password": _TEST_PASSWORD})
        status, headers, payload = self.request(
            "POST", "/api/auth/login", body,
            {"Content-Type": "application/json", "Content-Length": str(len(body))},
        )
        self.assertEqual(status, 200)
        login = json.loads(payload)
        self.assertEqual(login["user"]["roles"], ["dashboard.read"])
        cookie_header = headers["Set-Cookie"]
        self.assertIn("Secure", cookie_header)
        self.assertIn("HttpOnly", cookie_header)
        self.assertIn("SameSite=Strict", cookie_header)
        self.assertIn("Path=/manager/", cookie_header)
        cookie = cookie_header.split(";", 1)[0]
        token = cookie.split("=", 1)[1]
        self.assertNotIn(token, payload.decode())

        status, _headers, payload = self.request("GET", "/api/auth/me", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(payload)["authenticated"])

        status, headers, _payload = self.request("POST", "/api/auth/logout", headers={"Cookie": cookie})
        self.assertEqual(status, 204)
        self.assertIn("Max-Age=0", headers["Set-Cookie"])
        status, _headers, _payload = self.request("GET", "/api/auth/me", headers={"Cookie": cookie})
        self.assertEqual(status, 401)

        encoded_audit = json.dumps(self.audit_events).lower()
        for forbidden in (_TEST_PASSWORD.lower(), token.lower(), _TEST_USERNAME.lower(), "cookie"):
            self.assertNotIn(forbidden, encoded_audit)

    def test_client_cannot_supply_roles(self):
        body = json.dumps({"username": _TEST_USERNAME, "password": _TEST_PASSWORD,
                           "roles": ["manager.admin"]})
        status, _headers, _payload = self.request(
            "POST", "/api/auth/login", body,
            {"Content-Type": "application/json", "Content-Length": str(len(body))},
        )
        self.assertEqual(status, 400)
        self.assertEqual(len(self.sessions), 0)

    def test_audit_failure_prevents_session_issue(self):
        self.server.audit_writer = lambda *_event: False
        body = json.dumps({"username": _TEST_USERNAME, "password": _TEST_PASSWORD})
        status, headers, _payload = self.request(
            "POST", "/api/auth/login", body,
            {"Content-Type": "application/json", "Content-Length": str(len(body))},
        )
        self.assertEqual(status, 503)
        self.assertNotIn("Set-Cookie", headers)
        self.assertEqual(len(self.sessions), 0)

    def test_post_route_methods_and_health_remain_scoped(self):
        status, headers, _body = self.request("GET", "/api/auth/login")
        self.assertEqual(status, 405)
        self.assertEqual(headers.get("Allow"), "POST")
        status, _headers, body = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "ok")


class AuditContractTests(unittest.TestCase):
    def test_dispatcher_facts_are_reconciled_and_http_binding_uses_pending_provider(self):
        from worker.dispatcher import allowed_operations, _OPERATIONS
        self.assertIn("dashboard.snapshot.read.v1", allowed_operations())
        spec = _OPERATIONS["dashboard.snapshot.read.v1"]
        self.assertEqual(dict(spec.target), {"type": "dashboard", "id": "snapshot"})
        self.assertEqual(spec.required_role, "dashboard.read")
        self.assertEqual(spec.allowed_payload_keys, frozenset())
        self.assertTrue(AUDIT_BRIDGE_PLAN.dispatcher_operation_allowlisted)
        self.assertEqual((AUDIT_BRIDGE_PLAN.target_type, AUDIT_BRIDGE_PLAN.target_id), ("dashboard", "snapshot"))
        self.assertEqual(AUDIT_BRIDGE_PLAN.required_role, "dashboard.read")
        self.assertEqual(AUDIT_BRIDGE_PLAN.allowed_payload_keys, ())
        self.assertTrue(AUDIT_BRIDGE_PLAN.http_data_binding_implemented)
        self.assertFalse(AUDIT_BRIDGE_PLAN.dashboard_production_provider_connected)
        self.assertFalse(AUDIT_BRIDGE_PLAN.audit_ledger_survives_restart)

    def test_systemd_captured_auth_audit_is_sanitized(self):
        capture = io.StringIO()
        with patch("manager.auth.audit.sys.stderr", capture):
            self.assertTrue(write_auth_audit("AUTH_LOGIN", "DENIED", "INVALID_CREDENTIALS"))
        row = json.loads(capture.getvalue())
        self.assertEqual(row["event"], "AUTH_LOGIN")
        self.assertEqual(row["reason_code"], "INVALID_CREDENTIALS")
        encoded = capture.getvalue().lower()
        for forbidden in ("password", "token", "cookie", "secret", _TEST_USERNAME):
            self.assertNotIn(forbidden, encoded)


if __name__ == "__main__":
    unittest.main()
