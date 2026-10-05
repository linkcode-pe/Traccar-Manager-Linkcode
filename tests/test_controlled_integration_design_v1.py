import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from api.dev_fixture_sources_v1 import FixtureDashboardDataSource
from api.dev_http_dashboard_v1 import (
    DevelopmentSessionVerifier, FixtureReadAuthorizer, FixtureServerRoleResolver,
)
from api.identity_contract_v1 import DASHBOARD_OPERATION, DASHBOARD_ROLE, VerifiedIdentity
from api.read_only_dashboard_v1 import (
    ActorContext, DashboardAPIError, DashboardRequestDTO, DispatcherAuditGateway,
    ReadOnlyDashboardProvider, snapshot_to_json,
)
from api.web_session_identity_v1 import (
    WebSessionEvidence, WebSessionState, actor_from_verified_web_session,
)
from web.adapters.dashboard_client_v1 import decode_dashboard_response, to_existing_dashboard_model
from worker.audit.ledger import AuditLedger, LedgerError

TRUSTED = frozenset({"panel-web"})


def evidence(state=WebSessionState.AUTHENTICATED, subject="fixture-dashboard-reader", expires=None):
    expires = expires or (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(timespec="seconds").replace("+00:00", "Z")
    identity = VerifiedIdentity("panel-web", subject) if subject is not None else None
    return WebSessionEvidence(state, identity, expires, "integration-fixture-assertion-01")


def actor_for(evidence_value, resolver=None):
    return actor_from_verified_web_session(
        evidence_value, resolver or FixtureServerRoleResolver(),
        trusted_issuers=TRUSTED, operation=DASHBOARD_OPERATION,
    )


class ControlledFixtureFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.ledger = AuditLedger(Path(self.temp.name) / "audit.jsonl")
        self.source = FixtureDashboardDataSource()
        self.api = ReadOnlyDashboardProvider(
            self.source,
            allowed_provider_ids=frozenset({self.source.provider_id}),
            authorizer=FixtureReadAuthorizer(),
            execution_gateway=DispatcherAuditGateway(self.ledger),
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_full_injected_identity_dispatcher_durable_audit_fixture_dto_view_model_flow(self):
        server_verifier = DevelopmentSessionVerifier(evidence())
        trusted_evidence = server_verifier.verify()
        actor = actor_for(trusted_evidence)
        self.assertEqual(actor.roles, frozenset({DASHBOARD_ROLE}))
        rid = "controlled-fixture-e2e-01"
        with patch("worker.dispatcher.os.geteuid", return_value=1000):
            snapshot = self.api.read(DashboardRequestDTO(rid), actor)
        encoded = snapshot_to_json(snapshot)
        decoded = decode_dashboard_response(encoded)
        model = to_existing_dashboard_model(decoded)
        self.assertEqual(decoded.request_id, rid)
        self.assertEqual(model["traccar"]["status_label"], "Activo")
        self.assertEqual(model["server"]["cpu_percent"]["value"], 13.5)
        self.assertTrue(self.ledger.verify().valid)
        rows = [json.loads(line) for line in self.ledger.path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["event_type"] for row in rows], [
            "REQUEST_RECEIVED", "VALIDATION_PASSED", "PREVIEW_STARTED", "PREVIEW_COMPLETED",
            "AUTHORIZATION_REQUESTED", "AUTHORIZATION_GRANTED", "EXECUTION_STARTED",
            "EXECUTION_COMPLETED", "AUDIT_FINALIZED",
        ])
        self.assertEqual(self.source.metrics_source.calls, 1)
        self.assertEqual(self.source.status_source.calls, 1)
        audit_text = json.dumps(rows).lower()
        for excluded in ("response", "latitude", "longitude", "uniqueid", "address", "cookie", "password", "token"):
            self.assertNotIn(excluded, audit_text)
        self.assertEqual(set(json.loads(encoded)), {
            "schema_version", "request_id", "general", "server", "devices", "positions", "retention",
        })

    def test_absent_invalid_expired_and_untrusted_evidence_fail_closed(self):
        now = datetime.now(timezone.utc)
        untrusted = WebSessionEvidence(WebSessionState.AUTHENTICATED,
            VerifiedIdentity("untrusted-issuer", "opaque-subject"),
            (now + timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
            "integration-fixture-assertion-02")
        cases = [None, evidence(WebSessionState.ABSENT), evidence(WebSessionState.INVALID),
                 evidence(expires=(now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")),
                 untrusted]
        for item in cases:
            with self.subTest(item=item), self.assertRaises(DashboardAPIError) as cm:
                actor_for(item)
            self.assertEqual(cm.exception.code, "API_UNAUTHORIZED")
        self.assertEqual(self.source.metrics_source.calls, 0)

    def test_server_role_resolver_denies_reader_without_dashboard_role(self):
        with self.assertRaises(DashboardAPIError) as cm:
            actor_for(evidence(subject="fixture-no-role"))
        self.assertEqual(cm.exception.code, "API_FORBIDDEN")
        self.assertEqual(self.source.metrics_source.calls, 0)

    def test_durable_prepare_failure_blocks_fixture_provider(self):
        actor = actor_for(evidence())
        with patch.object(self.ledger, "prepare_execution", side_effect=LedgerError("E700_AUDIT_UNAVAILABLE")), \
             patch("worker.dispatcher.os.geteuid", return_value=1000):
            with self.assertRaises(DashboardAPIError) as cm:
                self.api.read(DashboardRequestDTO("controlled-prepare-fail"), actor)
        self.assertEqual(cm.exception.code, "API_AUDIT_UNAVAILABLE")
        self.assertEqual(self.source.metrics_source.calls, 0)

    def test_finalization_failure_withholds_fixture_dto(self):
        actor = actor_for(evidence())
        original = self.ledger.append
        def fail_final(event):
            if event.event_type == "AUDIT_FINALIZED":
                raise LedgerError("E700_AUDIT_UNAVAILABLE")
            return original(event)
        with patch.object(self.ledger, "append", side_effect=fail_final), \
             patch("worker.dispatcher.os.geteuid", return_value=1000):
            with self.assertRaises(DashboardAPIError) as cm:
                self.api.read(DashboardRequestDTO("controlled-final-fail"), actor)
        self.assertEqual(cm.exception.code, "API_AUDIT_UNAVAILABLE")
        self.assertEqual(self.source.metrics_source.calls, 1)

    def test_request_has_only_request_id_and_snapshot_contains_no_position_details(self):
        from api.read_only_dashboard_v1 import dashboard_request_from_mapping
        for field in ("service", "command", "sql", "table", "provider", "path", "unit"):
            with self.subTest(field=field), self.assertRaises(DashboardAPIError) as cm:
                dashboard_request_from_mapping({"request_id": "no-selectors", field: "x"})
            self.assertEqual(cm.exception.code, "API_INVALID_REQUEST")
        self.assertEqual(self.source.metrics_source.calls, 0)


if __name__ == "__main__":
    unittest.main()
