"""Contract for the output of a future trusted Web-session verifier.

This module neither reads PHP sessions/cookies nor verifies a signature. Only a
trusted server-side adapter may construct AUTHENTICATED evidence after doing so.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re

from api.identity_contract_v1 import (
    DASHBOARD_OPERATION, VerifiedIdentity, ServerRoleResolver,
    actor_context_for_operation,
)
from api.read_only_dashboard_v1 import ActorContext, DashboardAPIError

_ASSERTION_ID = re.compile(r"^[A-Za-z0-9._-]{16,128}$")


class WebSessionState(str, Enum):
    AUTHENTICATED = "AUTHENTICATED"
    ABSENT = "ABSENT"
    INVALID = "INVALID"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class WebSessionEvidence:
    """Trusted adapter result; no cookie, token, password, role or client user_id."""
    state: WebSessionState
    identity: VerifiedIdentity | None = None
    expires_at_utc: str | None = None
    assertion_id: str | None = None


def actor_from_verified_web_session(evidence: WebSessionEvidence | None,
                                   role_resolver: ServerRoleResolver, *,
                                   trusted_issuers: frozenset[str],
                                   operation: str = DASHBOARD_OPERATION,
                                   now_utc: datetime | None = None) -> ActorContext:
    """Fail closed; consumes only trusted verifier output, never HTTP fields."""
    if not isinstance(evidence, WebSessionEvidence):
        raise DashboardAPIError("API_UNAUTHORIZED")
    if evidence.state is not WebSessionState.AUTHENTICATED:
        raise DashboardAPIError("API_UNAUTHORIZED")
    if not isinstance(evidence.identity, VerifiedIdentity):
        raise DashboardAPIError("API_UNAUTHORIZED")
    if not isinstance(evidence.expires_at_utc, str) or not evidence.expires_at_utc.endswith("Z"):
        raise DashboardAPIError("API_UNAUTHORIZED")
    if not isinstance(evidence.assertion_id, str) or not _ASSERTION_ID.fullmatch(evidence.assertion_id):
        raise DashboardAPIError("API_UNAUTHORIZED")
    try:
        expiry = datetime.fromisoformat(evidence.expires_at_utc[:-1] + "+00:00")
    except ValueError:
        raise DashboardAPIError("API_UNAUTHORIZED") from None
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise DashboardAPIError("API_INTERNAL_ERROR")
    if expiry <= now.astimezone(timezone.utc):
        raise DashboardAPIError("API_UNAUTHORIZED")
    return actor_context_for_operation(
        evidence.identity, operation, role_resolver, trusted_issuers=trusted_issuers
    )
