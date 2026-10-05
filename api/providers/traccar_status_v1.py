"""Traccar service-status DTO adapter with an explicitly injected source.

Sources must be allowlisted. The candidate Worker is the only component that
may inject the fixed local status handler, behind UDS, RBAC, and audit checks.
This module does not select services, execute commands, or activate any source.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Protocol

from api.read_only_dashboard_v1 import GeneralStatusDTO, TraccarServiceDTO, ValueDTO

TRACCAR_STATUS_ERROR_CODES = frozenset({
    "TRACCAR_STATUS_PENDING_PROVIDER", "TRACCAR_STATUS_SOURCE_NOT_ALLOWED",
    "TRACCAR_STATUS_SOURCE_UNAVAILABLE", "TRACCAR_STATUS_DATA_INVALID",
    "TRACCAR_STATUS_TIMEOUT", "TRACCAR_STATUS_INTERNAL_ERROR",
})
STATUS_TIMEOUT_SECONDS = 5.0
_STATE_RE = re.compile(r"^[A-Za-z0-9_.+-]{1,64}$")


class TraccarStatusProviderError(RuntimeError):
    def __init__(self, code: str):
        self.code = code if code in TRACCAR_STATUS_ERROR_CODES else "TRACCAR_STATUS_INTERNAL_ERROR"
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class TraccarStatusRecord:
    """Fixed allowlisted state; intentionally has no unit/service selector."""
    load_state: str
    active_state: str
    sub_state: str
    unit_file_state: str
    result: str
    observed_at_utc: str

    def __post_init__(self):
        for value in (self.load_state, self.active_state, self.sub_state, self.unit_file_state, self.result):
            if not isinstance(value, str) or not _STATE_RE.fullmatch(value):
                raise ValueError("invalid status record")
        if not isinstance(self.observed_at_utc, str) or not self.observed_at_utc.endswith("Z"):
            raise ValueError("invalid status record")
        try:
            parsed = datetime.fromisoformat(self.observed_at_utc[:-1] + "+00:00")
        except ValueError:
            raise ValueError("invalid status record") from None
        if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
            raise ValueError("invalid status record")


class TraccarStatusSource(Protocol):
    @property
    def provider_id(self) -> str: ...
    def read_status(self, timeout_seconds: float) -> TraccarStatusRecord: ...


class TraccarStatusProvider:
    """Maps a trusted fixed-service status record into GeneralStatusDTO.

    Real systemd/Traccar source integration is intentionally absent in this phase.
    Call only behind the dashboard's RBAC + audit execution boundary.
    """
    timeout_seconds = STATUS_TIMEOUT_SECONDS

    def __init__(self, source: TraccarStatusSource | None, *, allowed_source_ids: frozenset[str]):
        if not isinstance(allowed_source_ids, frozenset):
            raise ValueError("invalid source allowlist")
        self._source = source
        self._allowed = allowed_source_ids

    def collect(self) -> GeneralStatusDTO:
        if self._source is None:
            raise TraccarStatusProviderError("TRACCAR_STATUS_PENDING_PROVIDER")
        source_id = getattr(self._source, "provider_id", None)
        if not isinstance(source_id, str) or source_id not in self._allowed:
            raise TraccarStatusProviderError("TRACCAR_STATUS_SOURCE_NOT_ALLOWED")
        try:
            record = self._source.read_status(self.timeout_seconds)
        except TraccarStatusProviderError:
            raise
        except TimeoutError:
            raise TraccarStatusProviderError("TRACCAR_STATUS_TIMEOUT") from None
        except OSError:
            raise TraccarStatusProviderError("TRACCAR_STATUS_SOURCE_UNAVAILABLE") from None
        except Exception:
            raise TraccarStatusProviderError("TRACCAR_STATUS_INTERNAL_ERROR") from None
        if not isinstance(record, TraccarStatusRecord):
            raise TraccarStatusProviderError("TRACCAR_STATUS_DATA_INVALID")
        try:
            record.__post_init__()
            observed = record.observed_at_utc
            service = TraccarServiceDTO(
                ValueDTO.available(record.active_state, observed),
                ValueDTO.available(record.sub_state, observed),
                ValueDTO.available(record.load_state, observed),
                ValueDTO.available(record.unit_file_state, observed),
                ValueDTO.available(record.result, observed),
            )
            # No uptime/version/overall-health field is derived or fabricated.
            return GeneralStatusDTO(service, ValueDTO.pending_provider(),
                                    ValueDTO.pending_provider(), ValueDTO.pending_provider(), observed)
        except Exception:
            raise TraccarStatusProviderError("TRACCAR_STATUS_DATA_INVALID") from None
