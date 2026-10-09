#!/usr/bin/env bash
# Run a copy of the test suite as an unprivileged user without production state.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAB="$(mktemp -d /tmp/traccar-manager-tests-XXXXXXXX)"
trap 'rm -rf -- "$LAB"' EXIT
for part in manager api worker tests migrations runner web deploy deployment docs; do
  if [[ -d "$ROOT/$part" ]]; then
    tar -C "$ROOT" --exclude='__pycache__' --exclude='.pytest_cache' -cf - "$part" | tar -C "$LAB" -xf -
  fi
done
cat > "$LAB/tests/conftest.py" <<'PY'
"""Isolate production incident/audit readers in the test copy only."""
import pytest

@pytest.fixture(autouse=True)
def isolated_readers(monkeypatch, tmp_path):
    import manager.incident_history as incidents
    import manager.incident_decisions as decisions
    import manager.operational_health_history as operational
    monkeypatch.setattr(incidents, 'PATH', tmp_path / 'incidents.json')
    monkeypatch.setattr(decisions, 'PATH', tmp_path / 'audit.jsonl')
    monkeypatch.setattr(operational, 'PATH', tmp_path / 'operational-health.json')
PY
if [[ $(id -u) -eq 0 ]]; then
  chown -R nobody:nogroup "$LAB"
  cd "$LAB"
  exec_cmd=(runuser -u nobody -- env PYTHONDONTWRITEBYTECODE=1 "$ROOT/.venv/bin/python" -m pytest -q -p no:cacheprovider)
else
  cd "$LAB"
  exec_cmd=(env PYTHONDONTWRITEBYTECODE=1 "$ROOT/.venv/bin/python" -m pytest -q -p no:cacheprovider)
fi
"${exec_cmd[@]}" "$@"
