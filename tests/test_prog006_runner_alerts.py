"""PROG-006 monitor regression using disposable SQLite and status files only."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from manager import progress
from manager.auth.session_store import SessionPrincipal


class RunnerAlertsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.db_patch = patch.object(progress, "DB_PATH", self.path / "progress.sqlite3")
        self.db_patch.start()
        progress.init()
        self.principal = SessionPrincipal("test", "test", ("development.progress.manage",), "2099-01-01T00:00:00Z")

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def write_status(self, result, when):
        (self.path / "prog006-run-status.json").write_text(json.dumps({"result": result, "last_run": when, "source_sha256": "a" * 64}))

    def test_missing_status_warns(self):
        self.assertEqual(progress.snapshot(self.principal)["runner_alert"], "missing")

    def test_failed_run_warns(self):
        self.write_status("tests_failed", datetime.now(timezone.utc).isoformat())
        self.assertEqual(progress.snapshot(self.principal)["runner_alert"], "failed")

    def test_overdue_run_warns(self):
        self.write_status("passed", (datetime.now(timezone.utc) - timedelta(hours=37)).isoformat())
        self.assertEqual(progress.snapshot(self.principal)["runner_alert"], "stale")

    def test_future_timestamp_warns(self):
        self.write_status("passed", (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
        self.assertEqual(progress.snapshot(self.principal)["runner_alert"], "stale")

    def test_recent_success_and_skip_do_not_warn(self):
        for result in ("passed", "skipped_unchanged"):
            with self.subTest(result=result):
                self.write_status(result, datetime.now(timezone.utc).isoformat())
                self.assertIsNone(progress.snapshot(self.principal)["runner_alert"])

    def test_history_is_bounded_and_sanitized(self):
        now = datetime.now(timezone.utc).isoformat()
        (self.path / "prog006-run-history.json").write_text(json.dumps([{"result": "passed", "last_run": now, "secret": "never expose"}] * 25))
        result = progress.snapshot(self.principal)
        self.assertEqual(len(result["runner_history"]), 10)
        self.assertEqual(set(result["runner_history"][0]), {"last_run", "result"})


if __name__ == "__main__":
    unittest.main()
