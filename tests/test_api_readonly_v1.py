import json
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import Mock

from api.read_only_dashboard_v1 import (
    API_CODES, ActorContext, Availability, DashboardAPIError, DashboardRequestDTO,
    DashboardSnapshotDTO, DeviceSummaryDTO, GeneralStatusDTO, PositionSummaryDTO,
    ProviderTimeout, ProviderUnavailable, ReadOnlyDashboardProvider,
    RetentionStatusDTO, ServerMetricsDTO, TraccarServiceDTO, ValueDTO,
    dashboard_request_from_mapping, pending_snapshot, snapshot_to_json,
)

STAMP = "2026-10-01T09:44:00.000000Z"
ACTOR = ActorContext("actor-test", frozenset({"dashboard.read"}))


class Policy:
    def __init__(self, allowed=True, error=None):
        self.allowed, self.error, self.calls = allowed, error, 0
    def allows(self, actor, operation):
        self.calls += 1
        if self.error:
            raise self.error
        return self.allowed


class FixtureSource:
    provider_id = "fixture.dashboard.v1"
    def __init__(self, snapshot=None, error=None, preserve_request_id=False):
        self.snapshot, self.error, self.calls = snapshot, error, 0
        self.preserve_request_id = preserve_request_id
    def read_dashboard(self, request):
        self.calls += 1
        if self.error:
            raise self.error
        if self.snapshot is None:
            return pending_snapshot(request.request_id)
        if isinstance(self.snapshot, DashboardSnapshotDTO) and not self.preserve_request_id:
            return replace(self.snapshot, request_id=request.request_id)
        return self.snapshot


class PassGateway:
    def __init__(self): self.calls = 0
    def execute(self, request, actor, operation):
        self.calls += 1
        return operation()


class FailBeforeGateway:
    def execute(self, request, actor, operation):
        raise DashboardAPIError("API_AUDIT_UNAVAILABLE")


class FailAfterGateway:
    def execute(self, request, actor, operation):
        operation()
        raise DashboardAPIError("API_AUDIT_UNAVAILABLE")


def available(value): return ValueDTO.available(value, STAMP)
def pending(): return ValueDTO.pending_provider()


def fixture_snapshot(request_id="req-1"):
    svc = TraccarServiceDTO(available("active"), available("running"), available("loaded"),
                            available("enabled"), available("success"))
    return DashboardSnapshotDTO(
        1, request_id,
        GeneralStatusDTO(svc, pending(), pending(), pending(), STAMP),
        ServerMetricsDTO(pending(), pending(), pending(), pending(), pending(), None),
        DeviceSummaryDTO(available(20), available(18), available(2), STAMP),
        PositionSummaryDTO(available(17), pending(), available("AVAILABLE"), STAMP),
        RetentionStatusDTO(pending(), pending(), pending(), pending(), None),
    )


def make_provider(*, source=None, gateway=None, allowed=True, allowlist=None, policy_error=None):
    source = source if source is not None else FixtureSource(fixture_snapshot())
    if allowlist is None:
        allowlist = frozenset({source.provider_id}) if source is not None else frozenset()
    gateway = gateway if gateway is not None else PassGateway()
    return ReadOnlyDashboardProvider(
        source, allowed_provider_ids=allowlist,
        authorizer=Policy(allowed, policy_error), execution_gateway=gateway,
    )


