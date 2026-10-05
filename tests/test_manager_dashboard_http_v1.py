"""Authenticated HTTP binding tests; no production DB or provider is used."""
from __future__ import annotations

import http.client
import json
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from uuid import uuid4

from manager.auth.auth_store import AuthenticatedUser
from manager.auth.session_store import SessionStore
from manager.dashboard_http import ManagerDashboardAPI
from manager.web_app import ManagerHTTPServer
from worker.audit.ledger import AuditLedger


OBSERVED = "2026-10-04T09:00:00Z"
PROPERTIES = {
    "LoadState": "loaded", "ActiveState": "active", "SubState": "running",
    "UnitFileState": "enabled", "Result": "success",
}


def fixture_receipt(request_id, subject_id):
    return {
        "schema_version": 1, "protocol_version": 1, "request_id": request_id,
        "operation": "traccar.status.read", "ledger_operation": "traccar.status",
        "endpoint": "/api/dashboard/snapshot", "subject_id": subject_id,
        "role": "traccar.status.read", "phase": "AUDIT_FINALIZATION",
        "event_id": str(uuid4()), "ledger_sequence": 9,
        "previous_event_hash": "b" * 64, "event_hash": "c" * 64, "durable": True,
    }


class FixtureAuthStore:
    def authenticate(self, username, password):
        return None


class ReadOnlyFixtureLedger:
    read_only = True
    def __init__(self):
        self.receipt_checks = 0
    def verify_finalization_receipt(self, receipt, **kwargs):
        self.receipt_checks += 1
        return False
    def verify(self):
        return type("Integrity", (), {"valid": True, "event_count": 0})()


class DashboardHTTPBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.geteuid() == 0:
            raise RuntimeError("dashboard tests must not run as root")
        cls.audit_rows = []
        cls.audit_writer = lambda event, result, reason: (cls.audit_rows.append((event, result, reason)) or True)
        cls.worker_calls = []
        cls.ledger = ReadOnlyFixtureLedger()
        cls.sessions = SessionStore()
        cls.allowed_user = AuthenticatedUser("a" * 32, "fixture-viewer", ("dashboard.read",))
        cls.status_user = AuthenticatedUser("c" * 32, "fixture-status", ("dashboard.read", "traccar.status.read"))
        cls.wrong_role_user = AuthenticatedUser("b" * 32, "fixture-operator", ("traccar.status.read",))
        cls.allowed_token, _ = cls.sessions.create(cls.allowed_user)
        cls.status_token, _ = cls.sessions.create(cls.status_user)
        cls.wrong_role_token, _ = cls.sessions.create(cls.wrong_role_user)
        api = ManagerDashboardAPI(
            ledger=cls.ledger,
            worker_query=lambda *args: cls.worker_calls.append(args),
        )
        cls.server = ManagerHTTPServer(
            0, auth_store=FixtureAuthStore(), session_store=cls.sessions,
            audit_writer=cls.audit_writer, dashboard_api=api,
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def request(self, server, method, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        conn.request(method, path, headers=headers or {})
        response = conn.getresponse()
        body = response.read()
        result = (response.status, dict(response.getheaders()), body)
        conn.close()
        return result

    def test_anonymous_and_wrong_role_are_denied_before_worker_or_ledger(self):
        calls = len(self.worker_calls)
        checks = self.ledger.receipt_checks
        self.assertEqual(401, self.request(self.server, "GET", "/api/dashboard/snapshot?request_id=unauth-1")[0])
        status, _, _ = self.request(
            self.server, "GET", "/api/dashboard/snapshot?request_id=wrong-role-1",
            {"Cookie": "tm_session=" + self.wrong_role_token, "X-Role": "dashboard.read"},
        )
        self.assertEqual(403, status)
        self.assertEqual(calls, len(self.worker_calls))
        self.assertEqual(checks, self.ledger.receipt_checks)

    def test_dashboard_read_without_status_role_stays_pending_and_never_contacts_worker(self):
        cookie = {"Cookie": "tm_session=" + self.allowed_token}
        status, headers, body = self.request(
            self.server, "GET", "/api/dashboard/snapshot?request_id=dashboard-test-01", cookie,
        )
        self.assertEqual(200, status)
        self.assertEqual("no-store", headers.get("Cache-Control"))
        result = json.loads(body)
        self.assertEqual("dashboard-test-01", result["request_id"])
        self.assertTrue(all(
            result["general"]["traccar_service"][key]["availability"] == "PENDING_PROVIDER"
            for key in ("state", "substate", "load_state", "unit_file_state", "result")
        ))
        self.assertEqual([], self.worker_calls)
        self.assertEqual(0, self.ledger.receipt_checks)
        encoded = body.decode("utf-8").lower()
        for forbidden in ("uniqueid", "latitude", "longitude", "address", "password_hash", "tm_session"):
            self.assertNotIn(forbidden, encoded)
        self.assertIn(("AUTH_DASHBOARD_READ", "SUCCEEDED", "DISPATCHER_RECEIPT_VERIFIED"), self.audit_rows)

    def test_exact_route_query_and_header_spoofing_are_fail_closed(self):
        cookie = {"Cookie": "tm_session=" + self.allowed_token,
                  "X-Role": "traccar.status.read", "X-Manager-Subject": "forged"}
        self.assertEqual(400, self.request(self.server, "GET", "/api/dashboard/snapshot?request_id=a&request_id=b", cookie)[0])
        self.assertEqual(400, self.request(self.server, "GET", "/api/dashboard/snapshot?request_id=a&provider=anything", cookie)[0])
        self.assertEqual(404, self.request(self.server, "GET", "/api/dashboard/%2e%2e/auth/me", cookie)[0])
        self.assertEqual(404, self.request(self.server, "GET", "/api/dashboard/snapshot/../auth/me", cookie)[0])
        self.assertEqual(401, self.request(self.server, "GET", "/api/dashboard/snapshot?request_id=spoof-1",
                                           {"X-Role": "dashboard.read", "X-Manager-Subject": "a" * 32})[0])

    def test_post_dashboard_route_is_rejected(self):
        status, headers, _ = self.request(self.server, "POST", "/api/dashboard/snapshot")
        self.assertEqual(405, status)
        self.assertEqual("GET", headers.get("Allow"))

    def test_invalid_shared_audit_receipt_returns_no_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            # A read-only verifier with no shared ledger must fail closed after the Worker reply.
            ledger = AuditLedger(Path(temp) / "absent-parent" / "audit.jsonl", read_only=True,
                                 expected_file_mode=0o640, expected_directory_mode=0o750)
            def fake_query(request_id, subject_id, roles):
                return {"observed_at_utc": OBSERVED, "properties": PROPERTIES,
                        "audit_receipt": fixture_receipt(request_id, subject_id)}
            api = ManagerDashboardAPI(ledger=ledger, worker_query=fake_query)
            sessions = SessionStore()
            token, _ = sessions.create(self.status_user)
            server = ManagerHTTPServer(
                0, auth_store=FixtureAuthStore(), session_store=sessions,
                audit_writer=self.audit_writer, dashboard_api=api,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                status, _, body = self.request(
                    server, "GET", "/api/dashboard/snapshot?request_id=audit-fail-1",
                    {"Cookie": "tm_session=" + token},
                )
                self.assertEqual(503, status)
                self.assertNotIn("PENDING_PROVIDER", body.decode())
                self.assertNotIn("active", body.decode())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
