"""Audited RBAC read flow for the maintenance.logs.preview Worker operation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from typing import Any, Mapping
from uuid import UUID, uuid5

from worker.audit.ledger import AuditLedger, LedgerEvent, canonical_json
from worker.operations.log_retention_preview import MIN_RETENTION_DAYS, MAX_RETENTION_DAYS, preview_log_retention

OPERATION = "maintenance.logs.preview"
ROLE = "maintenance.logs.preview"
TARGET = {"type": "traccar-log-directory", "id": "/opt/traccar/logs"}
POLICY_ACTOR = {"subject_id": "rbac:maintenance.logs.preview", "actor_type": "policy"}
WORKER_ACTOR = {"subject_id": "traccar-manager-worker", "actor_type": "service"}
_NAMESPACE = UUID("a8764e9d-7442-43f1-b5b5-b97f74421d51")

class MaintenancePreviewError(RuntimeError):
    pass

def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()

def _event_id(request_id: str, event_type: str) -> str:
    return str(uuid5(_NAMESPACE, request_id + ":" + event_type))

def _stamp(value: datetime | None = None) -> str:
    return (value or datetime.now(timezone.utc)).isoformat(timespec="microseconds").replace("+00:00", "Z")

def _event(*, request_id: str, job_id: str, subject_id: str, parameters_hash: str,
           event_type: str, phase: str, actor: Mapping[str, Any], **kwargs: Any) -> LedgerEvent:
    requester = {"subject_id": subject_id, "actor_type": "human", "roles": [ROLE]}
    return LedgerEvent.create(
        event_id=_event_id(request_id, event_type), timestamp=kwargs.pop("timestamp", _stamp()),
        event_type=event_type, phase=phase, request_id=request_id, job_id=job_id,
        operation=OPERATION, actor=actor, requester=requester,
        parameters_hash=parameters_hash, target=TARGET, **kwargs,
    )

def _append(ledger: AuditLedger, event: LedgerEvent, *, authorization=False, prepare=False, result=False):
    try:
        if authorization:
            receipt = ledger.append_authorization(event)
        elif prepare:
            receipt = ledger.prepare_execution(event)
        elif result:
            receipt = ledger.record_result(event)
        else:
            receipt = ledger.append(event)
        if not receipt.durable or not ledger.verify_receipt(receipt):
            raise MaintenancePreviewError("AUDIT_UNAVAILABLE")
        return receipt
    except MaintenancePreviewError:
        raise
    except Exception:
        raise MaintenancePreviewError("AUDIT_UNAVAILABLE") from None

def execute(*, ledger: AuditLedger, request_id: str, subject_id: str,
            roles: tuple[str, ...], retention_days: int = 90) -> dict[str, Any]:
    if not isinstance(request_id, str) or not request_id or not isinstance(subject_id, str) or not subject_id:
        raise MaintenancePreviewError("INVALID_REQUEST")
    if not isinstance(roles, tuple) or ROLE not in roles:
        raise MaintenancePreviewError("FORBIDDEN")
    if type(retention_days) is not int or not MIN_RETENTION_DAYS <= retention_days <= MAX_RETENTION_DAYS:
        raise MaintenancePreviewError("INVALID_REQUEST")
    payload = {"retention_days": retention_days}
    parameters_hash = _digest(payload)
    job_id = "job-" + str(uuid5(_NAMESPACE, "job:" + request_id))
    requester = {"subject_id": subject_id, "actor_type": "human", "roles": [ROLE]}
    for event_type, phase, status in (
        ("REQUEST_RECEIVED", "REQUEST", "RECEIVED"),
        ("VALIDATION_PASSED", "VALIDATION", "PASSED"),
        ("PREVIEW_STARTED", "PREVIEW", "STARTED"),
    ):
        _append(ledger, _event(request_id=request_id, job_id=job_id, subject_id=subject_id,
                              parameters_hash=parameters_hash, event_type=event_type, phase=phase,
                              actor=requester, status=status))
    try:
        preview = preview_log_retention("/opt/traccar/logs", retention_days=retention_days)
    except Exception:
        raise MaintenancePreviewError("PREVIEW_FAILED") from None
    plan = {
        "log_dir": preview.log_dir, "retention_days": preview.retention_days, "cutoff_utc": preview.cutoff_utc,
        "candidate_count": preview.candidate_count, "candidate_bytes": preview.candidate_bytes,
        "candidates": [{"name": c.name, "size_bytes": c.size_bytes, "mtime_utc": c.mtime_utc} for c in preview.candidates],
        "active_log_protected": preview.active_log_protected,
        "destructive_action_performed": preview.destructive_action_performed,
    }
    preview_hash = _digest(plan)
    preview_id = "preview-" + preview_hash
    scope = {"operation": OPERATION, "target": TARGET, "parameters_hash": parameters_hash,
             "preview_hash": preview_hash}
    scope_hash = _digest(scope)
    _append(ledger, _event(request_id=request_id, job_id=job_id, subject_id=subject_id,
                          parameters_hash=parameters_hash, event_type="PREVIEW_COMPLETED", phase="PREVIEW",
                          actor=requester, status="COMPLETED", preview_id=preview_id,
                          preview_hash=preview_hash, authorization_scope_hash=scope_hash,
                          metadata={"candidate_count": plan["candidate_count"], "candidate_bytes": plan["candidate_bytes"]}))
    issued = datetime.now(timezone.utc)
    authorization_id = "auth-" + str(uuid5(_NAMESPACE, "auth:" + request_id))
    authorization = {
        "authorization_id": authorization_id, "requester": requester, "approver": POLICY_ACTOR,
        "operation": OPERATION, "target": TARGET, "preview_id": preview_id,
        "preview_hash": preview_hash, "timestamp": _stamp(issued),
        "expiration": _stamp(issued + timedelta(seconds=60)), "authorization_scope": scope,
        "parameters_hash": parameters_hash, "one_time_nonce": "nonce-" + str(uuid5(_NAMESPACE, authorization_id)),
        "decision": "PENDING", "approval_mode": "RBAC_READ",
    }
    common = dict(request_id=request_id, job_id=job_id, subject_id=subject_id,
                  parameters_hash=parameters_hash, preview_id=preview_id, preview_hash=preview_hash,
                  authorization_id=authorization_id, authorization_scope=scope,
                  authorization_scope_hash=scope_hash, approver=POLICY_ACTOR)
    _append(ledger, _event(**common, event_type="AUTHORIZATION_REQUESTED", phase="AUTHORIZATION",
                          actor=requester, status="REQUESTED", authorization=authorization), authorization=True)
    granted = dict(authorization, decision="GRANTED")
    _append(ledger, _event(**common, event_type="AUTHORIZATION_GRANTED", phase="AUTHORIZATION",
                          actor=POLICY_ACTOR, status="GRANTED", authorization=granted), authorization=True)
    _append(ledger, _event(**common, event_type="EXECUTION_STARTED", phase="AUDIT_PREPARE",
                          actor=WORKER_ACTOR, status="STARTED", authorization=granted), prepare=True)
    result = {"confirmed": True, "outcome": "SUCCEEDED", "preview": plan}
    _append(ledger, _event(**common, event_type="EXECUTION_COMPLETED", phase="AUDIT_RESULT",
                          actor=WORKER_ACTOR, status="COMPLETED", authorization=granted,
                          result_code="OK", result=result), result=True)
    _append(ledger, _event(**common, event_type="AUDIT_FINALIZED", phase="AUDIT_FINALIZATION",
                          actor=WORKER_ACTOR, status="FINALIZED", authorization=granted,
                          result_code="OK", result=result))
    report = ledger.verify()
    if not report.valid:
        raise MaintenancePreviewError("AUDIT_UNAVAILABLE")
    return {"preview": plan, "preview_id": preview_id}