class ReadOnlyDashboardV1Tests(unittest.TestCase):
    def test_valid_dto_and_explicit_pending_fields(self):
        dto = fixture_snapshot()
        self.assertEqual(dto.schema_version, 1)
        self.assertEqual(dto.general.traccar_service.state.value, "active")
        self.assertEqual(dto.general.uptime_seconds.availability, Availability.PENDING_PROVIDER)
        self.assertEqual(dto.server.cpu_percent.availability, Availability.PENDING_PROVIDER)
        self.assertEqual(dto.retention.cutoff_utc.availability, Availability.PENDING_PROVIDER)

    def test_incomplete_provider_dto_is_rejected(self):
        source = FixtureSource(snapshot=object())
        api = make_provider(source=source)
        with self.assertRaises(DashboardAPIError) as cm:
            api.read(DashboardRequestDTO("req-1"), ACTOR)
        self.assertEqual(cm.exception.code, "API_DATA_UNAVAILABLE")

    def test_request_accepts_only_request_id(self):
        self.assertEqual(dashboard_request_from_mapping({"request_id": "req-1"}), DashboardRequestDTO("req-1"))
        for extra in ({"request_id": "req-1", "provider": "x"},
                      {"request_id": "req-1", "sql": "SELECT 1"},
                      {"request_id": "req-1", "command": "systemctl"}):
            with self.subTest(extra=extra), self.assertRaises(DashboardAPIError) as cm:
                dashboard_request_from_mapping(extra)
            self.assertEqual(cm.exception.code, "API_INVALID_REQUEST")

    def test_provider_available_returns_snapshot(self):
        source, gateway = FixtureSource(fixture_snapshot()), PassGateway()
        result = make_provider(source=source, gateway=gateway).read(DashboardRequestDTO("req-1"), ACTOR)
        self.assertEqual(result.devices.total.value, 20)
        self.assertEqual(source.calls, 1)
        self.assertEqual(gateway.calls, 1)

    def test_provider_missing_returns_controlled_error(self):
        api = make_provider(source=None, allowlist=frozenset())
        api._data_source = None
        with self.assertRaises(DashboardAPIError) as cm:
            api.read(DashboardRequestDTO("req-1"), ACTOR)
        self.assertEqual(cm.exception.code, "API_PROVIDER_UNAVAILABLE")

    def test_unallowlisted_provider_is_not_called(self):
        source = FixtureSource(fixture_snapshot())
        api = make_provider(source=source, allowlist=frozenset({"other.fixture"}))
        with self.assertRaises(DashboardAPIError) as cm:
            api.read(DashboardRequestDTO("req-1"), ACTOR)
        self.assertEqual(cm.exception.code, "API_SOURCE_NOT_ALLOWED")
        self.assertEqual(source.calls, 0)

    def test_provider_unavailable_error_is_sanitized(self):
        api = make_provider(source=FixtureSource(error=ProviderUnavailable("DSN secret content")))
        with self.assertRaises(DashboardAPIError) as cm:
            api.read(DashboardRequestDTO("req-1"), ACTOR)
        self.assertEqual(cm.exception.code, "API_PROVIDER_UNAVAILABLE")
        self.assertEqual(str(cm.exception), "API_PROVIDER_UNAVAILABLE")
        self.assertNotIn("DSN", str(cm.exception))

    def test_provider_timeout_has_stable_code(self):
        api = make_provider(source=FixtureSource(error=ProviderTimeout("private timeout detail")))
        with self.assertRaises(DashboardAPIError) as cm:
            api.read(DashboardRequestDTO("req-1"), ACTOR)
        self.assertEqual(cm.exception.code, "API_TIMEOUT")

    def test_prepare_failure_gateway_blocks_source(self):
        source = FixtureSource(fixture_snapshot())
        api = make_provider(source=source, gateway=FailBeforeGateway())
        with self.assertRaises(DashboardAPIError) as cm:
            api.read(DashboardRequestDTO("req-prepare-fail"), ACTOR)
        self.assertEqual(cm.exception.code, "API_AUDIT_UNAVAILABLE")
        self.assertEqual(source.calls, 0)

    def test_finalization_failure_gateway_withholds_snapshot(self):
        source = FixtureSource(fixture_snapshot())
        api = make_provider(source=source, gateway=FailAfterGateway())
        with self.assertRaises(DashboardAPIError) as cm:
            api.read(DashboardRequestDTO("req-final-fail"), ACTOR)
        self.assertEqual(cm.exception.code, "API_AUDIT_UNAVAILABLE")
        self.assertEqual(source.calls, 1)

    def test_missing_gateway_fails_closed_before_provider(self):
        source = FixtureSource(fixture_snapshot())
        api = make_provider(source=source, gateway=None)
        api._execution_gateway = None
        with self.assertRaises(DashboardAPIError) as cm:
            api.read(DashboardRequestDTO("req-no-gateway"), ACTOR)
        self.assertEqual(cm.exception.code, "API_AUDIT_UNAVAILABLE")
        self.assertEqual(source.calls, 0)

    def test_authorization_denial_blocks_provider(self):
        source = FixtureSource(fixture_snapshot())
        api = make_provider(source=source, allowed=False)
        with self.assertRaises(DashboardAPIError) as cm:
            api.read(DashboardRequestDTO("req-denied"), ACTOR)
        self.assertEqual(cm.exception.code, "API_FORBIDDEN")
        self.assertEqual(source.calls, 0)

    def test_policy_exception_is_sanitized(self):
        api = make_provider(source=FixtureSource(fixture_snapshot()), policy_error=RuntimeError("token=db-secret"))
        with self.assertRaises(DashboardAPIError) as cm:
            api.read(DashboardRequestDTO("req-policy"), ACTOR)
        self.assertEqual(cm.exception.code, "API_INTERNAL_ERROR")
        self.assertNotIn("secret", str(cm.exception))

    def test_response_serialization_is_deterministic(self):
        dto = fixture_snapshot()
        self.assertEqual(snapshot_to_json(dto), snapshot_to_json(dto))
        self.assertIn('"schema_version":1', snapshot_to_json(dto))

    def test_api_cache_is_idempotent_and_bound_to_actor(self):
        source, gateway = FixtureSource(fixture_snapshot()), PassGateway()
        api = make_provider(source=source, gateway=gateway)
        request = DashboardRequestDTO("req-idem")
        first, second = api.read(request, ACTOR), api.read(request, ACTOR)
        self.assertEqual(first, second)
        self.assertEqual(source.calls, 1)
        self.assertEqual(gateway.calls, 1)
        other = ActorContext("different-actor", frozenset({"dashboard.read"}))
        with self.assertRaises(DashboardAPIError) as cm:
            api.read(request, other)
        self.assertEqual(cm.exception.code, "API_INVALID_REQUEST")

    def test_policy_denial_is_not_human_approval(self):
        api = make_provider(source=FixtureSource(fixture_snapshot()), allowed=False)
        with self.assertRaises(DashboardAPIError) as cm:
            api.read(DashboardRequestDTO("req-denied-policy"), ACTOR)
        self.assertEqual(cm.exception.code, "API_FORBIDDEN")

    def test_full_mock_dashboard_has_all_sections_without_position_rows(self):
        result = make_provider(source=FixtureSource(fixture_snapshot())).read(DashboardRequestDTO("req-full"), ACTOR)
        dto = json.loads(snapshot_to_json(result))
        self.assertEqual(set(dto), {"schema_version", "request_id", "general", "server", "devices", "positions", "retention"})
        self.assertEqual(set(dto["positions"]), {"current_count", "older_than_retention_count", "availability_state", "observed_at_utc"})
        self.assertNotIn("coordinates", dto["positions"])
        self.assertEqual(dto["retention"]["cutoff_utc"]["availability"], "PENDING_PROVIDER")

    def test_provider_output_wrong_request_id_is_rejected(self):
        source = FixtureSource(fixture_snapshot("different"), preserve_request_id=True)
        api = make_provider(source=source)
        with self.assertRaises(DashboardAPIError) as cm:
            api.read(DashboardRequestDTO("req-1"), ACTOR)
        self.assertEqual(cm.exception.code, "API_DATA_UNAVAILABLE")

    def test_allowed_api_error_codes_are_stable(self):
        self.assertEqual(API_CODES, frozenset({"API_INVALID_REQUEST", "API_UNAUTHORIZED", "API_FORBIDDEN",
            "API_PROVIDER_UNAVAILABLE", "API_DATA_UNAVAILABLE", "API_SOURCE_NOT_ALLOWED", "API_TIMEOUT",
            "API_AUDIT_UNAVAILABLE", "API_INTERNAL_ERROR"}))

    def test_sensitive_fields_are_absent_from_fixture_response(self):
        raw = snapshot_to_json(make_provider(source=FixtureSource(fixture_snapshot())).read(
            DashboardRequestDTO("req-private"), ACTOR)).lower()
        for secretish in ("latitude", "longitude", "uniqueid", "address", "password", "token", "sql", "dsn"):
            self.assertNotIn(secretish, raw)


if __name__ == "__main__":
    unittest.main()
