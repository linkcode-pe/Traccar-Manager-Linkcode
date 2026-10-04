"""Fail-closed versioned migration planner, executor, and recovery authorizer."""
from dataclasses import dataclass
from datetime import datetime, timezone
import re

from manager.errors import (
    MigrationAuthorizationError, MigrationChecksumMismatch, MigrationExecutionError,
    MigrationHistoryError, MigrationRecoveryRequired,
)
from manager.migrations.discovery import discover_migrations

TRACKING_TABLE = "manager_schema_migrations"
RECOVERY_AUDIT_TABLE = "manager_schema_migration_recovery_audit"
RETIREMENT_AUDIT_TABLE = "manager_schema_migration_retirement_audit"
LOCK_NAME = "traccar_manager_schema_migrations"
APPLY_CONFIRMATION = "APPLY_NONPROD_MIGRATIONS"

@dataclass(frozen=True)
class MigrationPlanEntry:
    version: str
    name: str
    checksum: str
    status: str = "not-queried"

@dataclass(frozen=True)
class ApplyResult:
    applied_versions: tuple
    no_migrations: bool = False

@dataclass(frozen=True)
class RecoveryResult:
    version: str
    status: str
    already_authorized: bool = False

@dataclass(frozen=True)
class RetirementResult:
    version: str
    status: str
    already_retired: bool = False

def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def split_sql_statements(sql):
    """Split ordinary SQL on semicolons outside quotes/comments.

    DELIMITER/procedure definitions are intentionally unsupported.
    """
    parts, buf = [], []
    quote = None
    line_comment = False
    block_comment = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ""
        if line_comment:
            buf.append(ch)
            if ch in "\r\n":
                line_comment = False
            i += 1
            continue
        if block_comment:
            buf.append(ch)
            if ch == "*" and nxt == "/":
                buf.append(nxt)
                i += 2
                block_comment = False
            else:
                i += 1
            continue
        if quote is not None:
            buf.append(ch)
            if ch == "\\" and quote in ("'", '"') and nxt:
                buf.append(nxt)
                i += 2
                continue
            if ch == quote:
                if nxt == quote:
                    buf.append(nxt)
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "-" and nxt == "-" and (i + 2 == len(sql) or sql[i + 2].isspace()):
            buf.extend((ch, nxt))
            i += 2
            line_comment = True
            continue
        if ch == "#":
            buf.append(ch)
            i += 1
            line_comment = True
            continue
        if ch == "/" and nxt == "*":
            buf.extend((ch, nxt))
            i += 2
            block_comment = True
            continue
        if ch == ";":
            statement = "".join(buf).strip()
            if statement:
                parts.append(statement)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    if quote is not None or block_comment:
        raise MigrationHistoryError("Unterminated quote or comment in migration SQL")
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    if not parts or any(part.upper().startswith("DELIMITER ") for part in parts):
        raise MigrationHistoryError("Migration must contain ordinary SQL statements only")
    return tuple(parts)


