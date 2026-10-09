import json
import unittest
from datetime import datetime, timezone

from api.read_only_dashboard_v1 import (
    ActorContext, AuditPhase, Availability, DashboardAPIError, DashboardRequestDTO,
    DashboardSnapshotDTO, DeviceSummaryDTO, GeneralStatusDTO, PositionSummaryDTO,
    ProviderTimeout, ReadOnlyDashboardProvider, RetentionStatusDTO,
    ServerMetricsDTO, TraccarServiceDTO, ValueDTO, pending_snapshot, snapshot_to_json,
)
from api.providers.system_metrics_v1 import SystemMetricsProvider, SystemMetricsSample
from api.providers.traccar_status_v1 import TraccarStatusProvider, TraccarStatusRecord
from web.adapters.dashboard_client_v1 import (
    build_dashboard_request, decode_dashboard_response, to_existing_dashboard_model,
)

STAMP="2026-10-01T10:03:00Z"
ACTOR=ActorContext("web-contract-test",frozenset({"dashboard.read"}))


class FixtureMetrics:
    provider_id="fixture.web.metrics.v1"
    def __init__(self):self.calls=0;self.timeout=None
    def read(self,timeout_seconds):
        self.calls+=1;self.timeout=timeout_seconds
        return SystemMetricsSample(12.5,8_000_000,3_000_000,100_000_000,40_000_000,STAMP)

class FixtureTraccar:
    provider_id="fixture.web.traccar.v1"
    def __init__(self):self.calls=0;self.timeout=None
    def read_status(self,timeout_seconds):
        self.calls+=1;self.timeout=timeout_seconds
        return TraccarStatusRecord("loaded","active","running","enabled","success",STAMP)

class FixtureAudit:
    def __init__(self,fail_phase=None):self.events=[];self.fail_phase=fail_phase
    def append(self,event):
        if event.phase is self.fail_phase:raise RuntimeError("audit private detail")
        self.events.append(event)

class FixturePolicy:
    def allows(self,actor,operation):return True

class PassGateway:
    def execute(self,request,actor,operation):return operation()

class FailGateway:
    def execute(self,request,actor,operation):raise DashboardAPIError("API_AUDIT_UNAVAILABLE")

class MockDashboardDataSource:
    provider_id="fixture.web.dashboard.v1"
    def __init__(self,audit,metrics=None,traccar=None,error=None):
        self.audit=audit;self.metrics=metrics or FixtureMetrics();self.traccar=traccar or FixtureTraccar();self.error=error;self.calls=0
    def read_dashboard(self,request):
        self.calls+=1
        if self.error:raise self.error
        g=TraccarStatusProvider(self.traccar,allowed_source_ids=frozenset({self.traccar.provider_id})).collect()
        m=SystemMetricsProvider(self.metrics,allowed_source_ids=frozenset({self.metrics.provider_id})).collect()
        p=ValueDTO.pending_provider()
        return DashboardSnapshotDTO(1,request.request_id,g,m,DeviceSummaryDTO(p,p,p),
                                    PositionSummaryDTO(p,p,p),RetentionStatusDTO(p,p,p,p))


def provider_for(source,audit,allowed=None):
    return ReadOnlyDashboardProvider(source,allowed_provider_ids=frozenset(allowed or {source.provider_id}),
        authorizer=FixturePolicy(),execution_gateway=PassGateway())


