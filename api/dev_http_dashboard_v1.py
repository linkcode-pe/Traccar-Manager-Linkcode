"""DEVELOPMENT_ONLY loopback endpoint using server-side fixture identity.

Never accepts identity, user, roles, or permissions from HTTP fields. The
session verifier and provider are injected server-side fixtures in this phase;
there is no PHP session integration or production datasource.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
import ipaddress
import json
import os
from pathlib import Path
import socket
import tempfile
from urllib.parse import parse_qsl, urlsplit

from api.dev_fixture_sources_v1 import (
    DEVELOPMENT_ONLY, FIXTURE_DASHBOARD_PROVIDER_ID, FixtureDashboardDataSource,
)
from api.identity_contract_v1 import DASHBOARD_OPERATION, DASHBOARD_ROLE, VerifiedIdentity
from api.read_only_dashboard_v1 import (
    ActorContext, DashboardAPIError, ReadOnlyDashboardProvider, snapshot_to_json,
)
from api.web_session_identity_v1 import (
    WebSessionEvidence, WebSessionState, actor_from_verified_web_session,
)
from api.read_only_dashboard_v1 import DispatcherAuditGateway
from worker.audit.ledger import AuditLedger

LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DASHBOARD_STATUS_PATH = "/api/v1/dashboard/status"
TRUSTED_SESSION_ISSUERS = frozenset({"panel-web"})


class DevelopmentSessionVerifier:
    """A server-owned fixture, independent of all request headers and fields."""
    development_only = True

    def __init__(self, evidence: WebSessionEvidence | None = None):
        self._evidence = evidence if evidence is not None else self._default_evidence()

    @staticmethod
    def _default_evidence() -> WebSessionEvidence:
        now = datetime.now(timezone.utc)
        expiry = (now + timedelta(minutes=5)).isoformat(timespec="seconds").replace("+00:00", "Z")
        return WebSessionEvidence(
            WebSessionState.AUTHENTICATED,
            VerifiedIdentity("panel-web", "fixture-dashboard-reader"),
            expiry,
            "dev-session-assertion-0001",
        )

    def verify(self) -> WebSessionEvidence | None:
        """Return fixed fixture evidence; this method receives no client data."""
        return self._evidence


class FixtureServerRoleResolver:
    """Server-owned role mapping; role and subject never come from the request."""
    development_only = True

    def roles_for(self, identity: VerifiedIdentity) -> frozenset[str]:
        if identity.issuer != "panel-web":
            return frozenset()
        if identity.subject_id == "fixture-dashboard-reader":
            return frozenset({DASHBOARD_ROLE})
        return frozenset()


class FixtureReadAuthorizer:
    """Defense-in-depth policy; Dispatcher repeats the required-role check."""
    development_only = True

    def allows(self, actor: ActorContext, operation: str) -> bool:
        return operation == DASHBOARD_OPERATION and DASHBOARD_ROLE in actor.roles


class LoopbackHTTPServer(HTTPServer):
    address_family = socket.AF_INET
    allow_reuse_address = False
    request_queue_size = 8

    def __init__(self, server_address, RequestHandlerClass):
        host, _port = server_address
        if host != LOOPBACK_HOST:
            raise ValueError("development API must bind to IPv4 loopback")
        super().__init__((LOOPBACK_HOST, _port), RequestHandlerClass, bind_and_activate=True)
        self.daemon_threads = True
        if self.server_address[0] != LOOPBACK_HOST:
            super().server_close()
            raise RuntimeError("loopback bind verification failed")

    def server_close(self):
        try:
            super().server_close()
        finally:
            temporary = getattr(self, "_development_temporary_directory", None)
            if temporary is not None:
                temporary.cleanup()
                self._development_temporary_directory = None


class _UseDefault:
    pass


_USE_DEFAULT = _UseDefault()


def _handler_for(api: ReadOnlyDashboardProvider, identity_verifier, role_resolver):
    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "TraccarManagerDevelopmentAPI/1"
        sys_version = ""
        protocol_version = "HTTP/1.0"

        def log_message(self, _format, *args):
            # Never log query, identity, header, or provider data.
            return

        def _send_json(self, status: HTTPStatus, payload: dict, *, head_only: bool = False):
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
            self.send_response(int(status))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if not head_only:
                self.wfile.write(body)

        def _error(self, code: str, status: HTTPStatus | None = None, *, head_only: bool = False):
            statuses = {
                "API_INVALID_REQUEST": HTTPStatus.BAD_REQUEST,
                "API_UNAUTHORIZED": HTTPStatus.UNAUTHORIZED,
                "API_FORBIDDEN": HTTPStatus.FORBIDDEN,
                "API_SOURCE_NOT_ALLOWED": HTTPStatus.FORBIDDEN,
                "API_PROVIDER_UNAVAILABLE": HTTPStatus.SERVICE_UNAVAILABLE,
                "API_TIMEOUT": HTTPStatus.GATEWAY_TIMEOUT,
                "API_AUDIT_UNAVAILABLE": HTTPStatus.SERVICE_UNAVAILABLE,
                "API_DATA_UNAVAILABLE": HTTPStatus.SERVICE_UNAVAILABLE,
                "API_INTERNAL_ERROR": HTTPStatus.INTERNAL_SERVER_ERROR,
            }
            safe_code = code if code in statuses else "API_INTERNAL_ERROR"
            self._send_json(status or statuses[safe_code], {"error": {"code": safe_code}}, head_only=head_only)

        def _method_not_allowed(self, *, head_only: bool = False):
            self.send_response(int(HTTPStatus.METHOD_NOT_ALLOWED))
            self.send_header("Allow", "GET")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            body = b'{"error":{"code":"API_INVALID_REQUEST"}}'
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if not head_only:
                self.wfile.write(body)

        def _actor(self) -> ActorContext:
            # Crucially, verifier.verify() has no access to HTTP headers or params.
            evidence = identity_verifier.verify()
            return actor_from_verified_web_session(
                evidence, role_resolver, trusted_issuers=TRUSTED_SESSION_ISSUERS,
                operation=DASHBOARD_OPERATION,
            )

        def do_GET(self):
            try:
                peer = ipaddress.ip_address(self.client_address[0])
                if not peer.is_loopback:
                    self._error("API_FORBIDDEN")
                    return
                if len(self.path) > 1024:
                    self._error("API_INVALID_REQUEST")
                    return
                parsed = urlsplit(self.path)
                if parsed.path != DASHBOARD_STATUS_PATH:
                    self._error("API_INVALID_REQUEST", HTTPStatus.NOT_FOUND)
                    return
                if self.headers.get("Transfer-Encoding") is not None:
                    self._error("API_INVALID_REQUEST")
                    return
                content_lengths = self.headers.get_all("Content-Length", [])
                if len(content_lengths) > 1:
                    self._error("API_INVALID_REQUEST")
                    return
                if content_lengths:
                    try:
                        if int(content_lengths[0], 10) != 0:
                            self._error("API_INVALID_REQUEST")
                            return
                    except ValueError:
                        self._error("API_INVALID_REQUEST")
                        return
                if len(parsed.query) > 512:
                    self._error("API_INVALID_REQUEST")
                    return
                try:
                    pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=2)
                except ValueError:
                    self._error("API_INVALID_REQUEST")
                    return
                if len(pairs) != 1 or pairs[0][0] != "request_id":
                    self._error("API_INVALID_REQUEST")
                    return
                request = {"request_id": pairs[0][1]}
                try:
                    actor = self._actor()
                    result = api.read(request, actor)
                except DashboardAPIError as exc:
                    self._error(exc.code)
                    return
                except Exception:
                    self._error("API_INTERNAL_ERROR")
                    return
                body = snapshot_to_json(result).encode("utf-8")
                self.send_response(int(HTTPStatus.OK))
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)
            except Exception:
                self._error("API_INTERNAL_ERROR")

        def do_HEAD(self): self._method_not_allowed(head_only=True)
        def do_POST(self): self._method_not_allowed()
        def do_PUT(self): self._method_not_allowed()
        def do_PATCH(self): self._method_not_allowed()
        def do_DELETE(self): self._method_not_allowed()
        def do_OPTIONS(self): self._method_not_allowed()
        def do_TRACE(self): self._method_not_allowed()
        def do_CONNECT(self): self._method_not_allowed()

    return DashboardHandler


def build_server(port: int = DEFAULT_PORT, *, data_source=_USE_DEFAULT, ledger=_USE_DEFAULT,
                 identity_verifier=_USE_DEFAULT, role_resolver=_USE_DEFAULT) -> LoopbackHTTPServer:
    """Build (but do not start) a DEVELOPMENT_ONLY loopback server."""
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("invalid local port")
    if data_source is _USE_DEFAULT:
        data_source = FixtureDashboardDataSource()
    if identity_verifier is _USE_DEFAULT:
        identity_verifier = DevelopmentSessionVerifier()
    if role_resolver is _USE_DEFAULT:
        role_resolver = FixtureServerRoleResolver()
    temporary = None
    if ledger is _USE_DEFAULT:
        temporary = tempfile.TemporaryDirectory(prefix="traccar-manager-dev-ledger-")
        ledger = AuditLedger(Path(temporary.name) / "audit.jsonl")
    api = ReadOnlyDashboardProvider(
        data_source, allowed_provider_ids=frozenset({FIXTURE_DASHBOARD_PROVIDER_ID}),
        authorizer=FixtureReadAuthorizer(), execution_gateway=DispatcherAuditGateway(ledger),
    )
    try:
        server = LoopbackHTTPServer((LOOPBACK_HOST, port), _handler_for(api, identity_verifier, role_resolver))
    except Exception:
        if temporary is not None:
            temporary.cleanup()
        raise
    server._development_temporary_directory = temporary
    server._development_api = api
    server._development_source = data_source
    server._development_ledger = ledger
    server._development_identity_verifier = identity_verifier
    server._development_role_resolver = role_resolver
    return server


def _port_number(value: str) -> int:
    try:
        port = int(value, 10)
    except ValueError:
        raise argparse.ArgumentTypeError("invalid port") from None
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be 1024..65535")
    return port


def main(argv=None) -> int:
    if os.environ.get("TRACCAR_MANAGER_DEV_API") != "1":
        raise SystemExit("DEVELOPMENT_ONLY: set TRACCAR_MANAGER_DEV_API=1 to opt in")
    parser = argparse.ArgumentParser(description="Traccar Manager DEVELOPMENT_ONLY fixture API")
    parser.add_argument("--port", type=_port_number, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    server = build_server(args.port)
    try:
        print(f"DEVELOPMENT_ONLY listening on http://{LOOPBACK_HOST}:{server.server_port}{DASHBOARD_STATUS_PATH}")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
