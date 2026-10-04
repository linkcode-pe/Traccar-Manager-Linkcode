# Manager persistence and migrations

## Scope and source sets

The Python migration runner is a separate Manager infrastructure component. It is not invoked by PHP, Traccar, workers, scheduler or service startup. `migrations/` is the normal source set. TEST-ONLY validation assets live only in `tests/fixtures/migrations_test_only/` and are excluded from normal discovery and planning.

The fixtures are `20261003000100` (empty infrastructure probe), `20261003000200` (deliberate missing-table failure), and `20261003000300` (successful apply/result-drain probe). Each carries a first-line machine marker binding its version and body checksum. They remain historical test assets and must not be promoted into a production migration set.

## Destination identity and TLS

MySQL operations require `TRACCAR_MANAGER_DB_ENVIRONMENT=nonprod` and the matching CLI confirmation. Those gates are not endpoint identity. Before opening a socket, `MySQLConnectionFactory` compares hostname, database, username, port and approved CA path with the source-controlled nonproduction destination allowlist. After TLS connection it verifies `DATABASE()`, `CURRENT_USER()`, server version and a nonempty session TLS cipher before returning a connection. A target outside the allowlist fails before acquiring the migration lock or issuing migration DDL/DML.

The current allowlisted destination is the already validated `traccar-tem` target only. Its TLS hostname remains the certificate identity; a narrowly scoped process-local resolver maps only that exact hostname to the approved loopback address during `mysql-connector-python` pure-Python connect. The hostname passed to TLS is not rewritten, certificate and identity verification remain enabled, and the resolver is restored immediately. No global host file is modified. The standard read-only check is:

`python runner/migrate.py verify-target --confirm-nonprod`

It reports only the allowlisted nonsecret identity, server version and negotiated TLS cipher.

SQLite is confined to an existing file-backed test database inside the checkout when the environment is `test`; it is not a MySQL or production fallback. The CLI never silently switches backends.

## Discovery and checksums

Migration filenames are `VYYYYMMDDHHMMSS__lowercase_description.sql`; versions must be valid 14-digit timestamps and unique. Ordinary migrations use SHA-256 over the complete exact file bytes. For TEST-ONLY fixtures, discovery validates the single first-line marker, filename/version match and SHA-256 over the exact bytes after the marker. No normalization is performed. Thus 00300’s canonical checksum is `529763174d46d3203402b037635cdb1d55b1792e80d953517e31e12caead5379`; the marker-inclusive whole-file digest is different by design.

Normal discovery, `plan` and `apply` omit marked TEST-ONLY files. Explicit fixture inspection/execution requires `--test-only-fixtures`, the exact fixture directory, explicit confirmation and a nonproduction/test environment. Invalid markers fail closed even when fixtures are excluded.

## CLI and operational gates

`plan` without `--with-status` reads local files only and never connects. Status planning takes the advisory lock, checks selected sources and tracking, and releases the lock in `finally`. `apply` requires `--confirm-nonprod`, an allowlisted nonproduction MySQL target (or an explicitly existing in-checkout SQLite test database), and validates the full local/tracking sequence under the advisory lock before executing pending migration SQL. Unknown tracking versions, checksum changes, invalid states, failed/running migrations, retry inconsistencies and earlier pending gaps block execution. A valid `retired_test` fixture is skipped, never represented as `applied`; it can allow a later explicitly selected fixture to proceed.

The runner has no migration rollback command. MySQL DDL may commit implicitly, so a failed migration can leave partial schema effects. The runner records `failed` when it can; review actual schema state before authorizing a retry. No automatic repair of tracking is performed.

## Recovery and TEST-ONLY retirement

`recover` requires an exact version, actor, reason and confirmation. Under the advisory lock it permits only a reviewed `failed` → `retry_authorized` transition, with an audit record; it does not execute SQL or mark a migration applied. A separate confirmed `apply` is needed for any retry.

`retire-test` is restricted to explicitly selected TEST-ONLY fixtures and requires exact version, actor, reason, checksum, marker and confirmation. It accepts only a failed row, preserves its checksum/error/start time and null `applied_at_utc`, records a separate audit row and never executes the fixture SQL. An identical request is a no-op. `retired_test` means only that a failed fixture was administratively retired; it is not success and is not equivalent to `applied`.

The audit tables are append-only in the application’s available operations. Database-level immutability and grants are deployment responsibilities; no WORM guarantee is claimed by this code.

## Known E2E evidence

A previously authorized, isolated nonproduction run against `traccar-tem` applied 00300 once, then returned “No pending migrations” on the second invocation. The reported tracking state was 00100=`applied`, 00200=`retired_test`, 00300=`applied`; no production MySQL was accessed. This is historical validation evidence, not a live status read by this document update.
