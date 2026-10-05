import json,tempfile,os,unittest
from unittest.mock import patch
import worker.retention_boundary_server as s
class Tests(unittest.TestCase):
 def test_valid_request_reports_all_revalidated_before_final_gate(self):
  class R: eligible=True
  with patch.object(s,'revalidate',return_value=R()):
   d=json.loads(s.handle(b'{"operation":"DELETE_EXPIRED_HISTORICAL_LOGS","names":["tracker-server.log.20260101"],"retention_days":90}'))
  self.assertEqual('DENIED_BY_PRODUCTION_GATE',d['status']);self.assertEqual(1,d['revalidated_count']);self.assertFalse(d['destructive_action_performed'])
 def test_failed_fs_revalidation_never_reaches_final_gate(self):
  class R: eligible=False
  with patch.object(s,'revalidate',return_value=R()):
   d=json.loads(s.handle(b'{"operation":"DELETE_EXPIRED_HISTORICAL_LOGS","names":["tracker-server.log.20260101"],"retention_days":90}'))
  self.assertEqual('DENIED_BY_REVALIDATION',d['status']);self.assertEqual(0,d['revalidated_count']);self.assertFalse(d['destructive_action_performed'])
