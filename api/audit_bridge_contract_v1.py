"""Non-executable design contract for dashboard API reads and audit status.

The Dispatcher now allowlists dashboard.snapshot.read.v1 with its fixed target,
role, and empty payload. This module does not bind HTTP requests to that path,
construct LedgerEvents, or call the ledger/dispatcher.
"""
from __future__ import annotations
from dataclasses import dataclass

from api.read_only_dashboard_v1 import AuditPhase, ReadAuditEvent

DASHBOARD_READ_OPERATION = "dashboard.snapshot.read.v1"
DASHBOARD_READ_TARGET_TYPE = "dashboard"
DASHBOARD_READ_TARGET_ID = "snapshot"
DASHBOARD_READ_REQUIRED_ROLE = "dashboard.read"
DASHBOARD_READ_ALLOWED_PAYLOAD_KEYS: tuple[str, ...] = ()
REQUIRED_API_READ_PHASES = (
    AuditPhase.PREVIEW, AuditPhase.AUTHORIZATION, AuditPhase.AUDIT_PREPARE,
    AuditPhase.EXECUTION, AuditPhase.RESULT, AuditPhase.AUDIT_FINALIZATION,
)


@dataclass(frozen=True, slots=True)
class AuditBridgePlan:
    operation: str = DASHBOARD_READ_OPERATION
    status: str = "HTTP_BINDING_IMPLEMENTED_PENDING_PRODUCTION_PROVIDER"
    dispatcher_operation_allowlisted: bool = True
    target_type: str = DASHBOARD_READ_TARGET_TYPE
    target_id: str = DASHBOARD_READ_TARGET_ID
    required_role: str = DASHBOARD_READ_REQUIRED_ROLE
    allowed_payload_keys: tuple[str, ...] = DASHBOARD_READ_ALLOWED_PAYLOAD_KEYS
    http_data_binding_implemented: bool = True
    dashboard_production_provider_connected: bool = False
    audit_ledger_survives_restart: bool = False
    direct_ledger_append_allowed: bool = False
    durable_receipt_required: bool = True
    final_receipt_verification_required: bool = True
    durable_idempotency_available: bool = False
    current_api_sink_returns_receipt: bool = False


AUDIT_BRIDGE_PLAN = AuditBridgePlan()


def read_idempotency_scope(request_id: str, actor_subject: str) -> tuple[str, str, str]:
    if not isinstance(request_id, str) or not request_id or not isinstance(actor_subject, str) or not actor_subject:
        raise ValueError("invalid idempotency scope")
    return DASHBOARD_READ_OPERATION, request_id, actor_subject


def complete_successful_read_audit(events: tuple[ReadAuditEvent, ...] | list[ReadAuditEvent],
                                   request_id: str, actor_subject: str) -> bool:
    """Validate an API mock-audit sequence; not a durable ledger receipt."""
    if not isinstance(events, (tuple, list)):
        return False
    relevant = [event for event in events if isinstance(event, ReadAuditEvent)
                and event.request_id == request_id and event.actor == actor_subject]
    if len(relevant) != len(REQUIRED_API_READ_PHASES):
        return False
    if tuple(event.phase for event in relevant) != REQUIRED_API_READ_PHASES:
        return False
    expected_results = ("PREVIEWED", "GRANTED", "READY", "STARTED", "SUCCEEDED", "FINALIZED")
    if tuple(event.result for event in relevant) != expected_results:
        return False
    return all(event.operation == DASHBOARD_READ_OPERATION
               and event.resource_type == "dashboard_snapshot"
               and event.error_code is None for event in relevant)
