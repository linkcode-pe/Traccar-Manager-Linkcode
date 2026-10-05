"""Strict local UDS client for the fixed Traccar status Worker operation."""
from __future__ import annotations

from datetime import datetime, timezone
import grp
import json
import os
from pathlib import Path
import pwd
import re
import socket
import stat
import struct
from uuid import UUID

SOCKET_PATH = "/run/traccar-manager/traccar-status.sock"
WEB_UID = 996
WORKER_NAME = "traccar-manager-worker"
WORKER_GROUP = "traccar-manager-worker"
IPC_GROUP = "traccar-manager-ipc"
OPERATION = "traccar.status.read"
ROLE = "traccar.status.read"
PROTOCOL_VERSION = 1
ENDPOINT = "/api/dashboard/snapshot"
LEDGER_OPERATION = "traccar.status"
MAX_MESSAGE_BYTES = 8192
ROUNDTRIP_TIMEOUT_SECONDS = 15.0
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SUBJECT_RE = re.compile(r"^[0-9a-f]{32}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_PROPERTIES = ("LoadState", "ActiveState", "SubState", "UnitFileState", "Result")
_STATE_RE = re.compile(r"^[A-Za-z0-9_.+-]{1,64}$")
_AUDIT_RECEIPT_KEYS = frozenset({
    "schema_version", "protocol_version", "request_id", "operation",
    "ledger_operation", "endpoint", "subject_id", "role", "phase",
    "event_id", "ledger_sequence", "previous_event_hash", "event_hash", "durable",
})


class WorkerTransportError(RuntimeError):
    """Sanitized local transport failure."""


def _pairs_no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _peer_credentials(sock: socket.socket) -> tuple[int, int, int]:
    size = struct.calcsize("3i")
    try:
        raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, size)
        pid, uid, gid = struct.unpack("3i", raw)
    except (AttributeError, OSError, struct.error):
        raise WorkerTransportError("WORKER_UNAVAILABLE") from None
    if pid <= 0 or uid < 0 or gid < 0:
        raise WorkerTransportError("WORKER_UNAVAILABLE")
    return pid, uid, gid


