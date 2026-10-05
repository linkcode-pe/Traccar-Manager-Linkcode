"""Dedicated non-root UDS server for the fixed traccar.status.read protocol."""
from __future__ import annotations

import grp
import json
import os
from pathlib import Path
import pwd
import re
import signal
import socket
import stat
import struct
import sys
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from uuid import UUID, uuid5

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from api.providers.traccar_status_v1 import TraccarStatusProvider, TraccarStatusProviderError, TraccarStatusRecord
from api.providers.traccar_status_protocol_v1 import (
    general_status_to_dispatcher_result, handler_result_to_record,
)
from worker.audit.ledger import AuditLedger, SHARED_STATUS_AUDIT_PATH
from worker.dispatcher import ActorContext, DispatchError, Job, create_preview, dispatch_job, record_authorization
from worker.operations.traccar_status import OperationError, handle as read_fixed_systemd_status

SOCKET_PATH = "/run/traccar-manager/traccar-status.sock"
AUDIT_PATH = SHARED_STATUS_AUDIT_PATH
WORKER_NAME = "traccar-manager-worker"
WORKER_GROUP = "traccar-manager-worker"
IPC_GROUP = "traccar-manager-ipc"
WEB_NAME = "traccar-manager-web"
WEB_UID = 996
OPERATION = "traccar.status.read"
_DISPATCH_OPERATION = "traccar.status"
ROLE = "traccar.status.read"
PROTOCOL_VERSION = 1
ENDPOINT = "/api/dashboard/snapshot"
MAX_MESSAGE_BYTES = 8192
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SUBJECT_RE = re.compile(r"^[0-9a-f]{32}$")
_STOP = False
_NAMESPACE = UUID("f4032784-8f15-4b74-b081-82b967f40cfb")


class RequestError(Exception):
    pass


def _stop(_signum, _frame):
    global _STOP
    _STOP = True


def _pairs_no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _read_message(connection: socket.socket) -> dict[str, object]:
    connection.settimeout(3.0)
    chunks = []
    total = 0
    while True:
        chunk = connection.recv(2048)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_MESSAGE_BYTES:
            raise RequestError()
        chunks.append(chunk)
    raw = b"".join(chunks)
    if not raw.endswith(b"\n") or raw.count(b"\n") != 1 or b"\r" in raw:
        raise RequestError()
    try:
        message = json.loads(raw[:-1].decode("utf-8"), object_pairs_hook=_pairs_no_duplicates,
                             parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("constant")))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise RequestError() from None
    expected = {"protocol_version", "operation", "request_id", "subject_id", "roles", "payload"}
    if not isinstance(message, dict) or set(message) != expected:
        raise RequestError()
    if type(message.get("protocol_version")) is not int or message["protocol_version"] != PROTOCOL_VERSION:
        raise RequestError()
    if message.get("operation") != OPERATION or message.get("payload") != {}:
        raise RequestError()
    request_id = message.get("request_id")
    subject_id = message.get("subject_id")
    roles = message.get("roles")
    if not isinstance(request_id, str) or not _REQUEST_ID_RE.fullmatch(request_id):
        raise RequestError()
    if not isinstance(subject_id, str) or not _SUBJECT_RE.fullmatch(subject_id):
        raise RequestError()
    if not isinstance(roles, list) or roles != [ROLE]:
        raise RequestError()
    return message


class _FixedSystemdSource:
    provider_id = "systemd.traccar.service.v1"

    def __init__(self, record: TraccarStatusRecord):
        self._record = record

    def read_status(self, timeout_seconds: float) -> TraccarStatusRecord:
        if timeout_seconds != 5.0:
            raise TraccarStatusProviderError("TRACCAR_STATUS_DATA_INVALID")
        return self._record


