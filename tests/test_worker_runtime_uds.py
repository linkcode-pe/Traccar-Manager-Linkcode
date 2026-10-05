"""Mock-only integration tests for the production UDS status path."""
from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path
import socket
import stat
import tempfile
import threading
from uuid import uuid4
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from api.read_only_dashboard_v1 import Availability, DashboardAPIError
from manager.auth.auth_store import AuthenticatedUser
from manager.auth.session_store import SessionPrincipal
from manager.dashboard_http import ManagerDashboardAPI
import manager.worker_uds as uds
from worker.audit.ledger import AuditLedger, LedgerError
from worker.operations.traccar_status import handle as traccar_status_handle
import worker.operations.traccar_status as operation
import worker.runtime_server as runtime


PROPERTIES = {
    "LoadState": "loaded",
    "ActiveState": "active",
    "SubState": "running",
    "UnitFileState": "enabled",
    "Result": "success",
}
OBSERVED = "2026-10-04T09:00:00Z"


def wire_receipt(request_id, subject_id):
    return {
        "schema_version": 1, "protocol_version": 1, "request_id": request_id,
        "operation": "traccar.status.read", "ledger_operation": "traccar.status",
        "endpoint": "/api/dashboard/snapshot", "subject_id": subject_id,
        "role": "traccar.status.read", "phase": "AUDIT_FINALIZATION",
        "event_id": str(uuid4()), "ledger_sequence": 9,
        "previous_event_hash": "b" * 64, "event_hash": "c" * 64, "durable": True,
    }


def worker_message(request_id="worker-test", subject_id="e" * 32):
    return {"protocol_version": 1, "operation": "traccar.status.read",
            "request_id": request_id, "subject_id": subject_id,
            "roles": ["traccar.status.read"], "payload": {}}


def worker_ledger(directory, ledger_type=AuditLedger):
    state = Path(directory) / "worker-state"
    state.mkdir(mode=0o750)
    os.chmod(state, 0o750)
    return ledger_type(
        state / "audit.jsonl", create_mode=0o640,
        expected_owner_uid=os.geteuid(), expected_group_gid=os.getegid(),
        expected_file_mode=0o640, expected_directory_mode=0o750,
        event_metadata={"endpoint": "/api/dashboard/snapshot",
                        "protocol_operation": "traccar.status.read"},
    )


def _serve_one_process(listener, audit_path, peer_uid, peer_gid):
    ledger = AuditLedger(
        audit_path, create_mode=0o640,
        expected_owner_uid=peer_uid, expected_group_gid=peer_gid,
        expected_file_mode=0o640, expected_directory_uid=peer_uid,
        expected_directory_gid=peer_gid, expected_directory_mode=0o750,
        event_metadata={"endpoint": "/api/dashboard/snapshot",
                        "protocol_operation": "traccar.status.read"},
    )
    connection, _ = listener.accept()
    with connection:
        runtime._serve_one(connection, peer_uid, peer_gid, ledger)
    listener.close()


class AcceptReceiptLedger:
    read_only = True
    def verify_finalization_receipt(self, receipt, **kwargs):
        return True
    def verify(self):
        return SimpleNamespace(valid=True, event_count=0)


class WorkerUDSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.geteuid() == 0:
            raise RuntimeError("Worker UDS tests must not run as root")
    def test_web_uds_client_correlates_response_and_uses_only_unix_socket(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "status.sock"
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(path))
            os.chmod(path, 0o660)
            os.chmod(temporary, 0o750)
            server.listen(1)
            received = []

            def serve():
                conn, _ = server.accept()
                with conn:
                    chunks = []
                    while True:
                        chunk = conn.recv(1024)
                        if not chunk:
                            break
                        chunks.append(chunk)
                    request = json.loads(b"".join(chunks).decode().strip())
                    received.append(request)
                    reply = {"schema_version": 1, "protocol_version": 1,
                             "operation": "traccar.status.read",
                             "request_id": request["request_id"], "outcome": "SUCCEEDED",
                             "observed_at_utc": OBSERVED, "properties": PROPERTIES,
                             "audit_receipt": wire_receipt(request["request_id"], request["subject_id"])}
                    conn.sendall(json.dumps(reply, separators=(",", ":")).encode() + b"\n")
                server.close()

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            fake_worker = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
            fake_group = SimpleNamespace(gr_gid=os.getgid())
            with patch.object(uds, "SOCKET_PATH", str(path)), \
                 patch.object(uds, "WEB_UID", os.geteuid()), \
                 patch.object(uds.pwd, "getpwnam", return_value=fake_worker), \
                 patch.object(uds.grp, "getgrnam", return_value=fake_group):
                response = uds.query_status("test-request-01", "a" * 32, ("traccar.status.read",))
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertEqual("test-request-01", received[0]["request_id"])
            self.assertEqual("traccar.status.read", received[0]["operation"])
            self.assertEqual(1, received[0]["protocol_version"])
            self.assertEqual({}, received[0]["payload"])
            self.assertEqual(["traccar.status.read"], received[0]["roles"])
            self.assertEqual(OBSERVED, response["observed_at_utc"])
            self.assertEqual(PROPERTIES, response["properties"])

    def test_web_client_rejects_wrong_worker_peer_uid(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "status.sock"
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(path)); os.chmod(path, 0o660); os.chmod(temporary, 0o750); server.listen(1)
            def serve():
                conn, _ = server.accept()
                with conn:
                    conn.recv(1024)
                server.close()
            thread = threading.Thread(target=serve, daemon=True); thread.start()
            with patch.object(uds, "SOCKET_PATH", str(path)), \
                 patch.object(uds, "WEB_UID", os.geteuid()), \
                 patch.object(uds.pwd, "getpwnam", return_value=SimpleNamespace(
                     pw_uid=os.getuid(), pw_gid=os.getgid())), \
                 patch.object(uds.grp, "getgrnam", return_value=SimpleNamespace(gr_gid=os.getgid())), \
                 patch.object(uds, "_peer_credentials", return_value=(os.getpid(), os.getuid() + 1, os.getgid())):
                with self.assertRaises(uds.WorkerTransportError):
                    uds.query_status("wrong-peer-request", "a" * 32, ("traccar.status.read",))
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())

    def test_worker_rejects_wrong_web_peer_uid_before_dispatch(self):
        server_sock, client_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        ledger = AuditLedger("/path/not-used-by-peer-check.jsonl")
        try:
            with patch.object(runtime, "_peer_credentials", return_value=(1234, 987)), \
                 patch.object(runtime, "_perform") as perform:
                runtime._serve_one(server_sock, 996, 987, ledger)
                reply = json.loads(client_sock.recv(2048).decode().strip())
                self.assertEqual("FAILED", reply["outcome"])
                perform.assert_not_called()
        finally:
            server_sock.close(); client_sock.close()

    def test_web_client_rejects_uncorrelated_response(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "status.sock"
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(path)); os.chmod(path, 0o660); os.chmod(temporary, 0o750); server.listen(1)
            def serve():
                conn, _ = server.accept()
                with conn:
                    while conn.recv(2048):
                        pass
                    reply = {"schema_version": 1, "protocol_version": 1,
                             "operation": "traccar.status.read", "request_id": "another-request",
                             "outcome": "SUCCEEDED", "observed_at_utc": OBSERVED,
                             "properties": PROPERTIES,
                             "audit_receipt": wire_receipt("another-request", "b" * 32)}
                    conn.sendall(json.dumps(reply).encode() + b"\n")
                server.close()
            thread = threading.Thread(target=serve, daemon=True); thread.start()
            with patch.object(uds, "SOCKET_PATH", str(path)), \
                 patch.object(uds, "WEB_UID", os.geteuid()), \
                 patch.object(uds.pwd, "getpwnam", return_value=SimpleNamespace(
                     pw_uid=os.getuid(), pw_gid=os.getgid())), \
                 patch.object(uds.grp, "getgrnam", return_value=SimpleNamespace(gr_gid=os.getgid())):
                with self.assertRaises(uds.WorkerTransportError):
                    uds.query_status("test-request-02", "b" * 32, ("traccar.status.read",))
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())

    def test_roleless_dashboard_is_pending_and_never_contacts_worker(self):
        calls = []
        api = ManagerDashboardAPI(worker_query=lambda *args: calls.append(args))
        principal = SessionPrincipal("c" * 32, "viewer", ("dashboard.read",), OBSERVED)
        try:
            snapshot = api.read("pending-request", principal)
            self.assertTrue(all(getattr(snapshot.general.traccar_service, field).availability is Availability.PENDING_PROVIDER
                                for field in ("state", "substate", "load_state", "unit_file_state", "result")))
            self.assertEqual([], calls)
        finally:
            api.close()

    def test_authorized_worker_result_is_limited_to_status_fields(self):
        calls = []
        def fake_query(request_id, subject_id, roles):
            calls.append((request_id, subject_id, roles))
            return {"observed_at_utc": OBSERVED, "properties": PROPERTIES,
                    "audit_receipt": wire_receipt(request_id, subject_id)}
        api = ManagerDashboardAPI(ledger=AcceptReceiptLedger(), worker_query=fake_query)
        principal = SessionPrincipal("d" * 32, "viewer", ("dashboard.read", "traccar.status.read"), OBSERVED)
        try:
            snapshot = api.read("status-request", principal)
            service = snapshot.general.traccar_service
            self.assertEqual("active", service.state.value)
            self.assertEqual("running", service.substate.value)
            self.assertEqual("loaded", service.load_state.value)
            self.assertEqual("enabled", service.unit_file_state.value)
            self.assertEqual("success", service.result.value)
            self.assertEqual(OBSERVED, service.state.observed_at_utc)
            self.assertTrue(all(getattr(snapshot.server, field).availability is Availability.PENDING_PROVIDER
                                for field in ("cpu_percent", "memory_total_bytes", "memory_used_bytes", "disk_total_bytes", "disk_free_bytes")))
            self.assertEqual([("status-request", "d" * 32, ("dashboard.read", "traccar.status.read"))], calls)
        finally:
            api.close()

    def test_fixed_command_is_mocked_and_exact(self):
        stdout = "LoadState=loaded\nActiveState=active\nSubState=running\nUnitFileState=enabled\nResult=success\n"
        completed = SimpleNamespace(returncode=0, stdout=stdout)
        with patch.object(operation.subprocess, "run", return_value=completed) as run:
            result = traccar_status_handle({})
        run.assert_called_once()
        self.assertEqual(["/usr/bin/systemctl", "show", "--no-pager",
                          "--property=LoadState,ActiveState,SubState,UnitFileState,Result",
                          "traccar.service"], run.call_args.args[0])
        self.assertIs(run.call_args.kwargs["shell"], False)
        self.assertEqual(5, run.call_args.kwargs["timeout"])
        self.assertEqual(PROPERTIES, result["state"])


    def test_worker_rejects_root_and_operation_rejects_payload(self):
        with patch.object(operation.os, "geteuid", return_value=0), \
             patch.object(operation.subprocess, "run") as run:
            with self.assertRaises(operation.OperationError) as cm:
                traccar_status_handle({})
            self.assertEqual("RUN_AS_ROOT_FORBIDDEN", cm.exception.code)
            run.assert_not_called()
        for payload in ({"unit": "other.service"}, {"command": ["id"]},
                        {"properties": ["ActiveState"]}):
            with self.subTest(payload=payload), patch.object(operation.subprocess, "run") as run:
                with self.assertRaises(operation.OperationError) as cm:
                    traccar_status_handle(payload)
                self.assertEqual("INVALID_PAYLOAD", cm.exception.code)
                run.assert_not_called()

    def test_systemctl_errors_and_outputs_are_sanitized(self):
        cases = (
            ("SYSTEMD_TIMEOUT", patch.object(
                operation.subprocess, "run",
                side_effect=operation.subprocess.TimeoutExpired("fixed", 5, stderr="secret-stderr"),
            )),
            ("SYSTEMD_QUERY_FAILED", patch.object(
                operation.subprocess, "run",
                return_value=SimpleNamespace(returncode=1, stdout="", stderr="secret-stderr"),
            )),
        )
        for code, run_patch in cases:
            with self.subTest(code=code), run_patch:
                with self.assertRaises(operation.OperationError) as cm:
                    traccar_status_handle({})
                self.assertEqual(code, cm.exception.code)
                self.assertNotIn("secret-stderr", str(cm.exception))

        bad_outputs = (
            "LoadState=loaded\nActiveState=active\n",
            "Unexpected=value\n",
            "LoadState=loaded\nLoadState=duplicate\n",
        )
        for output in bad_outputs:
            with self.subTest(output=output), patch.object(operation.subprocess, "run",
                    return_value=SimpleNamespace(returncode=0, stdout=output, stderr="private")):
                with self.assertRaises(operation.OperationError) as cm:
                    traccar_status_handle({})
                self.assertEqual("OUTPUT_INVALID", cm.exception.code)
                self.assertNotIn("private", str(cm.exception))

    def test_worker_dispatch_audits_success_before_response_and_uses_no_real_command(self):

        legacy = {"schema_version": 1, "operation": "traccar.status", "result": "SUCCEEDED",
                  "observed_at_utc": OBSERVED, "source": "systemd", "unit": "traccar.service",
                  "state": PROPERTIES}
        with tempfile.TemporaryDirectory() as temporary:
            ledger = worker_ledger(temporary)
            with patch.object(runtime, "read_fixed_systemd_status", return_value=legacy) as query, \
                 patch("worker.dispatcher.os.geteuid", return_value=1001):
                result = runtime._perform(worker_message("worker-audit-01", "e" * 32), ledger)
            query.assert_called_once_with({})
            self.assertEqual("worker-audit-01", result["request_id"])
            report = ledger.verify()
            self.assertTrue(report.valid)
            self.assertEqual(9, report.event_count)
            records = [json.loads(line) for line in Path(ledger.path).read_text().splitlines()]
            self.assertEqual("AUDIT_FINALIZED", records[-1]["event_type"])
            self.assertEqual("worker-audit-01", records[-1]["request_id"])
            self.assertEqual(["traccar.status.read"], records[0]["requester"]["roles"])
            self.assertEqual("/api/dashboard/snapshot", records[-1]["metadata"]["endpoint"])
            self.assertEqual("traccar.status.read", records[-1]["metadata"]["protocol_operation"])
            self.assertEqual(0o640, stat.S_IMODE(Path(ledger.path).stat().st_mode))

    def test_isolated_web_uds_worker_shared_ledger_receipt_end_to_end(self):
        """Exercise Web -> local UDS -> separate Worker process with a mocked handler."""
        legacy = {"schema_version": 1, "operation": "traccar.status", "result": "SUCCEEDED",
                  "observed_at_utc": OBSERVED, "source": "systemd", "unit": "traccar.service",
                  "state": PROPERTIES}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "worker-state"
            state.mkdir(mode=0o750)
            os.chmod(state, 0o750)
            ipc = root / "ipc"
            ipc.mkdir(mode=0o750)
            os.chmod(ipc, 0o750)
            socket_path = ipc / "status.sock"
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(socket_path))
            os.chmod(socket_path, 0o660)
            listener.listen(1)

            audit_path = state / "audit.jsonl"
            reader = AuditLedger(
                audit_path, expected_owner_uid=os.geteuid(), expected_group_gid=os.getegid(),
                expected_file_mode=0o640, expected_directory_uid=os.geteuid(),
                expected_directory_gid=os.getegid(), expected_directory_mode=0o750,
                read_only=True,
            )
            calls = multiprocessing.get_context("fork").Queue()

            def fake_handler(payload):
                calls.put(payload)
                return legacy

            principal = SessionPrincipal(
                "e" * 32, "fixture-status", ("dashboard.read", "traccar.status.read"), OBSERVED,
            )
            api = ManagerDashboardAPI(ledger=reader)
            process = multiprocessing.get_context("fork").Process(
                target=_serve_one_process,
                args=(listener, str(audit_path), os.geteuid(), os.getegid()),
            )
            try:
                with patch.object(runtime, "read_fixed_systemd_status", side_effect=fake_handler), \
                     patch.object(uds, "SOCKET_PATH", str(socket_path)), \
                     patch.object(uds, "WEB_UID", os.geteuid()), \
                     patch.object(uds.pwd, "getpwnam", return_value=SimpleNamespace(
                         pw_uid=os.geteuid(), pw_gid=os.getegid())), \
                     patch.object(uds.grp, "getgrnam", return_value=SimpleNamespace(
                         gr_gid=os.getegid())):
                    process.start()
                    listener.close()
                    snapshot = api.read("isolated-uds-req-01", principal)
                process.join(timeout=10)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=3)
                self.assertEqual(0, process.exitcode)
                self.assertEqual("active", snapshot.general.traccar_service.state.value)
                self.assertEqual("isolated-uds-req-01", snapshot.request_id)
                self.assertEqual({}, calls.get(timeout=2))
                report = reader.verify()
                self.assertTrue(report.valid)
                self.assertEqual(9, report.event_count)
                receipt = reader.finalization_receipt(
                    request_id="isolated-uds-req-01", subject_id=principal.subject_id,
                    role="traccar.status.read", endpoint="/api/dashboard/snapshot",
                    protocol_operation="traccar.status.read", operation="traccar.status",
                    target={"type": "systemd-unit", "id": "traccar.service"},
                )
                self.assertIsNotNone(receipt)
                self.assertTrue(reader.verify_finalization_receipt(
                    receipt, request_id="isolated-uds-req-01", subject_id=principal.subject_id,
                    role="traccar.status.read", endpoint="/api/dashboard/snapshot",
                    protocol_operation="traccar.status.read", operation="traccar.status",
                    target={"type": "systemd-unit", "id": "traccar.service"},
                ))
                forged = dict(receipt, event_hash="0" * 64)
                self.assertFalse(reader.verify_finalization_receipt(
                    forged, request_id="isolated-uds-req-01", subject_id=principal.subject_id,
                    role="traccar.status.read", endpoint="/api/dashboard/snapshot",
                    protocol_operation="traccar.status.read", operation="traccar.status",
                    target={"type": "systemd-unit", "id": "traccar.service"},
                ))
                with self.assertRaises(LedgerError) as cm:
                    reader.append(None)
                self.assertEqual("E700_AUDIT_UNAVAILABLE", cm.exception.code)
            finally:
                api.close()
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=3)
                if listener.fileno() >= 0:
                    listener.close()
                calls.close()
                calls.join_thread()

    def test_audit_finalization_failure_never_returns_success_or_retries_command(self):
        class FinalizationFailLedger(AuditLedger):
            def append(self, event):
                if event.event_type == "AUDIT_FINALIZED":
                    raise LedgerError("E701_AUDIT_WRITE_FAILED")
                return super().append(event)
        legacy = {"schema_version": 1, "operation": "traccar.status", "result": "SUCCEEDED",
                  "observed_at_utc": OBSERVED, "source": "systemd", "unit": "traccar.service",
                  "state": PROPERTIES}
        with tempfile.TemporaryDirectory() as temporary:
            ledger = worker_ledger(temporary, FinalizationFailLedger)
            with patch.object(runtime, "read_fixed_systemd_status", return_value=legacy) as query, \
                 patch("worker.dispatcher.os.geteuid", return_value=1001):
                with self.assertRaises(Exception):
                    runtime._perform(worker_message("worker-audit-final-fail", "1" * 32), ledger)
            query.assert_called_once_with({})
            events = [json.loads(line)["event_type"] for line in Path(ledger.path).read_text().splitlines()]
            self.assertNotIn("AUDIT_FINALIZED", events)

    def test_audit_prepare_failure_prevents_status_provider_call(self):
        with tempfile.TemporaryDirectory() as temporary:
            ledger = AuditLedger(Path(temporary) / "absent" / "audit.jsonl", create_mode=0o640, expected_file_mode=0o640)
            with patch.object(runtime, "read_fixed_systemd_status") as query, \
                 patch("worker.dispatcher.os.geteuid", return_value=1001):
                with self.assertRaises(Exception):
                    runtime._perform(worker_message("worker-audit-fail", "f" * 32), ledger)
            query.assert_not_called()

    def test_worker_message_rejects_unknown_fields_and_duplicate_keys(self):
        class FakeSocket:
            def __init__(self, data): self.data = data
            def settimeout(self, value): pass
            def recv(self, size):
                data, self.data = self.data[:size], self.data[size:]
                return data
        base = json.dumps(worker_message("req-1", "a" * 32), separators=(",", ":")).encode() + b"\n"
        message = runtime._read_message(FakeSocket(base))
        self.assertEqual("req-1", message["request_id"])
        for extra in ({"unit": "other.service"}, {"command": ["id"]},
                      {"properties": ["ActiveState"]}, {"provider": "other"}):
            bad = dict(worker_message("req-1", "a" * 32), **extra)
            with self.subTest(extra=extra), self.assertRaises(runtime.RequestError):
                runtime._read_message(FakeSocket(json.dumps(bad).encode() + b"\n"))
        bad_payload = worker_message("req-1", "a" * 32); bad_payload["payload"] = {"unit": "other.service"}
        with self.assertRaises(runtime.RequestError):
            runtime._read_message(FakeSocket(json.dumps(bad_payload).encode() + b"\n"))
        bad_version = worker_message("req-1", "a" * 32); bad_version["protocol_version"] = 2
        with self.assertRaises(runtime.RequestError):
            runtime._read_message(FakeSocket(json.dumps(bad_version).encode() + b"\n"))
        bad_role = worker_message("req-1", "a" * 32); bad_role["roles"] = ["dashboard.read"]
        with self.assertRaises(runtime.RequestError):
            runtime._read_message(FakeSocket(json.dumps(bad_role).encode() + b"\n"))
        duplicate = base.replace(b'"operation":', b'"operation":"bad","operation":', 1)
        with self.assertRaises(runtime.RequestError):
            runtime._read_message(FakeSocket(duplicate))

    def test_worker_unit_is_unix_only_and_hardened(self):
        root = Path(__file__).parents[1]
        worker_unit = (root / "deploy" / "traccar-manager-worker.service").read_text()
        manager_dropin = (root / "deploy" / "20-worker-uds.conf").read_text()
        self.assertIn("RestrictAddressFamilies=AF_UNIX", worker_unit)
        self.assertNotIn("AF_INET", worker_unit)
        self.assertIn("NoNewPrivileges=true", worker_unit)
        self.assertIn("PrivateTmp=true", worker_unit)
        self.assertIn("ProtectSystem=strict", worker_unit)
        self.assertIn("ProtectHome=true", worker_unit)
        self.assertIn("RestrictSUIDSGID=true", worker_unit)
        self.assertIn("StateDirectory=traccar-manager-worker", worker_unit)
        self.assertIn("StateDirectoryMode=0750", worker_unit)
        self.assertIn("UMask=0027", worker_unit)
        # Validated production runtime: tmpfiles owns the shared IPC directory.
        self.assertIn("After=local-fs.target systemd-tmpfiles-setup.service", worker_unit)
        self.assertIn("ReadWritePaths=/run/traccar-manager", worker_unit)
        self.assertNotIn("RuntimeDirectory=traccar-manager", worker_unit)
        tmpfiles = (root / "deploy" / "traccar-manager-runtime.conf").read_text()
        self.assertEqual(tmpfiles.strip(), "d /run/traccar-manager 0750 traccar-manager-worker traccar-manager-ipc -")
        self.assertIn("RestrictAddressFamilies=AF_INET AF_UNIX", manager_dropin)
        self.assertIn("SupplementaryGroups=traccar-manager-worker traccar-manager-ipc", manager_dropin)
        web_source = (root / "manager" / "web_app.py").read_text()
        self.assertIn("address_family = socket.AF_INET", web_source)
        self.assertIn('BIND_ADDRESS = "127.0.0.1"', web_source)

    def test_web_source_has_no_subprocess_or_systemctl_execution(self):
        web = (Path(__file__).parents[1] / "manager" / "web_app.py").read_text()
        binding = (Path(__file__).parents[1] / "manager" / "dashboard_http.py").read_text()
        client = (Path(__file__).parents[1] / "manager" / "worker_uds.py").read_text()
        self.assertNotIn("subprocess", web + binding + client)
        self.assertNotIn("systemctl", web + binding + client)
        self.assertIn("socket.AF_UNIX", client)
        self.assertNotIn("socket.AF_INET", client)


if __name__ == "__main__":
    unittest.main()
