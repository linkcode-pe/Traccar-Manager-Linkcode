import unittest
from datetime import datetime,timezone
from worker.operations.log_retention_preview import LogCandidate,LogRetentionPreview
from worker.operations.log_retention_prepare import prepare_log_retention,_hash,_plan
from worker.operations.log_retention_execute import validate_execution_gate,LogRetentionExecuteError
class ExecuteGateTests(unittest.TestCase):
 def setUp(self):
  self.p=LogRetentionPreview('/opt/traccar/logs',90,'2026-07-07T00:00:00Z',1,10,(LogCandidate('tracker-server.log.20260101','/opt/traccar/logs/tracker-server.log.20260101',10,'2026-01-01T00:00:00Z'),)); self.pid='preview-'+_hash(_plan(self.p)); self.prep=prepare_log_retention(self.pid,retention_days=90,preview_provider=lambda *a,**k:self.p,now=datetime(2026,10,5,0,0,tzinfo=timezone.utc))
 def test_valid_gate_still_cannot_delete(self):
  r=validate_execution_gate(self.prep,confirmation='CONFIRMAR LIMPIEZA',nonce=self.prep.one_time_nonce,preview_provider=lambda *a,**k:self.p,now=datetime(2026,10,5,0,1,tzinfo=timezone.utc)); self.assertTrue(r.revalidated);self.assertFalse(r.execution_enabled);self.assertFalse(r.authorization_consumed);self.assertFalse(r.destructive_action_performed)
 def test_confirmation_nonce_and_expiry_fail_closed(self):
  for kwargs,code in [({'confirmation':'x','nonce':self.prep.one_time_nonce,'now':datetime(2026,10,5,0,1,tzinfo=timezone.utc)},'CONFIRMATION_REQUIRED'),({'confirmation':'CONFIRMAR LIMPIEZA','nonce':'bad','now':datetime(2026,10,5,0,1,tzinfo=timezone.utc)},'NONCE_MISMATCH'),({'confirmation':'CONFIRMAR LIMPIEZA','nonce':self.prep.one_time_nonce,'now':datetime(2026,10,5,0,6,tzinfo=timezone.utc)},'PREPARATION_EXPIRED')]:
   with self.assertRaisesRegex(LogRetentionExecuteError,code):validate_execution_gate(self.prep,preview_provider=lambda *a,**k:self.p,**kwargs)
 def test_changed_plan_is_stale(self):
  changed=LogRetentionPreview('/opt/traccar/logs',90,'2026-07-07T00:00:00Z',0,0,())
  with self.assertRaisesRegex(LogRetentionExecuteError,'PREVIEW_STALE'):validate_execution_gate(self.prep,confirmation='CONFIRMAR LIMPIEZA',nonce=self.prep.one_time_nonce,preview_provider=lambda *a,**k:changed,now=datetime(2026,10,5,0,1,tzinfo=timezone.utc))

class ExecuteConsumptionTests(ExecuteGateTests):
 def test_durable_consumption_is_exactly_once(self):
  import tempfile
  from pathlib import Path
  from worker.operations.log_retention_consumption import PreparationConsumptionStore
  with tempfile.TemporaryDirectory() as td:
   store=PreparationConsumptionStore(Path(td)/'consumed.jsonl')
   first=validate_execution_gate(self.prep,confirmation='CONFIRMAR LIMPIEZA',nonce=self.prep.one_time_nonce,preview_provider=lambda *a,**k:self.p,now=datetime(2026,10,5,0,1,tzinfo=timezone.utc),consumption_store=store)
   self.assertTrue(first.authorization_consumed);self.assertFalse(first.execution_enabled);self.assertFalse(first.destructive_action_performed)
   with self.assertRaisesRegex(LogRetentionExecuteError,'PREPARATION_ALREADY_CONSUMED'):
    validate_execution_gate(self.prep,confirmation='CONFIRMAR LIMPIEZA',nonce=self.prep.one_time_nonce,preview_provider=lambda *a,**k:self.p,now=datetime(2026,10,5,0,1,tzinfo=timezone.utc),consumption_store=store)
 def test_failed_validation_does_not_consume(self):
  import tempfile
  from pathlib import Path
  from worker.operations.log_retention_consumption import PreparationConsumptionStore
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'consumed.jsonl';store=PreparationConsumptionStore(path)
   with self.assertRaises(LogRetentionExecuteError): validate_execution_gate(self.prep,confirmation='wrong',nonce=self.prep.one_time_nonce,preview_provider=lambda *a,**k:self.p,now=datetime(2026,10,5,0,1,tzinfo=timezone.utc),consumption_store=store)
   self.assertFalse(path.exists())
