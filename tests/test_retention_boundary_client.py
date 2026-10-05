import unittest
from unittest.mock import patch
import worker.retention_boundary_client as c
class Sock:
 def settimeout(self,x):pass
 def connect(self,p):pass
 def sendall(self,b):pass
 def recv(self,n):return (b'{"active_log_denied":true,"allowed_name_pattern":"tracker-server.log.YYYYMMDD","allowed_operation":"DELETE_EXPIRED_HISTORICAL_LOGS","component":"traccar-manager-retention-boundary","destructive_action_performed":false,"mode":"DENY_PRODUCTION","network_access":false,"production_access":false,"separate_identity_required":true,"shell_access":false,"status":"healthy"}')
 def close(self):pass
class Tests(unittest.TestCase):
 def test_accepts_exact_contract(self):
  with patch.object(c.socket,'socket',return_value=Sock()):self.assertEqual('healthy',c.query_health()['status'])
 def test_rejects_tampered_contract(self):
  x=Sock();x.recv=lambda n:b'{"status":"healthy"}'
  with patch.object(c.socket,'socket',return_value=x),self.assertRaises(c.BoundaryUnavailable):c.query_health()
