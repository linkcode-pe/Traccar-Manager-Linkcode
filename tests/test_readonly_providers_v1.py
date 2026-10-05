import ast
import inspect
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from api.read_only_dashboard_v1 import (
    ActorContext, AuditPhase, DashboardAPIError, DashboardRequestDTO, DashboardSnapshotDTO,
    DeviceSummaryDTO, GeneralStatusDTO, PositionSummaryDTO, ReadOnlyDashboardProvider,
    RetentionStatusDTO, ServerMetricsDTO, ValueDTO,
)
from api.providers.system_metrics_v1 import (
    METRICS_ERROR_CODES, MetricsProviderError, ProcfsSystemMetricsSource,
    SystemMetricsProvider, SystemMetricsSample, cpu_percent_between,
    parse_proc_meminfo, parse_proc_stat_cpu,
)
from api.providers.traccar_status_v1 import (
    STATUS_TIMEOUT_SECONDS, TRACCAR_STATUS_ERROR_CODES, TraccarStatusProvider,
    TraccarStatusProviderError, TraccarStatusRecord,
)

STAMP="2026-10-01T09:56:00Z"
ACTOR=ActorContext("provider-test",frozenset({"dashboard.read"}))


class FixtureMetricsSource:
    provider_id="fixture.metrics.v1"
    def __init__(self,sample=None,error=None):self.sample=sample;self.error=error;self.calls=0;self.timeout=None
    def read(self,timeout_seconds):
        self.calls+=1;self.timeout=timeout_seconds
        if self.error:raise self.error
        return self.sample


class FixtureStatusSource:
    provider_id="fixture.traccar-status.v1"
    def __init__(self,record=None,error=None):self.record=record;self.error=error;self.calls=0;self.timeout=None
    def read_status(self,timeout_seconds):
        self.calls+=1;self.timeout=timeout_seconds
        if self.error:raise self.error
        return self.record


class MemoryAudit:
    def __init__(self,fail_phase=None):self.events=[];self.fail_phase=fail_phase
    def append(self,event):
        if event.phase is self.fail_phase:raise RuntimeError("audit unavailable details")
        self.events.append(event)


class AllowRead:
    def allows(self,actor,operation):return True


def sample():return SystemMetricsSample(12.5,8_000_000,3_000_000,100_000_000,40_000_000,STAMP)
def record():return TraccarStatusRecord("loaded","active","running","enabled","success",STAMP)
def metric_provider(source):return SystemMetricsProvider(source,allowed_source_ids=frozenset({"fixture.metrics.v1"}))
def status_provider(source):return TraccarStatusProvider(source,allowed_source_ids=frozenset({"fixture.traccar-status.v1"}))


class PassGateway:
    def execute(self,request,actor,operation):return operation()

class FailGateway:
    def execute(self,request,actor,operation):raise DashboardAPIError("API_AUDIT_UNAVAILABLE")

class ProviderFixtureSource:
    provider_id="fixture.dashboard.v1"
    def __init__(self,metrics,status):self.metrics=metrics;self.status=status;self.calls=0
    def read_dashboard(self,request):
        self.calls+=1
        general=self.status.collect();server=self.metrics.collect();p=ValueDTO.pending_provider()
        return DashboardSnapshotDTO(1,request.request_id,general,server,
            DeviceSummaryDTO(p,p,p),PositionSummaryDTO(p,p,p),RetentionStatusDTO(p,p,p,p))