class WebAPIReadOnlyBridgeTests(unittest.TestCase):
    def test_web_request_is_valid_and_has_fixed_allowlisted_shape(self):
        request=build_dashboard_request("web-request-001")
        self.assertEqual(request,{"request_id":"web-request-001"})
        self.assertEqual(set(request),{"request_id"})

    def test_invalid_request_id_is_rejected(self):
        with self.assertRaises(DashboardAPIError) as cm:build_dashboard_request("bad id")
        self.assertEqual(cm.exception.code,"API_INVALID_REQUEST")

    def test_mock_contract_response_is_consumed_as_valid_dto(self):
        audit=FixtureAudit();source=MockDashboardDataSource(audit)
        api=provider_for(source,audit)
        request=build_dashboard_request("web-request-002")
        dto=api.read(request,ACTOR)
        json_response=snapshot_to_json(dto)
        decoded=decode_dashboard_response(json_response)
        model=to_existing_dashboard_model(decoded)
        self.assertIsInstance(decoded,DashboardSnapshotDTO)
        self.assertEqual(model["traccar"]["status_label"],"Activo")
        self.assertEqual(model["server"]["cpu_percent"]["value"],12.5)
        self.assertEqual(source.calls,1)

    def test_mapper_unit_path_uses_injected_pass_through_gateway(self):
        audit=FixtureAudit();source=MockDashboardDataSource(audit)
        snapshot=provider_for(source,audit).read(DashboardRequestDTO("web-audit-1"),ACTOR)
        self.assertEqual(snapshot.general.traccar_service.state.value,"active")
        self.assertEqual(source.calls,1)

    def test_provider_not_allowlisted_is_rejected_before_call(self):
        audit=FixtureAudit();source=MockDashboardDataSource(audit)
        api=provider_for(source,audit,allowed={"different.fixture"})
        with self.assertRaises(DashboardAPIError) as cm:api.read(DashboardRequestDTO("web-no-source"),ACTOR)
        self.assertEqual(cm.exception.code,"API_SOURCE_NOT_ALLOWED")
        self.assertEqual(source.calls,0)

    def test_missing_provider_is_pending_error_not_fake_snapshot(self):
        audit=FixtureAudit();api=ReadOnlyDashboardProvider(None,allowed_provider_ids=frozenset(),
            authorizer=FixturePolicy(),execution_gateway=PassGateway())
        with self.assertRaises(DashboardAPIError) as cm:api.read(DashboardRequestDTO("web-pending"),ACTOR)
        self.assertEqual(cm.exception.code,"API_PROVIDER_UNAVAILABLE")

    def test_unavailable_sections_remain_pending_not_zero(self):
        snapshot=pending_snapshot("web-empty")
        model=to_existing_dashboard_model(snapshot)
        self.assertEqual(model["database"]["availability"],"PENDING_PROVIDER")
        self.assertIsNone(model["devices"]["total"]["value"])
        self.assertIsNone(model["positions"]["current_count"]["value"])
        self.assertIsNone(model["retention"]["generic"]["cutoff_utc"]["value"])

    def test_injected_gateway_failure_blocks_provider_and_returns_no_dto(self):
        audit=FixtureAudit();source=MockDashboardDataSource(audit)
        api=ReadOnlyDashboardProvider(source,allowed_provider_ids=frozenset({source.provider_id}),
            authorizer=FixturePolicy(),execution_gateway=FailGateway())
        with self.assertRaises(DashboardAPIError) as cm:api.read(DashboardRequestDTO("web-audit-fail"),ACTOR)
        self.assertEqual(cm.exception.code,"API_AUDIT_UNAVAILABLE")
        self.assertEqual(source.calls,0)

    def test_provider_failure_returns_stable_code_without_details(self):
        audit=FixtureAudit();source=MockDashboardDataSource(audit,error=ProviderTimeout("dsn or secret detail"))
        with self.assertRaises(DashboardAPIError) as cm:provider_for(source,audit).read(DashboardRequestDTO("web-timeout"),ACTOR)
        self.assertEqual(cm.exception.code,"API_TIMEOUT")
        self.assertNotIn("secret",str(cm.exception))

    def test_response_has_no_credentials_or_secrets(self):
        audit=FixtureAudit();source=MockDashboardDataSource(audit)
        raw=snapshot_to_json(provider_for(source,audit).read(DashboardRequestDTO("web-clean"),ACTOR))
        for token in ("password","secret","credential","DSN","token="):
            self.assertNotIn(token.lower(),raw.lower())

    def test_positions_expose_only_approved_aggregates(self):
        audit=FixtureAudit();source=MockDashboardDataSource(audit)
        model=to_existing_dashboard_model(provider_for(source,audit).read(DashboardRequestDTO("web-pos"),ACTOR))
        self.assertEqual(model["positions"]["rows"]["availability"],"PENDING_PROVIDER")
        raw=json.dumps(model).lower()
        for forbidden in ("latitude","longitude","uniqueid","address"):
            self.assertNotIn(forbidden,raw)

    def test_sensitive_or_unknown_position_fields_rejected(self):
        payload=json.loads(snapshot_to_json(pending_snapshot("web-extra")))
        payload["positions"]["latitude"]=-12.0
        with self.assertRaises(DashboardAPIError) as cm:decode_dashboard_response(json.dumps(payload))
        self.assertEqual(cm.exception.code,"API_DATA_UNAVAILABLE")

    def test_incomplete_dto_is_rejected(self):
        payload=json.loads(snapshot_to_json(pending_snapshot("web-missing")))
        del payload["devices"]["inactive"]
        with self.assertRaises(DashboardAPIError):decode_dashboard_response(json.dumps(payload))

    def test_duplicate_json_keys_are_rejected(self):
        raw=snapshot_to_json(pending_snapshot("web-duplicate"))
        raw=raw.replace('"schema_version":1,','"schema_version":1,"schema_version":1,',1)
        with self.assertRaises(DashboardAPIError) as cm:decode_dashboard_response(raw)
        self.assertEqual(cm.exception.code,"API_DATA_UNAVAILABLE")

    def test_sql_shell_systemd_and_service_selectors_are_not_in_request(self):
        for key in ("sql","command","shell","systemctl","service","unit","path","file"):
            with self.subTest(key=key),self.assertRaises(DashboardAPIError) as cm:
                from api.read_only_dashboard_v1 import dashboard_request_from_mapping
                dashboard_request_from_mapping({"request_id":"web-no-params",key:"arbitrary"})
            self.assertEqual(cm.exception.code,"API_INVALID_REQUEST")

    def test_no_http_or_system_execution_in_adapter(self):
        import ast
        from pathlib import Path
        path=Path("web/adapters/dashboard_client_v1.py")
        tree=ast.parse(path.read_text(encoding="utf-8"))
        imported={alias.name for node in ast.walk(tree) if isinstance(node,(ast.Import,ast.ImportFrom)) for alias in node.names}
        self.assertFalse(imported & {"requests","urllib","subprocess","socket"})
        names={node.func.id for node in ast.walk(tree) if hasattr(node,"func") and hasattr(node.func,"id")}
        self.assertNotIn("fetch",names);self.assertNotIn("system",names)

    def test_generic_retention_not_misrepresented_as_both_legacy_jobs(self):
        p=ValueDTO.available("completed",STAMP)
        snapshot=pending_snapshot("web-retention")
        snapshot=DashboardSnapshotDTO(snapshot.schema_version,snapshot.request_id,snapshot.general,snapshot.server,
            snapshot.devices,snapshot.positions,RetentionStatusDTO(ValueDTO.available(True,STAMP),ValueDTO.available(STAMP,STAMP),p,ValueDTO.available(STAMP,STAMP),STAMP))
        model=to_existing_dashboard_model(snapshot)
        self.assertEqual(model["retention"]["generic"]["last_run_state"]["value"],"completed")
        self.assertEqual(model["retention"]["positions_90d"]["availability"],"PENDING_PROVIDER")
        self.assertEqual(model["retention"]["logs_30d"]["availability"],"PENDING_PROVIDER")

    def test_mapping_is_deterministic(self):
        model1=to_existing_dashboard_model(pending_snapshot("web-deterministic"))
        model2=to_existing_dashboard_model(pending_snapshot("web-deterministic"))
        self.assertEqual(model1,model2)

    def test_login_and_existing_visual_assets_are_not_part_of_adapter(self):
        # Authentication remains untouched; the client adapter exposes no login or credential fields.
        request=build_dashboard_request("web-no-auth")
        self.assertEqual(set(request),{"request_id"})
        self.assertNotIn("password",request);self.assertNotIn("username",request)


if __name__=="__main__":unittest.main()
