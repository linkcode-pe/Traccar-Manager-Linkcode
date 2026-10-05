import os,tempfile,unittest
from worker.operations.log_retention_plan_fingerprint import fingerprint,verify
from worker.operations.log_retention_boundary_executor import execute_sandbox,SandboxExecutionError
BASE='/tmp/traccar-manager-retention-sandbox'
class Tests(unittest.TestCase):
 def test_exact_plan_verifies_and_any_change_fails(self):
  names=['tracker-server.log.20260101'];f=fingerprint('prep-1',names,90)
  self.assertTrue(verify(f,'prep-1',names,90));self.assertFalse(verify(f,'prep-2',names,90));self.assertFalse(verify(f,'prep-1',['tracker-server.log.20260102'],90));self.assertFalse(verify(f,'prep-1',names,91))
 def test_executor_rejects_tampered_plan_before_claim_or_mutation(self):
  os.makedirs(BASE,exist_ok=True)
  with tempfile.TemporaryDirectory(dir=BASE) as d:
   n='tracker-server.log.20260101';open(os.path.join(d,n),'w').close();f=fingerprint('prep-bound', [n],90)
   with self.assertRaisesRegex(SandboxExecutionError,'PLAN_FINGERPRINT_MISMATCH'):execute_sandbox(d,[n],91,sandbox_authorized=True,preparation_id='prep-bound',plan_fingerprint=f)
   self.assertTrue(os.path.exists(os.path.join(d,n)));self.assertFalse(os.path.exists(os.path.join(d,'.claims')))
