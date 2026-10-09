"""Authorized, bounded ledger API with isolated database and report files."""
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from manager import progress
from manager.auth.session_store import SessionPrincipal
from manager.progress_evidence_ledger import record_success


class LedgerSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.patch_db = patch.object(progress, 'DB_PATH', self.base / 'progress.sqlite3')
        self.patch_db.start()
        self.addCleanup(self.patch_db.stop)
        progress.init()
        self.allowed = SessionPrincipal('test', 'test', ('development.progress.manage',), '2099-01-01T00:00:00Z')
        self.denied = SessionPrincipal('test', 'test', (), '2099-01-01T00:00:00Z')
        self.args = dict(event_id='test-run-' + 'a' * 24, task_id='PROG-006', source_sha256='b' * 64,
                         report_path='docs/test-runs/test-ledger.md', report_sha256='c' * 64)

    def test_unauthorized_cannot_read(self):
        with self.assertRaises(PermissionError):
            progress.snapshot(self.denied)

    def test_missing_table_is_backward_compatible(self):
        result = progress.snapshot(self.allowed)
        self.assertEqual(result['evidence_ledger'], [])
        self.assertEqual(result['evidence_ledger_count'], 0)

    def test_missing_report_is_explicit(self):
        with progress.connect() as db:
            record_success(db, **self.args)
        result = progress.snapshot(self.allowed)
        self.assertEqual(result['evidence_ledger_count'], 1)
        self.assertEqual(result['evidence_ledger'][0]['integrity'], 'missing')

    def test_history_is_limited_to_ten(self):
        with progress.connect() as db:
            for i in range(13):
                record_success(db, **dict(self.args, event_id='test-run-' + format(i, '024x')))
        result = progress.snapshot(self.allowed)
        self.assertEqual(result['evidence_ledger_count'], 13)
        self.assertEqual(len(result['evidence_ledger']), 10)

    def test_integrity_summary_detects_missing_and_tampered(self):
        with progress.connect() as db:
            record_success(db, **self.args)
            record_success(db, **dict(self.args, event_id='test-run-' + 'b' * 24,
                                      report_path='docs/test-runs/PROG-006-other.md'))
        result = progress.snapshot(self.allowed)
        self.assertEqual(result['evidence_ledger_integrity']['missing'], 2)
        self.assertEqual(result['evidence_ledger_count'], 2)

    def test_integrity_summary_empty_when_no_table(self):
        result = progress.snapshot(self.allowed)
        self.assertEqual(sum(result['evidence_ledger_integrity'].values()), 0)
