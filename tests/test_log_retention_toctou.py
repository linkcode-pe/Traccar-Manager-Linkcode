import os,tempfile,unittest
from worker.operations.log_retention_boundary_executor import execute_sandbox
BASE='/tmp/traccar-manager-retention-sandbox'
class Tests(unittest.TestCase):
 def test_replacement_between_open_and_unlink_is_detected_and_preserved(self):
  os.makedirs(BASE,exist_ok=True)
  with tempfile.TemporaryDirectory(dir=BASE) as d:
   n='tracker-server.log.20260101';p=os.path.join(d,n);open(p,'w').close()
   def swap(_n,_dfd):os.rename(p,p+'.old');open(p,'w').close()
   r=execute_sandbox(d,[n],90,sandbox_authorized=True,before_unlink=swap)
   self.assertEqual('SANDBOX_PARTIAL_FAILURE',r['status']);self.assertEqual('IDENTITY_CHANGED',r['file_outcomes'][0]['outcome']);self.assertTrue(os.path.exists(p));self.assertTrue(os.path.exists(p+'.old'));self.assertEqual([],r['deleted_names'])
