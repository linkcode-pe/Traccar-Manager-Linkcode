"""Read-only handler for the fixed traccar.status operation.

The candidate Worker may call this only behind its fixed UDS operation and audit
boundary. It is not installed or activated by this source-only candidate. The
handler requires a dedicated non-root identity and never accepts a unit or
command from the request payload.
"""
from datetime import datetime, timezone
import os
import subprocess

_SYSTEMCTL = "/usr/bin/systemctl"
_UNIT = "traccar.service"
_PROPERTIES = ("LoadState", "ActiveState", "SubState", "UnitFileState", "Result")


class OperationError(RuntimeError):
    """Sanitized operation failure; never carries stderr or secret values."""

    def __init__(self, code, retryable=False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def handle(payload):
    """Return allowlisted systemd state; this function performs no writes."""
    if os.geteuid() == 0:
        raise OperationError("RUN_AS_ROOT_FORBIDDEN")
    if not isinstance(payload, dict) or payload:
        raise OperationError("INVALID_PAYLOAD")

    command = [
        _SYSTEMCTL,
        "show",
        "--no-pager",
        "--property=" + ",".join(_PROPERTIES),
        _UNIT,
    ]
    env = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "SYSTEMD_PAGER": "cat",
        "SYSTEMD_COLORS": "0",
    }
    try:
        completed = subprocess.run(
            command,
            shell=False,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
        )
    except FileNotFoundError:
        raise OperationError("SYSTEMD_UNAVAILABLE") from None
    except PermissionError:
        raise OperationError("SYSTEMD_PERMISSION_DENIED") from None
    except subprocess.TimeoutExpired:
        raise OperationError("SYSTEMD_TIMEOUT", retryable=True) from None
    except OSError:
        raise OperationError("SYSTEMD_QUERY_FAILED") from None

    if completed.returncode != 0:
        raise OperationError("SYSTEMD_QUERY_FAILED")

    state = {}
    allowed = set(_PROPERTIES)
    for line in completed.stdout.splitlines():
        if "=" not in line:
            raise OperationError("OUTPUT_INVALID")
        key, value = line.split("=", 1)
        if key not in allowed or key in state:
            raise OperationError("OUTPUT_INVALID")
        state[key] = value
    if set(state) != allowed:
        raise OperationError("OUTPUT_INVALID")

    observed = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return {
        "schema_version": 1,
        "operation": "traccar.status",
        "result": "SUCCEEDED",
        "observed_at_utc": observed,
        "source": "systemd",
        "unit": _UNIT,
        "state": state,
    }