class MigrationRunner:
    def __init__(self, migrations_directory, *, include_test_only=False):
        self._directory = migrations_directory
        self._include_test_only = bool(include_test_only)

    def plan(self, connection_factory=None):
        """Inspect local files; optionally read tracking under the advisory lock."""
        migrations = discover_migrations(self._directory, include_test_only=self._include_test_only)
        if connection_factory is None:
            return tuple(MigrationPlanEntry(m.version, m.name, m.checksum)
                         for m in migrations)
        self._validate_target(connection_factory)
        connection = connection_factory.connect()
        locked = False
        try:
            connection.acquire_migration_lock(LOCK_NAME, 10)
            locked = True
            rows = self._load_tracking_details(connection)
            self._validate_apply_history(connection, migrations, rows)
            by_version = {migration.version: migration for migration in migrations}
            for version, row in rows.items():
                migration = by_version.get(version)
                if migration is None:
                    raise MigrationHistoryError("A tracked migration is missing from the selected source set")
                if row[2] != migration.checksum:
                    raise MigrationChecksumMismatch("A tracked migration checksum differs from its local file")
            entries = []
            for migration in migrations:
                row = rows.get(migration.version)
                if row is None:
                    status = "PENDING"
                else:
                    state = row[3]
                    if state == "retired_test":
                        if not migration.test_only:
                            raise MigrationRecoveryRequired("Only formally test-only migrations may be retired")
                        audit = self._latest_retirement_record(connection, migration.version)
                        self._validate_retired_test_record(migration, row, audit)
                        status = "RETIRED_TEST"
                    elif state == "retry_authorized":
                        audit = self._latest_recovery_record(connection, migration.version)
                        self._validate_recovery_record(migration, row, audit)
                        status = "RETRY_AUTHORIZED"
                    elif state in ("applied", "failed", "running"):
                        status = state.upper()
                    else:
                        raise MigrationRecoveryRequired("Unknown migration tracking state")
                entries.append(MigrationPlanEntry(migration.version, migration.name,
                                                  migration.checksum, status))
            return tuple(entries)
        finally:
            try:
                if locked:
                    connection.release_migration_lock()
            finally:
                connection.close()

    @staticmethod
    def _validate_target(connection_factory):
        environment = getattr(connection_factory, "environment", None)
        backend = getattr(connection_factory, "backend", None)
        if not ((environment == "nonprod" and backend == "mysql") or
                (environment == "test" and backend == "sqlite")):
            raise MigrationAuthorizationError(
                "Migration operations are restricted to explicit nonprod MySQL or isolated SQLite test targets"
            )

    def apply(self, connection_factory, *, confirmation=None, lock_timeout=10):
        if confirmation != APPLY_CONFIRMATION:
            raise MigrationAuthorizationError("Explicit migration confirmation is required")
        self._validate_target(connection_factory)
        migrations = discover_migrations(self._directory, include_test_only=self._include_test_only)
        if not migrations:
            return ApplyResult((), no_migrations=True)
        connection = connection_factory.connect()
        locked = False
        try:
            connection.acquire_migration_lock(LOCK_NAME, lock_timeout)
            locked = True
            self._ensure_tracking_table(connection)
            rows = self._load_tracking_details(connection)
            self._validate_apply_history(connection, migrations, rows)
            applied = []
            for migration in migrations:
                row = rows.get(migration.version)
                if row and row[3] in ("applied", "retired_test"):
                    continue
                if row and row[3] == "retry_authorized":
                    self._mark_retry_running(connection, migration)
                else:
                    self._mark_running(connection, migration)
                try:
                    connection.begin()
                    for statement in split_sql_statements(migration.sql):
                        cursor = connection.execute(statement)
                        try:
                            self._consume_cursor_results(cursor)
                        except Exception as execution_error:
                            try:
                                cursor.close()
                            except Exception as close_error:
                                raise execution_error from close_error
                            raise
                        cursor.close()
                    connection.commit()
                except Exception as exc:
                    try:
                        connection.rollback()
                    except Exception:
                        pass
                    try:
                        self._mark_failed(connection, migration, type(exc).__name__)
                    except Exception:
                        raise MigrationExecutionError(
                            "Migration " + migration.version + " failed and its tracking state could not be finalized"
                        ) from exc
                    raise MigrationExecutionError(
                        "Migration " + migration.version + " failed; manual review is required"
                    ) from None
                self._mark_applied(connection, migration)
                applied.append(migration.version)
            return ApplyResult(tuple(applied))
        finally:
            try:
                if locked:
                    connection.release_migration_lock()
            finally:
                connection.close()

    def _validate_apply_history(self, connection, migrations, rows):
        by_version = {migration.version: migration for migration in migrations}
        for version, row in rows.items():
            migration = by_version.get(version)
            if migration is None:
                raise MigrationHistoryError("A tracked migration is missing from the selected source set")
            if row[2] != migration.checksum:
                raise MigrationChecksumMismatch("A tracked migration checksum differs from its local file")
            state = row[3]
            if state == "applied":
                if row[5] is None or row[6] is not None:
                    raise MigrationHistoryError("An applied migration has inconsistent timestamps or error state")
            elif state == "failed":
                if row[5] is not None:
                    raise MigrationHistoryError("A failed migration cannot have an applied timestamp")
                raise MigrationRecoveryRequired("A failed migration blocks apply pending manual review")
            elif state == "running":
                raise MigrationRecoveryRequired("An in-progress migration blocks apply pending manual review")
            elif state == "retry_authorized":
                if row[5] is not None:
                    raise MigrationHistoryError("A retry-authorized migration cannot have an applied timestamp")
                audit = self._latest_recovery_record(connection, version)
                self._validate_recovery_record(migration, row, audit)
            elif state == "retired_test":
                if not self._include_test_only or not migration.test_only:
                    raise MigrationRecoveryRequired("Only an explicitly selected TEST-ONLY migration may be retired")
                if row[5] is not None:
                    raise MigrationHistoryError("A retired test migration cannot have an applied timestamp")
                audit = self._latest_retirement_record(connection, version)
                self._validate_retired_test_record(migration, row, audit)
            else:
                raise MigrationRecoveryRequired("Unknown migration tracking state")

        # A later tracked version cannot conceal an earlier local version missing
        # from tracking. A valid retired_test row is a classified fixture skip,
        # not an applied state; failed/running states already block above.
        pending_seen = False
        for migration in migrations:
            if migration.version not in rows:
                pending_seen = True
            elif pending_seen:
                raise MigrationRecoveryRequired(
                    "A later migration is tracked while an earlier local migration is pending"
                )
        for version, row in rows.items():
            if row[3] == "retry_authorized" and any(later > version for later in rows):
                raise MigrationRecoveryRequired(
                    "A later migration is tracked after a retry-authorized migration"
                )

    @staticmethod
    def _validate_recovery_record(migration, tracking_row, audit):
        if (not audit or audit[0] != migration.checksum or audit[1] != "failed"
                or audit[2] != "authorize_retry" or audit[3] != tracking_row[6]
                or not audit[4] or not audit[5] or not audit[6]):
            raise MigrationRecoveryRequired("A valid recovery audit record is required")

    def recover(self, connection_factory, *, version, actor, reason,
                confirmation=None, lock_timeout=10):
        """Authorize one explicit future retry; never execute the migration here."""
        if confirmation != APPLY_CONFIRMATION:
            raise MigrationAuthorizationError("Explicit migration confirmation is required")
        self._validate_target(connection_factory)
        if not isinstance(version, str) or not re.fullmatch(r"\d{14}", version):
            raise MigrationHistoryError("An exact 14-digit migration version is required")
        actor = self._audit_text(actor, "actor", 128)
        reason = self._audit_text(reason, "reason", 500)
        migrations = discover_migrations(self._directory, include_test_only=self._include_test_only)
        by_version = {migration.version: migration for migration in migrations}
        migration = by_version.get(version)
        if migration is None:
            raise MigrationHistoryError("The exact migration version must exist in the local migration directory")

        connection = connection_factory.connect()
        locked = False
        transaction_started = False
        try:
            connection.acquire_migration_lock(LOCK_NAME, lock_timeout)
            locked = True
            # Close the transaction opened by MySQL's connection-scoped lock/read path.
            connection.commit()
            rows = self._load_tracking(connection)
            target = self._read_tracking_row(connection, version)
            connection.commit()
            if target is None:
                raise MigrationHistoryError("The requested migration has no tracking row")
            if target[2] != migration.checksum:
                raise MigrationChecksumMismatch("The failed migration checksum differs from its local file")
            self._validate_recovery_order(migrations, rows, version)
            state = target[3]
            if state == "applied":
                raise MigrationRecoveryRequired("Applied migrations cannot be recovered")
            if state not in ("failed", "retry_authorized"):
                raise MigrationRecoveryRequired("Only a failed migration can be recovered")
            if state == "failed" and target[5] is not None:
                raise MigrationRecoveryRequired("A failed migration with an applied timestamp is inconsistent")

            # All preconditions, including the local checksum, pass before this idempotent DDL.
            self._ensure_recovery_audit_table(connection)
            connection.commit()
            connection.begin()
            transaction_started = True
            rows_now = self._load_tracking(connection, end_transaction=False)
            current = self._read_tracking_row(connection, version, end_transaction=False)
            if current is None or current[2] != migration.checksum:
                raise MigrationHistoryError("Migration tracking changed during recovery")
            self._validate_recovery_order(migrations, rows_now, version)
            audit = self._latest_recovery_record(connection, version, end_transaction=False)
            if current[3] == "retry_authorized":
                if (audit and audit[0] == migration.checksum and audit[2] == "authorize_retry"
                        and audit[5] == actor and audit[6] == reason):
                    connection.commit()
                    transaction_started = False
                    return RecoveryResult(version, "retry_authorized", True)
                raise MigrationRecoveryRequired("Recovery was already authorized with different audit details")
            if current[3] != "failed":
                raise MigrationRecoveryRequired("Migration state changed and is no longer failed")
            if audit and audit[2] != "authorize_retry":
                raise MigrationRecoveryRequired("Unexpected recovery audit history")
            p = connection.placeholder
            cursor = connection.execute(
                "INSERT INTO " + RECOVERY_AUDIT_TABLE + " "
                "(migration_version, migration_checksum, previous_status, action, original_error_code, "
                "recovered_at_utc, recovered_by, reason) VALUES (" + ",".join([p] * 8) + ")",
                (version, migration.checksum, "failed", "authorize_retry", current[6],
                 _utc_now(), actor, reason),
            )
            cursor.close()
            cursor = connection.execute(
                "UPDATE " + TRACKING_TABLE + " SET status=" + p + " WHERE migration_version=" + p +
                " AND status=" + p + " AND checksum=" + p,
                ("retry_authorized", version, "failed", migration.checksum),
            )
            changed = cursor.rowcount
            cursor.close()
            if changed != 1:
                raise MigrationRecoveryRequired("Failed migration state changed during recovery")
            connection.commit()
            transaction_started = False
            return RecoveryResult(version, "retry_authorized", False)
        except Exception:
            if transaction_started:
                try:
                    connection.rollback()
                except Exception:
                    pass
            raise
        finally:
            try:
                if locked:
                    connection.release_migration_lock()
            finally:
                connection.close()

    def retire_test(self, connection_factory, *, version, actor, reason,
                    confirmation=None, lock_timeout=10):
        """Append an administrative retirement record for one failed test-only migration."""
        if confirmation != APPLY_CONFIRMATION:
            raise MigrationAuthorizationError("Explicit migration confirmation is required")
        self._validate_target(connection_factory)
        if not isinstance(version, str) or not re.fullmatch(r"\d{14}", version):
            raise MigrationHistoryError("An exact 14-digit migration version is required")
        actor = self._audit_text(actor, "actor", 128)
        reason = self._audit_text(reason, "reason", 500)
        migrations = discover_migrations(self._directory, include_test_only=self._include_test_only)
        migration = next((m for m in migrations if m.version == version), None)
        if migration is None:
            raise MigrationHistoryError("The exact migration version must exist in the local migration directory")
        if not migration.test_only:
            raise MigrationAuthorizationError("Only explicitly marked test-only migrations may be retired")

        connection = connection_factory.connect()
        locked = False
        transaction_started = False
        try:
            connection.acquire_migration_lock(LOCK_NAME, lock_timeout)
            locked = True
            connection.commit()
            rows = self._load_tracking(connection)
            target = self._read_tracking_row(connection, version)
            connection.commit()
            if target is None:
                raise MigrationHistoryError("The requested migration has no tracking row")
            if target[2] != migration.checksum:
                raise MigrationChecksumMismatch("The failed migration checksum differs from its local file")
            self._validate_recovery_order(migrations, rows, version)

            if target[3] == "retired_test":
                audit = self._latest_retirement_record(connection, version)
                self._validate_retired_test_record(migration, target, audit)
                if audit[5] == actor and audit[6] == reason:
                    return RetirementResult(version, "retired_test", True)
                raise MigrationRecoveryRequired("Migration was already retired with different audit details")
            if target[3] != "failed":
                raise MigrationRecoveryRequired("Only a failed test-only migration may be retired")
            if target[5] is not None:
                raise MigrationRecoveryRequired("A failed migration with an applied timestamp is inconsistent")
            if any(tracked_version > version for tracked_version in rows):
                raise MigrationRecoveryRequired("A later migration is already tracked; retirement order is invalid")

            # DDL is isolated to an append-only audit table and follows all read-only checks.
            self._ensure_retirement_audit_table(connection)
            connection.commit()
            connection.begin()
            transaction_started = True
            rows_now = self._load_tracking(connection, end_transaction=False)
            current = self._read_tracking_row(connection, version, end_transaction=False)
            if current is None or current[2] != migration.checksum:
                raise MigrationHistoryError("Migration tracking changed during retirement")
            self._validate_recovery_order(migrations, rows_now, version)
            if current[3] != "failed" or current[5] is not None:
                raise MigrationRecoveryRequired("Migration state changed and is no longer eligible for retirement")
            previous_audit = self._latest_retirement_record(connection, version, end_transaction=False)
            if previous_audit is not None:
                raise MigrationRecoveryRequired("A retirement record already exists for this migration")

            p = connection.placeholder
            cursor = connection.execute(
                "INSERT INTO " + RETIREMENT_AUDIT_TABLE + " "
                "(migration_version, migration_checksum, previous_status, action, original_error_code, "
                "retired_at_utc, retired_by, reason) VALUES (" + ",".join([p] * 8) + ")",
                (version, migration.checksum, "failed", "retire_test", current[6],
                 _utc_now(), actor, reason),
            )
            cursor.close()
            update_sql = (
                "UPDATE " + TRACKING_TABLE + " SET status=" + p + " WHERE migration_version=" + p +
                " AND status=" + p + " AND checksum=" + p + " AND applied_at_utc IS NULL"
            )
            update_params = ["retired_test", version, "failed", migration.checksum]
            if current[6] is None:
                update_sql += " AND error_code IS NULL"
            else:
                update_sql += " AND error_code=" + p
                update_params.append(current[6])
            cursor = connection.execute(update_sql, tuple(update_params))
            changed = cursor.rowcount
            cursor.close()
            if changed != 1:
                raise MigrationRecoveryRequired("Failed migration tracking changed during retirement")
            connection.commit()
            transaction_started = False
            return RetirementResult(version, "retired_test", False)
        except Exception:
            if transaction_started:
                try:
                    connection.rollback()
                except Exception:
                    pass
            raise
        finally:
            try:
                if locked:
                    connection.release_migration_lock()
            finally:
                connection.close()

    @staticmethod
    def _validate_retired_test_record(migration, tracking_row, audit):
        if not migration.test_only:
            raise MigrationRecoveryRequired("Retired status is valid only for a test-only migration")
        if tracking_row is None or tracking_row[3] != "retired_test":
            raise MigrationRecoveryRequired("Retired test tracking row is unavailable or inconsistent")
        if tracking_row[2] != migration.checksum:
            raise MigrationChecksumMismatch("Retired test migration checksum differs from its source")
        if tracking_row[5] is not None:
            raise MigrationRecoveryRequired("A retired test migration cannot have an applied timestamp")
        if (not audit or audit[0] != migration.checksum or audit[1] != "failed"
                or audit[2] != "retire_test" or audit[3] != tracking_row[6]
                or not audit[4] or not audit[5] or not audit[6]):
            raise MigrationRecoveryRequired("A valid retirement audit record is required")

    @staticmethod
    def _audit_text(value, label, limit):
        if not isinstance(value, str):
            raise MigrationAuthorizationError("Recovery " + label + " is required")
        value = value.strip()
        if not value or len(value) > limit or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            raise MigrationAuthorizationError("Recovery " + label + " is empty or outside its allowed format")
        return value

    @staticmethod
    def _validate_recovery_order(migrations, rows, target_version):
        by_version = {m.version: m for m in migrations}
        for migration in migrations:
            if migration.version >= target_version:
                break
            row = rows.get(migration.version)
            if row is None or row[0] != "applied":
                raise MigrationRecoveryRequired("An earlier migration is pending or incomplete")
            if row[1] != migration.checksum:
                raise MigrationChecksumMismatch("An earlier migration checksum has changed")
        for version, row in rows.items():
            if version < target_version:
                if version not in by_version:
                    raise MigrationHistoryError("An earlier tracked migration is missing from the source tree")
                if row[0] != "applied":
                    raise MigrationRecoveryRequired("An earlier migration is pending or incomplete")
            elif version > target_version:
                raise MigrationRecoveryRequired("A later tracked migration makes recovery order inconsistent")

    @staticmethod
    def _consume_cursor_results(cursor):
        """Drain row-producing statements before closing their DB-API cursor."""
        has_rows = bool(getattr(cursor, "with_rows", False))
        if not has_rows:
            has_rows = getattr(cursor, "description", None) is not None
        if has_rows:
            while cursor.fetchmany(1000):
                pass

    def _ensure_tracking_table(self, connection):
        suffix = " ENGINE=InnoDB" if connection.backend == "mysql" else ""
        sql = (
            "CREATE TABLE IF NOT EXISTS " + TRACKING_TABLE + " ("
            "migration_version VARCHAR(14) NOT NULL PRIMARY KEY, "
            "migration_name VARCHAR(255) NOT NULL, "
            "checksum CHAR(64) NOT NULL, "
            "status VARCHAR(16) NOT NULL, "
            "started_at_utc VARCHAR(40) NOT NULL, "
            "applied_at_utc VARCHAR(40), "
            "error_code VARCHAR(128)"
            ")" + suffix
        )
        cursor = connection.execute(sql)
        cursor.close()
        connection.commit()

    def _ensure_recovery_audit_table(self, connection):
        if connection.backend == "mysql":
            identifier = "BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY"
            suffix = " ENGINE=InnoDB"
        else:
            identifier = "INTEGER PRIMARY KEY AUTOINCREMENT"
            suffix = ""
        sql = (
            "CREATE TABLE IF NOT EXISTS " + RECOVERY_AUDIT_TABLE + " ("
            "recovery_id " + identifier + ", "
            "migration_version VARCHAR(14) NOT NULL, "
            "migration_checksum CHAR(64) NOT NULL, "
            "previous_status VARCHAR(16) NOT NULL, "
            "action VARCHAR(32) NOT NULL, "
            "original_error_code VARCHAR(128), "
            "recovered_at_utc VARCHAR(40) NOT NULL, "
            "recovered_by VARCHAR(128) NOT NULL, "
            "reason VARCHAR(500) NOT NULL"
            ")" + suffix
        )
        cursor = connection.execute(sql)
        cursor.close()
        # MySQL DDL implicitly commits; ensure no transaction is carried into DML.
        connection.commit()

    def _ensure_retirement_audit_table(self, connection):
        if connection.backend == "mysql":
            identifier = "BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY"
            suffix = " ENGINE=InnoDB"
        else:
            identifier = "INTEGER PRIMARY KEY AUTOINCREMENT"
            suffix = ""
        sql = (
            "CREATE TABLE IF NOT EXISTS " + RETIREMENT_AUDIT_TABLE + " ("
            "retirement_id " + identifier + ", "
            "migration_version VARCHAR(14) NOT NULL, "
            "migration_checksum CHAR(64) NOT NULL, "
            "previous_status VARCHAR(16) NOT NULL, "
            "action VARCHAR(32) NOT NULL, "
            "original_error_code VARCHAR(128), "
            "retired_at_utc VARCHAR(40) NOT NULL, "
            "retired_by VARCHAR(128) NOT NULL, "
            "reason VARCHAR(500) NOT NULL, "
            "UNIQUE (migration_version, action)"
            ")" + suffix
        )
        cursor = connection.execute(sql)
        cursor.close()
        connection.commit()

    def _latest_retirement_record(self, connection, version, *, end_transaction=True):
        p = connection.placeholder
        sql = (
            "SELECT migration_checksum, previous_status, action, original_error_code, retired_at_utc, "
            "retired_by, reason FROM " + RETIREMENT_AUDIT_TABLE + " WHERE migration_version=" + p +
            " ORDER BY retirement_id DESC LIMIT 1"
        )
        try:
            cursor = connection.execute(sql, (version,))
        except Exception:
            raise MigrationHistoryError("The test-retirement audit record is unavailable") from None
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
        if end_transaction:
            connection.commit()
        return tuple(row) if row is not None else None

    def _load_tracking_details(self, connection, *, end_transaction=True):
        cursor = connection.execute(
            "SELECT migration_version, migration_name, checksum, status, started_at_utc, "
            "applied_at_utc, error_code FROM " + TRACKING_TABLE
        )
        try:
            rows = cursor.fetchall()
        finally:
            cursor.close()
        if end_transaction:
            connection.commit()
        return {str(row[0]): tuple(row) for row in rows}

    def _load_tracking(self, connection, *, end_transaction=True):
        cursor = connection.execute(
            "SELECT migration_version, status, checksum FROM " + TRACKING_TABLE
        )
        try:
            rows = cursor.fetchall()
        finally:
            cursor.close()
        if end_transaction:
            connection.commit()
        return {str(row[0]): (str(row[1]), str(row[2])) for row in rows}

    def _read_tracking_row(self, connection, version, *, end_transaction=True):
        p = connection.placeholder
        cursor = connection.execute(
            "SELECT migration_version, migration_name, checksum, status, started_at_utc, applied_at_utc, error_code "
            "FROM " + TRACKING_TABLE + " WHERE migration_version=" + p,
            (version,),
        )
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
        if end_transaction:
            connection.commit()
        return tuple(row) if row is not None else None

    def _latest_recovery_record(self, connection, version, *, end_transaction=True):
        p = connection.placeholder
        sql = (
            "SELECT migration_checksum, previous_status, action, original_error_code, recovered_at_utc, "
            "recovered_by, reason FROM " + RECOVERY_AUDIT_TABLE + " WHERE migration_version=" + p +
            " ORDER BY recovery_id DESC LIMIT 1"
        )
        try:
            cursor = connection.execute(sql, (version,))
        except Exception:
            raise MigrationHistoryError("The migration recovery audit record is unavailable") from None
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
        if end_transaction:
            connection.commit()
        return tuple(row) if row is not None else None

    def _mark_running(self, connection, migration):
        p = connection.placeholder
        connection.begin()
        cursor = connection.execute(
            "INSERT INTO " + TRACKING_TABLE + " "
            "(migration_version, migration_name, checksum, status, started_at_utc, applied_at_utc, error_code) "
            "VALUES (" + ",".join([p] * 7) + ")",
            (migration.version, migration.name, migration.checksum, "running", _utc_now(), None, None),
        )
        cursor.close()
        connection.commit()

    def _mark_retry_running(self, connection, migration):
        p = connection.placeholder
        connection.begin()
        cursor = connection.execute(
            "UPDATE " + TRACKING_TABLE + " SET status=" + p +
            " WHERE migration_version=" + p + " AND status=" + p + " AND checksum=" + p,
            ("running", migration.version, "retry_authorized", migration.checksum),
        )
        changed = cursor.rowcount
        cursor.close()
        if changed != 1:
            connection.rollback()
            raise MigrationRecoveryRequired("Recovery authorization is no longer valid")
        connection.commit()

    def _mark_failed(self, connection, migration, error_code):
        p = connection.placeholder
        connection.begin()
        cursor = connection.execute(
            "UPDATE " + TRACKING_TABLE + " SET status=" + p + ", error_code=" + p +
            " WHERE migration_version=" + p + " AND status=" + p + " AND checksum=" + p +
            " AND applied_at_utc IS NULL",
            ("failed", error_code[:128], migration.version, "running", migration.checksum),
        )
        changed = cursor.rowcount
        cursor.close()
        if changed != 1:
            connection.rollback()
            raise MigrationHistoryError("Running migration tracking changed before failure finalization")
        connection.commit()

    def _mark_applied(self, connection, migration):
        p = connection.placeholder
        connection.begin()
        cursor = connection.execute(
            "UPDATE " + TRACKING_TABLE + " SET status=" + p + ", applied_at_utc=" + p +
            ", error_code=NULL WHERE migration_version=" + p + " AND status=" + p +
            " AND checksum=" + p + " AND applied_at_utc IS NULL",
            ("applied", _utc_now(), migration.version, "running", migration.checksum),
        )
        changed = cursor.rowcount
        cursor.close()
        if changed != 1:
            connection.rollback()
            raise MigrationHistoryError("Running migration tracking changed before apply finalization")
        connection.commit()
