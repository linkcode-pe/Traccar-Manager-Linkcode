#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ ! -d .visual-test/node_modules/playwright ]]; then
  echo 'Playwright not installed in isolated local .visual-test directory' >&2
  exit 2
fi
# Use the existing local dependency; never authenticate against live user data.
node "$ROOT/tests/visual/device-fixture.mjs"
node "$ROOT/tests/visual/alerts-partial-fixture.mjs"
node "$ROOT/tests/visual/maintenance-preview-fixture.mjs"
node "$ROOT/tests/visual/capacity-partial-fixture.mjs"
node "$ROOT/tests/visual/database-error-fixture.mjs"
node "$ROOT/tests/visual/audit-partial-fixture.mjs"
node "$ROOT/tests/visual/password-network-fixture.mjs"
node "$ROOT/tests/visual/avatar-network-fixture.mjs"
node "$ROOT/tests/visual/profile-validation-fixture.mjs"
node "$ROOT/tests/visual/account-accessibility-fixture.mjs"
node "$ROOT/tests/visual/services-evidence-fixture.mjs"
node "$ROOT/tests/visual/services-error-reset-fixture.mjs"
node "$ROOT/tests/visual/protection-error-reset-fixture.mjs"
node "$ROOT/tests/visual/fleet-error-reset-fixture.mjs"
node "$ROOT/tests/visual/avatar-drawer-reset-fixture.mjs"
node "$ROOT/tests/visual/avatar-preview-cleanup-fixture.mjs"
node "$ROOT/tests/visual/avatar-keyboard-fixture.mjs"
node "$ROOT/tests/visual/avatar-preview-race-fixture.mjs"
node "$ROOT/tests/visual/avatar-filetype-fixture.mjs"
