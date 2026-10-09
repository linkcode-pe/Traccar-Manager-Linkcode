"""Isolated, fail-closed audit integration for the declarative dispatcher.

This module is a testable library only: it has no configured executor and does
not import, start, or contact the production status adapter/runtime.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from types import MappingProxyType
from typing import Any, Callable, FrozenSet, Mapping, Optional, Protocol
from uuid import UUID, uuid4, uuid5

from worker.audit.ledger import AuditLedger, LedgerError, LedgerEvent, canonical_json, utc_now


_OPERATION = "traccar.status"
_TARGET = MappingProxyType({"type": "systemd-unit", "id": "traccar.service"})
_PROPERTIES = frozenset({"LoadState", "ActiveState", "SubState", "UnitFileState", "Result"})
_POLICY_ACTOR = MappingProxyType({"subject_id": "rbac:traccar.status.read", "actor_type": "policy"})
_WORKER_IDENTITY = "dispatcher-v1-test-port"
_NAMESPACE = UUID("8aaf8cc4-8679-4f38-8cac-157fefc9c8b9")


class DispatchError(RuntimeError):
    """Sanitized error carrying only a stable audit-model code."""

    def __init__(self, code: str):
        allowed = {
            "E100_OPERATION_NOT_ALLOWED", "E101_INVALID_OPERATION", "E102_INVALID_TARGET",
            "E103_INVALID_PARAMETERS", "E104_UNAUTHORIZED_REQUESTER", "E200_PREVIEW_REQUIRED",
            "E201_PREVIEW_INVALID", "E202_PREVIEW_EXPIRED", "E203_PREVIEW_MISMATCH",
            "E300_AUTHORIZATION_REQUIRED", "E301_AUTHORIZATION_INVALID", "E302_AUTHORIZATION_EXPIRED",
            "E303_AUTHORIZATION_SCOPE_MISMATCH", "E304_AUTHORIZATION_ALREADY_USED",
            "E400_WORKER_NOT_AUTHORIZED", "E401_HELPER_NOT_AUTHORIZED", "E402_PRIVILEGE_INSUFFICIENT",
            "E403_IDENTITY_MISMATCH", "E500_EXECUTION_FAILED", "E501_EXECUTION_TIMEOUT",
            "E502_TARGET_UNAVAILABLE", "E503_OPERATION_ALREADY_RUNNING", "E700_AUDIT_UNAVAILABLE",
            "E701_AUDIT_WRITE_FAILED", "E702_AUDIT_INTEGRITY_FAILURE", "E800_CONCURRENCY_CONFLICT",
            "E801_JOB_NOT_FOUND", "E802_JOB_STATE_INVALID", "E803_AUTHORIZATION_SERVICE_UNAVAILABLE",
            "E900_INTERNAL_ERROR",
        }
        self.code = code if code in allowed else "E900_INTERNAL_ERROR"
        super().__init__(self.code)


@dataclass(frozen=True)
class Job:
    schema_version: int
    job_id: str
    operation: str
    payload: Mapping[str, Any]
    requested_by: str
    created_at_utc: str
    idempotency_key: str
    scheduled_at_utc: Optional[str] = None
    preview_id: Optional[str] = None
    authorization_id: Optional[str] = None
    request_id: Optional[str] = None


@dataclass(frozen=True)
class ActorContext:
    """Trusted identity context supplied by an authenticated caller."""

    subject: str
    roles: FrozenSet[str]


@dataclass(frozen=True)
class OperationSpec:
    required_role: str
    target: Mapping[str, str]
    allowed_payload_keys: FrozenSet[str]


@dataclass(frozen=True)
class Preview:
    preview_id: str
    preview_hash: str
    authorization_scope_hash: str
    parameters_hash: str
    plan: Mapping[str, Any]
    request_id: str
    job_id: str
    receipts: tuple[Any, ...]


@dataclass(frozen=True)
class AuthorizationGrant:
    authorization_id: str
    issued_at_utc: str
    expires_at_utc: str
    requester: Mapping[str, str]
    approver: Mapping[str, str]
    scope: Mapping[str, Any]
    scope_hash: str
    preview_id: str
    preview_hash: str
    parameters_hash: str
    receipts: tuple[Any, ...]


@dataclass(frozen=True)
class DashboardDispatchResult:
    request_id: str
    response: Mapping[str, Any]
    receipts: tuple[Any, ...]
    integrity_valid: bool


class ExecutorPort(Protocol):
    def __call__(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Return a structured confirmed status result; production port is unset."""
        ...


_DASHBOARD_OPERATION = "dashboard.snapshot.read.v1"
_DASHBOARD_TARGET = MappingProxyType({"type": "dashboard", "id": "snapshot"})
_DASHBOARD_ROLE = "dashboard.read"
_DASHBOARD_POLICY_ACTOR = MappingProxyType({"subject_id": "rbac:dashboard.read", "actor_type": "policy"})

_OPERATIONS = MappingProxyType({
    _OPERATION: OperationSpec(
        required_role="traccar.status.read",
        target=_TARGET,
        allowed_payload_keys=frozenset(),
    ),
    _DASHBOARD_OPERATION: OperationSpec(
        required_role=_DASHBOARD_ROLE,
        target=_DASHBOARD_TARGET,
        allowed_payload_keys=frozenset(),
    ),
})


def allowed_operations() -> tuple[str, ...]:
    """Return the allowlist without invoking any operation."""
    return tuple(sorted(_OPERATIONS))


def _request_id(job: Job) -> str:
    if job.request_id is not None:
        return job.request_id
    return "req-" + str(uuid5(_NAMESPACE, "request:" + job.idempotency_key))


def _event_id(job: Job, event_type: str) -> str:
    return str(uuid5(_NAMESPACE, _request_id(job) + ":" + job.job_id + ":" + event_type))


