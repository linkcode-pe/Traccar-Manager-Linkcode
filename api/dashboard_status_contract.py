"""Pure status view model for the existing PHP dashboard.

This module performs no I/O and is not an HTTP endpoint. It accepts only a
confirmed dispatcher result and exposes the fields supported by traccar.status.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Mapping

_UNIT = "traccar.service"
_SOURCE = "systemd"
_PROPERTIES = frozenset({"LoadState", "ActiveState", "SubState", "UnitFileState", "Result"})
_RESULT_KEYS = frozenset({"confirmed", "outcome", "observed_at_utc", "source", "unit", "properties"})


def to_dashboard_status(result: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the dispatcher DTO and map it to safe dashboard fields.

    This is a data contract only: it does not fetch status, query systemd,
    access a database/filesystem, or assert application/HTTP/database health.
    """
    if not isinstance(result, Mapping) or set(result) != _RESULT_KEYS:
        raise ValueError("invalid status result")
    if (result.get("confirmed") is not True or result.get("outcome") != "SUCCEEDED"
            or result.get("source") != _SOURCE or result.get("unit") != _UNIT):
        raise ValueError("invalid status result")
    observed = result.get("observed_at_utc")
    if not isinstance(observed, str) or not observed.endswith("Z"):
        raise ValueError("invalid status result")
    try:
        parsed = datetime.fromisoformat(observed[:-1] + "+00:00")
    except ValueError:
        raise ValueError("invalid status result") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("invalid status result")
    properties = result.get("properties")
    if not isinstance(properties, Mapping) or set(properties) != _PROPERTIES:
        raise ValueError("invalid status result")
    for value in properties.values():
        if not isinstance(value, str) or len(value) > 128 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("invalid status result")
    active = properties["ActiveState"]
    sub = properties["SubState"]
    if not re.fullmatch(r"[A-Za-z0-9_.+-]{1,64}", active or ""):
        raise ValueError("invalid status result")
    if not re.fullmatch(r"[A-Za-z0-9_.+-]{1,64}", sub or ""):
        raise ValueError("invalid status result")
    label = "Activo" if active == "active" and sub == "running" else "Estado: " + active
    return {
        "unit": _UNIT,
        "source": _SOURCE,
        "observed_at_utc": observed,
        "status_label": label,
        "state": {
            "load_state": properties["LoadState"],
            "active_state": active,
            "sub_state": sub,
            "unit_file_state": properties["UnitFileState"],
            "result": properties["Result"],
        },
        "interpretation": "systemd_unit_state_only",
    }
