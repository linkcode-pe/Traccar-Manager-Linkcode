"""Explicit, side-effect-free adapters for the fixed Traccar status protocol."""
from __future__ import annotations

from typing import Any, Mapping

from api.providers.traccar_status_v1 import TraccarStatusRecord
from api.read_only_dashboard_v1 import (
    Availability, GeneralStatusDTO, TraccarServiceDTO, ValueDTO,
)

PROTOCOL_OPERATION = "traccar.status.read"
DISPATCH_OPERATION = "traccar.status"
TARGET_UNIT = "traccar.service"
SOURCE_SYSTEMD = "systemd"
PROPERTIES = frozenset({"LoadState", "ActiveState", "SubState", "UnitFileState", "Result"})
_HANDLER_KEYS = frozenset({
    "schema_version", "operation", "result", "observed_at_utc", "source", "unit", "state",
})


def handler_result_to_record(value: Any) -> TraccarStatusRecord:
    """Adapt and validate the legacy systemd handler's `state` response."""
    if (not isinstance(value, dict) or set(value) != _HANDLER_KEYS
            or type(value.get("schema_version")) is not int or value["schema_version"] != 1
            or value.get("operation") != DISPATCH_OPERATION
            or value.get("result") != "SUCCEEDED" or value.get("source") != SOURCE_SYSTEMD
            or value.get("unit") != TARGET_UNIT):
        raise ValueError("invalid handler result")
    state = value.get("state")
    if not isinstance(state, dict) or set(state) != PROPERTIES:
        raise ValueError("invalid handler state")
    return TraccarStatusRecord(
        load_state=state["LoadState"], active_state=state["ActiveState"],
        sub_state=state["SubState"], unit_file_state=state["UnitFileState"],
        result=state["Result"], observed_at_utc=value["observed_at_utc"],
    )


def protocol_properties_to_record(properties: Any, observed_at_utc: Any) -> TraccarStatusRecord:
    """Adapt and validate the Worker protocol's `properties` response."""
    if not isinstance(properties, Mapping) or set(properties) != PROPERTIES:
        raise ValueError("invalid protocol properties")
    return TraccarStatusRecord(
        load_state=properties["LoadState"], active_state=properties["ActiveState"],
        sub_state=properties["SubState"], unit_file_state=properties["UnitFileState"],
        result=properties["Result"], observed_at_utc=observed_at_utc,
    )


def record_to_general_status(record: TraccarStatusRecord) -> GeneralStatusDTO:
    """Map only the five confirmed systemd fields; all other values stay pending."""
    if not isinstance(record, TraccarStatusRecord):
        raise ValueError("invalid status record")
    record.__post_init__()
    stamp = record.observed_at_utc
    service = TraccarServiceDTO(
        state=ValueDTO.available(record.active_state, stamp),
        substate=ValueDTO.available(record.sub_state, stamp),
        load_state=ValueDTO.available(record.load_state, stamp),
        unit_file_state=ValueDTO.available(record.unit_file_state, stamp),
        result=ValueDTO.available(record.result, stamp),
    )
    return GeneralStatusDTO(
        traccar_service=service,
        uptime_seconds=ValueDTO.pending_provider(),
        version=ValueDTO.pending_provider(),
        overall_state=ValueDTO.pending_provider(),
        observed_at_utc=stamp,
    )


def general_status_to_dispatcher_result(value: Any) -> dict[str, Any]:
    """Adapt the DTO to the Dispatcher executor contract without inference."""
    if not isinstance(value, GeneralStatusDTO):
        raise ValueError("invalid general status DTO")
    service = value.traccar_service
    fields = {
        "LoadState": service.load_state,
        "ActiveState": service.state,
        "SubState": service.substate,
        "UnitFileState": service.unit_file_state,
        "Result": service.result,
    }
    observed = value.observed_at_utc
    if not isinstance(observed, str) or not observed.endswith("Z"):
        raise ValueError("invalid status timestamp")
    values = {}
    for key, item in fields.items():
        if (not isinstance(item, ValueDTO) or item.availability is not Availability.AVAILABLE
                or item.observed_at_utc != observed or not isinstance(item.value, str)):
            raise ValueError("incomplete status DTO")
        values[key] = item.value
    # Revalidate every field at the protocol boundary.
    record = protocol_properties_to_record(values, observed)
    return {
        "confirmed": True,
        "outcome": "SUCCEEDED",
        "observed_at_utc": record.observed_at_utc,
        "source": SOURCE_SYSTEMD,
        "unit": TARGET_UNIT,
        "properties": values,
    }
