import unittest
from worker.operations.log_retention_production_delete import delete,ProductionDeleteError
class Tests(unittest.TestCase):
 def test_rejects_active(self):
  with self.assertRaisesRegex(ProductionDeleteError,'NAME_DENIED'): delete(['tracker-server.log'],30)
 def test_rejects_arbitrary(self):
  with self.assertRaisesRegex(ProductionDeleteError,'NAME_DENIED'): delete(['../../etc/passwd'],30)
 def test_rejects_duplicate(self):
  with self.assertRaisesRegex(ProductionDeleteError,'DUPLICATE_NAME'): delete(['tracker-server.log.20000101']*2,30)
