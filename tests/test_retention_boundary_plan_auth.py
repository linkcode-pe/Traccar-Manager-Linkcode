import json,unittest
from unittest.mock import patch
import worker.retention_boundary_server as s
class R: eligible=True
class Tests(unittest.TestCase):
 def test_boundary_issues_and_verifies_exact_plan_but_denies_mutation(self):
  key=b'k'*32;base={'operation':'DELETE_EXPIRED_HISTORICAL_LOGS','preparation_id':'prep-auth','names':['tracker-server.log.20260101'],'retention_days':90}
  with patch.object(s,'load_hmac_key',return_value=key),patch.object(s,'revalidate',return_value=R()):
   issue=json.loads(s.handle(json.dumps({'action':'ISSUE_AUTH',**base}).encode(),peer_authorized=True));self.assertEqual('AUTH_ISSUED',issue['status'])
   ok=json.loads(s.handle(json.dumps({'action':'VERIFY',**base,'plan_auth':issue['plan_auth']}).encode(),peer_authorized=True));self.assertEqual('DENIED_BY_PRODUCTION_GATE',ok['status']);self.assertFalse(ok['destructive_action_performed'])
   bad=dict(base);bad['retention_days']=91
   denied=json.loads(s.handle(json.dumps({'action':'VERIFY',**bad,'plan_auth':issue['plan_auth']}).encode(),peer_authorized=True));self.assertEqual('DENIED_BY_PLAN_AUTH',denied['status'])
   peer=json.loads(s.handle(json.dumps({'action':'ISSUE_AUTH',**base}).encode(),peer_authorized=False));self.assertEqual('DENIED_BY_PEER_IDENTITY',peer['status'])
