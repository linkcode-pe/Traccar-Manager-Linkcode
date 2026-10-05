import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from worker.operations.log_retention_preview import PreviewError, preview_log_retention


class LogRetentionPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tm-log-preview-")
        self.root = Path(self.temp.name)
        self.now = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.temp.cleanup()

    def _file(self, name, *, age_days, content=b"x"):
        path = self.root / name
        path.write_bytes(content)
        timestamp = (self.now - timedelta(days=age_days)).timestamp()
        os.utime(path, (timestamp, timestamp))
        return path

    def test_default_is_90_days_and_preview_is_non_destructive(self):
        old = self._file("tracker-server.log.20260601", age_days=126, content=b"old")
        recent = self._file("tracker-server.log.20260920", age_days=15, content=b"recent")
        active = self._file("tracker-server.log", age_days=200, content=b"active")
        result = preview_log_retention(self.root, now=self.now)
        self.assertEqual(90, result.retention_days)
        self.assertEqual(1, result.candidate_count)
        self.assertEqual(3, result.candidate_bytes)
        self.assertEqual(2, result.historical_count)
        self.assertEqual(9, result.historical_bytes)
        self.assertEqual("2026-06-01T12:00:00Z", result.oldest_candidate_utc)
        self.assertEqual("2026-06-01T12:00:00Z", result.newest_candidate_utc)
        self.assertEqual((old.name,), tuple(item.name for item in result.candidates))
        self.assertTrue(result.active_log_protected)
        self.assertFalse(result.destructive_action_performed)
        self.assertTrue(old.exists())
        self.assertTrue(recent.exists())
        self.assertTrue(active.exists())

    def test_only_exact_allowlisted_historical_names_are_candidates(self):
        accepted = self._file("tracker-server.log.20260101", age_days=200)
        self._file("tracker-server.log.20260101.gz", age_days=200)
        self._file("other.log.20260101", age_days=200)
        self._file("tracker-server.log.BADDATE", age_days=200)
        result = preview_log_retention(self.root, now=self.now)
        self.assertEqual((accepted.name,), tuple(item.name for item in result.candidates))

    def test_symlink_candidate_is_rejected(self):
        target = self._file("target", age_days=200)
        (self.root / "tracker-server.log.20260101").symlink_to(target)
        result = preview_log_retention(self.root, now=self.now)
        self.assertEqual(0, result.candidate_count)

    def test_cutoff_is_strictly_older(self):
        self._file("tracker-server.log.20260707", age_days=90)
        result = preview_log_retention(self.root, now=self.now)
        self.assertEqual(0, result.candidate_count)

    def test_candidate_bytes_and_order_are_deterministic(self):
        self._file("tracker-server.log.20260102", age_days=200, content=b"22")
        self._file("tracker-server.log.20260101", age_days=201, content=b"111")
        result = preview_log_retention(self.root, now=self.now)
        self.assertEqual(5, result.candidate_bytes)
        self.assertEqual(
            ("tracker-server.log.20260101", "tracker-server.log.20260102"),
            tuple(item.name for item in result.candidates),
        )

    def test_relative_directory_fails_closed(self):
        with self.assertRaises(PreviewError):
            preview_log_retention("relative/logs", now=self.now)

    def test_missing_directory_fails_closed(self):
        with self.assertRaises(PreviewError):
            preview_log_retention(self.root / "missing", now=self.now)

    def test_directory_symlink_fails_closed(self):
        link = self.root.parent / (self.root.name + "-link")
        try:
            link.symlink_to(self.root, target_is_directory=True)
            with self.assertRaises(PreviewError):
                preview_log_retention(link, now=self.now)
        finally:
            link.unlink(missing_ok=True)

    def test_retention_bounds_fail_closed(self):
        for value in (29, 3651, True, 90.0):
            with self.subTest(value=value):
                with self.assertRaises(PreviewError):
                    preview_log_retention(self.root, retention_days=value, now=self.now)

    def test_naive_now_fails_closed(self):
        with self.assertRaises(PreviewError):
            preview_log_retention(self.root, now=datetime(2026, 10, 5, 12, 0))


if __name__ == "__main__":
    unittest.main()
