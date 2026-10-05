import json,os,tempfile,unittest
from worker.operations.log_retention_boundary_executor import execute_sandbox
BASE='/tmp/traccar-manager-retention-sandbox'
class Tests(unittest.TestCase):
 def test_execution_writes_durable_evidence(self):
  os.makedirs(BASE,exist_ok=True)
  with tempfile.TemporaryDirectory(dir=BASE) as d:
   n='tracker-server.log.20260101';open(os.path.join(d,n),'w').close();r=execute_sandbox(d,[n],90,sandbox_authorized=True,preparation_id='prep-123')
   a=os.path.join(d,'execution-audit.jsonl');self.assertTrue(os.path.exists(a));
   with open(a) as f:x=json.loads(f.readline())
   self.assertEqual('prep-123',x['preparation_id']);self.assertEqual([n],x['requested_names']);self.assertEqual(1,x['revalidated_count']);self.assertEqual([n],x['deleted_names']);self.assertFalse(x['active_log_included']);self.assertFalse(x['production_access']);self.assertEqual(64,len(x['record_hash']))
