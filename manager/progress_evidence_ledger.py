"""PROG-006 evidence ledger prototype; no production caller or migration yet.

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