class ReadOnlyProviderTests(unittest.TestCase):
    def test_proc_stat_fixture_parser_and_cpu_percent(self):
        before=parse_proc_stat_cpu("cpu 100 0 50 850 0 0 0 0\ncpu0 1 2 3 4\n")
        after=parse_proc_stat_cpu("cpu 120 0 60 870 0 0 0 0\n")
        self.assertEqual(before,(1000,850));self.assertAlmostEqual(cpu_percent_between(before,after),60.0)

    def test_proc_meminfo_fixture_parser(self):
        total,used=parse_proc_meminfo("MemTotal: 1000 kB\nMemAvailable: 400 kB\nBuffers: 10 kB\n")
        self.assertEqual((total,used),(1_024_000,614_400))

    def test_invalid_proc_stat_has_stable_error(self):
        with self.assertRaises(MetricsProviderError) as cm:parse_proc_stat_cpu("cpu nope\n")
        self.assertEqual(cm.exception.code,"METRICS_DATA_INVALID")

    def test_invalid_meminfo_has_stable_error(self):
        with self.assertRaises(MetricsProviderError) as cm:parse_proc_meminfo("MemTotal: 1 MB\n")
        self.assertEqual(cm.exception.code,"METRICS_DATA_INVALID")

    def test_cpu_counter_regression_is_rejected(self):
        with self.assertRaises(MetricsProviderError) as cm:cpu_percent_between((100,70),(90,65))
        self.assertEqual(cm.exception.code,"METRICS_DATA_INVALID")

    def test_system_metrics_provider_maps_fixture_to_dto(self):
        source=FixtureMetricsSource(sample());dto=metric_provider(source).collect()
        self.assertEqual(dto.cpu_percent.value,12.5);self.assertEqual(dto.memory_used_bytes.value,3_000_000)
        self.assertEqual(dto.disk_free_bytes.value,40_000_000);self.assertEqual(dto.observed_at_utc,STAMP)
        self.assertEqual(source.calls,1);self.assertEqual(source.timeout,2.0)

    def test_system_metrics_missing_source_is_pending_provider_error(self):
        with self.assertRaises(MetricsProviderError) as cm:
            SystemMetricsProvider(None,allowed_source_ids=frozenset()).collect()
        self.assertEqual(cm.exception.code,"METRICS_PROVIDER_PENDING")

    def test_system_metrics_source_must_be_allowlisted(self):
        source=FixtureMetricsSource(sample());source.provider_id="unapproved.source"
        provider=SystemMetricsProvider(source,allowed_source_ids=frozenset({"fixture.metrics.v1"}))
        with self.assertRaises(MetricsProviderError) as cm:provider.collect()
        self.assertEqual(cm.exception.code,"METRICS_SOURCE_NOT_ALLOWED");self.assertEqual(source.calls,0)

    def test_system_metrics_timeout_is_sanitized(self):
        source=FixtureMetricsSource(error=TimeoutError("private source detail"))
        with self.assertRaises(MetricsProviderError) as cm:metric_provider(source).collect()
        self.assertEqual(cm.exception.code,"METRICS_TIMEOUT");self.assertEqual(str(cm.exception),"METRICS_TIMEOUT")

    def test_system_metrics_unavailable_is_sanitized(self):
        source=FixtureMetricsSource(error=OSError("path and host detail"))
        with self.assertRaises(MetricsProviderError) as cm:metric_provider(source).collect()
        self.assertEqual(cm.exception.code,"METRICS_SOURCE_UNAVAILABLE")

    def test_system_metrics_invalid_sample_rejected(self):
        source=FixtureMetricsSource(sample={"cpu":1})
        with self.assertRaises(MetricsProviderError) as cm:metric_provider(source).collect()
        self.assertEqual(cm.exception.code,"METRICS_DATA_INVALID")

    def test_procfs_source_has_no_user_path_parameters_or_external_commands(self):
        self.assertEqual(list(inspect.signature(ProcfsSystemMetricsSource.read).parameters),["self","timeout_seconds"])
        tree=ast.parse(Path("api/providers/system_metrics_v1.py").read_text())
        imports={alias.name for node in ast.walk(tree) if isinstance(node,(ast.Import,ast.ImportFrom)) for alias in node.names}
        self.assertNotIn("subprocess",imports);self.assertNotIn("sqlite3",imports)

    def test_status_provider_maps_allowlisted_fixture_and_marks_missing_fields(self):
        source=FixtureStatusSource(record());dto=status_provider(source).collect()
        self.assertEqual(dto.traccar_service.state.value,"active")
        self.assertEqual(dto.traccar_service.substate.value,"running")
        self.assertEqual(dto.uptime_seconds.availability.value,"PENDING_PROVIDER")
        self.assertEqual(dto.version.availability.value,"PENDING_PROVIDER")
        self.assertEqual(dto.overall_state.availability.value,"PENDING_PROVIDER")
        self.assertEqual(source.timeout,STATUS_TIMEOUT_SECONDS)

    def test_status_provider_without_source_is_pending(self):
        provider=TraccarStatusProvider(None,allowed_source_ids=frozenset())
        with self.assertRaises(TraccarStatusProviderError) as cm:provider.collect()
        self.assertEqual(cm.exception.code,"TRACCAR_STATUS_PENDING_PROVIDER")

    def test_status_source_must_be_allowlisted(self):
        source=FixtureStatusSource(record());source.provider_id="other.status.source"
        provider=status_provider(source)
        with self.assertRaises(TraccarStatusProviderError) as cm:provider.collect()
        self.assertEqual(cm.exception.code,"TRACCAR_STATUS_SOURCE_NOT_ALLOWED");self.assertEqual(source.calls,0)

    def test_status_timeout_is_sanitized(self):
        source=FixtureStatusSource(error=TimeoutError("private timeout"))
        with self.assertRaises(TraccarStatusProviderError) as cm:status_provider(source).collect()
        self.assertEqual(cm.exception.code,"TRACCAR_STATUS_TIMEOUT");self.assertEqual(str(cm.exception),"TRACCAR_STATUS_TIMEOUT")

    def test_status_source_unavailable_is_sanitized(self):
        source=FixtureStatusSource(error=OSError("systemd details"))
        with self.assertRaises(TraccarStatusProviderError) as cm:status_provider(source).collect()
        self.assertEqual(cm.exception.code,"TRACCAR_STATUS_SOURCE_UNAVAILABLE")

    def test_status_invalid_payload_rejected_without_source_fields(self):
        source=FixtureStatusSource({"unit":"other.service","state":"active"})
        with self.assertRaises(TraccarStatusProviderError) as cm:status_provider(source).collect()
        self.assertEqual(cm.exception.code,"TRACCAR_STATUS_DATA_INVALID")

    def test_status_record_rejects_arbitrary_state_text(self):
        with self.assertRaises(ValueError):TraccarStatusRecord("loaded","active;rm","running","enabled","success",STAMP)

    def test_status_provider_accepts_no_service_selector(self):
        self.assertEqual(list(inspect.signature(TraccarStatusProvider.collect).parameters),["self"])
        self.assertEqual(list(inspect.signature(FixtureStatusSource.read_status).parameters),["self","timeout_seconds"])

    def test_procfs_cpu_memory_and_disk_are_not_read_by_unit_tests(self):
        # Tests use only in-memory fixtures; constructing the source does not perform I/O.
        ProcfsSystemMetricsSource()
        self.assertEqual(parse_proc_stat_cpu("cpu 1 0 1 8 0 0 0 0\n"),(10,8))

    def test_pending_mysql_positions_and_retention_remain_explicit(self):
        p=ValueDTO.pending_provider()
        self.assertEqual(DeviceSummaryDTO(p,p,p).total.availability.value,"PENDING_PROVIDER")
        self.assertEqual(PositionSummaryDTO(p,p,p).current_count.availability.value,"PENDING_PROVIDER")
        self.assertEqual(RetentionStatusDTO(p,p,p,p).cutoff_utc.availability.value,"PENDING_PROVIDER")

    def test_mapper_composition_uses_explicit_pass_through_gateway(self):
        class Policy:
            def allows(self,actor,operation):return True
        metrics=FixtureMetricsSource(sample());status=FixtureStatusSource(record())
        composite=ProviderFixtureSource(metric_provider(metrics),status_provider(status))
        api=ReadOnlyDashboardProvider(composite,allowed_provider_ids=frozenset({composite.provider_id}),
             authorizer=Policy(),execution_gateway=PassGateway())
        snapshot=api.read(DashboardRequestDTO("req-composite"),ACTOR)
        self.assertEqual(snapshot.server.cpu_percent.value,12.5)
        self.assertEqual(snapshot.general.traccar_service.state.value,"active")
        self.assertEqual(metrics.calls,1);self.assertEqual(status.calls,1)

    def test_gateway_failure_blocks_all_composed_providers(self):
        class Policy:
            def allows(self,actor,operation):return True
        metrics=FixtureMetricsSource(sample());status=FixtureStatusSource(record())
        composite=ProviderFixtureSource(metric_provider(metrics),status_provider(status))
        api=ReadOnlyDashboardProvider(composite,allowed_provider_ids=frozenset({composite.provider_id}),
             authorizer=Policy(),execution_gateway=FailGateway())
        with self.assertRaises(DashboardAPIError) as cm:api.read(DashboardRequestDTO("req-audit-block"),ACTOR)
        self.assertEqual(cm.exception.code,"API_AUDIT_UNAVAILABLE")
        self.assertEqual(metrics.calls,0);self.assertEqual(status.calls,0)

    def test_provider_error_codes_are_stable_and_do_not_expose_raw_messages(self):
        self.assertIn("METRICS_TIMEOUT",METRICS_ERROR_CODES)
        self.assertIn("TRACCAR_STATUS_SOURCE_NOT_ALLOWED",TRACCAR_STATUS_ERROR_CODES)
        self.assertEqual(str(MetricsProviderError("not-a-code")),"METRICS_INTERNAL_ERROR")
        self.assertEqual(str(TraccarStatusProviderError("bad")),"TRACCAR_STATUS_INTERNAL_ERROR")


if __name__=="__main__":unittest.main()
