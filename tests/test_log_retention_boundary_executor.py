import os,tempfile,unittest
from worker.operations.log_retention_boundary_executor import execute_sandbox,SandboxExecutionError
BASE='/tmp/traccar-manager-retention-sandbox'
class Tests(unittest.TestCase):
 def setUp(self):os.makedirs(BASE,exist_ok=True);self.d=tempfile.TemporaryDirectory(dir=BASE);self.root=self.d.name
 def tearDown(self):self.d.cleanup()
 def test_deletes_only_revalidated_sandbox_history(self):
  n='tracker-server.log.20260101';open(os.path.join(self.root,n),'w').close();r=execute_sandbox(self.root,[n],90,sandbox_authorized=True);self.assertEqual(1,r['deleted_count']);self.assertFalse(os.path.exists(os.path.join(self.root,n)));self.assertFalse(r['production_access'])
 def test_refuses_without_explicit_sandbox_authorization(self):
  with self.assertRaisesRegex(SandboxExecutionError,'SANDBOX_AUTH_REQUIRED'):execute_sandbox(self.root,[],90)
 def test_refuses_non_sandbox_path_even_authorized(self):
  with self.assertRaisesRegex(SandboxExecutionError,'PRODUCTION_PATH_DENIED'):execute_sandbox('/opt/traccar/logs',[],90,sandbox_authorized=True)
 def test_symlink_is_not_deleted(self):
  open(os.path.join(self.root,'target'),'w').close();n='tracker-server.log.20260101';os.symlink('target',os.path.join(self.root,n))
  with self.assertRaisesRegex(SandboxExecutionError,'REVALIDATION_DENIED'):execute_sandbox(self.root,[n],90,sandbox_authorized=True)
  self.assertTrue(os.path.islink(os.path.join(self.root,n)))