def _verify_socket_path() -> tuple[int, int, int]:
    try:
        directory = os.lstat(os.path.dirname(SOCKET_PATH))
        info = os.lstat(SOCKET_PATH)
        worker = pwd.getpwnam(WORKER_NAME)
        ipc_gid = grp.getgrnam(IPC_GROUP).gr_gid
    except (OSError, KeyError):
        raise WorkerTransportError("WORKER_UNAVAILABLE") from None
    worker_uid, worker_gid = worker.pw_uid, worker.pw_gid
    if (not stat.S_ISDIR(directory.st_mode) or stat.S_ISLNK(directory.st_mode)
            or directory.st_uid != worker_uid or directory.st_gid != ipc_gid
            or stat.S_IMODE(directory.st_mode) != 0o750):
        raise WorkerTransportError("WORKER_UNAVAILABLE")
    if (not stat.S_ISSOCK(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != worker_uid or info.st_gid != ipc_gid
            or stat.S_IMODE(info.st_mode) != 0o660):
        raise WorkerTransportError("WORKER_UNAVAILABLE")
    return worker_uid, worker_gid, ipc_gid


def _validate_receipt(receipt, *, request_id: str, subject_id: str) -> bool:
    if not isinstance(receipt, dict) or set(receipt) != _AUDIT_RECEIPT_KEYS:
        return False
    if (type(receipt.get("schema_version")) is not int or receipt["schema_version"] != 1
            or type(receipt.get("protocol_version")) is not int or receipt["protocol_version"] != PROTOCOL_VERSION
            or receipt.get("request_id") != request_id
            or receipt.get("operation") != OPERATION
            or receipt.get("ledger_operation") != LEDGER_OPERATION
            or receipt.get("endpoint") != ENDPOINT
            or receipt.get("subject_id") != subject_id
            or receipt.get("role") != ROLE
            or receipt.get("phase") != "AUDIT_FINALIZATION"
            or receipt.get("durable") is not True
            or type(receipt.get("ledger_sequence")) is not int
            or receipt["ledger_sequence"] < 1):
        return False
    event_id = receipt.get("event_id")
    if not isinstance(event_id, str):
        return False
    try:
        UUID(event_id)
    except (ValueError, TypeError, AttributeError):
        return False
    if not isinstance(receipt.get("event_hash"), str) or not _HASH_RE.fullmatch(receipt["event_hash"]):
        return False
    previous = receipt.get("previous_event_hash")
    return previous is None or (isinstance(previous, str) and bool(_HASH_RE.fullmatch(previous)))


def query_status(request_id: str, subject_id: str, roles: tuple[str, ...]) -> dict[str, object]:
    """Send one correlated fixed request; never retries and never uses TCP."""
    if (not isinstance(request_id, str) or not _REQUEST_ID_RE.fullmatch(request_id)
            or not isinstance(subject_id, str) or not _SUBJECT_RE.fullmatch(subject_id)
            or not isinstance(roles, tuple) or ROLE not in roles):
        raise WorkerTransportError("INVALID_REQUEST")
    if os.geteuid() != WEB_UID:
        raise WorkerTransportError("WORKER_UNAVAILABLE")
    worker_uid, worker_gid, _ipc_gid = _verify_socket_path()
    message = {
        "protocol_version": PROTOCOL_VERSION,
        "operation": OPERATION,
        "request_id": request_id,
        "subject_id": subject_id,
        "roles": [ROLE],
        "payload": {},
    }
    encoded = json.dumps(message, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise WorkerTransportError("INVALID_REQUEST")
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(ROUNDTRIP_TIMEOUT_SECONDS)
    try:
        client.connect(SOCKET_PATH)
        _pid, peer_uid, peer_gid = _peer_credentials(client)
        if peer_uid != worker_uid or peer_gid != worker_gid:
            raise WorkerTransportError("WORKER_UNAVAILABLE")
        client.sendall(encoded)
        client.shutdown(socket.SHUT_WR)
        chunks = []
        total = 0
        while True:
            chunk = client.recv(2048)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_MESSAGE_BYTES:
                raise WorkerTransportError("WORKER_UNAVAILABLE")
            chunks.append(chunk)
    except WorkerTransportError:
        raise
    except (OSError, TimeoutError):
        raise WorkerTransportError("WORKER_UNAVAILABLE") from None
    finally:
        client.close()
    raw = b"".join(chunks)
    if not raw.endswith(b"\n") or raw.count(b"\n") != 1 or b"\r" in raw:
        raise WorkerTransportError("WORKER_UNAVAILABLE")
    try:
        response = json.loads(raw[:-1].decode("utf-8"), object_pairs_hook=_pairs_no_duplicates,
                              parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("constant")))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise WorkerTransportError("WORKER_UNAVAILABLE") from None
    if not isinstance(response, dict):
        raise WorkerTransportError("WORKER_UNAVAILABLE")
    if (type(response.get("schema_version")) is not int or response.get("schema_version") != 1
            or type(response.get("protocol_version")) is not int or response.get("protocol_version") != PROTOCOL_VERSION
            or response.get("operation") != OPERATION or response.get("request_id") != request_id):
        raise WorkerTransportError("WORKER_UNAVAILABLE")
    if response.get("outcome") == "FAILED":
        if set(response) != {"schema_version", "protocol_version", "operation", "request_id", "outcome", "error_code"}:
            raise WorkerTransportError("WORKER_UNAVAILABLE")
        if response.get("error_code") not in {"WORKER_UNAVAILABLE"}:
            raise WorkerTransportError("WORKER_UNAVAILABLE")
        raise WorkerTransportError("WORKER_UNAVAILABLE")
    expected = {"schema_version", "protocol_version", "operation", "request_id", "outcome",
                "observed_at_utc", "properties", "audit_receipt"}
    if set(response) != expected or response.get("outcome") != "SUCCEEDED":
        raise WorkerTransportError("WORKER_UNAVAILABLE")
    properties = response.get("properties")
    if not isinstance(properties, dict) or set(properties) != set(_PROPERTIES):
        raise WorkerTransportError("WORKER_UNAVAILABLE")
    if any(not isinstance(properties[key], str) or not _STATE_RE.fullmatch(properties[key]) for key in _PROPERTIES):
        raise WorkerTransportError("WORKER_UNAVAILABLE")
    observed = response.get("observed_at_utc")
    if not isinstance(observed, str) or not observed.endswith("Z") or len(observed) > 40:
        raise WorkerTransportError("WORKER_UNAVAILABLE")
    try:
        parsed = datetime.fromisoformat(observed[:-1] + "+00:00")
    except ValueError:
        raise WorkerTransportError("WORKER_UNAVAILABLE") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise WorkerTransportError("WORKER_UNAVAILABLE")
    receipt = response.get("audit_receipt")
    if not _validate_receipt(receipt, request_id=request_id, subject_id=subject_id):
        raise WorkerTransportError("WORKER_UNAVAILABLE")
    return {"observed_at_utc": observed, "properties": dict(properties), "audit_receipt": dict(receipt)}

MAINTENANCE_OPERATION = "maintenance.logs.preview"
MAINTENANCE_ROLE = "maintenance.logs.preview"
MAINTENANCE_ENDPOINT = "/api/maintenance/logs/preview"

def query_maintenance_logs_preview(request_id: str, subject_id: str, roles: tuple[str, ...], retention_days: int = 90) -> dict[str, object]:
    """One correlated read-only maintenance preview over the existing AF_UNIX Worker channel."""
    if (not isinstance(request_id,str) or not _REQUEST_ID_RE.fullmatch(request_id)
            or not isinstance(subject_id,str) or not _SUBJECT_RE.fullmatch(subject_id)
            or not isinstance(roles,tuple) or MAINTENANCE_ROLE not in roles
            or type(retention_days) is not int or not 30 <= retention_days <= 3650):
        raise WorkerTransportError("INVALID_REQUEST")
    if os.geteuid()!=WEB_UID: raise WorkerTransportError("WORKER_UNAVAILABLE")
    worker_uid,worker_gid,_=_verify_socket_path()
    message={"protocol_version":PROTOCOL_VERSION,"operation":MAINTENANCE_OPERATION,"request_id":request_id,
             "subject_id":subject_id,"roles":[MAINTENANCE_ROLE],"payload":{"retention_days":retention_days}}
    encoded=json.dumps(message,sort_keys=True,separators=(",",":"),allow_nan=False).encode()+b"\n"
    client=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM); client.settimeout(ROUNDTRIP_TIMEOUT_SECONDS)
    try:
        client.connect(SOCKET_PATH); _pid,uid,gid=_peer_credentials(client)
        if uid!=worker_uid or gid!=worker_gid: raise WorkerTransportError("WORKER_UNAVAILABLE")
        client.sendall(encoded); client.shutdown(socket.SHUT_WR); chunks=[]; total=0
        while True:
            chunk=client.recv(2048)
            if not chunk: break
            total+=len(chunk)
            if total>MAX_MESSAGE_BYTES: raise WorkerTransportError("WORKER_UNAVAILABLE")
            chunks.append(chunk)
    except WorkerTransportError: raise
    except (OSError,TimeoutError): raise WorkerTransportError("WORKER_UNAVAILABLE") from None
    finally: client.close()
    raw=b"".join(chunks)
    if not raw.endswith(b"\n") or raw.count(b"\n")!=1 or b"\r" in raw: raise WorkerTransportError("WORKER_UNAVAILABLE")
    try: response=json.loads(raw[:-1].decode(),object_pairs_hook=_pairs_no_duplicates,parse_constant=lambda _v: (_ for _ in ()).throw(ValueError()))
    except Exception: raise WorkerTransportError("WORKER_UNAVAILABLE") from None
    if not isinstance(response,dict) or response.get("schema_version")!=1 or response.get("protocol_version")!=1 or response.get("operation")!=MAINTENANCE_OPERATION or response.get("request_id")!=request_id:
        raise WorkerTransportError("WORKER_UNAVAILABLE")
    if response.get("outcome")!="SUCCEEDED" or set(response)!={"schema_version","protocol_version","operation","request_id","outcome","preview","preview_id","audit_receipt"}:
        raise WorkerTransportError("WORKER_UNAVAILABLE")
    preview=response.get("preview"); receipt=response.get("audit_receipt"); preview_id=response.get("preview_id")
    required={"log_dir","retention_days","cutoff_utc","candidate_count","candidate_bytes","candidates","active_log_protected","destructive_action_performed"}
    if not isinstance(preview,dict) or set(preview)!=required or preview.get("log_dir")!="/opt/traccar/logs" or preview.get("retention_days")!=retention_days or preview.get("destructive_action_performed") is not False or preview.get("active_log_protected") is not True:
        raise WorkerTransportError("WORKER_UNAVAILABLE")
    if type(preview.get("candidate_count")) is not int or preview["candidate_count"]<0 or type(preview.get("candidate_bytes")) is not int or preview["candidate_bytes"]<0 or not isinstance(preview.get("candidates"),list) or len(preview["candidates"])!=preview["candidate_count"]:
        raise WorkerTransportError("WORKER_UNAVAILABLE")
    if not isinstance(preview_id,str) or not preview_id.startswith("preview-") or len(preview_id)!=72: raise WorkerTransportError("WORKER_UNAVAILABLE")
    if not isinstance(receipt,dict) or set(receipt)!=_AUDIT_RECEIPT_KEYS or receipt.get("operation")!=MAINTENANCE_OPERATION or receipt.get("ledger_operation")!=MAINTENANCE_OPERATION or receipt.get("endpoint")!=MAINTENANCE_ENDPOINT or receipt.get("role")!=MAINTENANCE_ROLE or receipt.get("request_id")!=request_id or receipt.get("subject_id")!=subject_id or receipt.get("durable") is not True:
        raise WorkerTransportError("WORKER_UNAVAILABLE")
    return {"preview":preview,"preview_id":preview_id,"audit_receipt":receipt}