def _executor(_payload):
    if not isinstance(_payload, dict) or _payload:
        return {"confirmed": True, "outcome": "FAILED", "error_code": "E500_EXECUTION_FAILED"}
    try:
        raw = read_fixed_systemd_status({})
        record = handler_result_to_record(raw)
        provider = TraccarStatusProvider(
            _FixedSystemdSource(record),
            allowed_source_ids=frozenset({_FixedSystemdSource.provider_id}),
        )
        general = provider.collect()
        return general_status_to_dispatcher_result(general)
    except OperationError as exc:
        if exc.code == "SYSTEMD_TIMEOUT":
            code = "E501_EXECUTION_TIMEOUT"
        elif exc.code in {"SYSTEMD_UNAVAILABLE", "SYSTEMD_PERMISSION_DENIED"}:
            code = "E502_TARGET_UNAVAILABLE"
        else:
            code = "E500_EXECUTION_FAILED"
        return {"confirmed": True, "outcome": "FAILED", "error_code": code}
    except (TraccarStatusProviderError, ValueError, TypeError):
        return {"confirmed": True, "outcome": "FAILED", "error_code": "E500_EXECUTION_FAILED"}
    except Exception:
        return {"confirmed": True, "outcome": "FAILED", "error_code": "E500_EXECUTION_FAILED"}


def _perform(message: dict[str, object], ledger: AuditLedger) -> dict[str, object]:
    expected = {"protocol_version", "operation", "request_id", "subject_id", "roles", "payload"}
    if (not isinstance(message, dict) or set(message) != expected
            or type(message.get("protocol_version")) is not int or message["protocol_version"] != PROTOCOL_VERSION
            or message.get("operation") != OPERATION or message.get("payload") != {}
            or message.get("roles") != [ROLE]):
        raise RequestError()
    request_id = message["request_id"]
    subject_id = message["subject_id"]
    actor = ActorContext(subject_id, frozenset({ROLE}))
    now = datetime.now(timezone.utc)
    created = now.isoformat(timespec="microseconds").replace("+00:00", "Z")
    job_uuid = uuid5(_NAMESPACE, "job:" + request_id)
    auth_uuid = uuid5(_NAMESPACE, "auth:" + request_id)
    job = Job(
        schema_version=1,
        job_id="job-" + str(job_uuid),
        operation=_DISPATCH_OPERATION,
        payload={},
        requested_by=subject_id,
        created_at_utc=created,
        idempotency_key="status:" + request_id,
        request_id=request_id,
    )
    preview = create_preview(ledger, job, actor)
    issued = datetime.now(timezone.utc)
    grant = record_authorization(
        ledger, job, actor, preview,
        authorization_id="auth-" + str(auth_uuid),
        issued_at_utc=issued.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        expires_at_utc=(issued + timedelta(seconds=60)).isoformat(timespec="microseconds").replace("+00:00", "Z"),
    )
    staged_job = replace(job, preview_id=preview.preview_id, authorization_id=grant.authorization_id)
    result = dispatch_job(staged_job, actor, ledger=ledger, preview=preview, authorization=grant, executor=_executor)
    if (not isinstance(result, dict) or result.get("confirmed") is not True
            or result.get("outcome") != "SUCCEEDED" or result.get("source") != "systemd"
            or result.get("unit") != "traccar.service" or result.get("observed_at_utc") is None):
        raise RequestError()
    integrity = ledger.verify()
    if not integrity.valid or integrity.event_count < 1:
        raise RequestError()
    receipt = ledger.finalization_receipt(
        request_id=request_id, subject_id=subject_id, role=ROLE,
        endpoint=ENDPOINT, protocol_operation=OPERATION,
        operation=_DISPATCH_OPERATION,
        target={"type": "systemd-unit", "id": "traccar.service"},
    )
    if not isinstance(receipt, dict):
        raise RequestError()
    return {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "operation": OPERATION,
        "request_id": request_id,
        "outcome": "SUCCEEDED",
        "observed_at_utc": result["observed_at_utc"],
        "properties": dict(result["properties"]),
        "audit_receipt": receipt,
    }


