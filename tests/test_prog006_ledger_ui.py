"""Run the actual browser script in an isolated Node VM with a minimal DOM."""
import shutil
import subprocess
from pathlib import Path
import pytest


def test_ledger_pagination_survives_periodic_refresh():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js unavailable')
    root = Path(__file__).resolve().parent.parent
    completed = subprocess.run([node, '--test', 'tests/prog006_ledger_ui.test.cjs'], cwd=root,
                               capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stdout + completed.stderr
