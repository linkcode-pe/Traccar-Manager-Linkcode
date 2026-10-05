import unittest
import manager.worker_uds as w
class Tests(unittest.TestCase):
 def test_dashboard_roundtrip_budget_covers_audited_worker_path(self):
  self.assertGreaterEqual(w.ROUNDTRIP_TIMEOUT_SECONDS,15.0)
  self.assertLessEqual(w.ROUNDTRIP_TIMEOUT_SECONDS,20.0)
