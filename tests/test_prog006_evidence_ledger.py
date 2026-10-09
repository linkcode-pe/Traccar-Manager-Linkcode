"""Ledger regression tests: disposable in-memory SQLite only."""
import sqlite3
import unittest
from manager.progress_evidence_ledger import append


class EvidenceLedgerTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.args = dict(event_id='test-run-' + 'a' * 24, task_id='PROG-006',
                         source_sha256='b' * 64, report_path='docs/test-runs/PROG-006-test.md',
                         report_sha256='c' * 64)

    def tearDown(self):
        self.db.close()

    def test_append_is_idempotent_and_preserves_history(self):
        self.assertTrue(append(self.db, **self.args))
        self.assertFalse(append(self.db, **self.args))
        for index in range(25):
            other = dict(self.args, event_id='test-run-' + format(index, '024x'))
            self.assertTrue(append(self.db, **other))
        self.assertEqual(self.db.execute('SELECT count(*) FROM progress_evidence_ledger').fetchone()[0], 26)

    def test_conflicting_event_is_rejected_without_change(self):
        append(self.db, **self.args)
        with self.assertRaisesRegex(ValueError, 'conflict'):
            append(self.db, **dict(self.args, report_sha256='d' * 64))
        self.assertEqual(self.db.execute('SELECT report_sha256 FROM progress_evidence_ledger').fetchone()[0], 'c' * 64)

    def test_invalid_input_does_not_create_table(self):
        for field, value in [('report_path', '../secret'), ('source_sha256', 'broken'),
                             ('event_id', 'wrong'), ('task_id', 'BAD')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                append(self.db, **dict(self.args, **{field: value}))
        self.assertIsNone(self.db.execute("SELECT name FROM sqlite_master WHERE name='progress_evidence_ledger'").fetchone())

    def test_failed_transaction_rolls_back(self):
        append(self.db, **self.args)
        self.db.execute("CREATE TRIGGER reject_ledger BEFORE INSERT ON progress_evidence_ledger BEGIN SELECT RAISE(ABORT, 'blocked'); END")
        with self.assertRaises(sqlite3.DatabaseError):
            append(self.db, **dict(self.args, event_id='test-run-' + 'e' * 24))
        self.assertEqual(self.db.execute('SELECT count(*) FROM progress_evidence_ledger').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
