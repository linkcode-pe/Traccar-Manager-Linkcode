import os,tempfile,unittest
from unittest.mock import patch
from worker.operations.log_retention_boundary_credential import load_hmac_key,BoundaryCredentialError
class Tests(unittest.TestCase):
 def test_loads_strong_key_from_systemd_directory(self):
  with tempfile.TemporaryDirectory() as d:
   
   with open(os.path.join(d,'retention-plan-hmac.key'),'wb') as f:f.write(b'x'*32)
   with patch.dict(os.environ,{'CREDENTIALS_DIRECTORY':d},clear=False):self.assertEqual(b'x'*32,load_hmac_key())
 def test_fails_closed_without_credential(self):
  with patch.dict(os.environ,{},clear=True):
   with self.assertRaisesRegex(BoundaryCredentialError,'CREDENTIAL_UNAVAILABLE'):load_hmac_key()
