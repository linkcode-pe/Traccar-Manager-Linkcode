"""Source-neutral, read-only dashboard contract/provider scaffold v1.

No HTTP server, production datasource, database client, shell, filesystem reader,
or service selector is implemented here. Real data access must be injected by a
separately reviewed provider and must remain behind the audited read-only port.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import json
import math
import re
from typing import Any, Callable, Mapping, Optional, Protocol
from uuid import NAMESPACE_URL, uuid5


API_CODES = frozenset({
    "API_INVALID_REQUEST", "API_UNAUTHORIZED", "API_FORBIDDEN",
    "API_PROVIDER_UNAVAILABLE", "API_DATA_UNAVAILABLE", "API_SOURCE_NOT_ALLOWED",
    "API_TIMEOUT", "API_AUDIT_UNAVAILABLE", "API_INTERNAL_ERROR",
})
_OPERATION = "dashboard.snapshot.read.v1"
_RESOURCE_TYPE = "dashboard_snapshot"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PROVIDER_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


class DashboardAPIError(RuntimeError):
    """Sanitized public error; never includes exception details or source data."""
    def __init__(self, code: str):
        self.code = code if code in API_CODES else "API_INTERNAL_ERROR"
        super().__init__(self.code)


class Availability(str, Enum):
    AVAILABLE = "AVAILABLE"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    PENDING_PROVIDER = "PENDING_PROVIDER"


class AuditPhase(str, Enum):
    PREVIEW = "PREVIEW"
    AUTHORIZATION = "AUTHORIZATION"
    AUDIT_PREPARE = "AUDIT_PREPARE"
    EXECUTION = "EXECUTION"
    RESULT = "RESULT"
    AUDIT_FINALIZATION = "AUDIT_FINALIZATION"


def _valid_timestamp(value: Optional[str]) -> bool:
    if value is None:
        return True
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def _safe_scalar(value: Any) -> bool:
    if type(value) in (bool, int):
        return True
    if type(value) is float:
        return math.isfinite(value)
    if isinstance(value, str):
        return len(value) <= 256 and not any(ord(c) < 32 or ord(c) == 127 for c in value)
    return False


@dataclass(frozen=True, slots=True)
class ValueDTO:
    availability: Availability
    value: Optional[str | int | float | bool] = None
    observed_at_utc: Optional[str] = None

    def __post_init__(self):
        if not isinstance(self.availability, Availability):
            raise ValueError("invalid availability")
        if self.availability is Availability.AVAILABLE:
            if self.value is None or not _safe_scalar(self.value) or not _valid_timestamp(self.observed_at_utc):
                raise ValueError("invalid available value")
        elif self.value is not None or self.observed_at_utc is not None:
            raise ValueError("unavailable values must be empty")

    @classmethod
    def available(cls, value: str | int | float | bool, observed_at_utc: Optional[str] = None) -> "ValueDTO":
        return cls(Availability.AVAILABLE, value, observed_at_utc)

    @classmethod
    def not_available(cls) -> "ValueDTO":
        return cls(Availability.NOT_AVAILABLE)

    @classmethod
    def pending_provider(cls) -> "ValueDTO":
        return cls(Availability.PENDING_PROVIDER)


def _expect(value: ValueDTO, types: tuple[type, ...], *, minimum: Optional[float] = None,
            maximum: Optional[float] = None, choices: Optional[frozenset[str]] = None) -> None:
    if not isinstance(value, ValueDTO):
        raise ValueError("invalid DTO field")
    if value.availability is not Availability.AVAILABLE:
        return
    if type(value.value) not in types:
        raise ValueError("invalid DTO field type")
    if minimum is not None and value.value < minimum:
        raise ValueError("invalid DTO range")
    if maximum is not None and value.value > maximum:
        raise ValueError("invalid DTO range")
    if choices is not None and value.value not in choices:
        raise ValueError("invalid DTO value")


def _check_observed(value: Optional[str]) -> None:
    if not _valid_timestamp(value):
        raise ValueError("invalid timestamp")


@dataclass(frozen=True, slots=True)
class TraccarServiceDTO:
    state: ValueDTO
    substate: ValueDTO
    load_state: ValueDTO
    unit_file_state: ValueDTO
    result: ValueDTO

    def __post_init__(self):
        for item in (self.state, self.substate, self.load_state, self.unit_file_state, self.result):
            _expect(item, (str,))


@dataclass(frozen=True, slots=True)
class GeneralStatusDTO:
    traccar_service: TraccarServiceDTO
    uptime_seconds: ValueDTO
    version: ValueDTO
    overall_state: ValueDTO
    observed_at_utc: Optional[str] = None

    def __post_init__(self):
        if not isinstance(self.traccar_service, TraccarServiceDTO):
            raise ValueError("invalid service DTO")
        _expect(self.uptime_seconds, (int,), minimum=0)
        _expect(self.version, (str,))
        _expect(self.overall_state, (str,), choices=frozenset({"HEALTHY", "DEGRADED", "UNKNOWN"}))
        _check_observed(self.observed_at_utc)


@dataclass(frozen=True, slots=True)
class ServerMetricsDTO:
    cpu_percent: ValueDTO
    memory_total_bytes: ValueDTO
    memory_used_bytes: ValueDTO
    disk_total_bytes: ValueDTO
    disk_free_bytes: ValueDTO
    observed_at_utc: Optional[str] = None

    def __post_init__(self):
        _expect(self.cpu_percent, (int, float), minimum=0, maximum=100)
        for item in (self.memory_total_bytes, self.memory_used_bytes, self.disk_total_bytes, self.disk_free_bytes):
            _expect(item, (int,), minimum=0)
        _check_observed(self.observed_at_utc)


@dataclass(frozen=True, slots=True)
class DeviceSummaryDTO:
    total: ValueDTO
    active: ValueDTO
    inactive: ValueDTO
    observed_at_utc: Optional[str] = None

    def __post_init__(self):
        for item in (self.total, self.active, self.inactive):
            _expect(item, (int,), minimum=0)
        _check_observed(self.observed_at_utc)


@dataclass(frozen=True, slots=True)
class PositionSummaryDTO:
    current_count: ValueDTO
    older_than_retention_count: ValueDTO
    availability_state: ValueDTO
    observed_at_utc: Optional[str] = None

    def __post_init__(self):
        for item in (self.current_count, self.older_than_retention_count):
            _expect(item, (int,), minimum=0)
        _expect(self.availability_state, (str,), choices=frozenset({"AVAILABLE", "NO_DATA", "UNKNOWN"}))
        _check_observed(self.observed_at_utc)


@dataclass(frozen=True, slots=True)
class RetentionStatusDTO:
    configuration_known: ValueDTO
    cutoff_utc: ValueDTO
    last_run_state: ValueDTO
    last_run_utc: ValueDTO
    observed_at_utc: Optional[str] = None

    def __post_init__(self):
        _expect(self.configuration_known, (bool,))
        _expect(self.cutoff_utc, (str,))
        _expect(self.last_run_state, (str,), choices=frozenset({"running", "time_limit", "completed", "error", "locked", "unknown"}))
        _expect(self.last_run_utc, (str,))
        if self.cutoff_utc.availability is Availability.AVAILABLE and not _valid_timestamp(self.cutoff_utc.value):
            raise ValueError("invalid cutoff")
        if self.last_run_utc.availability is Availability.AVAILABLE and not _valid_timestamp(self.last_run_utc.value):
            raise ValueError("invalid last-run timestamp")
        _check_observed(self.observed_at_utc)


@dataclass(frozen=True, slots=True)
class DashboardSnapshotDTO:
    schema_version: int
    request_id: str
    general: GeneralStatusDTO
    server: ServerMetricsDTO
    devices: DeviceSummaryDTO
    positions: PositionSummaryDTO
    retention: RetentionStatusDTO

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("invalid schema version")
        if not isinstance(self.request_id, str) or not _REQUEST_ID_RE.fullmatch(self.request_id):
            raise ValueError("invalid request id")
        if not all((isinstance(self.general, GeneralStatusDTO), isinstance(self.server, ServerMetricsDTO),
                    isinstance(self.devices, DeviceSummaryDTO), isinstance(self.positions, PositionSummaryDTO),
                    isinstance(self.retention, RetentionStatusDTO))):
            raise ValueError("incomplete dashboard DTO")


@dataclass(frozen=True, slots=True)
class DashboardRequestDTO:
    """Fixed full-dashboard read; intentionally has no resource/path/query selectors."""
    request_id: str

    def __post_init__(self):
        if not isinstance(self.request_id, str) or not _REQUEST_ID_RE.fullmatch(self.request_id):
            raise DashboardAPIError("API_INVALID_REQUEST")


def dashboard_request_from_mapping(value: Mapping[str, Any]) -> DashboardRequestDTO:
    if not isinstance(value, Mapping) or set(value) != {"request_id"}:
        raise DashboardAPIError("API_INVALID_REQUEST")
    try:
        return DashboardRequestDTO(request_id=value["request_id"])
    except (TypeError, ValueError):
        raise DashboardAPIError("API_INVALID_REQUEST") from None


@dataclass(frozen=True, slots=True)
class ActorContext:
    subject_id: str
    roles: frozenset[str]

    def __post_init__(self):
        if (not isinstance(self.subject_id, str) or not self.subject_id.strip()
                or len(self.subject_id) > 200 or not isinstance(self.roles, frozenset)
                or any(not isinstance(role, str) for role in self.roles)):
            raise DashboardAPIError("API_UNAUTHORIZED")


@dataclass(frozen=True, slots=True)
class ReadAuditEvent:
    event_id: str
    operation: str
    request_id: str
    actor: str
    phase: AuditPhase
    result: str
    error_code: Optional[str]
    timestamp_utc: str
    resource_type: str = _RESOURCE_TYPE


class DashboardDataSource(Protocol):
    @property
    def provider_id(self) -> str:
        """Trusted implementation identity, not supplied by a dashboard request."""
        ...

    def read_dashboard(self, request: DashboardRequestDTO) -> DashboardSnapshotDTO:
        ...


class ReadOnlyAuthorizer(Protocol):
    def allows(self, actor: ActorContext, operation: str) -> bool:
        ...


class DashboardExecutionGateway(Protocol):
    def execute(self, request: DashboardRequestDTO, actor: ActorContext,
                operation: Callable[[], DashboardSnapshotDTO]) -> DashboardSnapshotDTO:
        ...


class DispatcherAuditGateway:
    """Read-only dashboard execution routed exclusively through the Dispatcher."""
    def __init__(self, ledger, *, clock=None, authorization_ttl_seconds: int = 60):
        if type(authorization_ttl_seconds) is not int or not 1 <= authorization_ttl_seconds <= 300:
            raise ValueError("invalid authorization lifetime")
        self._ledger = ledger
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._authorization_ttl_seconds = authorization_ttl_seconds

    def _now(self) -> datetime:
        try:
            value = self._clock()
            if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
                raise ValueError
            return value.astimezone(timezone.utc)
        except Exception:
            raise DashboardAPIError("API_INTERNAL_ERROR") from None

    @staticmethod
    def _dispatcher_error(code: str) -> str:
        return {
            "E100_OPERATION_NOT_ALLOWED": "API_INVALID_REQUEST",
            "E103_INVALID_PARAMETERS": "API_INVALID_REQUEST",
            "E104_UNAUTHORIZED_REQUESTER": "API_FORBIDDEN",
            "E200_PREVIEW_REQUIRED": "API_INVALID_REQUEST",
            "E201_PREVIEW_INVALID": "API_INVALID_REQUEST",
            "E202_PREVIEW_EXPIRED": "API_INVALID_REQUEST",
            "E203_PREVIEW_MISMATCH": "API_INVALID_REQUEST",
            "E300_AUTHORIZATION_REQUIRED": "API_INVALID_REQUEST",
            "E301_AUTHORIZATION_INVALID": "API_INVALID_REQUEST",
            "E302_AUTHORIZATION_EXPIRED": "API_INVALID_REQUEST",
            "E303_AUTHORIZATION_SCOPE_MISMATCH": "API_INVALID_REQUEST",
            "E304_AUTHORIZATION_ALREADY_USED": "API_INVALID_REQUEST",
            "E700_AUDIT_UNAVAILABLE": "API_AUDIT_UNAVAILABLE",
            "E701_AUDIT_WRITE_FAILED": "API_AUDIT_UNAVAILABLE",
            "E702_AUDIT_INTEGRITY_FAILURE": "API_AUDIT_UNAVAILABLE",
            "E800_CONCURRENCY_CONFLICT": "API_INVALID_REQUEST",
            "E501_EXECUTION_TIMEOUT": "API_TIMEOUT",
            "E502_TARGET_UNAVAILABLE": "API_PROVIDER_UNAVAILABLE",
            "E500_EXECUTION_FAILED": "API_INTERNAL_ERROR",
            "E900_INTERNAL_ERROR": "API_INTERNAL_ERROR",
        }.get(code, "API_INTERNAL_ERROR")

    def execute(self, request: DashboardRequestDTO, actor: ActorContext,
                operation: Callable[[], DashboardSnapshotDTO]) -> DashboardSnapshotDTO:
        if not isinstance(request, DashboardRequestDTO) or not isinstance(actor, ActorContext) or not callable(operation):
            raise DashboardAPIError("API_INVALID_REQUEST")
        if self._ledger is None:
            raise DashboardAPIError("API_AUDIT_UNAVAILABLE")
        captured: dict[str, Any] = {}
        try:
            from dataclasses import replace as dataclass_replace
            from worker.dispatcher import (
                ActorContext as DispatcherActor, DashboardDispatchResult, DispatchError,
                Job, create_preview, dispatch_job, record_authorization,
            )
            now = self._now()
            issued = now.isoformat(timespec="microseconds").replace("+00:00", "Z")
            expires = (now + timedelta(seconds=self._authorization_ttl_seconds)).isoformat(
                timespec="microseconds").replace("+00:00", "Z")
            suffix = str(uuid5(NAMESPACE_URL, "dashboard-read-v1:" + request.request_id + ":" + actor.subject_id))
            dispatcher_actor = DispatcherActor(actor.subject_id, actor.roles)
            job = Job(
                schema_version=1, job_id="dashboard-" + suffix,
                operation=_OPERATION, payload={}, requested_by=actor.subject_id,
                created_at_utc=issued, idempotency_key="dashboard-read-" + suffix,
                request_id=request.request_id,
            )
            preview = create_preview(self._ledger, job, dispatcher_actor)
            authorization = record_authorization(
                self._ledger, job, dispatcher_actor, preview,
                authorization_id="auth-" + suffix,
                issued_at_utc=issued, expires_at_utc=expires,
            )
            job = dataclass_replace(job, preview_id=preview.preview_id,
                                    authorization_id=authorization.authorization_id)

            def execute_fixture_only(payload: Mapping[str, Any]) -> Mapping[str, Any]:
                if dict(payload) != {}:
                    return {"confirmed": True, "outcome": "FAILED", "error_code": "E900_INTERNAL_ERROR"}
                try:
                    snapshot = validate_snapshot(operation(), request.request_id)
                except DashboardAPIError as exc:
                    if exc.code == "API_DATA_UNAVAILABLE":
                        captured["api_error"] = "API_DATA_UNAVAILABLE"
                        return {"confirmed": True, "outcome": "FAILED", "error_code": "E500_EXECUTION_FAILED"}
                    return {"confirmed": True, "outcome": "FAILED", "error_code": "E900_INTERNAL_ERROR"}
                except ProviderTimeout:
                    return {"confirmed": True, "outcome": "FAILED", "error_code": "E501_EXECUTION_TIMEOUT"}
                except ProviderUnavailable:
                    return {"confirmed": True, "outcome": "FAILED", "error_code": "E502_TARGET_UNAVAILABLE"}
                except DashboardAPIError as exc:
                    code = "E501_EXECUTION_TIMEOUT" if exc.code == "API_TIMEOUT" else (
                        "E502_TARGET_UNAVAILABLE" if exc.code in {"PROVIDER_PENDING", "API_PROVIDER_UNAVAILABLE"}
                        else "E900_INTERNAL_ERROR")
                    return {"confirmed": True, "outcome": "FAILED", "error_code": code}
                except Exception:
                    return {"confirmed": True, "outcome": "FAILED", "error_code": "E900_INTERNAL_ERROR"}
                captured["snapshot"] = snapshot
                return {
                    "confirmed": True, "outcome": "SUCCEEDED",
                    "observed_at_utc": self._now().isoformat(timespec="microseconds").replace("+00:00", "Z"),
                    "response": snapshot_to_dict(snapshot),
                }

            result = dispatch_job(
                job, dispatcher_actor, ledger=self._ledger, preview=preview,
                authorization=authorization, executor=execute_fixture_only,
            )
            if (not isinstance(result, DashboardDispatchResult)
                    or result.request_id != request.request_id
                    or result.integrity_valid is not True or len(result.receipts) != 9
                    or not all(getattr(receipt, "durable", False) for receipt in result.receipts)
                    or "snapshot" not in captured
                    or dict(result.response) != snapshot_to_dict(captured["snapshot"])):
                raise DashboardAPIError("API_AUDIT_UNAVAILABLE")
            return captured["snapshot"]
        except DashboardAPIError:
            raise
        except Exception as exc:
            if captured.get("api_error") == "API_DATA_UNAVAILABLE":
                raise DashboardAPIError("API_DATA_UNAVAILABLE") from None
            code = self._dispatcher_error(getattr(exc, "code", "E900_INTERNAL_ERROR"))
            raise DashboardAPIError(code) from None


class ProviderUnavailable(Exception):
    """Internal signal mapped to a stable API code; message is discarded."""


class ProviderTimeout(Exception):
    """Internal signal mapped to a stable API code; message is discarded."""


def pending_snapshot(request_id: str) -> DashboardSnapshotDTO:
    """Return an explicit no-provider snapshot; never manufacture live values."""
    p = ValueDTO.pending_provider
    service = TraccarServiceDTO(p(), p(), p(), p(), p())
    return DashboardSnapshotDTO(
        schema_version=1, request_id=request_id,
        general=GeneralStatusDTO(service, p(), p(), p(), None),
        server=ServerMetricsDTO(p(), p(), p(), p(), p(), None),
        devices=DeviceSummaryDTO(p(), p(), p(), None),
        positions=PositionSummaryDTO(p(), p(), p(), None),
        retention=RetentionStatusDTO(p(), p(), p(), p(), None),
    )


def validate_snapshot(value: Any, request_id: str) -> DashboardSnapshotDTO:
    if not isinstance(value, DashboardSnapshotDTO) or value.schema_version != 1 or value.request_id != request_id:
        raise DashboardAPIError("API_DATA_UNAVAILABLE")
    try:
        value.__post_init__()
    except Exception:
        raise DashboardAPIError("API_DATA_UNAVAILABLE") from None
    return value


def snapshot_to_dict(snapshot: DashboardSnapshotDTO) -> dict[str, Any]:
    validate_snapshot(snapshot, snapshot.request_id)
    def wire(item: Any) -> Any:
        if isinstance(item, Enum):
            return item.value
        if is_dataclass(item):
            return {field.name: wire(getattr(item, field.name)) for field in fields(item)}
        if isinstance(item, Mapping):
            return {str(k): wire(v) for k, v in item.items()}
        if isinstance(item, (tuple, list)):
            return [wire(v) for v in item]
        return item
    return wire(snapshot)


def snapshot_to_json(snapshot: DashboardSnapshotDTO) -> str:
    return json.dumps(snapshot_to_dict(snapshot), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class ReadOnlyDashboardProvider:
    """Read-only façade; every uncached provider call must pass through Dispatcher."""
    def __init__(self, data_source: Optional[DashboardDataSource], *,
                 allowed_provider_ids: frozenset[str], authorizer: ReadOnlyAuthorizer,
                 execution_gateway: Optional[DashboardExecutionGateway], cache_limit: int = 256):
        if type(cache_limit) is not int or cache_limit < 1:
            raise ValueError("invalid cache limit")
        if not isinstance(allowed_provider_ids, frozenset) or any(
                not isinstance(item, str) or not _PROVIDER_ID_RE.fullmatch(item)
                for item in allowed_provider_ids):
            raise ValueError("invalid trusted provider allowlist")
        self._data_source = data_source
        self._allowed_provider_ids = allowed_provider_ids
        self._authorizer = authorizer
        self._execution_gateway = execution_gateway
        self._cache_limit = cache_limit
        self._cache: dict[str, tuple[tuple[str, frozenset[str]], DashboardSnapshotDTO]] = {}

    def _allowed(self, actor: ActorContext) -> bool:
        try:
            return self._authorizer.allows(actor, _OPERATION) is True
        except Exception:
            raise DashboardAPIError("API_INTERNAL_ERROR") from None

    def read(self, request: DashboardRequestDTO | Mapping[str, Any], actor: ActorContext) -> DashboardSnapshotDTO:
        if isinstance(request, Mapping):
            request = dashboard_request_from_mapping(request)
        if not isinstance(request, DashboardRequestDTO) or not isinstance(actor, ActorContext):
            raise DashboardAPIError("API_INVALID_REQUEST")
        identity = (actor.subject_id, actor.roles)
        cached = self._cache.get(request.request_id)
        if cached is not None:
            if cached[0] != identity:
                raise DashboardAPIError("API_INVALID_REQUEST")
            if not self._allowed(actor):
                raise DashboardAPIError("API_FORBIDDEN")
            return cached[1]

        if self._execution_gateway is None:
            raise DashboardAPIError("API_AUDIT_UNAVAILABLE")
        if not self._allowed(actor):
            raise DashboardAPIError("API_FORBIDDEN")
        if self._data_source is None:
            raise DashboardAPIError("API_PROVIDER_UNAVAILABLE")
        try:
            provider_id = self._data_source.provider_id
        except Exception:
            raise DashboardAPIError("API_PROVIDER_UNAVAILABLE") from None
        if not isinstance(provider_id, str) or provider_id not in self._allowed_provider_ids:
            raise DashboardAPIError("API_SOURCE_NOT_ALLOWED")

        try:
            snapshot = self._execution_gateway.execute(
                request, actor, lambda: self._data_source.read_dashboard(request)
            )
            snapshot = validate_snapshot(snapshot, request.request_id)
        except DashboardAPIError:
            raise
        except ProviderTimeout:
            raise DashboardAPIError("API_TIMEOUT") from None
        except ProviderUnavailable:
            raise DashboardAPIError("API_PROVIDER_UNAVAILABLE") from None
        except Exception:
            raise DashboardAPIError("API_INTERNAL_ERROR") from None
        self._cache[request.request_id] = (identity, snapshot)
        if len(self._cache) > self._cache_limit:
            self._cache.pop(next(iter(self._cache)))
        return snapshot
