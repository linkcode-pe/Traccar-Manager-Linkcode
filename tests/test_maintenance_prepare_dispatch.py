import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from worker.audit.ledger import AuditLedger
from worker.maintenance_prepare_dispatch import execute,MaintenancePrepareError,ROLE
from worker.operations.log_retention_preview import LogRetentionPreview

class MaintenancePrepareDispatchTests(unittest.TestCase):
 def setUp(self): self.t=tempfile.TemporaryDirectory(); self.l=AuditLedger(Path(self.t.name)/'a.jsonl'); self.p=LogRetentionPreview('/opt/traccar/logs',90,'2026-07-07T00:00:00Z',0,0,())
 def tearDown(self): self.t.cleanup()
 @patch('worker.maintenance_prepare_dispatch.preview_log_retention')
 def test_prepare_requires_exact_preview(self,mp):
  from worker.operations.log_retention_prepare import _hash,_plan,LogRetentionPreparation
  mp.return_value=self.p; pid='preview-'+_hash(_plan(self.p))
  r=execute(ledger=self.l,request_id='prep-1',subject_id='a'*32,roles=(ROLE,),preview_id=pid,retention_days=90)
  self.assertEqual(pid,r['preview_id']); self.assertFalse(r['destructive_action_performed'])
 @patch('worker.maintenance_prepare_dispatch.preview_log_retention')
 def test_stale_fails_before_prepare(self,ep):
  ep.return_value=self.p
  with self.assertRaisesRegex(MaintenancePrepareError,'PREVIEW_STALE'): execute(ledger=self.l,request_id='prep-2',subject_id='a'*32,roles=(ROLE,),preview_id='preview-'+'1'*64)
 def test_role_fails_closed(self):
  with self.assertRaisesRegex(MaintenancePrepareError,'FORBIDDEN'): execute(ledger=self.l,request_id='prep-3',subject_id='a'*32,roles=('maintenance.logs.preview',),preview_id='preview-'+'1'*64)

class MaintenancePrepareRuntimeTests(unittest.TestCase):
 @patch('worker.maintenance_prepare_dispatch.preview_log_retention')
 def test_runtime_prepare_returns_durable_receipt(self,mp):
  from worker import runtime_server as r
  from worker.operations.log_retention_prepare import _hash,_plan
  mp.return_value=self_p=LogRetentionPreview('/opt/traccar/logs',90,'2026-07-07T00:00:00Z',0,0,())
  pid='preview-'+_hash(_plan(self_p))
  with tempfile.TemporaryDirectory() as td:
   ledger=AuditLedger(Path(td)/'a.jsonl',event_metadata={'endpoint':r.MAINTENANCE_PREPARE_ENDPOINT,'protocol_operation':r.MAINTENANCE_PREPARE_OPERATION})
   msg={'protocol_version':1,'operation':r.MAINTENANCE_PREPARE_OPERATION,'request_id':'prep-runtime-1','subject_id':'a'*32,'roles':[r.MAINTENANCE_PREPARE_ROLE],'payload':{'retention_days':90,'preview_id':pid}}
   out=r._perform_maintenance_prepare(msg,ledger);self.assertEqual('SUCCEEDED',out['outcome']);self.assertFalse(out['preparation']['destructive_action_performed'])
   self.assertTrue(ledger.verify_finalization_receipt_generic(out['audit_receipt'],request_id='prep-runtime-1',subject_id='a'*32,role=r.MAINTENANCE_PREPARE_ROLE,endpoint=r.MAINTENANCE_PREPARE_ENDPOINT,protocol_operation=r.MAINTENANCE_PREPARE_OPERATION,operation=r.MAINTENANCE_PREPARE_OPERATION,target=r.MAINTENANCE_PREPARE_TARGET))

class MaintenancePrepareParserTests(unittest.TestCase):
 def test_parser_accepts_only_fixed_prepare_contract(self):
  import json
  from worker import runtime_server as r
  class Sock:
   def __init__(self,d):self.d=d
   def settimeout(self,_):pass
   def recv(self,_):v,self.d=self.d,b'';return v
  msg={'protocol_version':1,'operation':r.MAINTENANCE_PREPARE_OPERATION,'request_id':'prep-parse-1','subject_id':'a'*32,'roles':[r.MAINTENANCE_PREPARE_ROLE],'payload':{'retention_days':90,'preview_id':'preview-'+'1'*64}}
  self.assertEqual(msg,r._read_message(Sock(json.dumps(msg).encode()+b'\n')))
  for bad in ({**msg,'roles':['maintenance.logs.preview']},{**msg,'payload':{'retention_days':90,'preview_id':'bad'}},{**msg,'payload':{'retention_days':90,'preview_id':'preview-'+'1'*64,'path':'/tmp'}}):
   with self.assertRaises(r.RequestError):r._read_message(Sock(json.dumps(bad).encode()+b'\n'))

class PreparationStoreIntegrationTests(unittest.TestCase):
 def test_prepare_is_durably_bound_to_actor(self):
  import tempfile
  from pathlib import Path
  from datetime import datetime,timezone
  from worker.operations.log_retention_preparation_store import PreparationStore
  from worker.operations.log_retention_prepare import _hash,_plan
  from worker.operations.log_retention_preview import LogRetentionPreview
  with tempfile.TemporaryDirectory() as td:
   pv=LogRetentionPreview('/opt/traccar/logs',90,'2026-07-07T00:00:00Z',0,0,()); pid='preview-'+_hash(_plan(pv)); store=PreparationStore(Path(td)/'issued.jsonl')
   import worker.maintenance_prepare_dispatch as m
   old=m.preview_log_retention;m.preview_log_retention=lambda *a,**k:pv
   try:
    result=m.execute(ledger=AuditLedger(Path(td)/'audit.jsonl'),request_id='prep-store-1',subject_id='a'*32,roles=(m.ROLE,),preview_id=pid,retention_days=90,preparation_store=store)
    from worker.operations.log_retention_prepare import LogRetentionPreparation
    prep=LogRetentionPreparation(**result['preparation']);self.assertTrue(result['preparation_stored']);self.assertTrue(store.verify(prep,subject_id='a'*32))
   finally:m.preview_log_retention=old
