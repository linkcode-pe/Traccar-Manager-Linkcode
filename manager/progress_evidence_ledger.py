"""PROG-006 append-only evidence ledger; schema created on first authorized write.

Each append is transactional and immutable. Callers must validate report bytes and
successful test execution before invoking it. No checklist evidence is removed.
"""
import re
import sqlite3
from datetime import datetime, timezone

CREATE = """CREATE TABLE IF NOT EXISTS progress_evidence_ledger (
    event_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    report_path TEXT NOT NULL,
    report_sha256 TEXT NOT NULL,
    result TEXT NOT NULL CHECK(result = 'passed'),
    recorded_at TEXT NOT NULL
)"""


def append(db: sqlite3.Connection, *, event_id: str, task_id: str,
           source_sha256: str, report_path: str, report_sha256: str) -> bool:
    """Return True if inserted, False if exact duplicate; reject conflicts."""
    if not re.fullmatch(r'test-run-[a-f0-9]{24}', event_id):
        raise ValueError('invalid event id')
    if not re.fullmatch(r'[A-Z]{2,8}-[0-9]{3}', task_id):
        raise ValueError('invalid task id')
    if not re.fullmatch(r'[a-f0-9]{64}', source_sha256) or not re.fullmatch(r'[a-f0-9]{64}', report_sha256):
        raise ValueError('invalid digest')
    if not re.fullmatch(r'docs/test-runs/[A-Za-z0-9._-]{1,180}\.md', report_path):
        raise ValueError('invalid report path')
    with db:
        db.execute(CREATE)
        previous = db.execute('SELECT task_id,source_sha256,report_path,report_sha256,result FROM progress_evidence_ledger WHERE event_id=?', (event_id,)).fetchone()
        expected = (task_id, source_sha256, report_path, report_sha256, 'passed')
        if previous is not None:
            if tuple(previous) != expected:
                raise ValueError('event id conflict')
            return False
        db.execute('INSERT INTO progress_evidence_ledger VALUES (?,?,?,?,?,?,?)',
                   (event_id, *expected, datetime.now(timezone.utc).isoformat()))
        return True


def record_success(db: sqlite3.Connection, *, event_id: str, task_id: str,
                   source_sha256: str, report_path: str, report_sha256: str,
                   actor: str = 'system-ci-tests') -> bool:
    """Atomically append evidence and event without modifying checklist evidence."""
    if not isinstance(actor, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,64}', actor):
        raise ValueError('invalid actor')
    # Validate before opening a transaction; append() performs the same checks.
    if not re.fullmatch(r'test-run-[a-f0-9]{24}', event_id) or not re.fullmatch(r'[A-Z]{2,8}-[0-9]{3}', task_id):
        raise ValueError('invalid identifiers')
    if not re.fullmatch(r'[a-f0-9]{64}', source_sha256) or not re.fullmatch(r'[a-f0-9]{64}', report_sha256):
        raise ValueError('invalid digest')
    if not re.fullmatch(r'docs/test-runs/[A-Za-z0-9._-]{1,180}\.md', report_path):
        raise ValueError('invalid report path')
    with db:
        db.execute(CREATE)
        task = db.execute('SELECT state FROM tasks WHERE task_id=?', (task_id,)).fetchone()
        if task is None:
            raise ValueError('unknown task')
        if task[0] == 'verified':
            raise ValueError('verified task cannot be downgraded')
        previous = db.execute('SELECT task_id,source,state FROM progress_events WHERE event_id=?', (event_id,)).fetchone()
        existing = db.execute('SELECT task_id,source_sha256,report_path,report_sha256,result FROM progress_evidence_ledger WHERE event_id=?', (event_id,)).fetchone()
        expected = (task_id, source_sha256, report_path, report_sha256, 'passed')
        if previous is not None or existing is not None:
            if previous is None or existing is None or tuple(previous) != (task_id, 'scripts/progress-record-test-run', 'in_testing') or tuple(existing) != expected:
                raise ValueError('event id conflict')
            return False
        now = datetime.now(timezone.utc).isoformat()
        db.execute('INSERT INTO progress_evidence_ledger VALUES (?,?,?,?,?,?,?)', (event_id, *expected, now))
        db.execute('INSERT INTO progress_events VALUES (?,?,?,?,?,?)', (event_id, task_id, 'scripts/progress-record-test-run', actor, 'in_testing', now))
        db.execute('INSERT INTO history(task_id,actor,old_state,new_state,changed_at) VALUES (?,?,?,?,?)', (task_id, actor, task[0], 'in_testing', now))
        db.execute("UPDATE tasks SET state='in_testing',doc_state='in_review',updated_at=? WHERE task_id=?", (now, task_id))
        return True
