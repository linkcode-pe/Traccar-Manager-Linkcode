import tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone
from worker.audit.ledger import AuditLedger
from worker.operations.log_retention_preview import LogCandidate,LogRetentionPreview
from worker.operations.log_retention_prepare import prepare_log_retention,_hash,_plan
from worker.operations.log_retention_consumption import PreparationConsumptionStore
from worker.maintenance_execute_dispatch import execute,MaintenanceExecuteError,ROLE
class Tests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();root=Path(self.t.name);self.ledger=AuditLedger(root/'audit.jsonl');self.store=PreparationConsumptionStore(root/'consumed.jsonl');self.p=LogRetentionPreview('/opt/traccar/logs',90,'2026-07-07T00:00:00Z',1,10,(LogCandidate('tracker-server.log.20260101','/opt/traccar/logs/tracker-server.log.20260101',10,'2026-01-01T00:00:00Z'),));pid='preview-'+_hash(_plan(self.p));self.prep=prepare_log_retention(pid,retention_days=90,preview_provider=lambda *a,**k:self.p,now=datetime.now(timezone.utc))
 def tearDown(self):self.t.cleanup()
 def test_audited_gate_consumes_once_but_never_executes(self):
  r=execute(ledger=self.ledger,request_id='execute-1',subject_id='a'*32,roles=(ROLE,),preparation=self.prep,confirmation='CONFIRMAR LIMPIEZA',nonce=self.prep.one_time_nonce,consumption_store=self.store,preview_provider=lambda *a,**k:self.p,now=None);self.assertEqual('BLOCKED_BY_FEATURE_GATE',r['outcome']);self.assertTrue(r['gate']['authorization_consumed']);self.assertFalse(r['gate']['execution_enabled']);self.assertFalse(r['destructive_action_performed']);self.assertTrue(self.ledger.verify().valid)
  with self.assertRaisesRegex(MaintenanceExecuteError,'PREPARATION_ALREADY_CONSUMED'):execute(ledger=self.ledger,request_id='execute-2',subject_id='a'*32,roles=(ROLE,),preparation=self.prep,confirmation='CONFIRMAR LIMPIEZA',nonce=self.prep.one_time_nonce,consumption_store=self.store,preview_provider=lambda *a,**k:self.p,now=None)
 def test_forbidden_does_not_consume(self):
  with self.assertRaisesRegex(MaintenanceExecuteError,'FORBIDDEN'):execute(ledger=self.ledger,request_id='execute-3',subject_id='a'*32,roles=(),preparation=self.prep,confirmation='CONFIRMAR LIMPIEZA',nonce=self.prep.one_time_nonce,consumption_store=self.store,preview_provider=lambda *a,**k:self.p)
  self.assertFalse(self.store.path.exists())

class FailingPrepareLedger(AuditLedger):
 def prepare_execution(self,event):
  raise OSError('injected audit prepare failure')

class OrderingTests(Tests):
 def test_audit_prepare_failure_does_not_consume(self):
  ledger=FailingPrepareLedger(Path(self.t.name)/'failing-audit.jsonl')
  with self.assertRaisesRegex(MaintenanceExecuteError,'AUDIT_UNAVAILABLE'):
   execute(ledger=ledger,request_id='execute-order-fail',subject_id='a'*32,roles=(ROLE,),preparation=self.prep,confirmation='CONFIRMAR LIMPIEZA',nonce=self.prep.one_time_nonce,consumption_store=self.store,preview_provider=lambda *a,**k:self.p)
  self.assertFalse(self.store.path.exists())
 def test_successful_audit_prepare_then_consumes(self):
  r=execute(ledger=self.ledger,request_id='execute-order-ok',subject_id='a'*32,roles=(ROLE,),preparation=self.prep,confirmation='CONFIRMAR LIMPIEZA',nonce=self.prep.one_time_nonce,consumption_store=self.store,preview_provider=lambda *a,**k:self.p)
  self.assertTrue(r['gate']['authorization_consumed']);self.assertTrue(self.store.path.exists())
