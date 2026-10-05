"""Read-only dashboard bridge to the fixed Traccar status Worker."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from api.read_only_dashboard_v1 import (
    DashboardAPIError, DashboardRequestDTO, pending_snapshot, validate_snapshot,
)
from api.providers.traccar_status_v1 import (
    TraccarStatusProvider, TraccarStatusRecord,
)
from api.providers.traccar_status_protocol_v1 import protocol_properties_to_record
from manager.auth.session_store import SessionPrincipal
from manager.worker_uds import (
    ENDPOINT, LEDGER_OPERATION, OPERATION, ROLE, WORKER_GROUP, WORKER_NAME,
    WorkerTransportError, query_status,
)
from worker.audit.ledger import AuditLedger, SHARED_STATUS_AUDIT_PATH

DASHBOARD_READ_ROLE = "dashboard.read"
TARGET = {"type": "systemd-unit", "id": "traccar.service"}
WORKER_STATUS_PROVIDER_ID = "manager.worker.traccar-status.v1"


class _WorkerStatusSource:
    provider_id = WORKER_STATUS_PROVIDER_ID

    def __init__(self, record: TraccarStatusRecord):
        self._record = record

    def read_status(self, _timeout_seconds: float) -> TraccarStatusRecord:
        return self._record


def _shared_audit_reader() -> AuditLedger:
    return AuditLedger(
        SHARED_STATUS_AUDIT_PATH,
        expected_owner_name=WORKER_NAME,
        expected_group_name=WORKER_GROUP,
        expected_file_mode=0o640,
        expected_directory_mode=0o750,
        read_only=True,
    )


class ManagerDashboardAPI:
    """Expose only verified Worker status; the Web never executes systemd."""

    def __init__(self, *, ledger: Any = None, worker_query=query_status):
        self._ledger = ledger if ledger is not None else _shared_audit_reader()
        self._worker_query = worker_query

    def read(self, request_id: str, principal: SessionPrincipal):
        if not isinstance(principal, SessionPrincipal):
            raise DashboardAPIError("API_UNAUTHORIZED")
        if DASHBOARD_READ_ROLE not in principal.roles:
            raise DashboardAPIError("API_FORBIDDEN")
        try:
            request = DashboardRequestDTO(request_id)
        except (TypeError, ValueError):
            raise DashboardAPIError("API_INVALID_REQUEST") from None

        if ROLE not in principal.roles:
            # Do not inspect the shared ledger or contact the UDS without the distinct role.
            return pending_snapshot(request.request_id)

        try:
            response = self._worker_query(request.request_id, principal.subject_id, principal.roles)
        except WorkerTransportError:
            raise DashboardAPIError("API_PROVIDER_UNAVAILABLE") from None
        except Exception:
            raise DashboardAPIError("API_PROVIDER_UNAVAILABLE") from None

        if not isinstance(response, dict) or set(response) != {"observed_at_utc", "properties", "audit_receipt"}:
            raise DashboardAPIError("API_PROVIDER_UNAVAILABLE")
        try:
            verified = self._ledger.verify_finalization_receipt(
                response["audit_receipt"],
                request_id=request.request_id,
                subject_id=principal.subject_id,
                role=ROLE,
                endpoint=ENDPOINT,
                protocol_operation=OPERATION,
                operation=LEDGER_OPERATION,
                target=TARGET,
            )
        except Exception:
            verified = False
        if verified is not True:
            raise DashboardAPIError("API_AUDIT_UNAVAILABLE")

        try:
            record = protocol_properties_to_record(response["properties"], response["observed_at_utc"])
            provider = TraccarStatusProvider(
                _WorkerStatusSource(record),
                allowed_source_ids=frozenset({WORKER_STATUS_PROVIDER_ID}),
            )
            general = provider.collect()
            pending = pending_snapshot(request.request_id)
            snapshot = replace(pending, general=general)
            return validate_snapshot(snapshot, request.request_id)
        except Exception:
            raise DashboardAPIError("API_PROVIDER_UNAVAILABLE") from None

    def verify_ledger(self):
        try:
            return self._ledger.verify()
        except Exception:
            return None

    def close(self):
        # The Web holds only a read-only view of the persistent Worker ledger.
        return None
