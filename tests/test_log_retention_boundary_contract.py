import unittest
from worker.operations.log_retention_boundary_contract import BoundaryContract,validate_request
class Tests(unittest.TestCase):
 def test_production_is_denied(self):
  s=BoundaryContract().public_status();self.assertEqual('DENY_PRODUCTION',s['mode']);self.assertFalse(s['production_access']);self.assertTrue(s['separate_identity_required'])
 def test_only_historical_names_are_allowlisted(self):
  self.assertTrue(validate_request('DELETE_EXPIRED_HISTORICAL_LOGS',['tracker-server.log.20260101']))
  for bad in ['tracker-server.log','../tracker-server.log.20260101','tracker-server.log.20260101.gz','x']:
   self.assertFalse(validate_request('DELETE_EXPIRED_HISTORICAL_LOGS',[bad]))
 def test_operation_and_duplicates_denied(self):
  self.assertFalse(validate_request('SHELL',['tracker-server.log.20260101']));self.assertFalse(validate_request('DELETE_EXPIRED_HISTORICAL_LOGS',['tracker-server.log.20260101']*2))
