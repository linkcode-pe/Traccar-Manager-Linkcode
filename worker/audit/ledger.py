"""Isolated append-only JSONL audit ledger; not connected to the runtime."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import fcntl
import grp
import hashlib
import json
import os
import pwd
from pathlib import Path
import re
import stat
from typing import Any, Mapping, Optional
from uuid import UUID, uuid4

DOMAIN_SEPARATOR = b"TRACCAR-MANAGER-AUDIT-V1\x00"
GENESIS_HASH = "0" * 64
SHARED_STATUS_AUDIT_PATH = "/var/lib/traccar-manager-worker/audit.jsonl"
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_OPERATION_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_EVENT_TYPES = frozenset({
    "REQUEST_RECEIVED", "VALIDATION_PASSED", "VALIDATION_FAILED",
    "PREVIEW_STARTED", "PREVIEW_COMPLETED", "PREVIEW_FAILED",
    "AUTHORIZATION_REQUESTED", "AUTHORIZATION_GRANTED", "AUTHORIZATION_DENIED",
    "EXECUTION_STARTED", "EXECUTION_COMPLETED", "EXECUTION_FAILED", "EXECUTION_DENIED",
    "ROLLBACK_STARTED", "ROLLBACK_COMPLETED", "ROLLBACK_FAILED",
    "AUDIT_WRITE_FAILED", "JOB_REJECTED", "AUDIT_FINALIZED",
    "AUDIT_INTEGRITY_FAILURE", "AUDIT_RECONCILIATION",
})
_ERROR_CODES = frozenset({
    "E100_OPERATION_NOT_ALLOWED", "E101_INVALID_OPERATION", "E102_INVALID_TARGET",
    "E103_INVALID_PARAMETERS", "E104_UNAUTHORIZED_REQUESTER", "E200_PREVIEW_REQUIRED",
    "E201_PREVIEW_INVALID", "E202_PREVIEW_EXPIRED", "E203_PREVIEW_MISMATCH",
    "E300_AUTHORIZATION_REQUIRED", "E301_AUTHORIZATION_INVALID", "E302_AUTHORIZATION_EXPIRED",
    "E303_AUTHORIZATION_SCOPE_MISMATCH", "E304_AUTHORIZATION_ALREADY_USED",
    "E400_WORKER_NOT_AUTHORIZED", "E401_HELPER_NOT_AUTHORIZED", "E402_PRIVILEGE_INSUFFICIENT",
    "E403_IDENTITY_MISMATCH", "E500_EXECUTION_FAILED", "E501_EXECUTION_TIMEOUT",
    "E502_TARGET_UNAVAILABLE", "E503_OPERATION_ALREADY_RUNNING", "E600_ROLLBACK_REQUIRED",
    "E601_ROLLBACK_FAILED", "E602_ROLLBACK_NOT_SUPPORTED", "E700_AUDIT_UNAVAILABLE",
    "E701_AUDIT_WRITE_FAILED", "E702_AUDIT_INTEGRITY_FAILURE", "E800_CONCURRENCY_CONFLICT",
    "E801_JOB_NOT_FOUND", "E802_JOB_STATE_INVALID", "E803_AUTHORIZATION_SERVICE_UNAVAILABLE",
    "E900_INTERNAL_ERROR",
})
_ROLLBACK_STATES = frozenset({
    "NOT_APPLICABLE", "NOT_STARTED", "REQUIRED", "IN_PROGRESS", "COMPLETED", "FAILED", "NOT_SUPPORTED"
})
_BASE_FIELDS = frozenset({
    "event_id", "event_type", "event_version", "timestamp", "request_id", "job_id",
    "operation", "operation_version", "phase", "actor", "requester", "approver",
    "worker_identity", "helper_identity", "target", "authorization", "authorization_id",
    "preview_id", "preview_hash", "authorization_scope", "authorization_scope_hash",
    "parameters_hash", "status", "error_code", "result_code", "result",
    "rollback_status", "duration_ms", "metadata",
})
_CHAIN_FIELDS = frozenset({
    "ledger_sequence", "previous_event_id", "previous_event_hash", "previous_hash", "event_hash"
})
_PHASES = frozenset({
    "REQUEST", "VALIDATION", "PREVIEW", "AUTHORIZATION", "AUDIT_PREPARE",
    "EXECUTION", "AUDIT_RESULT", "ROLLBACK", "AUDIT_FINALIZATION",
})
_PHASES_BY_EVENT = {
    "REQUEST_RECEIVED": frozenset({"REQUEST"}),
    "VALIDATION_PASSED": frozenset({"VALIDATION"}),
    "VALIDATION_FAILED": frozenset({"VALIDATION"}),
    "PREVIEW_STARTED": frozenset({"PREVIEW"}),
    "PREVIEW_COMPLETED": frozenset({"PREVIEW"}),
    "PREVIEW_FAILED": frozenset({"PREVIEW"}),
    "AUTHORIZATION_REQUESTED": frozenset({"AUTHORIZATION"}),
    "AUTHORIZATION_GRANTED": frozenset({"AUTHORIZATION"}),
    "AUTHORIZATION_DENIED": frozenset({"AUTHORIZATION"}),
    "EXECUTION_STARTED": frozenset({"AUDIT_PREPARE"}),
    "EXECUTION_DENIED": frozenset({"EXECUTION"}),
    "EXECUTION_COMPLETED": frozenset({"AUDIT_RESULT"}),
    "EXECUTION_FAILED": frozenset({"AUDIT_RESULT"}),
    "ROLLBACK_STARTED": frozenset({"ROLLBACK"}),
    "ROLLBACK_COMPLETED": frozenset({"ROLLBACK"}),
    "ROLLBACK_FAILED": frozenset({"ROLLBACK"}),
    "AUDIT_WRITE_FAILED": frozenset({"AUDIT_PREPARE", "AUDIT_RESULT", "AUDIT_FINALIZATION"}),
    "JOB_REJECTED": frozenset({"REQUEST", "VALIDATION", "PREVIEW", "AUTHORIZATION", "EXECUTION"}),
    "AUDIT_FINALIZED": frozenset({"AUDIT_FINALIZATION"}),
    "AUDIT_INTEGRITY_FAILURE": frozenset({"AUDIT_FINALIZATION"}),
    "AUDIT_RECONCILIATION": frozenset({"AUDIT_FINALIZATION"}),
}
_TRANSITIONS = {
    "REQUEST_RECEIVED": frozenset({"VALIDATION_PASSED", "VALIDATION_FAILED"}),
    "VALIDATION_PASSED": frozenset({"PREVIEW_STARTED"}),
    "VALIDATION_FAILED": frozenset({"JOB_REJECTED"}),
    "PREVIEW_STARTED": frozenset({"PREVIEW_COMPLETED", "PREVIEW_FAILED"}),
    "PREVIEW_COMPLETED": frozenset({"AUTHORIZATION_REQUESTED"}),
    "PREVIEW_FAILED": frozenset({"JOB_REJECTED"}),
    "AUTHORIZATION_REQUESTED": frozenset({"AUTHORIZATION_GRANTED", "AUTHORIZATION_DENIED"}),
    "AUTHORIZATION_GRANTED": frozenset({"EXECUTION_STARTED", "EXECUTION_DENIED"}),
    "AUTHORIZATION_DENIED": frozenset({"JOB_REJECTED"}),
    "EXECUTION_STARTED": frozenset({"EXECUTION_COMPLETED", "EXECUTION_FAILED", "AUDIT_WRITE_FAILED"}),
    "EXECUTION_DENIED": frozenset({"JOB_REJECTED"}),
    "EXECUTION_COMPLETED": frozenset({"AUDIT_FINALIZED"}),
    "EXECUTION_FAILED": frozenset({"ROLLBACK_STARTED", "AUDIT_FINALIZED", "AUDIT_WRITE_FAILED"}),
    "ROLLBACK_STARTED": frozenset({"ROLLBACK_COMPLETED", "ROLLBACK_FAILED", "AUDIT_WRITE_FAILED"}),
    "ROLLBACK_COMPLETED": frozenset({"AUDIT_FINALIZED"}),
    "ROLLBACK_FAILED": frozenset({"AUDIT_FINALIZED", "AUDIT_WRITE_FAILED"}),
    "JOB_REJECTED": frozenset({"AUDIT_FINALIZED"}),
    "AUDIT_WRITE_FAILED": frozenset(),
    "AUDIT_FINALIZED": frozenset(),
    "AUDIT_INTEGRITY_FAILURE": frozenset(),
    "AUDIT_RECONCILIATION": frozenset(),
}
_SENSITIVE_KEY_RE = re.compile(r"(?i)(password|passwd|token|secret|credential|private[_-]?key|raw[_-]?payload|sql)")


class LedgerError(Exception):
    """Sanitized failure carrying only a stable code from audit-model-v1.md."""
    def __init__(self, code: str):
        if code not in _ERROR_CODES:
            code = "E900_INTERNAL_ERROR"
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class LedgerEvent:
    """Unchained event draft; the ledger supplies sequence and hash fields."""
    event_id: str
    event_type: str
    event_version: int
    timestamp: str
    request_id: str
    job_id: str
    operation: str
    phase: str
    actor: Mapping[str, Any]
    requester: Mapping[str, Any]
    parameters_hash: str
    target: Mapping[str, Any]
    operation_version: Optional[str] = None
    approver: Optional[Mapping[str, Any]] = None
    worker_identity: Optional[str] = None
    helper_identity: Optional[str] = None
    authorization: Optional[Mapping[str, Any]] = None
    authorization_id: Optional[str] = None
    preview_id: Optional[str] = None
    preview_hash: Optional[str] = None
    authorization_scope: Optional[Mapping[str, Any]] = None
    authorization_scope_hash: Optional[str] = None
    status: str = "ACCEPTED"
    error_code: Optional[str] = None
    result_code: Optional[str] = None
    result: Optional[Mapping[str, Any]] = None
    rollback_status: str = "NOT_APPLICABLE"
    duration_ms: Optional[int] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, *, event_type: str, phase: str, request_id: str, job_id: str,
               operation: str, actor: Mapping[str, Any], parameters_hash: str,
               target: Mapping[str, Any], requester: Optional[Mapping[str, Any]] = None,
               event_id: Optional[str] = None, timestamp: Optional[str] = None, **kwargs: Any) -> "LedgerEvent":
        return cls(
            event_id=event_id or str(uuid4()), event_type=event_type, event_version=1,
            timestamp=timestamp or utc_now(), request_id=request_id, job_id=job_id,
            operation=operation, phase=phase, actor=actor,
            requester=requester if requester is not None else actor,
            parameters_hash=parameters_hash, target=target, **kwargs,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id, "event_type": self.event_type,
            "event_version": self.event_version, "timestamp": self.timestamp,
            "request_id": self.request_id, "job_id": self.job_id,
            "operation": self.operation, "operation_version": self.operation_version,
            "phase": self.phase, "actor": _plain(self.actor), "requester": _plain(self.requester),
            "approver": _plain(self.approver), "worker_identity": self.worker_identity,
            "helper_identity": self.helper_identity, "target": _plain(self.target),
            "authorization": _plain(self.authorization), "authorization_id": self.authorization_id,
            "preview_id": self.preview_id, "preview_hash": self.preview_hash,
            "authorization_scope": _plain(self.authorization_scope),
            "authorization_scope_hash": self.authorization_scope_hash,
            "parameters_hash": self.parameters_hash, "status": self.status,
            "error_code": self.error_code, "result_code": self.result_code,
            "result": _plain(self.result), "rollback_status": self.rollback_status,
            "duration_ms": self.duration_ms, "metadata": _plain(self.metadata),
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _plain(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise LedgerError("E103_INVALID_PARAMETERS") from None


def _parse_utc(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed if parsed.utcoffset() == timezone.utc.utcoffset(parsed) else None


def _safe_tree(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or _SENSITIVE_KEY_RE.search(key):
                return False
            if not _safe_tree(child):
                return False
        return True
    if isinstance(value, (list, tuple)):
        return all(_safe_tree(item) for item in value)
    if isinstance(value, str):
        return "-----BEGIN PRIVATE KEY-----" not in value and not re.search(r"(?i)bearer\s+[A-Za-z0-9._~+/-]{16,}", value)
    return value is None or isinstance(value, (str, int, float, bool))


def _identity_ok(value: Any) -> bool:
    return (isinstance(value, Mapping) and isinstance(value.get("subject_id"), str)
            and bool(value["subject_id"].strip()) and isinstance(value.get("actor_type"), str)
            and bool(value["actor_type"].strip()))


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and bool(_HASH_RE.fullmatch(value))


def _auth_validate(payload: Mapping[str, Any], *, historical: bool) -> None:
    auth = payload.get("authorization")
    et = payload.get("event_type")
    auth_events = {"AUTHORIZATION_REQUESTED", "AUTHORIZATION_GRANTED", "AUTHORIZATION_DENIED"}
    if et not in auth_events:
        return
    required = {"authorization_id", "requester", "approver", "operation", "target", "preview_id",
                "preview_hash", "timestamp", "expiration", "authorization_scope", "parameters_hash",
                "one_time_nonce", "decision", "approval_mode"}
    if not isinstance(auth, Mapping) or not required.issubset(auth):
        raise LedgerError("E301_AUTHORIZATION_INVALID")
    if not isinstance(auth.get("authorization_id"), str) or not auth["authorization_id"].strip():
        raise LedgerError("E301_AUTHORIZATION_INVALID")
    if payload.get("authorization_id") != auth.get("authorization_id"):
        raise LedgerError("E301_AUTHORIZATION_INVALID")
    if auth.get("operation") != payload.get("operation") or auth.get("target") != payload.get("target"):
        raise LedgerError("E303_AUTHORIZATION_SCOPE_MISMATCH")
    if auth.get("requester") != payload.get("requester"):
        raise LedgerError("E403_IDENTITY_MISMATCH")
    if auth.get("preview_id") != payload.get("preview_id") or auth.get("preview_hash") != payload.get("preview_hash"):
        raise LedgerError("E203_PREVIEW_MISMATCH")
    if auth.get("parameters_hash") != payload.get("parameters_hash"):
        raise LedgerError("E303_AUTHORIZATION_SCOPE_MISMATCH")
    if not _identity_ok(auth.get("requester")) or not _identity_ok(auth.get("approver")):
        raise LedgerError("E301_AUTHORIZATION_INVALID")
    if not isinstance(auth.get("authorization_scope"), Mapping):
        raise LedgerError("E301_AUTHORIZATION_INVALID")
    issued, expires = _parse_utc(auth.get("timestamp")), _parse_utc(auth.get("expiration"))
    if issued is None or expires is None or expires <= issued:
        raise LedgerError("E301_AUTHORIZATION_INVALID")
    if not isinstance(auth.get("one_time_nonce"), str) or not auth["one_time_nonce"].strip():
        raise LedgerError("E301_AUTHORIZATION_INVALID")
    if auth.get("approval_mode") not in {"HUMAN", "RBAC_READ"}:
        raise LedgerError("E301_AUTHORIZATION_INVALID")
    decision = auth.get("decision")
    expected = {"AUTHORIZATION_REQUESTED": {"PENDING"},
                "AUTHORIZATION_GRANTED": {"GRANTED"},
                "AUTHORIZATION_DENIED": {"DENIED", "EXPIRED", "INVALID"}}
    if decision not in expected[et]:
        raise LedgerError("E301_AUTHORIZATION_INVALID")
    if et == "AUTHORIZATION_GRANTED" and not historical and expires <= datetime.now(timezone.utc):
        raise LedgerError("E302_AUTHORIZATION_EXPIRED")


def validate_event(event: LedgerEvent, *, historical: bool = False) -> None:
    """Validate a draft without writing or executing anything."""
    if not isinstance(event, LedgerEvent):
        raise LedgerError("E103_INVALID_PARAMETERS")
    payload = event.to_payload()
    if set(payload) != _BASE_FIELDS:
        raise LedgerError("E103_INVALID_PARAMETERS")
    try:
        UUID(payload["event_id"])
    except (ValueError, TypeError, AttributeError):
        raise LedgerError("E103_INVALID_PARAMETERS") from None
    if payload["event_type"] not in _EVENT_TYPES:
        raise LedgerError("E103_INVALID_PARAMETERS")
    if type(payload["event_version"]) is not int or payload["event_version"] != 1:
        raise LedgerError("E103_INVALID_PARAMETERS")
    if _parse_utc(payload["timestamp"]) is None:
        raise LedgerError("E103_INVALID_PARAMETERS")
    for key in ("request_id", "job_id"):
        if not isinstance(payload[key], str) or not payload[key].strip() or len(payload[key]) > 200:
            raise LedgerError("E103_INVALID_PARAMETERS")
    if not isinstance(payload["operation"], str) or not _OPERATION_RE.fullmatch(payload["operation"]):
        raise LedgerError("E101_INVALID_OPERATION")
    if payload["phase"] not in _PHASES_BY_EVENT.get(payload["event_type"], frozenset()):
        raise LedgerError("E103_INVALID_PARAMETERS")
    if not _identity_ok(payload["actor"]) or not _identity_ok(payload["requester"]):
        raise LedgerError("E104_UNAUTHORIZED_REQUESTER")
    if payload["approver"] is not None and not _identity_ok(payload["approver"]):
        raise LedgerError("E301_AUTHORIZATION_INVALID")
    target = payload["target"]
    if not isinstance(target, Mapping) or not all(isinstance(target.get(k), str) and target[k].strip() for k in ("type", "id")):
        raise LedgerError("E102_INVALID_TARGET")
    if not _valid_hash(payload["parameters_hash"]):
        raise LedgerError("E103_INVALID_PARAMETERS")
    for key in ("preview_hash", "authorization_scope_hash"):
        if payload[key] is not None and not _valid_hash(payload[key]):
            raise LedgerError("E103_INVALID_PARAMETERS")
    if payload["preview_id"] is not None and (not isinstance(payload["preview_id"], str) or not payload["preview_id"].strip()):
        raise LedgerError("E201_PREVIEW_INVALID")
    if payload["authorization_id"] is not None and (not isinstance(payload["authorization_id"], str) or not payload["authorization_id"].strip()):
        raise LedgerError("E301_AUTHORIZATION_INVALID")
    if not isinstance(payload["status"], str) or not payload["status"].strip():
        raise LedgerError("E103_INVALID_PARAMETERS")
    if payload["error_code"] is not None and payload["error_code"] not in _ERROR_CODES:
        raise LedgerError("E103_INVALID_PARAMETERS")
    if payload["result_code"] is not None and (not isinstance(payload["result_code"], str) or not payload["result_code"].strip()):
        raise LedgerError("E103_INVALID_PARAMETERS")
    if payload["result"] is not None and not isinstance(payload["result"], Mapping):
        raise LedgerError("E103_INVALID_PARAMETERS")
    if payload["rollback_status"] not in _ROLLBACK_STATES:
        raise LedgerError("E103_INVALID_PARAMETERS")
    if payload["duration_ms"] is not None and (type(payload["duration_ms"]) is not int or payload["duration_ms"] < 0):
        raise LedgerError("E103_INVALID_PARAMETERS")
    if payload["authorization_scope"] is not None and not isinstance(payload["authorization_scope"], Mapping):
        raise LedgerError("E103_INVALID_PARAMETERS")
    if not isinstance(payload["metadata"], Mapping):
        raise LedgerError("E103_INVALID_PARAMETERS")
    if payload["authorization"] is not None and not isinstance(payload["authorization"], Mapping):
        raise LedgerError("E301_AUTHORIZATION_INVALID")
    if not _safe_tree(payload):
        raise LedgerError("E103_INVALID_PARAMETERS")
    try:
        encoded = canonical_json(payload)
    except LedgerError:
        raise
    if len(encoded) > 65536:
        raise LedgerError("E103_INVALID_PARAMETERS")
    if payload["event_type"] == "PREVIEW_COMPLETED" and (not payload["preview_id"] or not payload["preview_hash"]):
        raise LedgerError("E201_PREVIEW_INVALID")
    if payload["event_type"] in {"AUTHORIZATION_REQUESTED", "AUTHORIZATION_GRANTED", "AUTHORIZATION_DENIED"}:
        _auth_validate(payload, historical=historical)
        if payload["approver"] != payload["authorization"].get("approver"):
            raise LedgerError("E403_IDENTITY_MISMATCH")
    if payload["event_type"] == "EXECUTION_STARTED":
        if not payload["authorization_id"]:
            raise LedgerError("E300_AUTHORIZATION_REQUIRED")
        if not payload["preview_id"] or not payload["preview_hash"]:
            raise LedgerError("E200_PREVIEW_REQUIRED")
    if payload["event_type"] == "EXECUTION_COMPLETED":
        if not isinstance(payload["result"], Mapping) or payload["result"].get("confirmed") is not True:
            raise LedgerError("E500_EXECUTION_FAILED")
    if payload["event_type"] in {"VALIDATION_FAILED", "PREVIEW_FAILED", "AUTHORIZATION_DENIED", "EXECUTION_DENIED", "EXECUTION_FAILED", "ROLLBACK_FAILED", "AUDIT_WRITE_FAILED"} and not payload["error_code"]:
        raise LedgerError("E103_INVALID_PARAMETERS")
    if payload["event_type"] == "AUDIT_WRITE_FAILED" and payload["error_code"] not in {"E700_AUDIT_UNAVAILABLE", "E701_AUDIT_WRITE_FAILED"}:
        raise LedgerError("E103_INVALID_PARAMETERS")
    if payload["event_type"] == "ROLLBACK_FAILED" and payload["error_code"] not in {"E601_ROLLBACK_FAILED", "E602_ROLLBACK_NOT_SUPPORTED"}:
        raise LedgerError("E103_INVALID_PARAMETERS")


@dataclass(frozen=True)
class AppendReceipt:
    event_id: str
    ledger_sequence: int
    previous_event_hash: Optional[str]
    event_hash: str
    durable: bool = True

    @property
    def previous_hash(self) -> Optional[str]:
        return self.previous_event_hash


@dataclass(frozen=True)
class IntegrityReport:
    valid: bool
    event_count: int
    last_event_id: Optional[str]
    last_event_hash: Optional[str]
    error_code: Optional[str] = None
    failed_sequence: Optional[int] = None


def _record_hash(record: Mapping[str, Any]) -> str:
    previous = record.get("previous_event_hash")
    previous_bytes = bytes.fromhex(previous) if isinstance(previous, str) else bytes(32)
    body = {k: v for k, v in record.items() if k != "event_hash"}
    return hashlib.sha256(DOMAIN_SEPARATOR + previous_bytes + b"\x00" + canonical_json(body)).hexdigest()


def _calculate_event_hash(record: Mapping[str, Any]) -> str:
    """Expose deterministic hash calculation for independent test vectors."""
    return _record_hash(record)


def _base_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if k in _BASE_FIELDS}


def _receipt(record: Mapping[str, Any]) -> AppendReceipt:
    return AppendReceipt(record["event_id"], record["ledger_sequence"],
                         record["previous_event_hash"], record["event_hash"], True)


def _same_request(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    ignored = {"event_id", "timestamp"}
    return canonical_json({k: v for k, v in _base_record(left).items() if k not in ignored}) == canonical_json(
        {k: v for k, v in right.items() if k not in ignored})


def _bind_to_prior(records: list[Mapping[str, Any]], payload: Mapping[str, Any], *, historical: bool = False) -> None:
    if payload["event_type"] in {"AUTHORIZATION_REQUESTED", "AUTHORIZATION_GRANTED", "AUTHORIZATION_DENIED"}:
        preview = next((r for r in reversed(records) if r.get("job_id") == payload["job_id"] and r.get("event_type") == "PREVIEW_COMPLETED"), None)
        if preview is None or any(payload.get(k) != preview.get(k) for k in ("preview_id", "preview_hash", "parameters_hash", "target", "operation")):
            raise LedgerError("E203_PREVIEW_MISMATCH")
    if payload["event_type"] == "AUTHORIZATION_GRANTED":
        requested = next((r for r in reversed(records) if r.get("job_id") == payload["job_id"] and r.get("event_type") == "AUTHORIZATION_REQUESTED"), None)
        if requested is None or requested.get("authorization_id") != payload.get("authorization_id"):
            raise LedgerError("E301_AUTHORIZATION_INVALID")
        if requested.get("authorization") != payload.get("authorization"):
            # Decision may change PENDING -> GRANTED; the binding fields must remain identical.
            a, b = requested.get("authorization") or {}, payload.get("authorization") or {}
            ignore = {"decision"}
            if {k:v for k,v in a.items() if k not in ignore} != {k:v for k,v in b.items() if k not in ignore}:
                raise LedgerError("E303_AUTHORIZATION_SCOPE_MISMATCH")
    if payload["event_type"] == "EXECUTION_STARTED":
        grant = next((r for r in reversed(records) if r.get("job_id") == payload["job_id"] and r.get("event_type") == "AUTHORIZATION_GRANTED"), None)
        if grant is None:
            raise LedgerError("E300_AUTHORIZATION_REQUIRED")
        if any(payload.get(k) != grant.get(k) for k in ("authorization_id", "preview_id", "preview_hash", "parameters_hash", "target", "operation")):
            raise LedgerError("E303_AUTHORIZATION_SCOPE_MISMATCH")
        auth = grant.get("authorization") or {}
        expiry = _parse_utc(auth.get("expiration"))
        if expiry is None or (not historical and expiry <= datetime.now(timezone.utc)):
            raise LedgerError("E302_AUTHORIZATION_EXPIRED")
        if auth.get("approval_mode") not in {"HUMAN", "RBAC_READ"}:
            raise LedgerError("E301_AUTHORIZATION_INVALID")
        if any(r.get("event_type") == "EXECUTION_STARTED" and r.get("authorization_id") == payload.get("authorization_id") for r in records):
            raise LedgerError("E304_AUTHORIZATION_ALREADY_USED")


def _validate_transition(records: list[Mapping[str, Any]], payload: Mapping[str, Any], *, historical: bool) -> None:
    job_records = [r for r in records if r.get("job_id") == payload.get("job_id")]
    if not job_records:
        if payload["event_type"] != "REQUEST_RECEIVED":
            raise LedgerError("E802_JOB_STATE_INVALID")
        return
    root = next((r for r in job_records if r.get("event_type") == "REQUEST_RECEIVED"), None)
    if root is None:
        raise LedgerError("E702_AUDIT_INTEGRITY_FAILURE")
    for key in ("request_id", "job_id", "operation", "requester", "parameters_hash", "target"):
        if payload.get(key) != root.get(key):
            raise LedgerError("E802_JOB_STATE_INVALID")
    previous = job_records[-1].get("event_type")
    allowed = set(_TRANSITIONS.get(previous, ()))
    if payload["event_type"] not in allowed:
        raise LedgerError("E802_JOB_STATE_INVALID")
    if payload["event_type"] in {"AUTHORIZATION_REQUESTED", "AUTHORIZATION_GRANTED", "AUTHORIZATION_DENIED", "EXECUTION_STARTED"}:
        _bind_to_prior(records, payload, historical=historical)
    if payload["event_type"] == "EXECUTION_DENIED" and not payload.get("error_code"):
        raise LedgerError("E300_AUTHORIZATION_REQUIRED")


def _verify_bytes(data: bytes) -> tuple[IntegrityReport, list[dict[str, Any]]]:
    if not data:
        return IntegrityReport(True, 0, None, None), []
    if not data.endswith(b"\n"):
        return IntegrityReport(False, 0, None, None, "E702_AUDIT_INTEGRITY_FAILURE", 1), []
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_requests: dict[str, Mapping[str, Any]] = {}
    lines = data.splitlines()
    for sequence, line in enumerate(lines, 1):
        try:
            record = json.loads(line.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            return IntegrityReport(False, len(records), records[-1]["event_id"] if records else None,
                                   records[-1]["event_hash"] if records else None,
                                   "E702_AUDIT_INTEGRITY_FAILURE", sequence), records
        if not isinstance(record, dict) or set(record) != (_BASE_FIELDS | _CHAIN_FIELDS):
            return IntegrityReport(False, len(records), records[-1]["event_id"] if records else None,
                                   records[-1]["event_hash"] if records else None,
                                   "E702_AUDIT_INTEGRITY_FAILURE", sequence), records
        expected_prev_id = records[-1]["event_id"] if records else None
        expected_prev_hash = records[-1]["event_hash"] if records else None
        if (record.get("ledger_sequence") != sequence or record.get("previous_event_id") != expected_prev_id
                or record.get("previous_event_hash") != expected_prev_hash
                or record.get("previous_hash") != expected_prev_hash):
            return IntegrityReport(False, len(records), records[-1]["event_id"] if records else None,
                                   records[-1]["event_hash"] if records else None,
                                   "E702_AUDIT_INTEGRITY_FAILURE", sequence), records
        if record.get("event_id") in seen_ids:
            return IntegrityReport(False, len(records), records[-1]["event_id"] if records else None,
                                   records[-1]["event_hash"] if records else None,
                                   "E702_AUDIT_INTEGRITY_FAILURE", sequence), records
        if not isinstance(record.get("event_hash"), str) or not _HASH_RE.fullmatch(record["event_hash"]):
            return IntegrityReport(False, len(records), records[-1]["event_id"] if records else None,
                                   records[-1]["event_hash"] if records else None,
                                   "E702_AUDIT_INTEGRITY_FAILURE", sequence), records
        try:
            payload = _base_record(record)
            validate_event(_event_from_payload(payload), historical=True)
            if _record_hash(record) != record["event_hash"]:
                raise LedgerError("E702_AUDIT_INTEGRITY_FAILURE")
            if payload["event_type"] == "REQUEST_RECEIVED":
                old = seen_requests.get(payload["request_id"])
                if old is not None:
                    raise LedgerError("E702_AUDIT_INTEGRITY_FAILURE")
                seen_requests[payload["request_id"]] = record
            _validate_transition(records, payload, historical=True)
        except LedgerError:
            return IntegrityReport(False, len(records), records[-1]["event_id"] if records else None,
                                   records[-1]["event_hash"] if records else None,
                                   "E702_AUDIT_INTEGRITY_FAILURE", sequence), records
        seen_ids.add(record["event_id"])
        records.append(record)
    return IntegrityReport(True, len(records), records[-1]["event_id"], records[-1]["event_hash"]), records


def _event_from_payload(payload: Mapping[str, Any]) -> LedgerEvent:
    return LedgerEvent(**dict(payload))


class AuditLedger:
    """Hash-chained file ledger with explicit access policy; not WORM."""

    def __init__(self, path: os.PathLike[str] | str, *, create_mode: int = 0o600,
                 expected_owner_uid: Optional[int] = None,
                 expected_group_gid: Optional[int] = None,
                 expected_owner_name: Optional[str] = None,
                 expected_group_name: Optional[str] = None,
                 expected_file_mode: Optional[int] = None,
                 expected_directory_uid: Optional[int] = None,
                 expected_directory_gid: Optional[int] = None,
                 expected_directory_mode: Optional[int] = None,
                 read_only: bool = False,
                 event_metadata: Optional[Mapping[str, Any]] = None):
        self.path = Path(path)
        if type(create_mode) is not int or create_mode not in {0o600, 0o640}:
            raise ValueError("invalid audit file mode")
        if expected_file_mode is not None and (type(expected_file_mode) is not int or expected_file_mode not in {0o600, 0o640}):
            raise ValueError("invalid expected audit file mode")
        if type(read_only) is not bool:
            raise ValueError("invalid audit access mode")
        if event_metadata is not None and not isinstance(event_metadata, Mapping):
            raise ValueError("invalid audit metadata")
        self.create_mode = create_mode
        self.expected_owner_uid = expected_owner_uid
        self.expected_group_gid = expected_group_gid
        self.expected_owner_name = expected_owner_name
        self.expected_group_name = expected_group_name
        self.expected_file_mode = expected_file_mode
        self.expected_directory_uid = expected_directory_uid
        self.expected_directory_gid = expected_directory_gid
        self.expected_directory_mode = expected_directory_mode
        self.read_only = read_only
        self.event_metadata = dict(event_metadata or {})
        if not _safe_tree(self.event_metadata):
            raise ValueError("invalid audit metadata")

    def _identity_policy(self) -> tuple[Optional[int], Optional[int]]:
        uid = self.expected_owner_uid
        gid = self.expected_group_gid
        try:
            if self.expected_owner_name is not None:
                named_uid = pwd.getpwnam(self.expected_owner_name).pw_uid
                if uid is not None and uid != named_uid:
                    raise OSError("audit owner policy mismatch")
                uid = named_uid
            if self.expected_group_name is not None:
                named_gid = grp.getgrnam(self.expected_group_name).gr_gid
                if gid is not None and gid != named_gid:
                    raise OSError("audit group policy mismatch")
                gid = named_gid
        except KeyError:
            raise OSError("audit identity unavailable") from None
        return uid, gid

    def _check_directory(self) -> os.stat_result:
        try:
            owner_uid, group_gid = self._identity_policy()
            info = self.path.parent.lstat()
        except (OSError, ValueError):
            raise OSError("audit directory unavailable") from None
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise OSError("audit directory invalid")
        expected_uid = self.expected_directory_uid if self.expected_directory_uid is not None else owner_uid
        expected_gid = self.expected_directory_gid if self.expected_directory_gid is not None else group_gid
        if expected_uid is not None and info.st_uid != expected_uid:
            raise OSError("audit directory owner invalid")
        if expected_gid is not None and info.st_gid != expected_gid:
            raise OSError("audit directory group invalid")
        if self.expected_directory_mode is not None and stat.S_IMODE(info.st_mode) != self.expected_directory_mode:
            raise OSError("audit directory mode invalid")
        return info

    def _check_file(self, info: os.stat_result) -> None:
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise OSError("audit file invalid")
        expected_uid, expected_gid = self._identity_policy()
        if expected_uid is not None and info.st_uid != expected_uid:
            raise OSError("audit file owner invalid")
        if expected_gid is not None and info.st_gid != expected_gid:
            raise OSError("audit file group invalid")
        if self.expected_file_mode is not None and stat.S_IMODE(info.st_mode) != self.expected_file_mode:
            raise OSError("audit file mode invalid")

    def _open(self, *, writable: bool) -> tuple[int, bool]:
        self._check_directory()
        if writable and self.read_only:
            raise OSError("audit ledger is read-only")
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        cloexec = getattr(os, "O_CLOEXEC", 0)
        if writable:
            flags = os.O_RDWR | os.O_APPEND | nofollow | cloexec
            try:
                fd = os.open(self.path, flags)
                created = False
            except FileNotFoundError:
                try:
                    fd = os.open(self.path, flags | os.O_CREAT | os.O_EXCL, self.create_mode)
                    created = True
                except FileExistsError:
                    fd = os.open(self.path, flags)
                    created = False
        else:
            fd = os.open(self.path, os.O_RDONLY | nofollow | cloexec)
            created = False
        try:
            if created:
                os.fchmod(fd, self.create_mode)
            self._check_file(os.fstat(fd))
            return fd, created
        except Exception:
            os.close(fd)
            raise

    @staticmethod
    def _read_fd(fd: int) -> bytes:
        os.lseek(fd, 0, os.SEEK_SET)
        parts = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            parts.append(chunk)
        return b"".join(parts)

    def _read_verified_records(self) -> tuple[IntegrityReport, list[dict[str, Any]]]:
        try:
            fd, _ = self._open(writable=False)
        except FileNotFoundError:
            return IntegrityReport(True, 0, None, None), []
        except OSError:
            return IntegrityReport(False, 0, None, None, "E700_AUDIT_UNAVAILABLE", 1), []
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
            return _verify_bytes(self._read_fd(fd))
        except OSError:
            return IntegrityReport(False, 0, None, None, "E700_AUDIT_UNAVAILABLE", 1), []
        finally:
            os.close(fd)

    def verify(self) -> IntegrityReport:
        report, _ = self._read_verified_records()
        return report

    def append_authorization(self, event: LedgerEvent) -> AppendReceipt:
        if not isinstance(event, LedgerEvent) or event.event_type not in {
            "AUTHORIZATION_REQUESTED", "AUTHORIZATION_GRANTED", "AUTHORIZATION_DENIED"
        }:
            raise LedgerError("E103_INVALID_PARAMETERS")
        return self.append(event)

    def prepare_execution(self, event: LedgerEvent) -> AppendReceipt:
        """Durably record execution intent; deliberately does not execute it."""
        if not isinstance(event, LedgerEvent) or event.event_type != "EXECUTION_STARTED" or event.phase != "AUDIT_PREPARE":
            raise LedgerError("E103_INVALID_PARAMETERS")
        return self.append(event)

    def record_result(self, event: LedgerEvent) -> AppendReceipt:
        """Append a caller-attested result; this method does not run an operation."""
        if not isinstance(event, LedgerEvent) or event.event_type not in {"EXECUTION_COMPLETED", "EXECUTION_FAILED"} or event.phase != "AUDIT_RESULT":
            raise LedgerError("E103_INVALID_PARAMETERS")
        return self.append(event)

    def append(self, event: LedgerEvent) -> AppendReceipt:
        if self.read_only:
            raise LedgerError("E700_AUDIT_UNAVAILABLE")
        if not isinstance(event, LedgerEvent):
            raise LedgerError("E103_INVALID_PARAMETERS")
        if self.event_metadata:
            metadata = dict(event.metadata)
            for key, value in self.event_metadata.items():
                if key in metadata and metadata[key] != value:
                    raise LedgerError("E103_INVALID_PARAMETERS")
                metadata[key] = value
            event = replace(event, metadata=metadata)
        validate_event(event)
        payload = event.to_payload()
        if payload["event_type"] != "REQUEST_RECEIVED" and not os.path.lexists(self.path):
            raise LedgerError("E700_AUDIT_UNAVAILABLE")
        try:
            fd, created = self._open(writable=True)
        except OSError:
            raise LedgerError("E700_AUDIT_UNAVAILABLE") from None
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            if created:
                dir_fd = os.open(self.path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            data = self._read_fd(fd)
            report, records = _verify_bytes(data)
            if not report.valid:
                raise LedgerError("E702_AUDIT_INTEGRITY_FAILURE")
            base = _base_record(payload)
            for old in records:
                if old["event_id"] == payload["event_id"]:
                    if canonical_json(_base_record(old)) != canonical_json(base):
                        raise LedgerError("E800_CONCURRENCY_CONFLICT")
                    os.fsync(fd)
                    return _receipt(old)
            if payload["event_type"] == "REQUEST_RECEIVED":
                old_request = next((r for r in records if r["event_type"] == "REQUEST_RECEIVED" and r["request_id"] == payload["request_id"]), None)
                if old_request is not None:
                    if _same_request(old_request, payload):
                        os.fsync(fd)
                        return _receipt(old_request)
                    raise LedgerError("E800_CONCURRENCY_CONFLICT")
            if payload["event_type"] == "EXECUTION_STARTED" and any(
                r.get("event_type") == "EXECUTION_STARTED" and r.get("authorization_id") == payload.get("authorization_id")
                for r in records
            ):
                raise LedgerError("E304_AUTHORIZATION_ALREADY_USED")
            _validate_transition(records, payload, historical=False)
            if payload["event_type"] == "EXECUTION_STARTED":
                _bind_to_prior(records, payload)
            previous = records[-1] if records else None
            record = dict(base)
            record.update({
                "ledger_sequence": len(records) + 1,
                "previous_event_id": previous["event_id"] if previous else None,
                "previous_event_hash": previous["event_hash"] if previous else None,
                "previous_hash": previous["event_hash"] if previous else None,
            })
            record["event_hash"] = _record_hash(record)
            line = canonical_json(record) + b"\n"
            view = memoryview(line)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("append incomplete")
                view = view[written:]
            os.fsync(fd)
            return _receipt(record)
        except LedgerError:
            raise
        except OSError:
            # Bytes may have reached storage; caller must treat the result as unknown and not replay effects.
            raise LedgerError("E701_AUDIT_WRITE_FAILED") from None
        finally:
            os.close(fd)

    def verify_receipt(self, receipt: AppendReceipt) -> bool:
        if not isinstance(receipt, AppendReceipt) or receipt.durable is not True:
            return False
        report, records = self._read_verified_records()
        if not report.valid:
            return False
        for record in records:
            if record["event_id"] == receipt.event_id:
                return (record["ledger_sequence"] == receipt.ledger_sequence
                        and record["event_hash"] == receipt.event_hash
                        and record["previous_event_hash"] == receipt.previous_event_hash)
        return False

    def _find_finalized_status_record(self, *, request_id: str, subject_id: str,
                                      role: str, endpoint: str,
                                      protocol_operation: str, operation: str,
                                      target: Mapping[str, str]) -> Optional[dict[str, Any]]:
        report, records = self._read_verified_records()
        if not report.valid:
            return None
        finals = [r for r in records if r.get("event_type") == "AUDIT_FINALIZED"
                  and r.get("request_id") == request_id]
        if len(finals) != 1:
            return None
        final = finals[0]
        job_id = final.get("job_id")
        job_records = [r for r in records if r.get("job_id") == job_id]
        expected_steps = [
            ("REQUEST_RECEIVED", "REQUEST"),
            ("VALIDATION_PASSED", "VALIDATION"),
            ("PREVIEW_STARTED", "PREVIEW"),
            ("PREVIEW_COMPLETED", "PREVIEW"),
            ("AUTHORIZATION_REQUESTED", "AUTHORIZATION"),
            ("AUTHORIZATION_GRANTED", "AUTHORIZATION"),
            ("EXECUTION_STARTED", "AUDIT_PREPARE"),
            ("EXECUTION_COMPLETED", "AUDIT_RESULT"),
            ("AUDIT_FINALIZED", "AUDIT_FINALIZATION"),
        ]
        if [(r.get("event_type"), r.get("phase")) for r in job_records] != expected_steps:
            return None
        if job_records[-1] is not final:
            return None
        for record in job_records:
            requester = record.get("requester")
            metadata = record.get("metadata")
            if (record.get("request_id") != request_id or record.get("operation") != operation
                    or record.get("target") != dict(target)
                    or not isinstance(requester, Mapping)
                    or requester.get("subject_id") != subject_id
                    or requester.get("roles") != [role]
                    or not isinstance(metadata, Mapping)
                    or metadata.get("endpoint") != endpoint
                    or metadata.get("protocol_operation") != protocol_operation):
                return None
        result = job_records[-2].get("result")
        properties = result.get("properties") if isinstance(result, Mapping) else None
        if (job_records[-2].get("result_code") != "SUCCEEDED"
                or not isinstance(result, Mapping) or result.get("confirmed") is not True
                or result.get("outcome") != "SUCCEEDED" or result.get("source") != "systemd"
                or result.get("unit") != "traccar.service"
                or not isinstance(properties, Mapping)
                or set(properties) != {"LoadState", "ActiveState", "SubState", "UnitFileState", "Result"}
                or job_records[-1].get("status") != "FINALIZED"):
            return None
        return final

    def finalization_receipt_generic(self, *, request_id: str, subject_id: str, role: str,
                                     endpoint: str, protocol_operation: str, operation: str,
                                     target: Mapping[str, str]) -> Optional[dict[str, Any]]:
        report, records = self._read_verified_records()
        if not report.valid:
            return None
        finals = [r for r in records if r.get("event_type") == "AUDIT_FINALIZED" and r.get("request_id") == request_id]
        if len(finals) != 1:
            return None
        final = finals[0]; job_id = final.get("job_id")
        job_records = [r for r in records if r.get("job_id") == job_id]
        expected = [("REQUEST_RECEIVED","REQUEST"),("VALIDATION_PASSED","VALIDATION"),
                    ("PREVIEW_STARTED","PREVIEW"),("PREVIEW_COMPLETED","PREVIEW"),
                    ("AUTHORIZATION_REQUESTED","AUTHORIZATION"),("AUTHORIZATION_GRANTED","AUTHORIZATION"),
                    ("EXECUTION_STARTED","AUDIT_PREPARE"),("EXECUTION_COMPLETED","AUDIT_RESULT"),
                    ("AUDIT_FINALIZED","AUDIT_FINALIZATION")]
        if [(r.get("event_type"),r.get("phase")) for r in job_records] != expected or job_records[-1] is not final:
            return None
        for record in job_records:
            requester=record.get("requester"); metadata=record.get("metadata")
            if (record.get("request_id") != request_id or record.get("operation") != operation
                    or record.get("target") != dict(target) or not isinstance(requester, Mapping)
                    or requester.get("subject_id") != subject_id or requester.get("roles") != [role]
                    or not isinstance(metadata, Mapping) or metadata.get("endpoint") != endpoint
                    or metadata.get("protocol_operation") != protocol_operation):
                return None
        result=job_records[-2].get("result")
        if (not isinstance(result, Mapping) or result.get("confirmed") is not True
                or result.get("outcome") != "SUCCEEDED" or job_records[-1].get("status") != "FINALIZED"):
            return None
        receipt=_receipt(final)
        return {"schema_version":1,"protocol_version":1,"request_id":request_id,
                "operation":protocol_operation,"ledger_operation":operation,"endpoint":endpoint,
                "subject_id":subject_id,"role":role,"phase":"AUDIT_FINALIZATION",
                "event_id":receipt.event_id,"ledger_sequence":receipt.ledger_sequence,
                "previous_event_hash":receipt.previous_event_hash,"event_hash":receipt.event_hash,"durable":True}

    def verify_finalization_receipt_generic(self, receipt: Mapping[str, Any], **expected: Any) -> bool:
        rebuilt=self.finalization_receipt_generic(**expected)
        return isinstance(receipt, Mapping) and rebuilt is not None and dict(receipt) == rebuilt

    def finalization_receipt(self, *, request_id: str, subject_id: str, role: str,
                             endpoint: str, protocol_operation: str,
                             operation: str, target: Mapping[str, str]) -> Optional[dict[str, Any]]:
        record = self._find_finalized_status_record(
            request_id=request_id, subject_id=subject_id, role=role, endpoint=endpoint,
            protocol_operation=protocol_operation, operation=operation, target=target,
        )
        if record is None:
            return None
        receipt = _receipt(record)
        return {
            "schema_version": 1,
            "protocol_version": 1,
            "request_id": request_id,
            "operation": protocol_operation,
            "ledger_operation": operation,
            "endpoint": endpoint,
            "subject_id": subject_id,
            "role": role,
            "phase": "AUDIT_FINALIZATION",
            "event_id": receipt.event_id,
            "ledger_sequence": receipt.ledger_sequence,
            "previous_event_hash": receipt.previous_event_hash,
            "event_hash": receipt.event_hash,
            "durable": True,
        }

    def verify_finalization_receipt(self, receipt: Mapping[str, Any], *,
                                    request_id: str, subject_id: str, role: str,
                                    endpoint: str, protocol_operation: str,
                                    operation: str, target: Mapping[str, str]) -> bool:
        expected_keys = {
            "schema_version", "protocol_version", "request_id", "operation",
            "ledger_operation", "endpoint", "subject_id", "role", "phase",
            "event_id", "ledger_sequence", "previous_event_hash", "event_hash", "durable",
        }
        if (not isinstance(receipt, Mapping) or set(receipt) != expected_keys
                or type(receipt.get("schema_version")) is not int or receipt.get("schema_version") != 1
                or type(receipt.get("protocol_version")) is not int or receipt.get("protocol_version") != 1
                or receipt.get("request_id") != request_id or receipt.get("operation") != protocol_operation
                or receipt.get("ledger_operation") != operation or receipt.get("endpoint") != endpoint
                or receipt.get("subject_id") != subject_id or receipt.get("role") != role
                or receipt.get("phase") != "AUDIT_FINALIZATION" or receipt.get("durable") is not True
                or not isinstance(receipt.get("event_id"), str)
                or type(receipt.get("ledger_sequence")) is not int or receipt["ledger_sequence"] < 1
                or not isinstance(receipt.get("event_hash"), str) or not _HASH_RE.fullmatch(receipt["event_hash"])
                or (receipt.get("previous_event_hash") is not None
                    and (not isinstance(receipt["previous_event_hash"], str)
                         or not _HASH_RE.fullmatch(receipt["previous_event_hash"])) )):
            return False
        record = self._find_finalized_status_record(
            request_id=request_id, subject_id=subject_id, role=role, endpoint=endpoint,
            protocol_operation=protocol_operation, operation=operation, target=target,
        )
        if record is None:
            return False
        expected = _receipt(record)
        return (receipt["event_id"] == expected.event_id
                and receipt["ledger_sequence"] == expected.ledger_sequence
                and receipt["previous_event_hash"] == expected.previous_event_hash
                and receipt["event_hash"] == expected.event_hash
                and expected.durable)
