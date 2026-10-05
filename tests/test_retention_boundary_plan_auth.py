import json,unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import worker.retention_boundary_server as s
class R: eligible=True
class Tests(unittest.TestCase):
 def test_boundary_issues_and_verifies_exact_plan_but_denies_mutation(self):
  now=datetime.now(timezone.utc);base={'operation':'DELETE_EXPIRED_HISTORICAL_LOGS','preparation_id':'prep-auth','names':['tracker-server.log.20260101'],'retention_days':90,'issued_at_utc':now.isoformat().replace('+00:00','Z'),'expires_at_utc':(now+timedelta(seconds=300)).isoformat().replace('+00:00','Z'),'preparation_binding_hash':'a'*64}
  with patch.object(s,'load_hmac_key',return_value=b'k'*32),patch.object(s,'revalidate',return_value=R()),patch.object(s,'_attested',return_value=True):
   issue=json.loads(s.handle(json.dumps({'action':'ISSUE_AUTH',**base}).encode(),peer_authorized=True));self.assertEqual('AUTH_ISSUED',issue['status'])
   ok=json.loads(s.handle(json.dumps({'action':'VERIFY',**base,'plan_auth':issue['plan_auth']}).encode(),peer_authorized=True));self.assertEqual('DENIED_BY_PRODUCTION_GATE',ok['status']);self.assertFalse(ok['destructive_action_performed'])
   bad=dict(base);bad['retention_days']=91
   denied=json.loads(s.handle(json.dumps({'action':'VERIFY',**bad,'plan_auth':issue['plan_auth']}).encode(),peer_authorized=True));self.assertEqual('DENIED_BY_PLAN_AUTH',denied['status'])