MAINTENANCE_PREPARE_OPERATION = "maintenance.logs.prepare"
MAINTENANCE_PREPARE_ROLE = "maintenance.logs.prepare"
MAINTENANCE_PREPARE_ENDPOINT = "/api/maintenance/logs/prepare"

def query_maintenance_logs_prepare(request_id: str, subject_id: str, roles: tuple[str, ...], preview_id: str, retention_days: int = 90) -> dict[str, object]:
    if (not isinstance(request_id,str) or not _REQUEST_ID_RE.fullmatch(request_id) or not isinstance(subject_id,str) or not _SUBJECT_RE.fullmatch(subject_id)
            or not isinstance(roles,tuple) or MAINTENANCE_PREPARE_ROLE not in roles or not isinstance(preview_id,str) or not preview_id.startswith("preview-") or len(preview_id)!=72
            or type(retention_days) is not int or not 30 <= retention_days <= 3650): raise WorkerTransportError("INVALID_REQUEST")
    if os.geteuid()!=WEB_UID: raise WorkerTransportError("WORKER_UNAVAILABLE")
    worker_uid,worker_gid,_=_verify_socket_path(); message={"protocol_version":1,"operation":MAINTENANCE_PREPARE_OPERATION,"request_id":request_id,"subject_id":subject_id,"roles":[MAINTENANCE_PREPARE_ROLE],"payload":{"retention_days":retention_days,"preview_id":preview_id}}
    encoded=json.dumps(message,sort_keys=True,separators=(",",":"),allow_nan=False).encode()+b"\n"; client=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM); client.settimeout(ROUNDTRIP_TIMEOUT_SECONDS)
    try:
        client.connect(SOCKET_PATH); _pid,uid,gid=_peer_credentials(client)
        if uid!=worker_uid or gid!=worker_gid: raise WorkerTransportError("WORKER_UNAVAILABLE")
        client.sendall(encoded); client.shutdown(socket.SHUT_WR); chunks=[]; total=0
        while True:
            chunk=client.recv(2048)
            if not chunk: break
            total+=len(chunk)
            if total>MAX_MESSAGE_BYTES: raise WorkerTransportError("WORKER_UNAVAILABLE")
            chunks.append(chunk)
    except WorkerTransportError: raise
    except (OSError,TimeoutError): raise WorkerTransportError("WORKER_UNAVAILABLE") from None
    finally: client.close()
    raw=b"".join(chunks)
    try: response=json.loads(raw[:-1].decode(),object_pairs_hook=_pairs_no_duplicates) if raw.endswith(b"\n") and raw.count(b"\n")==1 else None
    except Exception: response=None
    if not isinstance(response,dict) or set(response)!={"schema_version","protocol_version","operation","request_id","outcome","preparation","preview_id","preparation_stored","execution_readiness","boundary_execute_probe","boundary_candidate_count","audit_receipt"} or response.get("operation")!=MAINTENANCE_PREPARE_OPERATION or response.get("request_id")!=request_id or response.get("outcome")!="SUCCEEDED" or response.get("preview_id")!=preview_id: raise WorkerTransportError("WORKER_UNAVAILABLE")
    preparation=response.get("preparation"); receipt=response.get("audit_receipt")
    required={"preparation_id","preview_id","preview_hash","retention_days","candidate_count","candidate_bytes","issued_at_utc","expires_at_utc","one_time_nonce","revalidated","destructive_action_performed"}
    if response.get("preparation_stored") is not True or response.get("execution_readiness")!="READY_BLOCKED" or response.get("boundary_execute_probe")!="DENIED_BY_PRODUCTION_GATE" or response.get("boundary_candidate_count")!=preparation.get("candidate_count"): raise WorkerTransportError("WORKER_UNAVAILABLE")
    if not isinstance(preparation,dict) or set(preparation)!=required or preparation.get("preview_id")!=preview_id or preparation.get("retention_days")!=retention_days or preparation.get("revalidated") is not True or preparation.get("destructive_action_performed") is not False: raise WorkerTransportError("WORKER_UNAVAILABLE")
    if not isinstance(receipt,dict) or receipt.get("operation")!=MAINTENANCE_PREPARE_OPERATION or receipt.get("request_id")!=request_id or receipt.get("subject_id")!=subject_id or receipt.get("durable") is not True: raise WorkerTransportError("WORKER_UNAVAILABLE")
    return {"preparation":preparation,"preview_id":preview_id,"preparation_stored":True,"execution_readiness":"READY_BLOCKED","boundary_execute_probe":"DENIED_BY_PRODUCTION_GATE","boundary_candidate_count":response["boundary_candidate_count"],"audit_receipt":receipt}

