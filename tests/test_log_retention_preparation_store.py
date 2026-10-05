import tempfile,unittest
from dataclasses import replace
from pathlib import Path
from datetime import datetime,timezone
from worker.operations.log_retention_preview import LogRetentionPreview
from worker.operations.log_retention_prepare import prepare_log_retention,_hash,_plan
from worker.operations.log_retention_preparation_store import PreparationStore,PreparationStoreError
class Tests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.store=PreparationStore(Path(self.t.name)/'issued.jsonl');self.pv=LogRetentionPreview('/opt/traccar/logs',90,'2026-07-07T00:00:00Z',0,0,());pid='preview-'+_hash(_plan(self.pv));self.p=prepare_log_retention(pid,retention_days=90,preview_provider=lambda *a,**k:self.pv,now=datetime(2026,10,5,tzinfo=timezone.utc))
 def tearDown(self):self.t.cleanup()
 def test_issue_and_verify_same_actor(self):self.store.issue(self.p,subject_id='actor-a');self.assertTrue(self.store.verify(self.p,subject_id='actor-a'))
 def test_forged_unissued_rejected(self):
  with self.assertRaisesRegex(PreparationStoreError,'PREPARATION_NOT_ISSUED'):self.store.verify(self.p,subject_id='actor-a')
 def test_other_actor_rejected(self):
  self.store.issue(self.p,subject_id='actor-a')
  with self.assertRaisesRegex(PreparationStoreError,'PREPARATION_ACTOR_MISMATCH'):self.store.verify(self.p,subject_id='actor-b')
 def test_tampered_preparation_rejected(self):
  self.store.issue(self.p,subject_id='actor-a');tampered=replace(self.p,candidate_bytes=999)
  with self.assertRaisesRegex(PreparationStoreError,'PREPARATION_BINDING_MISMATCH'):self.store.verify(tampered,subject_id='actor-a')
 def test_store_symlink_rejected(self):
  target=Path(self.t.name)/'target';target.write_text('');self.store.path.symlink_to(target)
  with self.assertRaisesRegex(PreparationStoreError,'PREPARATION_STORE_UNAVAILABLE'):self.store.issue(self.p,subject_id='actor-a')
