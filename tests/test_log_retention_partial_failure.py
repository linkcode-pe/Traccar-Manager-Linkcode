import json,os,tempfile,unittest
from worker.operations.log_retention_boundary_executor import execute_sandbox
BASE='/tmp/traccar-manager-retention-sandbox'
class Tests(unittest.TestCase):
 def test_partial_failure_is_exactly_audited_and_stops(self):
  os.makedirs(BASE,exist_ok=True)
  with tempfile.TemporaryDirectory(dir=BASE) as d:
   names=['tracker-server.log.20260101','tracker-server.log.20260102','tracker-server.log.20260103']
   for n in names:open(os.path.join(d,n),'w').close()
   calls=[]
   def unlink(n,*,dir_fd):
    calls.append(n)
    if n==names[1]:raise OSError('injected')
    os.unlink(n,dir_fd=dir_fd)
   r=execute_sandbox(d,names,90,sandbox_authorized=True,preparation_id='prep-partial',unlink_func=unlink)
   self.assertEqual('SANDBOX_PARTIAL_FAILURE',r['status']);self.assertEqual([names[0]],r['deleted_names']);self.assertEqual([names[1]],r['failed_names']);self.assertEqual([names[2]],r['not_attempted_names']);self.assertEqual(names[:2],calls)
   with open(os.path.join(d,'execution-audit.jsonl')) as f:a=json.loads(f.readline())
   self.assertEqual(r['deleted_names'],a['deleted_names']);self.assertEqual(r['failed_names'],a['failed_names']);self.assertEqual(r['not_attempted_names'],a['not_attempted_names']);self.assertFalse(a['active_log_included']);self.assertFalse(a['production_access'])
