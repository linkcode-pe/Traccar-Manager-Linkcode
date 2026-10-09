# TEST-ONLY migration fixtures

These three fixtures are retained for isolated validation and are not part of normal migration discovery:

- `20261003000100`: empty infrastructure probe.
- `20261003000200`: intentional missing-table failure; historical status is retired only in `traccar-tem`.
- `20261003000300`: successful apply/result-draining probe.

Use only through the explicit `--test-only-fixtures --migrations-dir tests/fixtures/migrations_test_only --confirm-nonprod` gate and an authorized nonproduction/test database. Never copy these files into a production migration source set.
