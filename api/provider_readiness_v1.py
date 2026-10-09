"""Static future-source readiness catalogue; performs no reads or I/O."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from api.read_only_dashboard_v1 import DashboardAPIError


class ProviderReadiness(str, Enum):
    PENDING_PROVIDER = "PENDING_PROVIDER"
    PENDING_PRIVILEGED_PROVIDER = "PENDING_PRIVILEGED_PROVIDER"


@dataclass(frozen=True, slots=True)
class ProviderPlan:
    resource: str
    readiness: ProviderReadiness
    proposed_source: str
    timeout_seconds: float | None
    allowed_fields: frozenset[str]
    forbidden_fields: frozenset[str]
    reason: str


_PLANS = {
    "traccar_status": ProviderPlan(
        "traccar_status", ProviderReadiness.PENDING_PRIVILEGED_PROVIDER,
        "fixed traccar.service status adapter through approved dispatcher", 5.0,
        frozenset({"load_state", "active_state", "sub_state", "unit_file_state", "result", "observed_at_utc"}),
        frozenset({"client_unit", "command", "shell", "sql", "logs", "environment", "stderr"}),
        "A dedicated non-root execution identity and the required runtime/dispatcher authorization are not provisioned or authorized.",
    ),
    "system_metrics": ProviderPlan(
        "system_metrics", ProviderReadiness.PENDING_PROVIDER,
        "fixed /proc/stat, /proc/meminfo and statvfs(/)", 2.0,
        frozenset({"cpu_percent", "memory_total_bytes", "memory_used_bytes", "disk_total_bytes", "disk_free_bytes", "observed_at_utc"}),
        frozenset({"user_paths", "process_list", "shell", "subprocess", "sql", "filesystem_paths_from_client"}),
        "Read-only source code exists, but production sources were not opened, approved, connected or executed.",
    ),
    "application_version": ProviderPlan(
        "application_version", ProviderReadiness.PENDING_PROVIDER, "no approved source", None,
        frozenset(), frozenset({"secret_config", "shell", "arbitrary_files"}),
        "No non-secret approved version source is defined.",
    ),
    "devices": ProviderPlan(
        "devices", ProviderReadiness.PENDING_PROVIDER, "future allowlisted read-only aggregate source", None,
        frozenset({"total", "active", "inactive"}),
        frozenset({"uniqueid", "device_rows", "sql", "secret_config"}),
        "No database source or access is authorized in this phase.",
    ),
    "positions": ProviderPlan(
        "positions", ProviderReadiness.PENDING_PROVIDER, "future minimized aggregate source", None,
        frozenset({"current_count", "older_than_retention_count", "availability_state"}),
        frozenset({"latitude", "longitude", "coordinates", "address", "uniqueid", "individual_rows", "sql"}),
        "No source is authorized; location and identifier fields remain prohibited.",
    ),
    "retention": ProviderPlan(
        "retention", ProviderReadiness.PENDING_PROVIDER, "future approved status source", None,
        frozenset({"configuration_known", "cutoff_utc", "last_run_state", "last_run_utc"}),
        frozenset({"scripts", "timers", "status_files", "sql", "cleanup_execution"}),
        "No script, timer, status file or database source may be consulted.",
    ),
}
PROVIDER_PLANS = MappingProxyType(_PLANS)


def provider_plan(resource: str) -> ProviderPlan:
    if not isinstance(resource, str) or resource not in PROVIDER_PLANS:
        raise DashboardAPIError("API_INVALID_REQUEST")
    return PROVIDER_PLANS[resource]
