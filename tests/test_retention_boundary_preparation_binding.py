import json,unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import worker.retention_boundary_server as s
class R: eligible=True
class Tests(unittest.TestCase):
 def base(self):
  now=datetime.now(timezone.utc);return {'operation':'DELETE_EXPIRED_HISTORICAL_LOGS','preparation_id':'prepare-legit','names':['tracker-server.log.20260101'],'retention_days':90,'issued_at_utc':now.isoformat().replace('+00:00','Z'),'expires_at_utc':(now+timedelta(seconds=300)).isoformat().replace('+00:00','Z'),'preparation_binding_hash':'a'*64}
 def test_token_is_bound_to_preparation_record_and_expiry(self):
  b=self.base()
  with patch.object(s,'load_hmac_key',return_value=b'k'*32),patch.object(s,'revalidate',return_value=R()),patch.object(s,'_attested',return_value=True):
   issue=json.loads(s.handle(json.dumps({'action':'ISSUE_AUTH',**b}).encode(),peer_authorized=True));self.assertEqual('AUTH_ISSUED',issue['status'])
   ok=json.loads(s.handle(json.dumps({'action':'VERIFY',**b,'plan_auth':issue['plan_auth']}).encode(),peer_authorized=True));self.assertEqual('DENIED_BY_PRODUCTION_GATE',ok['status'])
   changed=dict(b);changed['preparation_binding_hash']='b'*64
   bad=json.loads(s.handle(json.dumps({'action':'VERIFY',**changed,'plan_auth':issue['plan_auth']}).encode(),peer_authorized=True));self.assertEqual('DENIED_BY_PLAN_AUTH',bad['status'])
 def test_expired_prepare_cannot_be_signed(self):
  b=self.base();past=datetime.now(timezone.utc)-timedelta(seconds=1);b['expires_at_utc']=past.isoformat().replace('+00:00','Z')
  with patch.object(s,'load_hmac_key',return_value=b'k'*32),patch.object(s,'_attested',return_value=True):
   denied=json.loads(s.handle(json.dumps({'action':'ISSUE_AUTH',**b}).encode(),peer_authorized=True));self.assertEqual('INVALID_REQUEST',denied['status'])