def _respond(connection: socket.socket, request_id: str, *, result=None) -> None:
    if result is not None:
        payload = result
    else:
        payload = {"schema_version": 1, "protocol_version": PROTOCOL_VERSION,
                   "operation": OPERATION, "request_id": request_id,
                   "outcome": "FAILED", "error_code": "WORKER_UNAVAILABLE"}
    try:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
        if len(encoded) > MAX_MESSAGE_BYTES:
            return
        connection.sendall(encoded)
    except (OSError, TypeError, ValueError):
        return


def _peer_credentials(connection: socket.socket) -> tuple[int, int]:
    try:
        raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        pid, uid, gid = struct.unpack("3i", raw)
    except (AttributeError, OSError, struct.error):
        raise RequestError() from None
    if pid <= 0 or gid < 0:
        raise RequestError()
    return uid, gid


def _check_runtime(worker_uid: int, ipc_gid: int) -> None:
    directory = os.lstat(os.path.dirname(SOCKET_PATH))
    if (not stat.S_ISDIR(directory.st_mode) or directory.st_uid != worker_uid
            or directory.st_gid != ipc_gid or stat.S_IMODE(directory.st_mode) != 0o750
            or stat.S_ISLNK(directory.st_mode)):
        raise OSError("runtime directory invalid")
    if os.path.lexists(SOCKET_PATH):
        raise OSError("socket path already exists")


def _serve_one(connection: socket.socket, web_uid: int, web_gid: int, ledger: AuditLedger) -> None:
    request_id = "invalid"
    try:
        if _peer_credentials(connection) != (web_uid, web_gid):
            raise RequestError()
        message = _read_message(connection)
        request_id = message["request_id"]
        result = _perform(message, ledger)
        _respond(connection, request_id, result=result)
    except (RequestError, DispatchError, OSError, ValueError, TypeError, KeyError, RuntimeError):
        _respond(connection, request_id)
    except Exception:
        _respond(connection, request_id)


def serve_forever() -> None:
    if os.geteuid() == 0:
        raise SystemExit(1)
    worker = pwd.getpwuid(os.geteuid())
    if worker.pw_name != WORKER_NAME:
        raise SystemExit(1)
    if os.geteuid() != pwd.getpwnam(WORKER_NAME).pw_uid:
        raise SystemExit(1)
    web_account = pwd.getpwnam(WEB_NAME)
    web_uid, web_gid = web_account.pw_uid, web_account.pw_gid
    if web_uid != WEB_UID:
        raise SystemExit(1)
    ipc_gid = grp.getgrnam(IPC_GROUP).gr_gid
    worker_gid = grp.getgrnam(WORKER_GROUP).gr_gid
    if os.getegid() != worker_gid:
        raise SystemExit(1)
    _check_runtime(os.geteuid(), ipc_gid)
    ledger = AuditLedger(
        AUDIT_PATH, create_mode=0o640,
        expected_owner_uid=os.geteuid(), expected_group_gid=worker_gid,
        expected_file_mode=0o640, expected_directory_mode=0o750,
        event_metadata={"endpoint": ENDPOINT, "protocol_operation": OPERATION},
    )
    report = ledger.verify()
    if not report.valid:
        raise SystemExit(1)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.settimeout(1.0)
    listener.bind(SOCKET_PATH)
    os.chown(SOCKET_PATH, os.geteuid(), ipc_gid)
    os.chmod(SOCKET_PATH, 0o660)
    socket_inode = os.lstat(SOCKET_PATH).st_ino
    listener.listen(16)
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    try:
        while not _STOP:
            try:
                connection, _address = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                if _STOP:
                    break
                raise
            with connection:
                _serve_one(connection, web_uid, web_gid, ledger)
    finally:
        listener.close()
        try:
            info = os.lstat(SOCKET_PATH)
            if stat.S_ISSOCK(info.st_mode) and info.st_ino == socket_inode and info.st_uid == os.geteuid():
                os.unlink(SOCKET_PATH)
        except OSError:
            pass


if __name__ == "__main__":
    try:
        serve_forever()
    except SystemExit:
        raise
    except Exception:
        raise SystemExit(1) from None
