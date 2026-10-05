import json,unittest
from worker.retention_boundary_server import handle
class Tests(unittest.TestCase):
 def test_valid_execute_reaches_final_gate_and_is_denied(self):
  d=json.loads(handle(b'{"operation":"DELETE_EXPIRED_HISTORICAL_LOGS","names":["tracker-server.log.20260101"]}\n'))
  self.assertEqual('DENIED_BY_PRODUCTION_GATE',d['status']);self.assertTrue(d['validated_request']);self.assertFalse(d['production_access']);self.assertFalse(d['destructive_action_performed'])
 def test_active_log_and_traversal_rejected_before_gate(self):
  for n in ['tracker-server.log','../tracker-server.log.20260101']:
   d=json.loads(handle(json.dumps({'operation':'DELETE_EXPIRED_HISTORICAL_LOGS','names':[n]}).encode()));self.assertEqual('INVALID_REQUEST',d['status']);self.assertFalse(d['destructive_action_performed'])
