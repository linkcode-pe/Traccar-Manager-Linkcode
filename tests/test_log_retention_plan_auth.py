import os,unittest
from worker.operations.log_retention_plan_auth import sign,verify
class Tests(unittest.TestCase):
 def test_hmac_authenticates_exact_plan_only(self):
  k=os.urandom(32);names=['tracker-server.log.20260101'];t=sign(k,'prep-auth',names,90)
  self.assertTrue(verify(k,t,'prep-auth',names,90));self.assertFalse(verify(k,t,'prep-auth',['tracker-server.log.20260102'],90));self.assertFalse(verify(k,t,'prep-auth',names,91));self.assertFalse(verify(os.urandom(32),t,'prep-auth',names,90))
 def test_key_strength_is_enforced(self):
  with self.assertRaisesRegex(ValueError,'WEAK_KEY'):sign(b'short','p',['tracker-server.log.20260101'],90)
