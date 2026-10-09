"""Design-only identity→RBAC contract for dashboard.read.

VerifiedIdentity must be created only by a future trusted authentication adapter
after validating the web session. This module does not authenticate sessions.
"""
from __future__ import annotations
from dataclasses import dataclass
import re
from typing import Protocol

from api.read_only_dashboard_v1 import ActorContext, DashboardAPIError

DASHBOARD_OPERATION = "dashboard.snapshot.read.v1"
DASHBOARD_ROLE = "dashboard.read"
_ID_RE = re.compile(r"^[A-Za-z0-9._:@/-]{1,128}$")


@dataclass(frozen=True, slots=True)
class VerifiedIdentity:
    """Trusted internal assertion: opaque issuer + subject; deliberately no roles."""
    issuer: str
    subject_id: str

    def __post_init__(self):
        if not isinstance(self.issuer, str) or not _ID_RE.fullmatch(self.issuer):
            raise DashboardAPIError("API_UNAUTHORIZED")
        if not isinstance(self.subject_id, str) or not _ID_RE.fullmatch(self.subject_id):
            raise DashboardAPIError("API_UNAUTHORIZED")


class ServerRoleResolver(Protocol):
    def roles_for(self, identity: VerifiedIdentity) -> frozenset[str]: ...


def actor_context_for_operation(identity: VerifiedIdentity | None, operation: str,
                                 role_resolver: ServerRoleResolver, *,
                                 trusted_issuers: frozenset[str]) -> ActorContext:
    """Resolve server-owned RBAC; never accepts client-supplied roles."""
    if not isinstance(trusted_issuers, frozenset) or not trusted_issuers or any(
            not isinstance(item, str) or not _ID_RE.fullmatch(item) for item in trusted_issuers):
        raise DashboardAPIError("API_INTERNAL_ERROR")
    if not isinstance(identity, VerifiedIdentity) or identity.issuer not in trusted_issuers:
        raise DashboardAPIError("API_UNAUTHORIZED")
    if operation != DASHBOARD_OPERATION:
        raise DashboardAPIError("API_FORBIDDEN")
    try:
        roles = role_resolver.roles_for(identity)
    except Exception:
        raise DashboardAPIError("API_INTERNAL_ERROR") from None
    if not isinstance(roles, frozenset) or any(not isinstance(role, str) for role in roles):
        raise DashboardAPIError("API_INTERNAL_ERROR")
    if DASHBOARD_ROLE not in roles:
        raise DashboardAPIError("API_FORBIDDEN")
    # Narrow the resulting context to the one operation's minimum role.
    return ActorContext(identity.subject_id, frozenset({DASHBOARD_ROLE}))
