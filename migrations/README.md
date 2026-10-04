# Normal migration source set

`migrations/` contains only production-candidate SQL migrations. Test fixtures do not belong here and are excluded from normal discovery.

The validation fixtures `V20261003000100`, `V20261003000200` and `V20261003000300` are preserved under `tests/fixtures/migrations_test_only/`. They are all explicitly TEST-ONLY, including the intentionally failing `00200`; do not copy them into a production migration set.

A TEST-ONLY marker must be the first line and bind the exact 14-digit filename version to the SHA-256 of every remaining byte. Do not normalize line endings or edit a fixture after it has been recorded. Normal discovery validates any marker it encounters but omits TEST-ONLY files; including fixtures requires the explicit CLI flag, explicit fixture directory, nonproduction/test environment and confirmation.

No production migration is currently present in this directory. The known nonproduction E2E state belongs to the isolated `traccar-tem` test database and is not a production baseline.
