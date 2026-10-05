import os,tempfile,unittest
from datetime import datetime,timezone
from worker.operations.log_retention_boundary_revalidate import revalidate
class Tests(unittest.TestCase):
 def setUp(self):self.d=tempfile.TemporaryDirectory();self.root=self.d.name;self.now=datetime(2026,10,5,tzinfo=timezone.utc)
 def tearDown(self):self.d.cleanup()
 def test_old_regular_is_eligible(self):
  open(os.path.join(self.root,'tracker-server.log.20260101'),'w').close();self.assertTrue(revalidate(self.root,'tracker-server.log.20260101',90,self.now).eligible)
 def test_active_traversal_and_recent_are_denied(self):
  for n in ['tracker-server.log','../tracker-server.log.20260101','tracker-server.log.20261001']:self.assertFalse(revalidate(self.root,n,90,self.now).eligible)
 def test_symlink_is_denied(self):
  open(os.path.join(self.root,'target'),'w').close();os.symlink('target',os.path.join(self.root,'tracker-server.log.20260101'));self.assertFalse(revalidate(self.root,'tracker-server.log.20260101',90,self.now).eligible)
