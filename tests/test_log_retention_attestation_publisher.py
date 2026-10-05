import json,tempfile,unittest
from pathlib import Path
from worker.operations.log_retention_attestation_publisher import publish
class Tests(unittest.TestCase):
 def test_append_only_spool_preserves_prior_attestations(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'spool';publish(p,preparation_id='p1',binding_hash='a'*64);publish(p,preparation_id='p2',binding_hash='b'*64)
   rows=[json.loads(x) for x in p.read_text().splitlines()];self.assertEqual(['p1','p2'],[x['preparation_id'] for x in rows])
