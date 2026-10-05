import json,unittest
from worker.retention_boundary_server import response
class Tests(unittest.TestCase):
 def test_health_is_non_destructive_and_denies_production(self):
  d=json.loads(response());self.assertEqual('healthy',d['status']);self.assertEqual('DENY_PRODUCTION',d['mode']);self.assertFalse(d['production_access']);self.assertFalse(d['destructive_action_performed']);self.assertFalse(d['network_access']);self.assertFalse(d['shell_access'])
