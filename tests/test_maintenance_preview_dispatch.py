import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from worker.audit.ledger import AuditLedger
from worker.maintenance_preview_dispatch import MaintenancePreviewError, ROLE, execute
from worker.operations.log_retention_preview import LogCandidate, LogRetentionPreview

class MaintenancePreviewDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ledger = AuditLedger(Path(self.temp.name) / "audit.jsonl")
        self.preview = LogRetentionPreview("/opt/traccar/logs", 90, "2026-07-07T00:00:00Z", 2, 300, (LogCandidate("tracker-server.log.20260701", "/opt/traccar/logs/tracker-server.log.20260701", 100, "2026-07-01T00:00:00Z"), LogCandidate("tracker-server.log.20260702", "/opt/traccar/logs/tracker-server.log.20260702", 200, "2026-07-02T00:00:00Z")))
    def tearDown(self): self.temp.cleanup()
    @patch("worker.maintenance_preview_dispatch.preview_log_retention")
    def test_authorized_preview_is_audited_with_nine_events(self, mock_preview):
        mock_preview.return_value = self.preview
        result = execute(ledger=self.ledger, request_id="req-1", subject_id="a"*32, roles=(ROLE,))
        self.assertEqual(2, result["preview"]["candidate_count"])
        report = self.ledger.verify(); self.assertTrue(report.valid); self.assertEqual(9, report.event_count)
    @patch("worker.maintenance_preview_dispatch.preview_log_retention")
    def test_missing_role_fails_before_filesystem_or_audit(self, mock_preview):
        with self.assertRaises(MaintenancePreviewError):
            execute(ledger=self.ledger, request_id="req-2", subject_id="a"*32, roles=("dashboard.read",))
        mock_preview.assert_not_called(); self.assertEqual(0, self.ledger.verify().event_count)
    def test_invalid_retention_fails_closed(self):
        with self.assertRaises(MaintenancePreviewError):
            execute(ledger=self.ledger, request_id="req-3", subject_id="a"*32, roles=(ROLE,), retention_days=0)
        self.assertEqual(0, self.ledger.verify().event_count)

if __name__ == "__main__": unittest.main()

class MaintenanceRuntimeProtocolTests(unittest.TestCase):
    @patch("worker.maintenance_preview_dispatch.preview_log_retention")
    def test_runtime_perform_returns_verified_receipt(self, mock_preview):
        from worker import runtime_server as runtime
        mock_preview.return_value = LogRetentionPreview("/opt/traccar/logs", 90, "2026-07-07T00:00:00Z", 0, 0, ())
        with tempfile.TemporaryDirectory() as td:
            ledger=AuditLedger(Path(td)/"audit.jsonl", event_metadata={"endpoint":runtime.MAINTENANCE_ENDPOINT,"protocol_operation":runtime.MAINTENANCE_OPERATION})
            msg={"protocol_version":1,"operation":runtime.MAINTENANCE_OPERATION,"request_id":"maint-runtime-1",
                 "subject_id":"a"*32,"roles":[runtime.MAINTENANCE_ROLE],"payload":{"retention_days":90}}
            result=runtime._perform_maintenance(msg,ledger)
            self.assertEqual("SUCCEEDED",result["outcome"]); self.assertEqual(0,result["preview"]["candidate_count"])
            self.assertTrue(ledger.verify_finalization_receipt_generic(result["audit_receipt"], request_id="maint-runtime-1", subject_id="a"*32, role=runtime.MAINTENANCE_ROLE, endpoint=runtime.MAINTENANCE_ENDPOINT, protocol_operation=runtime.MAINTENANCE_OPERATION, operation=runtime.MAINTENANCE_OPERATION, target=runtime.MAINTENANCE_TARGET))

    def test_runtime_parser_accepts_only_fixed_maintenance_contract(self):
        import json
        from worker import runtime_server as runtime
        class Sock:
            def __init__(self, data): self.data=data
            def settimeout(self, _): pass
            def recv(self, _):
                value,self.data=self.data,b""; return value
        msg={"protocol_version":1,"operation":"maintenance.logs.preview","request_id":"maint-1",
             "subject_id":"a"*32,"roles":["maintenance.logs.preview"],"payload":{"retention_days":90}}
        parsed=runtime._read_message(Sock(json.dumps(msg).encode()+b"\n"))
        self.assertEqual(msg,parsed)
        for mutation in (
            {**msg,"roles":["dashboard.read"]},
            {**msg,"payload":{"retention_days":29}},
            {**msg,"payload":{"retention_days":90,"path":"/tmp"}},
        ):
            with self.assertRaises(runtime.RequestError):
                runtime._read_message(Sock(json.dumps(mutation).encode()+b"\n"))
