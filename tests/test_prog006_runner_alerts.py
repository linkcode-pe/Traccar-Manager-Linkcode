"""PROG-006 monitor regression using disposable SQLite and status files only."""
import json
import importlib.util
import multiprocessing
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

    def test_unhandled_runner_failure_is_recorded_in_isolated_state(self):
        script = Path(__file__).resolve().parents[1] / "scripts/run-tests-with-progress.py"
        spec = importlib.util.spec_from_file_location("prog006_runner_under_test", script)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        real_path = Path
        with patch.object(runner, "Path", side_effect=lambda value: self.path if value == "/var/lib/traccar-manager-progress" else real_path(value)), \
             patch.object(runner.sys, "argv", [str(script), "--apply"]), \
             patch.object(runner.os, "geteuid", return_value=0), \
             patch.object(runner, "RUN_LOCK_ACQUIRED", True):
            runner.record_unhandled_failure()
        status = json.loads((self.path / "prog006-run-status.json").read_text())
        history = json.loads((self.path / "prog006-run-history.json").read_text())
        self.assertEqual(status["result"], "runner_failed")
        self.assertEqual(history[0], status)
        self.assertEqual(progress.snapshot(self.principal)["runner_alert"], "failed")
        self.assertEqual(progress.snapshot(self.principal)["runner_history"][0]["result"], "runner_failed")

    def test_unhandled_runner_failure_dry_run_does_not_write(self):
        script = Path(__file__).resolve().parents[1] / "scripts/run-tests-with-progress.py"
        spec = importlib.util.spec_from_file_location("prog006_runner_dry_run", script)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        with patch.object(runner.sys, "argv", [str(script)]):
            runner.record_unhandled_failure()
        self.assertFalse((self.path / "prog006-run-status.json").exists())

    def test_running_is_not_a_success_and_becomes_stale(self):
        self.write_status("running", datetime.now(timezone.utc).isoformat())
        self.assertEqual(progress.snapshot(self.principal)["runner_alert"], "running")
        self.write_status("running", (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat())
        self.assertEqual(progress.snapshot(self.principal)["runner_alert"], "stale")

    def test_runner_failure_without_lock_does_not_overwrite(self):
        script = Path(__file__).resolve().parents[1] / "scripts/run-tests-with-progress.py"
        spec = importlib.util.spec_from_file_location("prog006_runner_no_lock", script)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        with patch.object(runner.sys, "argv", [str(script), "--apply"]), \
             patch.object(runner.os, "geteuid", return_value=0):
            runner.record_unhandled_failure()
        self.assertFalse((self.path / "prog006-run-status.json").exists())

    def test_competing_process_cannot_acquire_same_lock(self):
        script = Path(__file__).resolve().parents[1] / "scripts/run-tests-with-progress.py"
        spec = importlib.util.spec_from_file_location("prog006_lock_test", script)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        first = runner.acquire_run_lock(self.path)
        self.assertIsNotNone(first)
        try:
            ctx = multiprocessing.get_context("fork")
            queue = ctx.Queue()
            def contender():
                second = runner.acquire_run_lock(self.path)
                queue.put(second is None)
                if second is not None:
                    second.close()
            proc = ctx.Process(target=contender)
            proc.start()
            proc.join(timeout=5)
            if proc.is_alive():
                proc.terminate()
                proc.join()
                self.fail("Contender hung")
            self.assertEqual(proc.exitcode, 0)
            self.assertTrue(queue.get(timeout=2))
        finally:
            first.close()
        retry = runner.acquire_run_lock(self.path)
        self.assertIsNotNone(retry)
        retry.close()

    def test_recovery_detects_abandoned_run_only(self):
        script = Path(__file__).resolve().parents[1] / "scripts/run-tests-with-progress.py"
        spec = importlib.util.spec_from_file_location("prog006_recovery_test", script)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        self.assertFalse(runner.previous_run_interrupted(self.path))
        self.write_status("running", datetime.now(timezone.utc).isoformat())
        self.assertTrue(runner.previous_run_interrupted(self.path))
        self.write_status("passed", datetime.now(timezone.utc).isoformat())
        self.assertFalse(runner.previous_run_interrupted(self.path))
        (self.path / "prog006-run-status.json").write_text("broken json")
        self.assertFalse(runner.previous_run_interrupted(self.path))

    def test_interrupted_status_is_not_a_success(self):
        self.write_status("interrupted", datetime.now(timezone.utc).isoformat())
        result = progress.snapshot(self.principal)
        self.assertEqual(result["runner_status"]["result"], "interrupted")
        self.assertEqual(result["runner_alert"], "failed")

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
