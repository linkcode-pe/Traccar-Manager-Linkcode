"""Isolated JSON-to-legacy-dashboard contract adapter; no network or DOM access.

This reference client mapper consumes the read-only v1 JSON shape and returns
plain view-model fields for the existing dashboard. It does not fetch an endpoint.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from api.read_only_dashboard_v1 import (
    Availability, DashboardAPIError, DashboardRequestDTO, DashboardSnapshotDTO,
    DeviceSummaryDTO, GeneralStatusDTO, PositionSummaryDTO, RetentionStatusDTO,
    ServerMetricsDTO, TraccarServiceDTO, ValueDTO, dashboard_request_from_mapping,
    validate_snapshot,
)


def build_dashboard_request(request_id: str) -> dict[str, str]:
    """Construct the only allowed request shape; resources are fixed server-side."""
    request = DashboardRequestDTO(request_id)
    return {"request_id": request.request_id}


def _object(value: Any, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise DashboardAPIError("API_DATA_UNAVAILABLE")
    return value


def _value(value: Any) -> ValueDTO:
    raw = _object(value, {"availability", "value", "observed_at_utc"})
    try:
        return ValueDTO(Availability(raw["availability"]), raw["value"], raw["observed_at_utc"])
    except Exception:
        raise DashboardAPIError("API_DATA_UNAVAILABLE") from None


def _service(value: Any) -> TraccarServiceDTO:
    raw = _object(value, {"state", "substate", "load_state", "unit_file_state", "result"})
    return TraccarServiceDTO(*(_value(raw[key]) for key in ("state", "substate", "load_state", "unit_file_state", "result")))


def _general(value: Any) -> GeneralStatusDTO:
    raw = _object(value, {"traccar_service", "uptime_seconds", "version", "overall_state", "observed_at_utc"})
    return GeneralStatusDTO(_service(raw["traccar_service"]), _value(raw["uptime_seconds"]),
                            _value(raw["version"]), _value(raw["overall_state"]), raw["observed_at_utc"])


def _server(value: Any) -> ServerMetricsDTO:
    raw = _object(value, {"cpu_percent", "memory_total_bytes", "memory_used_bytes", "disk_total_bytes", "disk_free_bytes", "observed_at_utc"})
    return ServerMetricsDTO(*(_value(raw[key]) for key in ("cpu_percent", "memory_total_bytes", "memory_used_bytes", "disk_total_bytes", "disk_free_bytes")),
                            observed_at_utc=raw["observed_at_utc"])


def _devices(value: Any) -> DeviceSummaryDTO:
    raw = _object(value, {"total", "active", "inactive", "observed_at_utc"})
    return DeviceSummaryDTO(_value(raw["total"]), _value(raw["active"]), _value(raw["inactive"]), raw["observed_at_utc"])


def _positions(value: Any) -> PositionSummaryDTO:
    raw = _object(value, {"current_count", "older_than_retention_count", "availability_state", "observed_at_utc"})
    return PositionSummaryDTO(_value(raw["current_count"]), _value(raw["older_than_retention_count"]),
                              _value(raw["availability_state"]), raw["observed_at_utc"])


def _retention(value: Any) -> RetentionStatusDTO:
    raw = _object(value, {"configuration_known", "cutoff_utc", "last_run_state", "last_run_utc", "observed_at_utc"})
    return RetentionStatusDTO(_value(raw["configuration_known"]), _value(raw["cutoff_utc"]),
                              _value(raw["last_run_state"]), _value(raw["last_run_utc"]), raw["observed_at_utc"])


def decode_dashboard_response(raw_json: str) -> DashboardSnapshotDTO:
    """Strictly decode the API DTO; reject missing, duplicate, unknown or sensitive fields."""
    if not isinstance(raw_json, str) or len(raw_json) > 262144:
        raise DashboardAPIError("API_DATA_UNAVAILABLE")
    def no_duplicates(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate object key")
            result[key] = item
        return result
    try:
        raw = json.loads(raw_json, object_pairs_hook=no_duplicates)
        raw = _object(raw, {"schema_version", "request_id", "general", "server", "devices", "positions", "retention"})
        snapshot = DashboardSnapshotDTO(raw["schema_version"], raw["request_id"], _general(raw["general"]),
                                        _server(raw["server"]), _devices(raw["devices"]),
                                        _positions(raw["positions"]), _retention(raw["retention"]))
        return validate_snapshot(snapshot, snapshot.request_id)
    except DashboardAPIError:
        raise
    except Exception:
        raise DashboardAPIError("API_DATA_UNAVAILABLE") from None


def _field(value: ValueDTO) -> dict[str, Any]:
    if not isinstance(value, ValueDTO):
        raise DashboardAPIError("API_DATA_UNAVAILABLE")
    available = value.availability is Availability.AVAILABLE
    return {"availability": value.availability.value, "value": value.value if available else None,
            "observed_at_utc": value.observed_at_utc if available else None}


def to_existing_dashboard_model(snapshot: DashboardSnapshotDTO) -> dict[str, Any]:
    """Map DTO values to semantic slots; never fills missing UI data with defaults."""
    snapshot = validate_snapshot(snapshot, snapshot.request_id)
    general = snapshot.general
    service = general.traccar_service
    service_state = _field(service.state)
    substate = _field(service.substate)
    if service_state["availability"] != Availability.AVAILABLE.value:
        status_label = Availability.PENDING_PROVIDER.value
    elif service_state["value"] == "active" and substate["availability"] == Availability.AVAILABLE.value and substate["value"] == "running":
        status_label = "Activo"
    else:
        status_label = "Estado: " + str(service_state["value"])
    pending = _field(ValueDTO.pending_provider())
    return {
        "database": pending,
        "traccar": {
            "availability": service_state["availability"], "status_label": status_label,
            "state": service_state, "substate": substate,
            "load_state": _field(service.load_state), "unit_file_state": _field(service.unit_file_state),
            "result": _field(service.result), "uptime_seconds": _field(general.uptime_seconds),
            "version": _field(general.version), "overall_state": _field(general.overall_state),
            "observed_at_utc": general.observed_at_utc,
        },
        "server": {
            "cpu_percent": _field(snapshot.server.cpu_percent),
            "memory_total_bytes": _field(snapshot.server.memory_total_bytes),
            "memory_used_bytes": _field(snapshot.server.memory_used_bytes),
            "disk_total_bytes": _field(snapshot.server.disk_total_bytes),
            "disk_free_bytes": _field(snapshot.server.disk_free_bytes),
            "observed_at_utc": snapshot.server.observed_at_utc,
        },
        "devices": {"total": _field(snapshot.devices.total), "active": _field(snapshot.devices.active),
                    "inactive": _field(snapshot.devices.inactive), "observed_at_utc": snapshot.devices.observed_at_utc},
        "positions": {
            "current_count": _field(snapshot.positions.current_count),
            "older_than_retention_count": _field(snapshot.positions.older_than_retention_count),
            "availability_state": _field(snapshot.positions.availability_state),
            "rows": pending, "observed_at_utc": snapshot.positions.observed_at_utc,
        },
        "retention": {
            "generic": {"configuration_known": _field(snapshot.retention.configuration_known),
                        "cutoff_utc": _field(snapshot.retention.cutoff_utc),
                        "last_run_state": _field(snapshot.retention.last_run_state),
                        "last_run_utc": _field(snapshot.retention.last_run_utc),
                        "observed_at_utc": snapshot.retention.observed_at_utc},
            # The API DTO does not distinguish the legacy 90d-position and 30d-log flows.
            "positions_90d": pending, "logs_30d": pending,
        },
    }
