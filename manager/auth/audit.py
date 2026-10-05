"""Sanitized authentication events written to systemd-captured stderr.

This is operational logging only, not a durable or tamper-evident ledger.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import sys
import threading

_ALLOWED = {
    ("AUTH_LOGIN", "SUCCEEDED", "AUTHENTICATED"),
    ("AUTH_LOGIN", "DENIED", "INVALID_CREDENTIALS"),
    ("AUTH_LOGIN", "DENIED", "INVALID_REQUEST"),
    ("AUTH_LOGIN", "UNAVAILABLE", "AUTH_STORE_UNAVAILABLE"),
    ("AUTH_LOGIN", "UNAVAILABLE", "AUDIT_UNAVAILABLE"),
    ("AUTH_SESSION_CHECK", "SUCCEEDED", "SESSION_VALID"),
    ("AUTH_SESSION_CHECK", "DENIED", "SESSION_ABSENT"),
    ("AUTH_SESSION_CHECK", "DENIED", "SESSION_INVALID_OR_EXPIRED"),
    ("AUTH_SESSION_CHECK", "UNAVAILABLE", "AUDIT_UNAVAILABLE"),
    ("AUTH_LOGOUT", "SUCCEEDED", "LOGOUT_COMPLETED"),
    ("AUTH_LOGOUT", "UNAVAILABLE", "AUDIT_UNAVAILABLE"),
    ("AUTH_DASHBOARD_READ", "REQUESTED", "READ_REQUESTED"),
    ("AUTH_DASHBOARD_READ", "DENIED", "ROLE_NOT_ALLOWED"),
    ("AUTH_DASHBOARD_READ", "DENIED", "INVALID_REQUEST"),
    ("AUTH_DASHBOARD_READ", "UNAVAILABLE", "AUDIT_UNAVAILABLE"),
    ("AUTH_DASHBOARD_READ", "UNAVAILABLE", "PROVIDER_UNAVAILABLE"),
    ("AUTH_DASHBOARD_READ", "UNAVAILABLE", "INTERNAL_ERROR"),
    ("AUTH_DASHBOARD_READ", "SUCCEEDED", "DISPATCHER_RECEIPT_VERIFIED"),
}
_LOCK = threading.Lock()


def write_auth_audit(event: str, result: str, reason_code: str) -> bool:
    """Emit only fixed fields/codes; never accept caller-controlled data."""
    if (event, result, reason_code) not in _ALLOWED:
        return False
    record = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "event": event,
        "result": result,
        "reason_code": reason_code,
    }
    line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
    try:
        with _LOCK:
            sys.stderr.write(line)
            sys.stderr.flush()
        return True
    except Exception:
        return False
