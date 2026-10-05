"""Synthetic fixture sources for the development HTTP API only.

No filesystem, network, database, shell, systemd, Traccar or Worker access.
"""
from __future__ import annotations

from dataclasses import dataclass

from api.read_only_dashboard_v1 import (
    DashboardSnapshotDTO, DeviceSummaryDTO, GeneralStatusDTO, PositionSummaryDTO,
    RetentionStatusDTO, ServerMetricsDTO, TraccarServiceDTO, ValueDTO,
)

DEVELOPMENT_ONLY = True
FIXTURE_TIMESTAMP = "2026-10-01T10:08:00Z"
FIXTURE_DASHBOARD_PROVIDER_ID = "fixture.dashboard.http.v1"


@dataclass(frozen=True, slots=True)
class FixtureMetrics:
    cpu_percent: float
    memory_total_bytes: int
    memory_used_bytes: int
    disk_total_bytes: int
    disk_free_bytes: int
    observed_at_utc: str


@dataclass(frozen=True, slots=True)
class FixtureStatus:
    load_state: str
    active_state: str
    sub_state: str
    unit_file_state: str
    result: str
    observed_at_utc: str


class FixtureMetricsSource:
    """Returns fixed synthetic metrics, never reads the operating system."""
    provider_id = "fixture.metrics.http.v1"
    def __init__(self):
        self.calls = 0
    def read_metrics(self) -> FixtureMetrics:
        self.calls += 1
        return FixtureMetrics(13.5, 8_589_934_592, 3_221_225_472,
                              107_374_182_400, 42_949_672_960, FIXTURE_TIMESTAMP)


class FixtureStatusSource:
    """Returns fixed synthetic service state, never queries systemd/Traccar."""
    provider_id = "fixture.traccar-status.http.v1"
    def __init__(self):
        self.calls = 0
    def read_status(self) -> FixtureStatus:
        self.calls += 1
        return FixtureStatus("loaded", "active", "running", "enabled", "success", FIXTURE_TIMESTAMP)


class FixtureDashboardDataSource:
    """One allowlisted development-only provider assembling fixture DTOs."""
    provider_id = FIXTURE_DASHBOARD_PROVIDER_ID
    def __init__(self):
        self.metrics_source = FixtureMetricsSource()
        self.status_source = FixtureStatusSource()
        self.calls = 0
    def read_dashboard(self, request) -> DashboardSnapshotDTO:
        self.calls += 1
        metrics = self.metrics_source.read_metrics()
        status = self.status_source.read_status()
        stamp = FIXTURE_TIMESTAMP
        service = TraccarServiceDTO(
            ValueDTO.available(status.active_state, stamp),
            ValueDTO.available(status.sub_state, stamp),
            ValueDTO.available(status.load_state, stamp),
            ValueDTO.available(status.unit_file_state, stamp),
            ValueDTO.available(status.result, stamp),
        )
        general = GeneralStatusDTO(service, ValueDTO.pending_provider(),
                                   ValueDTO.pending_provider(), ValueDTO.pending_provider(), stamp)
        server = ServerMetricsDTO(
            ValueDTO.available(metrics.cpu_percent, stamp),
            ValueDTO.available(metrics.memory_total_bytes, stamp),
            ValueDTO.available(metrics.memory_used_bytes, stamp),
            ValueDTO.available(metrics.disk_total_bytes, stamp),
            ValueDTO.available(metrics.disk_free_bytes, stamp), stamp,
        )
        pending = ValueDTO.pending_provider()
        return DashboardSnapshotDTO(
            1, request.request_id, general, server,
            DeviceSummaryDTO(pending, pending, pending),
            PositionSummaryDTO(pending, pending, pending),
            RetentionStatusDTO(pending, pending, pending, pending),
        )
