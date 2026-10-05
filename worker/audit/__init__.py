"""Audit event contract only; no persistence backend is configured."""
from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    job_id: str
    actor_id: str
    operation: str
    event_type: str
    occurred_at_utc: str
    payload_sha256: str
    result_code: Optional[str] = None


class AuditSink(Protocol):
    def append(self, event: AuditEvent) -> None:
        ...


class AuditUnavailable(RuntimeError):
    """Raised when an audit event cannot be durably accepted."""