BOUNDARY_HEALTH_OPERATION="maintenance.boundary.health"
BOUNDARY_HEALTH_ROLE=MAINTENANCE_ROLE

def query_retention_boundary_health(request_id:str,subject_id:str,roles:tuple[str,...])->dict[str,object]:
    if not isinstance(request_id,str) or not _REQUEST_ID_RE.fullmatch(request_id) or not isinstance(subject_id,str) or not _SUBJECT_RE.fullmatch(subject_id) or not isinstance(roles,tuple) or BOUNDARY_HEALTH_ROLE not in roles: raise WorkerTransportError("INVALID_REQUEST")
    if os.geteuid()!=WEB_UID: raise WorkerTransportError("WORKER_UNAVAILABLE")
    worker_uid,worker_gid,_=_verify_socket_path(); msg={"protocol_version":1,"operation":BOUNDARY_HEALTH_OPERATION,"request_id":request_id,"subject_id":subject_id,"roles":[BOUNDARY_HEALTH_ROLE],"payload":{}}
    c=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);c.settimeout(ROUNDTRIP_TIMEOUT_SECONDS)
    try:
        c.connect(SOCKET_PATH);_pid,uid,gid=_peer_credentials(c)
        if uid!=worker_uid or gid!=worker_gid: raise WorkerTransportError("WORKER_UNAVAILABLE")
        c.sendall(json.dumps(msg,sort_keys=True,separators=(",",":")).encode()+b"\n");c.shutdown(socket.SHUT_WR);raw=b""
        while True:
            x=c.recv(2048)
            if not x:break
            raw+=x
            if len(raw)>MAX_MESSAGE_BYTES:raise WorkerTransportError("WORKER_UNAVAILABLE")
    except WorkerTransportError:raise
    except OSError:raise WorkerTransportError("WORKER_UNAVAILABLE") from None
    finally:c.close()
    try:r=json.loads(raw[:-1].decode()) if raw.endswith(b"\n") and raw.count(b"\n")==1 else None
    except Exception:r=None
    expected={'active_log_denied':True,'allowed_name_pattern':'tracker-server.log.YYYYMMDD','allowed_operation':'DELETE_EXPIRED_HISTORICAL_LOGS','component':'traccar-manager-retention-boundary','destructive_action_performed':False,'mode':'DENY_PRODUCTION','network_access':False,'production_access':False,'separate_identity_required':True,'shell_access':False,'status':'healthy'}
    if not isinstance(r,dict) or set(r)!={'schema_version','protocol_version','operation','request_id','outcome','boundary'} or r.get('operation')!=BOUNDARY_HEALTH_OPERATION or r.get('request_id')!=request_id or r.get('outcome')!='SUCCEEDED' or r.get('boundary')!=expected:raise WorkerTransportError("WORKER_UNAVAILABLE")
    return dict(r['boundary'])

