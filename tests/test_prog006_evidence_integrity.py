import hashlib
import tempfile
import unittest
from pathlib import Path
from manager.progress_evidence_integrity import check_report

class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reports = self.root / 'docs' / 'test-runs'
        self.reports.mkdir(parents=True)
        self.path = self.reports / 'run.md'
        self.path.write_bytes(b'valid test report')
        self.digest = hashlib.sha256(b'valid test report').hexdigest()

    def check(self, path='docs/test-runs/run.md', digest=None):
        return check_report(self.root, path, digest or self.digest)

    def test_valid_report(self):
        self.assertEqual(self.check(), 'ok')

    def test_modified_report(self):
        self.path.write_bytes(b'tampered report')
        self.assertEqual(self.check(), 'mismatch')

    def test_missing_report(self):
        self.path.unlink()
        self.assertEqual(self.check(), 'missing')

    def test_symlink_report_rejected(self):
        self.path.rename(self.reports / 'original.md')
        self.path.symlink_to(self.reports / 'original.md')
        self.assertEqual(self.check(), 'invalid')

    def test_symlink_directory_rejected(self):
        self.reports.rename(self.root / 'real-reports')
        self.reports.symlink_to(self.root / 'real-reports', target_is_directory=True)
        self.assertEqual(self.check(), 'unavailable')

    def test_invalid_paths_and_digests(self):
        self.assertEqual(self.check('../run.md'), 'invalid')
        self.assertEqual(self.check('docs/test-runs/run.md', 'not-a-digest'), 'invalid')

    def test_oversized_report(self):
        self.path.write_bytes(b'x' * 200001)
        self.assertEqual(self.check(), 'invalid')

    def test_empty_report(self):
        self.path.write_bytes(b'')
        self.assertEqual(self.check(), 'invalid')
