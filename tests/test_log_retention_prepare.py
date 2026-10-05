import unittest
from datetime import datetime,timezone
from worker.operations.log_retention_preview import LogCandidate,LogRetentionPreview
from worker.operations.log_retention_prepare import LogRetentionPrepareError,_hash,_plan,prepare_log_retention

class LogRetentionPrepareTests(unittest.TestCase):
    def setUp(self):
        self.p=LogRetentionPreview('/opt/traccar/logs',90,'2026-07-07T00:00:00Z',1,123,(LogCandidate('tracker-server.log.20260101','/opt/traccar/logs/tracker-server.log.20260101',123,'2026-01-01T00:00:00Z'),))
        self.pid='preview-'+_hash(_plan(self.p))
    def provider(self,*a,**k): return self.p
    def test_prepare_revalidates_and_binds_exact_preview_without_mutation(self):
        r=prepare_log_retention(self.pid,retention_days=90,preview_provider=self.provider,now=datetime(2026,10,5,tzinfo=timezone.utc))
        self.assertEqual(self.pid,r.preview_id); self.assertEqual(1,r.candidate_count); self.assertTrue(r.revalidated)
        self.assertFalse(r.destructive_action_performed); self.assertTrue(r.preparation_id.startswith('prepare-'))
        self.assertEqual('2026-10-05T00:05:00.000000Z',r.expires_at_utc)
    def test_changed_candidates_make_preview_stale(self):
        changed=LogRetentionPreview('/opt/traccar/logs',90,'2026-07-07T00:00:00Z',0,0,())
        with self.assertRaisesRegex(LogRetentionPrepareError,'PREVIEW_STALE'):
            prepare_log_retention(self.pid,retention_days=90,preview_provider=lambda *a,**k: changed)
    def test_rejects_forged_preview_and_bad_retention_before_provider(self):
        called=[]
        provider=lambda *a,**k: called.append(1)
        with self.assertRaises(LogRetentionPrepareError): prepare_log_retention('preview-bad',retention_days=90,preview_provider=provider)
        with self.assertRaises(LogRetentionPrepareError): prepare_log_retention(self.pid,retention_days=29,preview_provider=provider)
        self.assertEqual([],called)