def _stamp(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise DispatchError("E103_INVALID_PARAMETERS")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise DispatchError("E103_INVALID_PARAMETERS") from None
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise DispatchError("E103_INVALID_PARAMETERS")
    return parsed


def _digest(value: Any) -> str:
    try:
        return hashlib.sha256(canonical_json(value)).hexdigest()
    except Exception:
        raise DispatchError("E103_INVALID_PARAMETERS") from None


def _identity(actor: ActorContext) -> dict[str, Any]:
    identity: dict[str, Any] = {"subject_id": actor.subject, "actor_type": "human"}
    if "traccar.status.read" in actor.roles:
        identity["roles"] = ["traccar.status.read"]
    return identity


def _validate(job: Job, actor: ActorContext, *, staged: bool = False) -> tuple[OperationSpec, str, dict[str, Any]]:
    if not isinstance(job, Job) or not isinstance(actor, ActorContext):
        raise DispatchError("E103_INVALID_PARAMETERS")
    if type(job.schema_version) is not int or job.schema_version != 1:
        raise DispatchError("E103_INVALID_PARAMETERS")
    for value in (job.job_id, job.requested_by, job.idempotency_key):
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise DispatchError("E103_INVALID_PARAMETERS")
    if not isinstance(job.created_at_utc, str) or not _valid_stamp(job.created_at_utc):
        raise DispatchError("E103_INVALID_PARAMETERS")
    if job.request_id is not None and (not isinstance(job.request_id, str) or not job.request_id.strip()):
        raise DispatchError("E103_INVALID_PARAMETERS")
    if actor.subject != job.requested_by or not isinstance(actor.subject, str) or not actor.subject.strip():
        raise DispatchError("E104_UNAUTHORIZED_REQUESTER")
    if not isinstance(actor.roles, frozenset) or any(not isinstance(role, str) for role in actor.roles):
        raise DispatchError("E104_UNAUTHORIZED_REQUESTER")
    spec = _OPERATIONS.get(job.operation)
    if spec is None:
        raise DispatchError("E100_OPERATION_NOT_ALLOWED")
    if not isinstance(job.payload, Mapping):
        raise DispatchError("E103_INVALID_PARAMETERS")
    payload = dict(job.payload)
    if set(payload) != set(spec.allowed_payload_keys):
        raise DispatchError("E103_INVALID_PARAMETERS")
    params_hash = _digest(payload)
    if not staged:
        if not isinstance(job.preview_id, str) or not job.preview_id.strip():
            raise DispatchError("E200_PREVIEW_REQUIRED")
        if not isinstance(job.authorization_id, str) or not job.authorization_id.strip():
            raise DispatchError("E300_AUTHORIZATION_REQUIRED")
    return spec, params_hash, payload


def _valid_stamp(value: str) -> bool:
    try:
        _stamp(value)
        return True
    except DispatchError:
        return False


def _event(job: Job, actor: Mapping[str, str], params_hash: str, event_type: str, phase: str,
           *, timestamp: Optional[str] = None, requester: Optional[Mapping[str, str]] = None,
           **kwargs: Any) -> LedgerEvent:
    spec = _OPERATIONS[_OPERATION]
    return LedgerEvent.create(
        event_id=_event_id(job, event_type), timestamp=timestamp or job.created_at_utc,
        event_type=event_type, phase=phase, request_id=_request_id(job), job_id=job.job_id,
        operation=_OPERATION, actor=actor, requester=requester or actor,
        parameters_hash=params_hash, target=spec.target, **kwargs,
    )


def _append_checked(ledger: AuditLedger, event: LedgerEvent, *, authorization: bool = False,
                    prepare: bool = False, result: bool = False) -> Any:
    try:
        if authorization:
            receipt = ledger.append_authorization(event)
        elif prepare:
            receipt = ledger.prepare_execution(event)
        elif result:
            receipt = ledger.record_result(event)
        else:
            receipt = ledger.append(event)
        if not getattr(receipt, "durable", False) or not ledger.verify_receipt(receipt):
            raise DispatchError("E700_AUDIT_UNAVAILABLE")
        return receipt
    except DispatchError:
        raise
    except LedgerError as exc:
        code = getattr(exc, "code", "E700_AUDIT_UNAVAILABLE")
        raise DispatchError(code) from None
    except Exception:
        raise DispatchError("E700_AUDIT_UNAVAILABLE") from None


def _make_plan() -> dict[str, Any]:
    # Fixed declarative plan only. No status query, systemd access, or adapter call.
    return {
        "operation": _OPERATION,
        "target": dict(_TARGET),
        "payload": {},
        "executor_port": "status_query",
        "properties": sorted(_PROPERTIES),
    }


def _dashboard_plan() -> dict[str, Any]:
    return {
        "operation": _DASHBOARD_OPERATION,
        "target": dict(_DASHBOARD_TARGET),
        "payload": {},
        "executor_port": "dashboard_snapshot",
    }


def _dashboard_event(job: Job, actor: Mapping[str, str], params_hash: str,
                     event_type: str, phase: str, *, timestamp: Optional[str] = None,
                     requester: Optional[Mapping[str, str]] = None,
                     event_id: Optional[str] = None, **kwargs: Any) -> LedgerEvent:
    return LedgerEvent.create(
        event_id=event_id or _event_id(job, event_type),
        timestamp=timestamp or job.created_at_utc,
        event_type=event_type, phase=phase, request_id=_request_id(job),
        job_id=job.job_id, operation=_DASHBOARD_OPERATION,
        actor=actor, requester=requester or actor, parameters_hash=params_hash,
        target=_DASHBOARD_TARGET, **kwargs,
    )


def _create_dashboard_preview(ledger: AuditLedger, job: Job, actor: ActorContext) -> Preview:
    spec, params_hash, payload = _validate(job, actor, staged=True)
    if job.operation != _DASHBOARD_OPERATION or spec.required_role not in actor.roles:
        raise DispatchError("E104_UNAUTHORIZED_REQUESTER")
    requester = _identity(actor)
    entries = (
        ("REQUEST_RECEIVED", "REQUEST", {"metadata": {"idempotency_key": job.idempotency_key}}),
        ("VALIDATION_PASSED", "VALIDATION", {"status": "PASSED"}),
        ("PREVIEW_STARTED", "PREVIEW", {"status": "STARTED"}),
    )
    receipts = []
    for event_type, phase, extras in entries:
        event = _dashboard_event(job, requester, params_hash, event_type, phase,
                                 requester=requester, **extras)
        receipts.append(_append_checked(ledger, event))
    plan = _dashboard_plan()
    preview_hash = _digest(plan)
    preview_id = "preview-" + preview_hash
    scope_hash = _digest({"operation": _DASHBOARD_OPERATION,
                          "target": dict(spec.target),
                          "parameters_hash": params_hash,
                          "preview_hash": preview_hash})
    completed = _dashboard_event(
        job, requester, params_hash, "PREVIEW_COMPLETED", "PREVIEW",
        requester=requester, preview_id=preview_id, preview_hash=preview_hash,
        authorization_scope_hash=scope_hash, status="COMPLETED",
        metadata={"plan": plan},
    )
    receipts.append(_append_checked(ledger, completed))
    return Preview(preview_id, preview_hash, scope_hash, params_hash, plan,
                   _request_id(job), job.job_id, tuple(receipts))


def _record_dashboard_authorization(ledger: AuditLedger, job: Job, actor: ActorContext,
                                    preview: Preview, *, authorization_id: str,
                                    issued_at_utc: str, expires_at_utc: str) -> AuthorizationGrant:
    spec, params_hash, _ = _validate(job, actor, staged=True)
    if job.operation != _DASHBOARD_OPERATION or spec.required_role not in actor.roles:
        raise DispatchError("E104_UNAUTHORIZED_REQUESTER")
    if not isinstance(preview, Preview) or preview.job_id != job.job_id or preview.request_id != _request_id(job):
        raise DispatchError("E201_PREVIEW_INVALID")
    plan = _dashboard_plan()
    preview_hash = _digest(plan)
    if (dict(preview.plan) != plan or preview.preview_hash != preview_hash
            or preview.preview_id != "preview-" + preview_hash
            or preview.parameters_hash != params_hash):
        raise DispatchError("E203_PREVIEW_MISMATCH")
    if not isinstance(authorization_id, str) or not authorization_id.strip():
        raise DispatchError("E301_AUTHORIZATION_INVALID")
    try:
        issued, expires = _stamp(issued_at_utc), _stamp(expires_at_utc)
    except DispatchError:
        raise DispatchError("E301_AUTHORIZATION_INVALID") from None
    if expires <= issued or expires <= datetime.now(timezone.utc):
        raise DispatchError("E302_AUTHORIZATION_EXPIRED")
    requester = _identity(actor)
    approver = dict(_DASHBOARD_POLICY_ACTOR)
    scope = {"operation": _DASHBOARD_OPERATION, "target": dict(spec.target),
             "parameters_hash": params_hash, "preview_hash": preview_hash}
    scope_hash = _digest(scope)
    if scope_hash != preview.authorization_scope_hash:
        raise DispatchError("E203_PREVIEW_MISMATCH")
    issued = issued.isoformat(timespec="microseconds").replace("+00:00", "Z")
    expires = expires.isoformat(timespec="microseconds").replace("+00:00", "Z")
    authorization = {
        "authorization_id": authorization_id, "requester": requester,
        "approver": approver, "operation": _DASHBOARD_OPERATION,
        "target": dict(spec.target), "preview_id": preview.preview_id,
        "preview_hash": preview_hash, "timestamp": issued, "expiration": expires,
        "authorization_scope": scope, "parameters_hash": params_hash,
        "one_time_nonce": "nonce-" + str(uuid5(_NAMESPACE, authorization_id)),
        "decision": "PENDING", "approval_mode": "RBAC_READ",
    }
    requested = _dashboard_event(
        job, requester, params_hash, "AUTHORIZATION_REQUESTED", "AUTHORIZATION",
        timestamp=issued, requester=requester, approver=approver,
        authorization=authorization, authorization_id=authorization_id,
        preview_id=preview.preview_id, preview_hash=preview_hash,
        authorization_scope=scope, authorization_scope_hash=scope_hash,
        status="REQUESTED",
    )
    requested_receipt = _append_checked(ledger, requested, authorization=True)
    granted_payload = dict(authorization, decision="GRANTED")
    granted = _dashboard_event(
        job, approver, params_hash, "AUTHORIZATION_GRANTED", "AUTHORIZATION",
        timestamp=issued, requester=requester, approver=approver,
        authorization=granted_payload, authorization_id=authorization_id,
        preview_id=preview.preview_id, preview_hash=preview_hash,
        authorization_scope=scope, authorization_scope_hash=scope_hash,
        status="GRANTED",
    )
    granted_receipt = _append_checked(ledger, granted, authorization=True)
    return AuthorizationGrant(authorization_id, issued, expires, requester, approver,
                              scope, scope_hash, preview.preview_id, preview_hash,
                              params_hash, (requested_receipt, granted_receipt))


def _check_dashboard_stage_receipts(ledger: AuditLedger, job: Job, actor: ActorContext,
                                    preview: Preview, authorization: AuthorizationGrant) -> None:
    if not isinstance(preview, Preview) or not isinstance(authorization, AuthorizationGrant):
        raise DispatchError("E201_PREVIEW_INVALID")
    plan = _dashboard_plan()
    preview_hash = _digest(plan)
    params_hash = _digest(dict(job.payload))
    scope = {"operation": _DASHBOARD_OPERATION, "target": dict(_DASHBOARD_TARGET),
             "parameters_hash": params_hash, "preview_hash": preview_hash}
    if (job.operation != _DASHBOARD_OPERATION or preview.job_id != job.job_id
            or preview.request_id != _request_id(job) or preview.preview_id != job.preview_id
            or preview.preview_hash != preview_hash or dict(preview.plan) != plan
            or preview.parameters_hash != params_hash):
        raise DispatchError("E203_PREVIEW_MISMATCH")
    if (authorization.authorization_id != job.authorization_id
            or authorization.preview_id != preview.preview_id
            or authorization.preview_hash != preview.preview_hash
            or authorization.parameters_hash != params_hash
            or dict(authorization.scope) != scope
            or authorization.scope_hash != _digest(scope)):
        raise DispatchError("E303_AUTHORIZATION_SCOPE_MISMATCH")
    try:
        issued, expires = _stamp(authorization.issued_at_utc), _stamp(authorization.expires_at_utc)
    except DispatchError:
        raise DispatchError("E301_AUTHORIZATION_INVALID") from None
    if expires <= datetime.now(timezone.utc):
        raise DispatchError("E302_AUTHORIZATION_EXPIRED")
    if expires <= issued:
        raise DispatchError("E301_AUTHORIZATION_INVALID")
    expected = ("REQUEST_RECEIVED", "VALIDATION_PASSED", "PREVIEW_STARTED", "PREVIEW_COMPLETED")
    expected_auth = ("AUTHORIZATION_REQUESTED", "AUTHORIZATION_GRANTED")
    if len(preview.receipts) != len(expected) or len(authorization.receipts) != len(expected_auth):
        raise DispatchError("E201_PREVIEW_INVALID")
    for event_type, receipt in tuple(zip(expected, preview.receipts)) + tuple(zip(expected_auth, authorization.receipts)):
        if getattr(receipt, "event_id", None) != _event_id(job, event_type):
            raise DispatchError("E201_PREVIEW_INVALID")
        try:
            valid = ledger.verify_receipt(receipt)
        except Exception:
            valid = False
        if not valid:
            raise DispatchError("E700_AUDIT_UNAVAILABLE")
    try:
        report = ledger.verify()
    except Exception:
        raise DispatchError("E700_AUDIT_UNAVAILABLE") from None
    if not getattr(report, "valid", False):
        raise DispatchError("E702_AUDIT_INTEGRITY_FAILURE")
    if actor.subject != job.requested_by or _identity(actor) != dict(authorization.requester):
        raise DispatchError("E403_IDENTITY_MISMATCH")


def _safe_dashboard_tree(value: Any, depth: int = 0) -> bool:
    if depth > 12:
        return False
    if value is None or type(value) in (bool, int, float):
        return True
    if isinstance(value, str):
        return len(value) <= 4096 and not any(ord(ch) < 32 and ord(ch) not in (9, 10, 13) for ch in value)
    if isinstance(value, Mapping):
        if len(value) > 256:
            return False
        forbidden = ("password", "secret", "token", "cookie", "credential", "latitude",
                     "longitude", "coordinate", "address", "uniqueid", "sql", "raw_exception")
        return all(isinstance(key, str) and not any(item in key.lower() for item in forbidden)
                   and _safe_dashboard_tree(item, depth + 1) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return len(value) <= 512 and all(_safe_dashboard_tree(item, depth + 1) for item in value)
    return False


def _validate_dashboard_executor_result(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("confirmed") is not True:
        raise DispatchError("E900_INTERNAL_ERROR")
    result = dict(value)
    if result.get("outcome") == "FAILED":
        if set(result) != {"confirmed", "outcome", "error_code"} or result["error_code"] not in {
                "E500_EXECUTION_FAILED", "E501_EXECUTION_TIMEOUT", "E502_TARGET_UNAVAILABLE", "E900_INTERNAL_ERROR"}:
            raise DispatchError("E900_INTERNAL_ERROR")
        return result
    if set(result) != {"confirmed", "outcome", "observed_at_utc", "response"} or result["outcome"] != "SUCCEEDED":
        raise DispatchError("E900_INTERNAL_ERROR")
    response = result["response"]
    if not isinstance(response, Mapping) or not _safe_dashboard_tree(response):
        raise DispatchError("E900_INTERNAL_ERROR")
    try:
        encoded = canonical_json(dict(response))
    except Exception:
        raise DispatchError("E900_INTERNAL_ERROR") from None
    if len(encoded) > 131072 or not _valid_stamp(result["observed_at_utc"]):
        raise DispatchError("E900_INTERNAL_ERROR")
    return {"confirmed": True, "outcome": "SUCCEEDED",
            "observed_at_utc": result["observed_at_utc"], "response": dict(response)}


def _dashboard_finalize(ledger: AuditLedger, job: Job, actor: ActorContext, params_hash: str,
                        preview: Preview, authorization: AuthorizationGrant) -> Any:
    event = _dashboard_event(
        job, {"subject_id": "audit-ledger-v1", "actor_type": "service"}, params_hash,
        "AUDIT_FINALIZED", "AUDIT_FINALIZATION", timestamp=utc_now(),
        requester=_identity(actor), event_id=str(uuid4()),
        worker_identity="dispatcher-v1-dashboard-read",
        authorization_id=authorization.authorization_id, preview_id=preview.preview_id,
        preview_hash=preview.preview_hash, authorization_scope=dict(authorization.scope),
        authorization_scope_hash=authorization.scope_hash, status="FINALIZED",
    )
    receipt = _append_checked(ledger, event)
    try:
        report = ledger.verify()
    except Exception:
        raise DispatchError("E702_AUDIT_INTEGRITY_FAILURE") from None
    if not getattr(report, "valid", False):
        raise DispatchError("E702_AUDIT_INTEGRITY_FAILURE")
    return receipt


def _dashboard_failure_and_finalize(ledger: AuditLedger, job: Job, actor: ActorContext,
                                    params_hash: str, preview: Preview,
                                    authorization: AuthorizationGrant, code: str) -> None:
    event = _dashboard_event(
        job, {"subject_id": "dispatcher-v1-dashboard-read", "actor_type": "service"},
        params_hash, "EXECUTION_FAILED", "AUDIT_RESULT", timestamp=utc_now(),
        requester=_identity(actor), event_id=str(uuid4()),
        worker_identity="dispatcher-v1-dashboard-read",
        authorization_id=authorization.authorization_id, preview_id=preview.preview_id,
        preview_hash=preview.preview_hash, authorization_scope=dict(authorization.scope),
        authorization_scope_hash=authorization.scope_hash, error_code=code,
        result_code=code, result={"outcome": "FAILED", "error_code": code}, status="FAILED",
    )
    try:
        _append_checked(ledger, event, result=True)
        _dashboard_finalize(ledger, job, actor, params_hash, preview, authorization)
    except DispatchError:
        raise DispatchError("E701_AUDIT_WRITE_FAILED") from None


def _dispatch_dashboard_snapshot_read(job: Job, actor: ActorContext, *, ledger: AuditLedger,
                                      preview: Preview, authorization: AuthorizationGrant,
                                      executor: Optional[ExecutorPort] = None) -> DashboardDispatchResult:
    if os.geteuid() == 0:
        raise DispatchError("E402_PRIVILEGE_INSUFFICIENT")
    spec, params_hash, payload = _validate(job, actor, staged=False)
    if spec.required_role not in actor.roles:
        raise DispatchError("E104_UNAUTHORIZED_REQUESTER")
    _check_dashboard_stage_receipts(ledger, job, actor, preview, authorization)
    if executor is None or not callable(executor):
        raise DispatchError("E401_HELPER_NOT_AUTHORIZED")
    prepare = _dashboard_event(
        job, {"subject_id": "dispatcher-v1-dashboard-read", "actor_type": "service"},
        params_hash, "EXECUTION_STARTED", "AUDIT_PREPARE", timestamp=utc_now(),
        requester=_identity(actor), event_id=str(uuid4()),
        worker_identity="dispatcher-v1-dashboard-read", approver=dict(_DASHBOARD_POLICY_ACTOR),
        authorization_id=authorization.authorization_id, preview_id=preview.preview_id,
        preview_hash=preview.preview_hash, authorization_scope=dict(authorization.scope),
        authorization_scope_hash=authorization.scope_hash, status="STARTED",
    )
    try:
        prepare_receipt = _append_checked(ledger, prepare, prepare=True)
    except DispatchError:
        raise
    if not ledger.verify_receipt(prepare_receipt):
        raise DispatchError("E700_AUDIT_UNAVAILABLE")
    try:
        normalized = _validate_dashboard_executor_result(executor(dict(payload)))
    except DispatchError as exc:
        _dashboard_failure_and_finalize(ledger, job, actor, params_hash, preview,
                                        authorization, exc.code)
        raise
    except Exception:
        _dashboard_failure_and_finalize(ledger, job, actor, params_hash, preview,
                                        authorization, "E900_INTERNAL_ERROR")
        raise DispatchError("E900_INTERNAL_ERROR") from None
    if normalized["outcome"] == "FAILED":
        code = normalized["error_code"]
        _dashboard_failure_and_finalize(ledger, job, actor, params_hash, preview, authorization, code)
        raise DispatchError(code)
    audit_result = {"confirmed": True, "outcome": "SUCCEEDED",
                    "observed_at_utc": normalized["observed_at_utc"],
                    "result_code": "DASHBOARD_READ_SUCCEEDED"}
    result_event = _dashboard_event(
        job, {"subject_id": "dispatcher-v1-dashboard-read", "actor_type": "service"},
        params_hash, "EXECUTION_COMPLETED", "AUDIT_RESULT", timestamp=utc_now(),
        requester=_identity(actor), event_id=str(uuid4()),
        worker_identity="dispatcher-v1-dashboard-read",
        authorization_id=authorization.authorization_id, preview_id=preview.preview_id,
        preview_hash=preview.preview_hash, authorization_scope=dict(authorization.scope),
        authorization_scope_hash=authorization.scope_hash, result=audit_result,
        result_code="SUCCEEDED", status="COMPLETED",
    )
    try:
        result_receipt = _append_checked(ledger, result_event, result=True)
        final_receipt = _dashboard_finalize(ledger, job, actor, params_hash, preview, authorization)
    except DispatchError:
        raise DispatchError("E701_AUDIT_WRITE_FAILED") from None
    receipts = tuple(preview.receipts) + tuple(authorization.receipts) + (prepare_receipt, result_receipt, final_receipt)
    if not all(getattr(receipt, "durable", False) for receipt in receipts):
        raise DispatchError("E701_AUDIT_WRITE_FAILED")
    return DashboardDispatchResult(_request_id(job), normalized["response"], receipts, True)


def create_preview(ledger: AuditLedger, job: Job, actor: ActorContext) -> Preview:
    """Append an idempotent request/validation/static-preview sequence."""
    if isinstance(job, Job) and job.operation == _DASHBOARD_OPERATION:
        return _create_dashboard_preview(ledger, job, actor)
    spec, params_hash, payload = _validate(job, actor, staged=True)
    if spec.required_role not in actor.roles:
        raise DispatchError("E104_UNAUTHORIZED_REQUESTER")
    requester = _identity(actor)
    req = _event(job, requester, params_hash, "REQUEST_RECEIVED", "REQUEST",
                 metadata={"idempotency_key": job.idempotency_key})
    req_receipt = _append_checked(ledger, req)
    validation = _event(job, requester, params_hash, "VALIDATION_PASSED", "VALIDATION",
                        requester=requester, status="PASSED")
    validation_receipt = _append_checked(ledger, validation)
    preview_started = _event(job, requester, params_hash, "PREVIEW_STARTED", "PREVIEW",
                             requester=requester, status="STARTED")
    started_receipt = _append_checked(ledger, preview_started)
    plan = _make_plan()
    preview_hash = _digest(plan)
    preview_id = "preview-" + preview_hash
    scope = {"operation": _OPERATION, "target": dict(spec.target),
             "parameters_hash": params_hash, "preview_hash": preview_hash}
    scope_hash = _digest(scope)
    completed = _event(job, requester, params_hash, "PREVIEW_COMPLETED", "PREVIEW",
                       requester=requester, preview_id=preview_id, preview_hash=preview_hash,
                       authorization_scope_hash=scope_hash, status="COMPLETED",
                       metadata={"plan": plan})
    completed_receipt = _append_checked(ledger, completed)
    return Preview(preview_id, preview_hash, scope_hash, params_hash, plan,
                   _request_id(job), job.job_id,
                   (req_receipt, validation_receipt, started_receipt, completed_receipt))


def record_authorization(ledger: AuditLedger, job: Job, actor: ActorContext, preview: Preview, *,
                         authorization_id: str, issued_at_utc: str, expires_at_utc: str) -> AuthorizationGrant:
    """Record the separate RBAC_READ decision; this function never dispatches."""
    if isinstance(job, Job) and job.operation == _DASHBOARD_OPERATION:
        return _record_dashboard_authorization(
            ledger, job, actor, preview, authorization_id=authorization_id,
            issued_at_utc=issued_at_utc, expires_at_utc=expires_at_utc,
        )
    spec, params_hash, _ = _validate(job, actor, staged=True)
    if spec.required_role not in actor.roles:
        raise DispatchError("E104_UNAUTHORIZED_REQUESTER")
    if not isinstance(preview, Preview) or preview.job_id != job.job_id or preview.request_id != _request_id(job):
        raise DispatchError("E201_PREVIEW_INVALID")
    expected_plan = _make_plan()
    preview_hash = _digest(expected_plan)
    if (dict(preview.plan) != expected_plan or preview.preview_hash != preview_hash
            or preview.preview_id != "preview-" + preview_hash or preview.parameters_hash != params_hash):
        raise DispatchError("E203_PREVIEW_MISMATCH")
    if not isinstance(authorization_id, str) or not authorization_id.strip():
        raise DispatchError("E301_AUTHORIZATION_INVALID")
    try:
        issued = _stamp(issued_at_utc)
        expires = _stamp(expires_at_utc)
    except DispatchError:
        raise DispatchError("E301_AUTHORIZATION_INVALID") from None
    if expires <= issued or expires <= datetime.now(timezone.utc):
        raise DispatchError("E302_AUTHORIZATION_EXPIRED")
    requester = _identity(actor)
    approver = dict(_POLICY_ACTOR)
    scope = {"operation": _OPERATION, "target": dict(spec.target),
             "parameters_hash": params_hash, "preview_hash": preview_hash}
    scope_hash = _digest(scope)
    if scope_hash != preview.authorization_scope_hash:
        raise DispatchError("E203_PREVIEW_MISMATCH")
    issued = issued.isoformat(timespec="microseconds").replace("+00:00", "Z")
    expires = expires.isoformat(timespec="microseconds").replace("+00:00", "Z")
    auth_payload = {
        "authorization_id": authorization_id, "requester": requester, "approver": approver,
        "operation": _OPERATION, "target": dict(spec.target), "preview_id": preview.preview_id,
        "preview_hash": preview_hash, "timestamp": issued, "expiration": expires,
        "authorization_scope": scope, "parameters_hash": params_hash,
        "one_time_nonce": "nonce-" + str(uuid5(_NAMESPACE, authorization_id)),
        "decision": "PENDING", "approval_mode": "RBAC_READ",
    }
    requested = _event(job, requester, params_hash, "AUTHORIZATION_REQUESTED", "AUTHORIZATION",
                       timestamp=issued, requester=requester, approver=approver,
                       authorization=auth_payload, authorization_id=authorization_id,
                       preview_id=preview.preview_id, preview_hash=preview_hash,
                       authorization_scope=scope, authorization_scope_hash=scope_hash,
                       status="REQUESTED")
    requested_receipt = _append_checked(ledger, requested, authorization=True)
    granted_payload = dict(auth_payload, decision="GRANTED")
    granted = _event(job, approver, params_hash, "AUTHORIZATION_GRANTED", "AUTHORIZATION",
                     timestamp=issued, requester=requester, approver=approver,
                     authorization=granted_payload, authorization_id=authorization_id,
                     preview_id=preview.preview_id, preview_hash=preview_hash,
                     authorization_scope=scope, authorization_scope_hash=scope_hash,
                     status="GRANTED")
    granted_receipt = _append_checked(ledger, granted, authorization=True)
    return AuthorizationGrant(authorization_id, issued, expires, requester, approver, scope,
                              scope_hash, preview.preview_id, preview_hash, params_hash,
                              (requested_receipt, granted_receipt))


def _check_stage_receipts(ledger: AuditLedger, job: Job, actor: ActorContext,
                          preview: Preview, authorization: AuthorizationGrant) -> None:
    if not isinstance(preview, Preview) or not isinstance(authorization, AuthorizationGrant):
        raise DispatchError("E201_PREVIEW_INVALID")
    expected_plan = _make_plan()
    expected_hash = _digest(expected_plan)
    if (preview.job_id != job.job_id or preview.request_id != _request_id(job)
            or preview.preview_id != job.preview_id or preview.preview_hash != expected_hash
            or preview.preview_id != "preview-" + expected_hash
            or dict(preview.plan) != expected_plan or preview.parameters_hash != _digest(dict(job.payload))):
        raise DispatchError("E203_PREVIEW_MISMATCH")
    if (authorization.authorization_id != job.authorization_id
            or authorization.preview_id != preview.preview_id
            or authorization.preview_hash != preview.preview_hash
            or authorization.parameters_hash != preview.parameters_hash
            or dict(authorization.scope) != {"operation": _OPERATION, "target": dict(_TARGET),
                                             "parameters_hash": preview.parameters_hash,
                                             "preview_hash": preview.preview_hash}
            or authorization.scope_hash != _digest(dict(authorization.scope))):
        raise DispatchError("E303_AUTHORIZATION_SCOPE_MISMATCH")
    try:
        expires = _stamp(authorization.expires_at_utc)
        issued = _stamp(authorization.issued_at_utc)
    except DispatchError:
        raise DispatchError("E301_AUTHORIZATION_INVALID") from None
    if expires <= datetime.now(timezone.utc):
        raise DispatchError("E302_AUTHORIZATION_EXPIRED")
    if expires <= issued:
        raise DispatchError("E301_AUTHORIZATION_INVALID")
    expected_types = ("REQUEST_RECEIVED", "VALIDATION_PASSED", "PREVIEW_STARTED", "PREVIEW_COMPLETED")
    expected_auth_types = ("AUTHORIZATION_REQUESTED", "AUTHORIZATION_GRANTED")
    if len(preview.receipts) != len(expected_types) or len(authorization.receipts) != len(expected_auth_types):
        raise DispatchError("E201_PREVIEW_INVALID")
    all_receipts = tuple(zip(expected_types, preview.receipts)) + tuple(zip(expected_auth_types, authorization.receipts))
    for event_type, receipt in all_receipts:
        if getattr(receipt, "event_id", None) != _event_id(job, event_type):
            raise DispatchError("E201_PREVIEW_INVALID")
        try:
            valid = ledger.verify_receipt(receipt)
        except Exception:
            valid = False
        if not valid:
            raise DispatchError("E700_AUDIT_UNAVAILABLE")
    # Independent chain verification is required before the execution gate.
    try:
        report = ledger.verify()
    except Exception:
        raise DispatchError("E700_AUDIT_UNAVAILABLE") from None
    if not getattr(report, "valid", False):
        raise DispatchError("E702_AUDIT_INTEGRITY_FAILURE")
    if actor.subject != job.requested_by or _identity(actor) != dict(authorization.requester):
        raise DispatchError("E403_IDENTITY_MISMATCH")


def _deny(ledger: AuditLedger, job: Job, actor: ActorContext, params_hash: str,
          code: str, authorization: Optional[AuthorizationGrant], preview: Optional[Preview]) -> None:
    """Best-effort terminal denial from a staged, not-yet-executing job."""
    if not isinstance(preview, Preview) or not isinstance(authorization, AuthorizationGrant):
        return
    try:
        denial = _event(job, dict(_POLICY_ACTOR), params_hash, "EXECUTION_DENIED", "EXECUTION",
                        timestamp=utc_now(), requester=_identity(actor),
                        approver=dict(_POLICY_ACTOR), authorization_id=job.authorization_id,
                        preview_id=job.preview_id, preview_hash=preview.preview_hash,
                        authorization_scope=authorization.scope,
                        authorization_scope_hash=authorization.scope_hash,
                        error_code=code, status="DENIED")
        _append_checked(ledger, denial)
        rejected = _event(job, dict(_POLICY_ACTOR), params_hash, "JOB_REJECTED", "EXECUTION",
                          timestamp=utc_now(), requester=_identity(actor),
                          authorization_id=job.authorization_id, preview_id=job.preview_id,
                          preview_hash=preview.preview_hash, error_code=code, status="REJECTED")
        _append_checked(ledger, rejected)
        finalized = _event(job, dict(_POLICY_ACTOR), params_hash, "AUDIT_FINALIZED", "AUDIT_FINALIZATION",
                           timestamp=utc_now(), requester=_identity(actor),
                           authorization_id=job.authorization_id, preview_id=job.preview_id,
                           preview_hash=preview.preview_hash, authorization_scope=authorization.scope,
                           authorization_scope_hash=authorization.scope_hash, status="FINALIZED")
        _append_checked(ledger, finalized)
    except DispatchError:
        # A denial must never become permission to execute if its audit failed.
        return


def dispatch_job(job: Job, actor: ActorContext, *, ledger: AuditLedger,
                 preview: Preview, authorization: AuthorizationGrant,
                 executor: Optional[ExecutorPort] = None) -> dict[str, Any] | DashboardDispatchResult:
    """Audit-prepare then call only an explicitly injected executor port."""
    if isinstance(job, Job) and job.operation == _DASHBOARD_OPERATION:
        return _dispatch_dashboard_snapshot_read(
            job, actor, ledger=ledger, preview=preview,
            authorization=authorization, executor=executor,
        )
    if os.geteuid() == 0:
        raise DispatchError("E402_PRIVILEGE_INSUFFICIENT")
    spec, params_hash, payload = _validate(job, actor, staged=False)
    if spec.required_role not in actor.roles:
        _deny(ledger, job, actor, params_hash, "E104_UNAUTHORIZED_REQUESTER", authorization, preview)
        raise DispatchError("E104_UNAUTHORIZED_REQUESTER")
    try:
        _check_stage_receipts(ledger, job, actor, preview, authorization)
    except DispatchError as exc:
        _deny(ledger, job, actor, params_hash, exc.code, authorization, preview)
        raise
    if executor is None or not callable(executor):
        _deny(ledger, job, actor, params_hash, "E401_HELPER_NOT_AUTHORIZED", authorization, preview)
        raise DispatchError("E401_HELPER_NOT_AUTHORIZED")

    prepare = LedgerEvent.create(
        event_type="EXECUTION_STARTED", phase="AUDIT_PREPARE", timestamp=utc_now(),
        request_id=_request_id(job), job_id=job.job_id, operation=_OPERATION,
        actor={"subject_id": _WORKER_IDENTITY, "actor_type": "service"},
        requester=_identity(actor), parameters_hash=params_hash, target=spec.target,
        worker_identity=_WORKER_IDENTITY, approver=dict(_POLICY_ACTOR),
        authorization_id=authorization.authorization_id, preview_id=preview.preview_id,
        preview_hash=preview.preview_hash, authorization_scope=dict(authorization.scope),
        authorization_scope_hash=authorization.scope_hash, status="STARTED",
    )
    # A unique start event ID ensures a replay reaches the ledger's one-use check
    # rather than receiving an idempotent receipt for an earlier execution.
    try:
        prepare_receipt = _append_checked(ledger, prepare, prepare=True)
    except DispatchError as exc:
        if exc.code == "E304_AUTHORIZATION_ALREADY_USED":
            raise
        raise
    # Must verify a durable receipt before crossing the injected executor port.
    if not getattr(prepare_receipt, "durable", False) or not ledger.verify_receipt(prepare_receipt):
        raise DispatchError("E700_AUDIT_UNAVAILABLE")

    try:
        raw_result = executor(dict(payload))
    except Exception:
        _write_failure_and_finalize(ledger, job, actor, params_hash, preview, authorization,
                                    "E900_INTERNAL_ERROR")
        raise DispatchError("E900_INTERNAL_ERROR") from None
    try:
        normalized = _validate_executor_result(raw_result)
    except DispatchError:
        _write_failure_and_finalize(ledger, job, actor, params_hash, preview, authorization,
                                    "E900_INTERNAL_ERROR")
        raise DispatchError("E900_INTERNAL_ERROR") from None
    if normalized["outcome"] == "FAILED":
        code = normalized["error_code"]
        _write_failure_and_finalize(ledger, job, actor, params_hash, preview, authorization, code,
                                    result=normalized)
        raise DispatchError(code)
    result_event = LedgerEvent.create(
        event_type="EXECUTION_COMPLETED", phase="AUDIT_RESULT", timestamp=utc_now(),
        request_id=_request_id(job), job_id=job.job_id, operation=_OPERATION,
        actor={"subject_id": _WORKER_IDENTITY, "actor_type": "service"},
        requester=_identity(actor), parameters_hash=params_hash, target=spec.target,
        worker_identity=_WORKER_IDENTITY, authorization_id=authorization.authorization_id,
        preview_id=preview.preview_id, preview_hash=preview.preview_hash,
        authorization_scope=dict(authorization.scope), authorization_scope_hash=authorization.scope_hash,
        result=normalized, result_code="SUCCEEDED", status="COMPLETED",
    )
    try:
        result_receipt = _append_checked(ledger, result_event, result=True)
        if not ledger.verify_receipt(result_receipt):
            raise DispatchError("E701_AUDIT_WRITE_FAILED")
        _finalize(ledger, job, actor, params_hash, preview, authorization)
    except DispatchError:
        # Execution may have happened; do not report success or replay it.
        raise DispatchError("E701_AUDIT_WRITE_FAILED") from None
    return dict(normalized)


def _validate_executor_result(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DispatchError("E900_INTERNAL_ERROR")
    result = dict(value)
    if result.get("confirmed") is not True:
        raise DispatchError("E900_INTERNAL_ERROR")
    outcome = result.get("outcome")
    if outcome == "FAILED":
        if set(result) != {"confirmed", "outcome", "error_code"}:
            raise DispatchError("E900_INTERNAL_ERROR")
        if result["error_code"] not in {"E500_EXECUTION_FAILED", "E501_EXECUTION_TIMEOUT",
                                        "E502_TARGET_UNAVAILABLE", "E900_INTERNAL_ERROR"}:
            raise DispatchError("E900_INTERNAL_ERROR")
        return result
    required = {"confirmed", "outcome", "observed_at_utc", "source", "unit", "properties"}
    if outcome != "SUCCEEDED" or set(result) != required:
        raise DispatchError("E900_INTERNAL_ERROR")
    if result["source"] != "systemd" or result["unit"] != "traccar.service" or not _valid_stamp(result["observed_at_utc"]):
        raise DispatchError("E900_INTERNAL_ERROR")
    properties = result["properties"]
    if (not isinstance(properties, Mapping) or set(properties) != _PROPERTIES
            or any(not isinstance(item, str) for item in properties.values())):
        raise DispatchError("E900_INTERNAL_ERROR")
    return {"confirmed": True, "outcome": "SUCCEEDED", "observed_at_utc": result["observed_at_utc"],
            "source": "systemd", "unit": "traccar.service", "properties": dict(properties)}


def _write_failure_and_finalize(ledger: AuditLedger, job: Job, actor: ActorContext,
                                params_hash: str, preview: Preview,
                                authorization: AuthorizationGrant, code: str,
                                result: Optional[Mapping[str, Any]] = None) -> None:
    event = LedgerEvent.create(
        event_type="EXECUTION_FAILED", phase="AUDIT_RESULT", timestamp=utc_now(),
        request_id=_request_id(job), job_id=job.job_id, operation=_OPERATION,
        actor={"subject_id": _WORKER_IDENTITY, "actor_type": "service"},
        requester=_identity(actor), parameters_hash=params_hash, target=_TARGET,
        worker_identity=_WORKER_IDENTITY, authorization_id=authorization.authorization_id,
        preview_id=preview.preview_id, preview_hash=preview.preview_hash,
        authorization_scope=dict(authorization.scope), authorization_scope_hash=authorization.scope_hash,
        error_code=code, result_code=code, result=dict(result) if result is not None else None,
        status="FAILED",
    )
    try:
        receipt = _append_checked(ledger, event, result=True)
        if not ledger.verify_receipt(receipt):
            raise DispatchError("E701_AUDIT_WRITE_FAILED")
        _finalize(ledger, job, actor, params_hash, preview, authorization)
    except DispatchError:
        raise DispatchError("E701_AUDIT_WRITE_FAILED") from None


def _finalize(ledger: AuditLedger, job: Job, actor: ActorContext, params_hash: str,
              preview: Preview, authorization: AuthorizationGrant) -> None:
    event = LedgerEvent.create(
        event_type="AUDIT_FINALIZED", phase="AUDIT_FINALIZATION", timestamp=utc_now(),
        request_id=_request_id(job), job_id=job.job_id, operation=_OPERATION,
        actor={"subject_id": "audit-ledger-v1", "actor_type": "service"},
        requester=_identity(actor), parameters_hash=params_hash, target=_TARGET,
        worker_identity=_WORKER_IDENTITY, authorization_id=authorization.authorization_id,
        preview_id=preview.preview_id, preview_hash=preview.preview_hash,
        authorization_scope=dict(authorization.scope), authorization_scope_hash=authorization.scope_hash,
        status="FINALIZED",
    )
    receipt = _append_checked(ledger, event)
    if not ledger.verify_receipt(receipt):
        raise DispatchError("E701_AUDIT_WRITE_FAILED")
    try:
        report = ledger.verify()
    except Exception:
        raise DispatchError("E702_AUDIT_INTEGRITY_FAILURE") from None
    if not getattr(report, "valid", False):
        raise DispatchError("E702_AUDIT_INTEGRITY_FAILURE")
