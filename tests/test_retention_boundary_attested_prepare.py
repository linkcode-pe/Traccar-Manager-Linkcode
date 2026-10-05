import json,tempfile,unittest
from unittest.mock import patch
import worker.retention_boundary_server as s
class Tests(unittest.TestCase):
 def test_exact_durable_attestation_required(self):
  with tempfile.NamedTemporaryFile('w+',delete=True) as f:
   f.write(json.dumps({'preparation_id':'prepare-1','subject_id':'u','binding_hash':'a'*64})+'\n');f.flush()
   with patch.object(s,'PREPARATION_ATTESTATION',f.name):
    self.assertTrue(s._attested('prepare-1','a'*64));self.assertFalse(s._attested('prepare-1','b'*64));self.assertFalse(s._attested('prepare-x','a'*64))
