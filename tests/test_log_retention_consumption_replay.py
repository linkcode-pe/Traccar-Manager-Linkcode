import tempfile,unittest
from pathlib import Path
from worker.operations.log_retention_consumption import PreparationConsumptionStore,PreparationConsumptionError
from worker.operations.log_retention_prepare import LogRetentionPreparation
class Tests(unittest.TestCase):
 def prep(self):return LogRetentionPreparation('p','v','h',90,0,0,(), '2026-10-05T00:00:00Z','2026-10-05T01:00:00Z','nonce-1234567890123456',False)
 def test_exact_preparation_consumes_once(self):
  with tempfile.TemporaryDirectory() as d:
   s=PreparationConsumptionStore(Path(d)/'c');p=self.prep();self.assertTrue(s.consume(p).consumed)
   with self.assertRaisesRegex(PreparationConsumptionError,'PREPARATION_ALREADY_CONSUMED'):s.consume(p)
