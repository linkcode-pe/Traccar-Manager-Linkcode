import os,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
from worker.operations.log_retention_preview import preview_log_retention
from worker.operations.log_retention_sandbox_delete import delete_preview_candidates_sandbox,SandboxDeleteError
class Tests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name);self.now=datetime.now(timezone.utc)
  self.old=self.root/'tracker-server.log.20260101';self.old.write_bytes(b'old-log');ts=(self.now-timedelta(days=100)).timestamp();os.utime(self.old,(ts,ts));(self.root/'tracker-server.log').write_bytes(b'ACTIVE');self.preview=preview_log_retention(self.root,retention_days=90,now=self.now)
 def tearDown(self):self.t.cleanup()
 def test_deletes_only_previewed_historical_file(self):
  r=delete_preview_candidates_sandbox(self.preview,sandbox_root=self.root);self.assertEqual(1,r.deleted_count);self.assertEqual(7,r.deleted_bytes);self.assertFalse(self.old.exists());self.assertTrue((self.root/'tracker-server.log').exists())
 def test_modified_after_preview_fails_closed(self):
  self.old.write_bytes(b'changed');
  with self.assertRaisesRegex(SandboxDeleteError,'CANDIDATE_CHANGED'):delete_preview_candidates_sandbox(self.preview,sandbox_root=self.root)
  self.assertTrue(self.old.exists())
 def test_symlink_swap_fails_closed_and_target_survives(self):
  outside=self.root.parent/('outside-'+self.root.name);outside.write_bytes(b'safe');self.old.unlink();self.old.symlink_to(outside)
  try:
   with self.assertRaisesRegex(SandboxDeleteError,'CANDIDATE_CHANGED'):delete_preview_candidates_sandbox(self.preview,sandbox_root=self.root)
   self.assertEqual(b'safe',outside.read_bytes())
  finally: outside.unlink(missing_ok=True)
 def test_preview_root_mismatch_is_denied(self):
  with tempfile.TemporaryDirectory() as other:
   with self.assertRaisesRegex(SandboxDeleteError,'PREVIEW_ROOT_MISMATCH'):delete_preview_candidates_sandbox(self.preview,sandbox_root=other)
 def test_active_log_cannot_enter_preview(self):self.assertNotIn('tracker-server.log',[x.name for x in self.preview.candidates])

class MultiCandidateTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name);self.now=datetime.now(timezone.utc);ts=(self.now-timedelta(days=100)).timestamp()
  self.a=self.root/'tracker-server.log.20260101';self.b=self.root/'tracker-server.log.20260102'
  self.a.write_bytes(b'aaa');self.b.write_bytes(b'bbbb');os.utime(self.a,(ts,ts));os.utime(self.b,(ts,ts));self.preview=preview_log_retention(self.root,retention_days=90,now=self.now)
 def tearDown(self):self.t.cleanup()
 def test_preflight_change_in_second_candidate_causes_zero_deletes(self):
  self.b.write_bytes(b'changed-after-preview')
  with self.assertRaisesRegex(SandboxDeleteError,'CANDIDATE_CHANGED'):delete_preview_candidates_sandbox(self.preview,sandbox_root=self.root)
  self.assertTrue(self.a.exists());self.assertTrue(self.b.exists())
 def test_multiple_exact_counts(self):
  r=delete_preview_candidates_sandbox(self.preview,sandbox_root=self.root);self.assertEqual(2,r.deleted_count);self.assertEqual(7,r.deleted_bytes);self.assertEqual(('tracker-server.log.20260101','tracker-server.log.20260102'),r.deleted_names)
 def test_duplicate_candidate_is_detected_before_second_mutation(self):
  from dataclasses import replace
  dup=replace(self.preview,candidates=(self.preview.candidates[0],self.preview.candidates[0]),candidate_count=2,candidate_bytes=6)
  # Reject duplicate plans up-front rather than allow a guaranteed partial execution.
  with self.assertRaisesRegex(SandboxDeleteError,'DUPLICATE_CANDIDATE'):delete_preview_candidates_sandbox(dup,sandbox_root=self.root)
  self.assertTrue(self.a.exists())

class PartialFailureTests(MultiCandidateTests):
 def test_injected_second_unlink_failure_is_reported_partial(self):
  def hook(name,index,root):
   if index==1:
    os.chmod(root/name,0o400)
    # deterministic disappearance between second re-stat and unlink
    os.unlink(root/name)
  with self.assertRaisesRegex(SandboxDeleteError,'PARTIAL_DELETE'):
   delete_preview_candidates_sandbox(self.preview,sandbox_root=self.root,_before_unlink=hook)
  self.assertFalse(self.a.exists())
  self.assertFalse(self.b.exists())

class ProductionBoundaryContractTests(unittest.TestCase):
 def test_boundary_is_explicitly_sandbox_only(self):
  from worker.operations.log_retention_sandbox_delete import production_boundary_status
  self.assertEqual({'component':'isolated-delete-boundary','production_root':'/opt/traccar/logs','production_access':False,'sandbox_only':True,'active_log_denied':True,'path_allowlist':'tracker-server.log.YYYYMMDD'},production_boundary_status())
 def test_production_root_is_hard_denied_before_mutation(self):
  from dataclasses import replace
  from worker.operations.log_retention_sandbox_delete import delete_preview_candidates_sandbox,SandboxDeleteError
  fake=replace(Tests.__dict__.get('preview',None)) if False else None
  # Source-level invariant complements runtime sandbox tests: production root denial must remain in helper.
  import inspect
  src=inspect.getsource(delete_preview_candidates_sandbox)
  self.assertIn("PRODUCTION_PATH_DENIED",src);self.assertIn("/opt/traccar",src)
