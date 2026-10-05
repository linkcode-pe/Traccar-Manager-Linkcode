import unittest
from unittest.mock import Mock
from manager.auth.session_store import SessionPrincipal
from manager.maintenance_http import ManagerMaintenanceAPI, MaintenanceAPIError
from worker.maintenance_preview_dispatch import ROLE

class ManagerMaintenanceAPITests(unittest.TestCase):
    def principal(self, roles=(ROLE,)):
        return SessionPrincipal("a"*32,"admin",roles,"2099-01-01T00:00:00Z")
    def test_roleless_fails_before_worker(self):
        worker=Mock(); api=ManagerMaintenanceAPI(ledger=Mock(),worker_query=worker)
        with self.assertRaisesRegex(MaintenanceAPIError,"API_FORBIDDEN"): api.preview_logs("req-1",self.principal(()),90)
        worker.assert_not_called()
    def test_verified_preview_returns_sanitized_model(self):
        preview={"log_dir":"/opt/traccar/logs","retention_days":90,"cutoff_utc":"2026-01-01T00:00:00Z","candidate_count":0,"candidate_bytes":0,"candidates":[],"active_log_protected":True,"destructive_action_performed":False}
        receipt={"x":1}; worker=Mock(return_value={"preview":preview,"preview_id":"preview-"+"a"*64,"audit_receipt":receipt})
        ledger=Mock(); ledger.verify_finalization_receipt_generic.return_value=True
        result=ManagerMaintenanceAPI(ledger=ledger,worker_query=worker).preview_logs("req-1",self.principal(),90)
        self.assertEqual(preview,result["preview"]); self.assertNotIn("audit_receipt",result); self.assertEqual(1,result["schema_version"])
    def test_invalid_audit_receipt_fails_closed(self):
        worker=Mock(return_value={"preview":{},"preview_id":"preview-"+"a"*64,"audit_receipt":{}}); ledger=Mock(); ledger.verify_finalization_receipt_generic.return_value=False
        with self.assertRaisesRegex(MaintenanceAPIError,"API_AUDIT_UNAVAILABLE"): ManagerMaintenanceAPI(ledger=ledger,worker_query=worker).preview_logs("req-1",self.principal(),90)
