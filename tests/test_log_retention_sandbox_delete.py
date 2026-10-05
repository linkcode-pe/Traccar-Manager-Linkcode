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
