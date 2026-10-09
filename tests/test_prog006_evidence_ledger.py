"""Ledger regression tests: disposable in-memory SQLite only."""
import sqlite3
import tempfile
import threading
from pathlib import Path
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

class AtomicEvidenceTests(unittest.TestCase):
    def setUp(self):
        from manager import progress
        self.db = sqlite3.connect(':memory:')
        self.db.execute('CREATE TABLE tasks(task_id TEXT PRIMARY KEY,state TEXT,doc_state TEXT,evidence TEXT,updated_at TEXT)')
        self.db.execute("INSERT INTO tasks VALUES ('PROG-006','pending','pending','[\"historic\"]','old')")
        self.db.execute('CREATE TABLE progress_events(event_id TEXT PRIMARY KEY,task_id TEXT,source TEXT,actor TEXT,state TEXT,recorded_at TEXT)')
        self.db.execute('CREATE TABLE history(id INTEGER PRIMARY KEY,task_id TEXT,actor TEXT,old_state TEXT,new_state TEXT,changed_at TEXT)')
        self.db.commit()
        self.args = dict(event_id='test-run-' + 'a' * 24, task_id='PROG-006', source_sha256='b' * 64,
                         report_path='docs/test-runs/PROG-006-test.md', report_sha256='c' * 64)

    def tearDown(self):
        self.db.close()

    def test_atomic_idempotent_preserves_checklist_evidence(self):
        from manager.progress_evidence_ledger import record_success
        self.assertTrue(record_success(self.db, **self.args))
        self.assertFalse(record_success(self.db, **self.args))
        self.assertEqual(self.db.execute('SELECT evidence FROM tasks').fetchone()[0], '["historic"]')
        self.assertEqual(self.db.execute('SELECT count(*) FROM progress_events').fetchone()[0], 1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM progress_evidence_ledger').fetchone()[0], 1)

    def test_conflict_and_rollback(self):
        from manager.progress_evidence_ledger import record_success
        record_success(self.db, **self.args)
        with self.assertRaisesRegex(ValueError, 'conflict'):
            record_success(self.db, **dict(self.args, report_sha256='d' * 64))
        self.db.execute("CREATE TRIGGER reject_history BEFORE INSERT ON history BEGIN SELECT RAISE(ABORT, 'blocked'); END")
        with self.assertRaises(sqlite3.DatabaseError):
            record_success(self.db, **dict(self.args, event_id='test-run-' + 'e' * 24))
        self.assertEqual(self.db.execute('SELECT count(*) FROM progress_events').fetchone()[0], 1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM progress_evidence_ledger').fetchone()[0], 1)

    def test_verified_task_rejected(self):
        from manager.progress_evidence_ledger import record_success
        self.db.execute("UPDATE tasks SET state='verified'")
        self.db.commit()
        with self.assertRaisesRegex(ValueError, 'verified'):
            record_success(self.db, **self.args)
        self.assertEqual(self.db.execute('SELECT count(*) FROM progress_events').fetchone()[0], 0)


class LedgerConcurrencyAndBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.db_path = self.path / 'progress.sqlite3'
        db = sqlite3.connect(self.db_path)
        db.execute('CREATE TABLE tasks(task_id TEXT PRIMARY KEY,state TEXT,doc_state TEXT,evidence TEXT,updated_at TEXT)')
        db.execute("INSERT INTO tasks VALUES ('PROG-006','pending','pending','[\"historical\"]','old')")
        db.execute('CREATE TABLE progress_events(event_id TEXT PRIMARY KEY,task_id TEXT,source TEXT,actor TEXT,state TEXT,recorded_at TEXT)')
        db.execute('CREATE TABLE history(id INTEGER PRIMARY KEY,task_id TEXT,actor TEXT,old_state TEXT,new_state TEXT,changed_at TEXT)')
        db.commit()
        db.close()
        self.args = dict(event_id='test-run-' + 'f' * 24, task_id='PROG-006', source_sha256='b' * 64,
                         report_path='docs/test-runs/PROG-006-test.md', report_sha256='c' * 64)

    def tearDown(self):
        self.temp.cleanup()

    def test_two_connections_race_same_event(self):
        from manager.progress_evidence_ledger import record_success
        barrier = threading.Barrier(2)
        results = []
        errors = []
        def worker():
            try:
                db = sqlite3.connect(self.db_path, timeout=5)
                barrier.wait(timeout=5)
                results.append(record_success(db, **self.args))
                db.close()
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=8)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertFalse(errors, repr(errors))
        self.assertCountEqual(results, [True, False])
        with sqlite3.connect(self.db_path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM progress_events').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM progress_evidence_ledger').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM history').fetchone()[0], 1)

    def test_sqlite_backup_and_restore_preserves_evidence(self):
        from manager.progress_evidence_ledger import record_success
        backup_path = self.path / 'backup.sqlite3'
        restored_path = self.path / 'restored.sqlite3'
        with sqlite3.connect(self.db_path) as db:
            record_success(db, **self.args)
            with sqlite3.connect(backup_path) as backup:
                db.backup(backup)
        with sqlite3.connect(backup_path) as backup, sqlite3.connect(restored_path) as restored:
            backup.backup(restored)
        with sqlite3.connect(restored_path) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('SELECT evidence FROM tasks').fetchone()[0], '["historical"]')
            self.assertEqual(db.execute('SELECT count(*) FROM progress_evidence_ledger').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM progress_events').fetchone()[0], 1)
            self.assertFalse(record_success(db, **self.args))