MAINTENANCE_EXECUTE_OPERATION = "maintenance.logs.execute"
MAINTENANCE_EXECUTE_ROLE = "maintenance.logs.execute"
MAINTENANCE_EXECUTE_ENDPOINT = "/api/maintenance/logs/execute"

def query_maintenance_logs_execute(request_id, subject_id, roles, preparation, confirmation, nonce):
    if not isinstance(request_id,str) or not _REQUEST_ID_RE.fullmatch(request_id) or not isinstance(subject_id,str) or not _SUBJECT_RE.fullmatch(subject_id) or not isinstance(roles,tuple) or MAINTENANCE_EXECUTE_ROLE not in roles or not isinstance(preparation,dict) or not isinstance(confirmation,str) or not isinstance(nonce,str): raise WorkerTransportError("INVALID_REQUEST")
    if os.geteuid()!=WEB_UID: raise WorkerTransportError("WORKER_UNAVAILABLE")
    worker_uid,worker_gid,_=_verify_socket_path()
    msg={"protocol_version":1,"operation":MAINTENANCE_EXECUTE_OPERATION,"request_id":request_id,"subject_id":subject_id,"roles":[MAINTENANCE_EXECUTE_ROLE],"payload":{"preparation":preparation,"confirmation":confirmation,"nonce":nonce}}
    c=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM); c.settimeout(ROUNDTRIP_TIMEOUT_SECONDS)
    try:
        c.connect(SOCKET_PATH); _pid,uid,gid=_peer_credentials(c)
        if uid!=worker_uid or gid!=worker_gid: raise WorkerTransportError("WORKER_UNAVAILABLE")
        c.sendall(json.dumps(msg,sort_keys=True,separators=(",",":"),allow_nan=False).encode()+b"\n"); c.shutdown(socket.SHUT_WR); raw=b""
        while True:
            x=c.recv(2048)
            if not x: break
            raw+=x
            if len(raw)>MAX_MESSAGE_BYTES: raise WorkerTransportError("WORKER_UNAVAILABLE")
    except WorkerTransportError: raise
    except (OSError,TimeoutError): raise WorkerTransportError("WORKER_UNAVAILABLE") from None
    finally: c.close()
    try: r=json.loads(raw[:-1].decode(),object_pairs_hook=_pairs_no_duplicates) if raw.endswith(b"\n") and raw.count(b"\n")==1 else None
    except Exception: r=None
    if not isinstance(r,dict) or r.get("operation")!=MAINTENANCE_EXECUTE_OPERATION or r.get("request_id")!=request_id or r.get("outcome")!="SUCCEEDED": raise WorkerTransportError("WORKER_UNAVAILABLE")
    e=r.get("execution")
    if not isinstance(e,dict) or e.get("outcome")!="BLOCKED_BY_FEATURE_GATE" or e.get("destructive_action_performed") is not False: raise WorkerTransportError("WORKER_UNAVAILABLE")
    return e
