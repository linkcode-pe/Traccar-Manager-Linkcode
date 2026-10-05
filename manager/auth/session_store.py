"""In-memory opaque, expiring Web sessions for Traccar Manager."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import re
import secrets
import threading
import time

from manager.auth.auth_store import AuthenticatedUser

_IDLE_TIMEOUT_SECONDS = 900
_ABSOLUTE_TIMEOUT_SECONDS = 28_800
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{40,64}$")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class SessionPrincipal:
    subject_id: str
    username: str
    roles: tuple[str, ...]
    expires_at_utc: str

    def public_dict(self) -> dict[str, object]:
        return {
            "subject_id": self.subject_id,
            "username": self.username,
            "roles": list(self.roles),
        }


@dataclass(slots=True)
class _SessionRecord:
    user: AuthenticatedUser
    created_at: float
    last_seen_at: float


class SessionStore:
    """Stores only SHA-256 token digests; tokens themselves are returned once."""

    def __init__(self, *, idle_timeout: int = _IDLE_TIMEOUT_SECONDS,
                 absolute_timeout: int = _ABSOLUTE_TIMEOUT_SECONDS,
                 clock=time.monotonic):
        if not isinstance(idle_timeout, int) or not 1 <= idle_timeout <= 86_400:
            raise ValueError("invalid idle timeout")
        if not isinstance(absolute_timeout, int) or not idle_timeout <= absolute_timeout <= 604_800:
            raise ValueError("invalid absolute timeout")
        self._idle_timeout = idle_timeout
        self._absolute_timeout = absolute_timeout
        self._clock = clock
        self._sessions: dict[bytes, _SessionRecord] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _digest(token: str) -> bytes | None:
        if not isinstance(token, str) or not _TOKEN_RE.fullmatch(token):
            return None
        try:
            raw = token.encode("ascii")
        except UnicodeEncodeError:
            return None
        return hashlib.sha256(raw).digest()

    def create(self, user: AuthenticatedUser) -> tuple[str, SessionPrincipal]:
        if not isinstance(user, AuthenticatedUser):
            raise TypeError("authenticated user required")
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode("ascii")).digest()
        now_mono = self._clock()
        now_utc = _utc_now()
        expiry = now_utc + timedelta(seconds=min(self._idle_timeout, self._absolute_timeout))
        with self._lock:
            self._purge_expired(now_mono)
            self._sessions[digest] = _SessionRecord(user, now_mono, now_mono)
        principal = SessionPrincipal(user.subject_id, user.username, user.roles, _stamp(expiry))
        return token, principal

    def _purge_expired(self, now: float) -> None:
        expired = [key for key, item in self._sessions.items()
                   if now - item.last_seen_at >= self._idle_timeout or
                   now - item.created_at >= self._absolute_timeout]
        for key in expired:
            self._sessions.pop(key, None)

    def get(self, token: str) -> SessionPrincipal | None:
        digest = self._digest(token)
        if digest is None:
            return None
        now = self._clock()
        with self._lock:
            self._purge_expired(now)
            record = self._sessions.get(digest)
            if record is None:
                return None
            record.last_seen_at = now
            remaining = min(self._idle_timeout, self._absolute_timeout - (now - record.created_at))
            expiry = _utc_now() + timedelta(seconds=max(0, remaining))
            return SessionPrincipal(record.user.subject_id, record.user.username,
                                    record.user.roles, _stamp(expiry))

    def revoke(self, token: str) -> bool:
        digest = self._digest(token)
        if digest is None:
            return False
        with self._lock:
            return self._sessions.pop(digest, None) is not None

    def has_role(self, token: str, required_role: str) -> bool:
        if not isinstance(required_role, str) or not required_role:
            return False
        principal = self.get(token)
        return principal is not None and required_role in principal.roles

    def __len__(self) -> int:
        with self._lock:
            self._purge_expired(self._clock())
            return len(self._sessions)
