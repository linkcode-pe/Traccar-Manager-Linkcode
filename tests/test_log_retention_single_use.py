import os,tempfile,threading,unittest
from worker.operations.log_retention_sandbox_claim import claim,ClaimError
BASE='/tmp/traccar-manager-retention-sandbox'
class Tests(unittest.TestCase):
 def test_atomic_claim_allows_exactly_one_concurrent_consumer(self):
  os.makedirs(BASE,exist_ok=True)
  with tempfile.TemporaryDirectory(dir=BASE) as d:
   results=[]
   def run():
    try:claim(d,'prep-concurrent');results.append('WON')
    except ClaimError as e:results.append(str(e))
   ts=[threading.Thread(target=run) for _ in range(12)]
   [t.start() for t in ts];[t.join() for t in ts]
   self.assertEqual(1,results.count('WON'));self.assertEqual(11,results.count('PREPARATION_ALREADY_CONSUMED'))
 def test_production_path_cannot_be_claimed(self):
  with self.assertRaisesRegex(ClaimError,'PRODUCTION_PATH_DENIED'):claim('/opt/traccar/logs','prep-x')
