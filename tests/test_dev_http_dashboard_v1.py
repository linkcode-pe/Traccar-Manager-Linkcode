import ast
import json
import socket
import threading
import time
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from api.dev_fixture_sources_v1 import (
    DEVELOPMENT_ONLY, FIXTURE_DASHBOARD_PROVIDER_ID, FixtureDashboardDataSource,
    FixtureMetricsSource, FixtureStatusSource,
)
from api.dev_http_dashboard_v1 import (
    DASHBOARD_STATUS_PATH, DevelopmentSessionVerifier, FixtureServerRoleResolver,
    LOOPBACK_HOST, build_server,
)
from api.identity_contract_v1 import VerifiedIdentity
from api.read_only_dashboard_v1 import ProviderTimeout
from api.web_session_identity_v1 import WebSessionEvidence, WebSessionState
from web.adapters.dashboard_client_v1 import build_dashboard_request, decode_dashboard_response, to_existing_dashboard_model
from worker.audit.ledger import AuditLedger, LedgerError

IDENTITY = "fixture-dashboard-reader"


def evidence(state=WebSessionState.AUTHENTICATED, identity=None, expiry=None):
    expiry = expiry or (datetime.now(timezone.utc) + timedelta(minutes=3)).isoformat(timespec="seconds").replace("+00:00", "Z")
    return WebSessionEvidence(state, identity or VerifiedIdentity("panel-web", IDENTITY), expiry, "fixture-assertion-0001")


def request(server, *, params=None, method="GET", headers=None, data=None, path=None, raw_query=None):
    if raw_query is None:
        params = params or build_dashboard_request("http-test-" + str(time.monotonic_ns()))
        query = urllib.parse.urlencode(params)
    else:
        query = raw_query
    target = (path or DASHBOARD_STATUS_PATH) + ("?" + query if query else "")
    request_headers = {"Host": "127.0.0.1"}
    if headers:
        request_headers.update(headers)
    if data is not None:
        request_headers["Content-Length"] = str(len(data))
    raw = (method + " " + target + " HTTP/1.0\r\n" + "".join(f"{k}: {v}\r\n" for k, v in request_headers.items()) + "\r\n").encode() + (data or b"")
    client, server_end = socket.socketpair()
    def serve_request():
        try:
            server.RequestHandlerClass(server_end, ("127.0.0.1", 41000), server)
        finally:
            server_end.close()
    handler = threading.Thread(target=serve_request, daemon=True)
    handler.start()
    client.sendall(raw); client.shutdown(socket.SHUT_WR)
    chunks = []
    while True:
        part = client.recv(8192)
        if not part: break
        chunks.append(part)
    client.close(); handler.join(timeout=3)
    if handler.is_alive(): raise AssertionError("temporary request handler did not finish")
    response = b"".join(chunks); head, sep, body = response.partition(b"\r\n\r\n")
    if not sep: raise AssertionError("malformed HTTP response")
    lines = head.split(b"\r\n"); status = int(lines[0].split()[1]); response_headers = {}
    for line in lines[1:]:
        if b":" in line:
            key, value = line.split(b":", 1); response_headers[key.decode().strip()] = value.decode().strip()
    return status, response_headers, body


class DevHTTPDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.ledger = AuditLedger(Path(self.temp.name) / "audit.jsonl")
        self.source = FixtureDashboardDataSource()
        self.verifier = DevelopmentSessionVerifier(evidence())
        self.server = build_server(0, data_source=self.source, ledger=self.ledger, identity_verifier=self.verifier)
        self.addCleanup(self.close)

    def close(self):
        if getattr(self, "server", None) is not None:
            self.server.server_close()
            self.assertEqual(self.server.fileno(), -1)
            self.server = None
        self.temp.cleanup()

    def send(self, **kwargs):
        # Dispatcher correctly refuses uid 0; tests exercise only a non-root fixture context.
        with patch("worker.dispatcher.os.geteuid", return_value=1000):
            return request(self.server, **kwargs)

    def records(self):
        return [json.loads(line) for line in self.ledger.path.read_text(encoding="utf-8").splitlines()]

    def test_server_is_ipv4_loopback_only_and_closed_in_teardown(self):
        self.assertEqual(self.server.server_address[0], LOOPBACK_HOST)
        self.assertEqual(self.server.address_family, socket.AF_INET)
        self.assertNotEqual(self.server.server_address[0], "0.0.0.0")
        self.assertGreaterEqual(self.server.fileno(), 0)

    def test_valid_fixture_flow_returns_dto_and_adapter_model(self):
        rid = "http-valid-001"
        status, headers, body = self.send(params={"request_id": rid})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        dto = decode_dashboard_response(body.decode("utf-8"))
        model = to_existing_dashboard_model(dto)
        self.assertEqual(dto.request_id, rid)
        self.assertEqual(model["traccar"]["status_label"], "Activo")
        self.assertEqual(model["server"]["cpu_percent"]["value"], 13.5)
        self.assertIs(type(self.source), FixtureDashboardDataSource)

    def test_forged_identity_role_user_and_token_headers_are_ignored(self):
        status, _, body = self.send(params={"request_id": "http-forged-header"}, headers={
            "X-Development-Identity": "attacker", "X-Development-Role": "admin",
            "X-User": "other", "X-Role": "dashboard.read", "Authorization": "Bearer fake",
            "Cookie": "session=not-a-session",
        })
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["request_id"], "http-forged-header")
        self.assertEqual(self.verifier.verify().identity.subject_id, IDENTITY)

    def test_absent_invalid_and_expired_session_evidence_returns_401(self):
        cases = [evidence(WebSessionState.ABSENT, identity=None),
                 evidence(WebSessionState.INVALID),
                 evidence(WebSessionState.EXPIRED),
                 evidence(expiry=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"))]
        for index, item in enumerate(cases):
            with self.subTest(index=index):
                self.verifier._evidence = item
                status, _, body = self.send(params={"request_id": f"http-unauth-{index}"})
                self.assertEqual(status, 401)
                self.assertEqual(json.loads(body), {"error": {"code": "API_UNAUTHORIZED"}})
        self.assertEqual(self.source.metrics_source.calls, 0)

    def test_insufficient_server_resolved_role_returns_403_even_with_forged_role_header(self):
        self.verifier._evidence = evidence(identity=VerifiedIdentity("panel-web", "fixture-no-role"))
        status, _, body = self.send(params={"request_id": "http-no-role"}, headers={"X-Development-Role": "dashboard.read"})
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"]["code"], "API_FORBIDDEN")
        self.assertEqual(self.source.metrics_source.calls, 0)

    def test_only_fixed_route_and_request_id_are_accepted(self):
        status, _, body = self.send(params={"request_id": "http-route"}, path="/api/v1/admin/execute")
        self.assertEqual(status, 404); self.assertEqual(json.loads(body)["error"]["code"], "API_INVALID_REQUEST")
        for query in ("request_id=a&request_id=b", "request_id=a&provider=x", "service=traccar"):
            status, _, body = self.send(raw_query=query)
            self.assertEqual(status, 400); self.assertEqual(json.loads(body)["error"]["code"], "API_INVALID_REQUEST")
        self.assertEqual(self.source.metrics_source.calls, 0)

    def test_allowlisted_fixture_only_and_pending_data_are_preserved(self):
        self.assertTrue(DEVELOPMENT_ONLY)
        self.assertEqual(self.source.provider_id, FIXTURE_DASHBOARD_PROVIDER_ID)
        self.assertIs(type(self.source.metrics_source), FixtureMetricsSource)
        self.assertIs(type(self.source.status_source), FixtureStatusSource)
        dto = decode_dashboard_response(self.send(params={"request_id": "http-pending"})[2].decode())
        model = to_existing_dashboard_model(dto)
        self.assertEqual(model["devices"]["total"]["availability"], "PENDING_PROVIDER")
        self.assertEqual(model["positions"]["rows"]["availability"], "PENDING_PROVIDER")
        self.assertEqual(model["retention"]["logs_30d"]["availability"], "PENDING_PROVIDER")

    def test_prepare_failure_blocks_fixture_provider(self):
        with patch.object(self.ledger, "prepare_execution", side_effect=LedgerError("E700_AUDIT_UNAVAILABLE")):
            status, _, body = self.send(params={"request_id": "http-prepare-fail"})
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)["error"]["code"], "API_AUDIT_UNAVAILABLE")
        self.assertEqual(self.source.metrics_source.calls, 0)

    def test_finalization_failure_withholds_dto(self):
        original = self.ledger.append
        def fail_final(event):
            if event.event_type == "AUDIT_FINALIZED": raise LedgerError("E700_AUDIT_UNAVAILABLE")
            return original(event)
        with patch.object(self.ledger, "append", side_effect=fail_final):
            status, _, body = self.send(params={"request_id": "http-final-fail"})
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body), {"error": {"code": "API_AUDIT_UNAVAILABLE"}})
        self.assertNotIn("schema_version", json.loads(body))
        self.assertEqual(self.source.metrics_source.calls, 1)

    def test_durable_audit_order_and_privacy(self):
        rid = "http-audit-sequence"
        self.assertEqual(self.send(params={"request_id": rid})[0], 200)
        rows = [row for row in self.records() if row["request_id"] == rid]
        self.assertEqual([row["event_type"] for row in rows], [
            "REQUEST_RECEIVED", "VALIDATION_PASSED", "PREVIEW_STARTED", "PREVIEW_COMPLETED",
            "AUTHORIZATION_REQUESTED", "AUTHORIZATION_GRANTED", "EXECUTION_STARTED",
            "EXECUTION_COMPLETED", "AUDIT_FINALIZED",
        ])
        self.assertTrue(all(row.get("target") == {"type": "dashboard", "id": "snapshot"} for row in rows))
        self.assertTrue(self.ledger.verify().valid)
        ledger_json = json.dumps(rows).lower()
        for forbidden in ("latitude", "longitude", "uniqueid", "address", "password", "cookie", "token", "response", "sql"):
            self.assertNotIn(forbidden, ledger_json)

    def test_unallowlisted_provider_is_rejected_without_invocation(self):
        class BadSource:
            provider_id = "unapproved.fixture.provider"
            calls = 0
            def read_dashboard(self, request): self.calls += 1; raise AssertionError("must not run")
        original = self.server._development_api._data_source
        source = BadSource(); self.server._development_api._data_source = source
        try:
            status, _, body = self.send(params={"request_id": "http-unapproved"})
        finally:
            self.server._development_api._data_source = original
        self.assertEqual(status, 403); self.assertEqual(json.loads(body)["error"]["code"], "API_SOURCE_NOT_ALLOWED")
        self.assertEqual(source.calls, 0)

    def test_provider_failure_is_sanitized(self):
        class FailedSource:
            provider_id = FIXTURE_DASHBOARD_PROVIDER_ID
            calls = 0
            def read_dashboard(self, request): self.calls += 1; raise ProviderTimeout("dsn secret stack")
        old = self.server._development_api._data_source; source = FailedSource()
        self.server._development_api._data_source = source
        try: status, _, body = self.send(params={"request_id": "http-provider-timeout"})
        finally: self.server._development_api._data_source = old
        self.assertEqual(status, 504); self.assertEqual(json.loads(body), {"error": {"code": "API_TIMEOUT"}})
        self.assertNotIn("secret", body.decode().lower()); self.assertEqual(source.calls, 1)

    def test_methods_body_and_sensitive_dto_fields_are_rejected_or_absent(self):
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE", "CONNECT"):
            status, headers, body = self.send(method=method, params={"request_id": "http-method-" + method})
            self.assertEqual(status, 405); self.assertEqual(headers.get("Allow"), "GET")
            if method != "HEAD": self.assertEqual(json.loads(body)["error"]["code"], "API_INVALID_REQUEST")
        status, _, body = self.send(params={"request_id": "http-body"}, data=b"body")
        self.assertEqual(status, 400)
        status, _, body = self.send(params={"request_id": "http-private"})
        self.assertEqual(status, 200)
        for secret in ("password", "secret", "credential", "latitude", "longitude", "uniqueid", "address", "sql"):
            self.assertNotIn(secret, body.decode().lower())

    def test_no_php_session_secret_file_or_process_integration(self):
        source = Path("api/dev_http_dashboard_v1.py").read_text(encoding="utf-8")
        self.assertNotIn("/etc/traccar-panel", source)
        self.assertNotIn("serve_forever()", "")
        tree = ast.parse(source)
        imports = {a.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for a in node.names}
        self.assertFalse(imports & {"subprocess", "sqlite3", "socketserver"})


if __name__ == "__main__": unittest.main()
