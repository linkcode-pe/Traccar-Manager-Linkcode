"""Isolated SQLite tests for Manager persistence and migration infrastructure."""
import contextlib
import hashlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from manager.config import DatabaseSettings
from manager.errors import (
    ConfigurationError, ConnectionUnavailable, MigrationAuthorizationError,
    MigrationChecksumMismatch, MigrationDiscoveryError, MigrationExecutionError,
    MigrationHistoryError, MigrationLockUnavailable, MigrationRecoveryRequired,
)
from manager.migrations.discovery import discover_migrations
from manager.migrations.runner import APPLY_CONFIRMATION, MigrationRunner
from manager.persistence.connection import DatabaseConnection, MySQLConnectionFactory, SQLiteConnectionFactory
from mysql.connector.errors import InternalError, ProgrammingError
from manager.persistence.unit_of_work import UnitOfWork
from runner import migrate as migration_cli

V1 = "20261003000100"
V2 = "20261003000200"
V3 = "20261003000300"
V3_CHECKSUM = "529763174d46d3203402b037635cdb1d55b1792e80d953517e31e12caead5379"

def write_test_only_migration(directory, version, name, sql):
    sql_bytes = sql.encode("utf-8")
    checksum = hashlib.sha256(sql_bytes).hexdigest()
    marker = ("-- manager:migration=test-only version=" + version + " checksum=" + checksum + "\n").encode("ascii")
    path = Path(directory) / ("V" + version + "__" + name + ".sql")
    path.write_bytes(marker + sql_bytes)
    return path, checksum

class _FakeMySQLCursor:
    def __init__(self, raw):
        self.raw = raw; self.rows = []; self.rowcount = -1; self.with_rows = False; self.is_select_one = False
    def _set_rows(self, rows, *, with_rows=True):
        self.rows = list(rows); self.with_rows = with_rows
    def execute(self, sql, params=()):
        statement = " ".join(sql.split()).upper(); self.rowcount = -1; self.with_rows = False; self.is_select_one = False
        if statement.startswith("SELECT GET_LOCK("):
            self.raw.lock_held = True; self.raw.lock_acquisitions += 1; self.raw.in_transaction = True; self._set_rows([(1,)])
        elif statement.startswith("SELECT RELEASE_LOCK("):
            was_held = self.raw.lock_held; self.raw.lock_held = False; self.raw.lock_releases += 1; self.raw.in_transaction = True; self._set_rows([(1 if was_held else None,)])
        elif statement.startswith("CREATE TABLE IF NOT EXISTS MANAGER_SCHEMA_MIGRATIONS"):
            self.raw.tracking_exists = True; self.raw.ddl_calls += 1; self.raw.in_transaction = False; self._set_rows([], with_rows=False)
        elif statement.startswith("CREATE TABLE IF NOT EXISTS MANAGER_SCHEMA_MIGRATION_RECOVERY_AUDIT"):
            self.raw.audit_exists = True; self.raw.ddl_calls += 1; self.raw.in_transaction = False; self._set_rows([], with_rows=False)
        elif statement.startswith("CREATE TABLE IF NOT EXISTS MANAGER_SCHEMA_MIGRATION_RETIREMENT_AUDIT"):
            self.raw.retirement_exists = True; self.raw.ddl_calls += 1; self.raw.in_transaction = False; self._set_rows([], with_rows=False)
        elif "CREATE TABLE MANAGER_SUCCESSFUL_APPLY_VALIDATION_PROBE" in statement:
            self.raw.success_probe_exists = True; self.raw.success_probe_ddl_calls += 1; self.raw.ddl_calls += 1; self.raw.in_transaction = False; self._set_rows([], with_rows=False)
        elif statement.startswith("SELECT MIGRATION_VERSION, MIGRATION_NAME, CHECKSUM, STATUS, STARTED_AT_UTC, APPLIED_AT_UTC, ERROR_CODE FROM MANAGER_SCHEMA_MIGRATIONS WHERE"):
            self.raw.in_transaction = True; self._set_rows([row for row in self.raw.tracking_rows if row[0] == params[0]])
        elif statement.startswith("SELECT MIGRATION_VERSION, MIGRATION_NAME, CHECKSUM, STATUS, STARTED_AT_UTC, APPLIED_AT_UTC, ERROR_CODE FROM MANAGER_SCHEMA_MIGRATIONS"):
            self.raw.in_transaction = True; self._set_rows(list(self.raw.tracking_rows))
        elif statement.startswith("SELECT MIGRATION_VERSION, STATUS, CHECKSUM FROM MANAGER_SCHEMA_MIGRATIONS"):
            self.raw.in_transaction = True; self._set_rows([(row[0], row[3], row[2]) for row in self.raw.tracking_rows])
        elif statement.startswith("SELECT MIGRATION_CHECKSUM, PREVIOUS_STATUS, ACTION, ORIGINAL_ERROR_CODE, RECOVERED_AT_UTC, RECOVERED_BY, REASON FROM MANAGER_SCHEMA_MIGRATION_RECOVERY_AUDIT"):
            if not self.raw.audit_exists: raise AssertionError("recovery audit table has not been created")
            self.raw.in_transaction = True; found=[row for row in self.raw.audit_rows if row[0]==params[0]];self._set_rows([found[-1][1:8]] if found else [])
        elif statement.startswith("SELECT MIGRATION_CHECKSUM, PREVIOUS_STATUS, ACTION, ORIGINAL_ERROR_CODE, RETIRED_AT_UTC, RETIRED_BY, REASON FROM MANAGER_SCHEMA_MIGRATION_RETIREMENT_AUDIT"):
            if not self.raw.retirement_exists: raise AssertionError("retirement audit table has not been created")
            self.raw.in_transaction = True; found=[row for row in self.raw.retirement_rows if row[0]==params[0]];self._set_rows([found[-1][1:8]] if found else [])
        elif statement.startswith("INSERT INTO MANAGER_SCHEMA_MIGRATION_RETIREMENT_AUDIT"):
            if not self.raw.in_transaction: raise AssertionError("retirement audit insert must be transactional")
            self.raw.retirement_rows.append(tuple(params));self.rowcount=1;self._set_rows([],with_rows=False)
        elif statement.startswith("INSERT INTO MANAGER_SCHEMA_MIGRATION_RECOVERY_AUDIT"):
            if not self.raw.in_transaction: raise AssertionError("recovery audit insert must be transactional")
            self.raw.audit_rows.append(tuple(params));self.rowcount=1;self._set_rows([],with_rows=False)
        elif statement.startswith("INSERT INTO MANAGER_SCHEMA_MIGRATIONS"):
            if not self.raw.in_transaction: raise AssertionError("running insert must be inside its transaction")
            self.raw.tracking_rows.append(tuple(params));self.rowcount=1;self._set_rows([],with_rows=False)
        elif statement.startswith("UPDATE MANAGER_SCHEMA_MIGRATIONS SET STATUS="):
            if params and params[0] == "retired_test":
                status,version,expected_status,checksum,*expected_error=params
                for i,old in enumerate(self.raw.tracking_rows):
                    if old[0]==version and old[3]==expected_status and old[2]==checksum and old[5] is None and ((expected_error and old[6]==expected_error[0]) or (not expected_error and old[6] is None)):
                        u=list(old);u[3]=status;self.raw.tracking_rows[i]=tuple(u);self.rowcount=1
            elif "APPLIED_AT_UTC=" in statement:
                status, applied_at, version, expected_status, checksum = params
                for i,old in enumerate(self.raw.tracking_rows):
                    if old[0]==version and old[3]==expected_status and old[2]==checksum and old[5] is None:
                        u=list(old);u[3]=status;u[5]=applied_at;u[6]=None;self.raw.tracking_rows[i]=tuple(u);self.rowcount=1
            elif "ERROR_CODE=" in statement:
                status,error,version,expected_status,checksum=params
                for i,old in enumerate(self.raw.tracking_rows):
                    if old[0]==version and old[3]==expected_status and old[2]==checksum and old[5] is None:
                        u=list(old);u[3]=status;u[6]=error;self.raw.tracking_rows[i]=tuple(u);self.rowcount=1
            else:
                status,version,expected_status,checksum=params
                for i,old in enumerate(self.raw.tracking_rows):
                    if old[0]==version and old[3]==expected_status and old[2]==checksum:u=list(old);u[3]=status;self.raw.tracking_rows[i]=tuple(u);self.rowcount=1
            self._set_rows([],with_rows=False)
        elif statement == "SELECT 1":
            self.raw.in_transaction=True;self.is_select_one=True;self._set_rows([(1,)])
        else: raise AssertionError("Unexpected fake-MySQL SQL: " + statement)
    def fetchall(self):
        result=list(self.rows);self.rows=[];return result
    def fetchone(self):
        if not self.rows:return None
        return self.rows.pop(0)
    def fetchmany(self,size=1):
        self.raw.fetchmany_calls+=1;result=self.rows[:size];self.rows=self.rows[size:]
        if self.is_select_one:self.raw.select_one_rows_consumed+=len(result)
        return result
    def close(self):
        if self.with_rows and self.rows:raise InternalError("Unread result found")

class _FakeMySQLRaw:
    def __init__(self):
        self.in_transaction=False;self.tracking_exists=False;self.tracking_rows=[];self.audit_exists=False;self.audit_rows=[];self.ddl_calls=0;self.success_probe_exists=False;self.success_probe_ddl_calls=0;self.retirement_exists=False;self.retirement_rows=[]
        self.lock_held=False;self.lock_acquisitions=0;self.lock_releases=0;self.begin_calls=0;self.commits=0;self.closed=False
        self.fetchmany_calls=0;self.select_one_rows_consumed=0
    def cursor(self):return _FakeMySQLCursor(self)
    def start_transaction(self):
        self.begin_calls+=1
        if self.in_transaction:raise ProgrammingError("Transaction already in progress")
        self.in_transaction=True
    def commit(self):self.commits+=1;self.in_transaction=False
    def rollback(self):self.in_transaction=False
    def close(self):self.closed=True;self.in_transaction=False
class _FakeMySQLFactory:
    backend = "mysql"
    environment = "nonprod"

    def __init__(self, raw):
        self.raw = raw

    def connect(self):
        return DatabaseConnection(self.raw, "mysql")

def write_migration(directory, version, name, sql):
    path = Path(directory) / ("V" + version + "__" + name + ".sql")
    path.write_text(sql, encoding="utf-8")
    return path

class PersistenceMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tm-manager-test-")
        self.root = Path(self.temp.name)
        self.migrations = self.root / "migrations"
        self.migrations.mkdir()
        self.db_path = self.root / "manager-test.sqlite3"
        self.factory = SQLiteConnectionFactory(str(self.db_path))

    def tearDown(self):
        self.temp.cleanup()

    def apply(self, runner, factory=None):
        return runner.apply(factory or self.factory, confirmation=APPLY_CONFIRMATION)

    def test_mysql_tracking_read_closes_implicit_transaction_before_begin(self):
        runner = MigrationRunner(self.migrations)

        # Reproduce the pre-fix driver state: SELECT under autocommit=False
        # leaves a transaction active, so start_transaction raises.
        old_raw = _FakeMySQLRaw()
        old_connection = DatabaseConnection(old_raw, "mysql")
        cursor = old_connection.execute(
            "SELECT migration_version, status, checksum FROM manager_schema_migrations"
        )
        cursor.fetchall(); cursor.close()
        self.assertTrue(old_raw.in_transaction)
        with self.assertRaisesRegex(ProgrammingError, "Transaction already in progress"):
            old_connection.begin()
        old_connection.close()

        # The Runner's tracking read now closes that read-only transaction.
        raw = _FakeMySQLRaw()
        connection = DatabaseConnection(raw, "mysql")
        self.assertEqual({}, runner._load_tracking(connection))
        self.assertFalse(raw.in_transaction)
        connection.begin()
        self.assertTrue(raw.in_transaction)
        connection.close()

    def test_mysql_apply_starts_running_and_preserves_tracking_checksum_and_lock(self):
        migration_path = write_migration(self.migrations, V1, "mysql_stub", "SELECT 1;")
        expected_checksum = hashlib.sha256(migration_path.read_bytes()).hexdigest()
        raw = _FakeMySQLRaw()
        result = MigrationRunner(self.migrations).apply(
            _FakeMySQLFactory(raw), confirmation=APPLY_CONFIRMATION
        )
        self.assertEqual((V1,), result.applied_versions)
        self.assertEqual(1, len(raw.tracking_rows))
        self.assertEqual(V1, raw.tracking_rows[0][0])
        self.assertEqual(expected_checksum, raw.tracking_rows[0][2])
        self.assertEqual("applied", raw.tracking_rows[0][3])
        self.assertEqual(3, raw.begin_calls)
        self.assertEqual(1, raw.lock_acquisitions)
        self.assertEqual(1, raw.lock_releases)
        self.assertFalse(raw.lock_held)
        self.assertTrue(raw.closed)
        self.assertFalse(raw.in_transaction)
        self.assertEqual(1, raw.select_one_rows_consumed)

    def test_discovery_sorts_versions_and_checksums(self):
        second = write_migration(self.migrations, V2, "create_second", "CREATE TABLE second(id INTEGER);")
        first = write_migration(self.migrations, V1, "create_first", "CREATE TABLE first(id INTEGER);")
        found = discover_migrations(self.migrations)
        self.assertEqual([V1, V2], [m.version for m in found])
        self.assertEqual(hashlib.sha256(first.read_bytes()).hexdigest(), found[0].checksum)
        self.assertEqual(hashlib.sha256(second.read_bytes()).hexdigest(), found[1].checksum)

    def test_duplicate_version_is_rejected(self):
        write_migration(self.migrations, V1, "first", "SELECT 1;")
        write_migration(self.migrations, V1, "second", "SELECT 2;")
        with self.assertRaises(MigrationDiscoveryError):
            discover_migrations(self.migrations)

    def test_invalid_version_is_rejected(self):
        (self.migrations / "V20260231010101__bad_date.sql").write_text("SELECT 1;", encoding="utf-8")
        with self.assertRaises(MigrationDiscoveryError):
            discover_migrations(self.migrations)

    def test_plan_is_file_only_and_does_not_connect(self):
        write_migration(self.migrations, V1, "create_sample", "CREATE TABLE sample(id INTEGER);")
        plan = MigrationRunner(self.migrations).plan()
        self.assertEqual([V1], [item.version for item in plan])
        self.assertFalse(self.db_path.exists())

    def test_apply_requires_library_confirmation_before_connect(self):
        write_migration(self.migrations, V1, "create_sample", "CREATE TABLE sample(id INTEGER);")
        with self.assertRaises(MigrationAuthorizationError):
            MigrationRunner(self.migrations).apply(self.factory)
        self.assertFalse(self.db_path.exists())

    def test_apply_rejects_unmarked_or_wrong_backend_before_connect(self):
        write_migration(self.migrations, V1, "create_sample", "CREATE TABLE sample(id INTEGER);")
        class WrongTarget:
            environment = "production"
            backend = "mysql"
            def connect(self):
                raise AssertionError("connection must not be attempted")
        with self.assertRaises(MigrationAuthorizationError):
            MigrationRunner(self.migrations).apply(WrongTarget(), confirmation=APPLY_CONFIRMATION)
        self.assertFalse(self.db_path.exists())

    def test_apply_tracks_migration_and_second_apply_is_noop(self):
        write_migration(self.migrations, V1, "create_sample", "CREATE TABLE sample(id INTEGER);")
        runner = MigrationRunner(self.migrations)
        first = self.apply(runner)
        connection = self.factory.connect()
        try:
            cursor = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='sample'")
            schema_before = cursor.fetchone()[0]; cursor.close()
        finally:
            connection.close()
        second = self.apply(runner)
        self.assertEqual((V1,), first.applied_versions)
        self.assertEqual((), second.applied_versions)
        connection = self.factory.connect()
        try:
            cursor = connection.execute("SELECT migration_version, status FROM manager_schema_migrations")
            self.assertEqual((V1, "applied"), tuple(cursor.fetchone())); cursor.close()
            cursor = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='sample'")
            self.assertEqual(schema_before, cursor.fetchone()[0]); cursor.close()
        finally:
            connection.close()

    def test_actual_nonprod_probe_migration_is_idempotent_on_sqlite_fixture(self):
        project_migrations = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "migrations_test_only"
        migrations = discover_migrations(project_migrations, include_test_only=True)
        self.assertEqual([V1, V2, V3], [m.version for m in migrations])
        self.assertIn("validation_infrastructure_probe", migrations[0].name)
        self.assertEqual("controlled_runner_failure_test", migrations[1].name)
        self.assertEqual("9af4bd3bc65234eaa817e808833c953ffdb2fa5ceda89f0071c5f3a0b3dcba5a", migrations[1].checksum)
        self.assertEqual(V3, migrations[2].version)
        self.assertEqual("successful_apply_validation_probe", migrations[2].name)
        self.assertEqual(V3_CHECKSUM, migrations[2].checksum)
        self.assertNotIn("manager_failure_probe_missing_20261003000200", migrations[2].sql)
        self.assertTrue(all(m.test_only for m in migrations))
        self.assertEqual("-- Controlled isolated failure; read-only statements only.\nSELECT 1;\nSELECT * FROM manager_failure_probe_missing_20261003000200;\n", migrations[1].sql)
        # Apply only the base probe here; discover and verify the separate failure-test migration above.
        probe_migrations = self.root / "probe-only-migrations"
        probe_migrations.mkdir()
        (probe_migrations / migrations[0].path.name).write_bytes(migrations[0].path.read_bytes())
        runner = MigrationRunner(probe_migrations, include_test_only=True)
        first = self.apply(runner)
        second = self.apply(runner)
        self.assertEqual((V1,), first.applied_versions)
        self.assertEqual((), second.applied_versions)
        connection = self.factory.connect()
        try:
            cursor = connection.execute("SELECT checksum, status FROM manager_schema_migrations WHERE migration_version=?", (V1,))
            self.assertEqual((migrations[0].checksum, "applied"), tuple(cursor.fetchone())); cursor.close()
            cursor = connection.execute("SELECT COUNT(*) FROM manager_persistence_validation_probe")
            self.assertEqual(0, cursor.fetchone()[0]); cursor.close()
        finally:
            connection.close()


    def test_successful_apply_validation_probe_sqlite_effect_and_idempotence(self):
        source = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "migrations_test_only" / "V20261003000300__successful_apply_validation_probe.sql"
        checksum = next(m.checksum for m in discover_migrations(source.parent, include_test_only=True) if m.version == V3)
        self.assertEqual(V3_CHECKSUM, checksum)
        isolated = self.root / "successful-apply-sqlite"
        isolated.mkdir()
        path = isolated / source.name
        path.write_bytes(source.read_bytes())
        checksum = discover_migrations(isolated, include_test_only=True)[0].checksum
        runner = MigrationRunner(isolated, include_test_only=True)
        first = self.apply(runner)
        second = self.apply(runner)
        self.assertEqual((V3,), first.applied_versions)
        self.assertEqual((), second.applied_versions)
        connection = self.factory.connect()
        try:
            cursor = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", ("manager_successful_apply_validation_probe",))
            self.assertEqual(("manager_successful_apply_validation_probe",), tuple(cursor.fetchone())); cursor.close()
            cursor = connection.execute("SELECT COUNT(*) FROM manager_successful_apply_validation_probe")
            self.assertEqual(0, cursor.fetchone()[0]); cursor.close()
            cursor = connection.execute("SELECT checksum,status,applied_at_utc,error_code FROM manager_schema_migrations WHERE migration_version=?", (V3,))
            row = tuple(cursor.fetchone()); cursor.close()
            self.assertEqual((checksum, "applied"), row[:2]); self.assertTrue(row[2]); self.assertIsNone(row[3])
        finally:
            connection.close()

    def test_successful_apply_validation_probe_fake_mysql_effect_and_idempotence(self):
        source = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "migrations_test_only" / "V20261003000300__successful_apply_validation_probe.sql"
        isolated = self.root / "successful-apply-mysql-fixture"
        isolated.mkdir()
        (isolated / source.name).write_bytes(source.read_bytes())
        raw = _FakeMySQLRaw()
        runner = MigrationRunner(isolated, include_test_only=True)
        first = runner.apply(_FakeMySQLFactory(raw), confirmation=APPLY_CONFIRMATION)
        second = runner.apply(_FakeMySQLFactory(raw), confirmation=APPLY_CONFIRMATION)
        self.assertEqual((V3,), first.applied_versions)
        self.assertEqual((), second.applied_versions)
        self.assertTrue(raw.success_probe_exists)
        self.assertEqual(1, raw.success_probe_ddl_calls)
        self.assertEqual(1, raw.select_one_rows_consumed)
        row = next(row for row in raw.tracking_rows if row[0] == V3)
        self.assertEqual(V3_CHECKSUM, row[2]); self.assertEqual("applied", row[3])
        self.assertTrue(row[5]); self.assertIsNone(row[6])
        self.assertFalse(raw.lock_held); self.assertFalse(raw.in_transaction)

    def test_successful_apply_validation_probe_checksum_change_fails_closed(self):
        source = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "migrations_test_only" / "V20261003000300__successful_apply_validation_probe.sql"
        isolated = self.root / "successful-apply-checksum"
        isolated.mkdir()
        path = isolated / source.name
        path.write_bytes(source.read_bytes())
        runner = MigrationRunner(isolated, include_test_only=True)
        self.assertEqual((V3,), self.apply(runner).applied_versions)
        write_test_only_migration(isolated, V3, "successful_apply_validation_probe", "CREATE TABLE manager_successful_apply_validation_probe (probe_key VARCHAR(32) NOT NULL PRIMARY KEY, note VARCHAR(80) NOT NULL);\nSELECT 2;\n")
        with self.assertRaises(MigrationChecksumMismatch):
            self.apply(runner)
        connection = self.factory.connect()
        try:
            cursor = connection.execute("SELECT checksum,status FROM manager_schema_migrations WHERE migration_version=?", (V3,))
            self.assertEqual((V3_CHECKSUM, "applied"), tuple(cursor.fetchone())); cursor.close()
        finally:
            connection.close()


    def test_test_only_marker_is_bound_to_version_and_canonical_checksum(self):
        path, checksum = write_test_only_migration(self.migrations, V2, "controlled_failure", "SELECT 1;\n")
        migration = discover_migrations(self.migrations, include_test_only=True)[0]
        self.assertTrue(migration.test_only)
        self.assertEqual(V2, migration.version)
        self.assertEqual(checksum, migration.checksum)
        self.assertEqual("SELECT 1;\n", migration.sql)
        self.assertNotEqual(hashlib.sha256(path.read_bytes()).hexdigest(), migration.checksum)

    def test_test_only_marker_absent_is_not_eligible(self):
        write_migration(self.migrations, V2, "ordinary", "SELECT 1;\n")
        migration = discover_migrations(self.migrations)[0]
        self.assertFalse(migration.test_only)

    def test_test_only_marker_rejects_wrong_version_or_checksum(self):
        sql = b"SELECT 1;\n"
        good_checksum = hashlib.sha256(sql).hexdigest()
        cases = (
            ("V20261003000200__bad_version.sql", b"-- manager:migration=test-only version=20261003000100 checksum=" + good_checksum.encode() + b"\n" + sql),
            ("V20261003000200__bad_checksum.sql", b"-- manager:migration=test-only version=20261003000200 checksum=" + ("0" * 64).encode() + b"\n" + sql),
            ("V20261003000200__duplicate_marker.sql", b"-- manager:migration=test-only version=20261003000200 checksum=" + good_checksum.encode() + b"\n-- manager:migration=test-only version=20261003000200 checksum=" + good_checksum.encode() + b"\n" + sql),
        )
        for filename, content in cases:
            with self.subTest(filename=filename):
                (self.migrations / filename).write_bytes(content)
                with self.assertRaises(MigrationDiscoveryError):
                    discover_migrations(self.migrations)
                (self.migrations / filename).unlink()

    def _prepare_retireable_test(self, *, include_later=False, sql=None, test_only=True):
        write_migration(self.migrations, V1, "base", "CREATE TABLE base_table(id INTEGER);\n")
        runner = MigrationRunner(self.migrations, include_test_only=test_only)
        self.apply(runner)
        failure_sql = sql or "CREATE TABLE transient_table(id INTEGER); INSERT INTO missing_table VALUES (1);\n"
        if test_only:
            path, checksum = write_test_only_migration(self.migrations, V2, "controlled_failure", failure_sql)
        else:
            path = write_migration(self.migrations, V2, "ordinary_failure", failure_sql)
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        if include_later:
            write_migration(self.migrations, V3, "later_technical", "CREATE TABLE later_technical_table(id INTEGER);\n")
        with self.assertRaises(MigrationExecutionError):
            self.apply(runner)
        return runner, path, checksum

    def test_retire_failed_preserves_tracking_and_append_only_evidence(self):
        runner, path, checksum = self._prepare_retireable_test()
        self.assertEqual(checksum, discover_migrations(self.migrations, include_test_only=True)[1].checksum)
        # Preserve a real earlier retry-authorization audit across the later failure and retirement.
        runner.recover(self.factory, version=V2, actor="reviewer", reason="retry review", confirmation=APPLY_CONFIRMATION)
        with self.assertRaises(MigrationExecutionError):
            self.apply(runner)
        connection = self.factory.connect()
        try:
            cursor = connection.execute("SELECT started_at_utc,error_code,applied_at_utc FROM manager_schema_migrations WHERE migration_version=?", (V2,))
            before = tuple(cursor.fetchone()); cursor.close()
            cursor = connection.execute("SELECT COUNT(*) FROM manager_schema_migration_recovery_audit WHERE migration_version=?", (V2,))
            prior_recovery_count = cursor.fetchone()[0]; cursor.close()
        finally:
            connection.close()
        result = runner.retire_test(self.factory, version=V2, actor="admin", reason="Controlled test retired", confirmation=APPLY_CONFIRMATION)
        self.assertEqual((V2, "retired_test", False), (result.version, result.status, result.already_retired))
        second = runner.retire_test(self.factory, version=V2, actor="admin", reason="Controlled test retired", confirmation=APPLY_CONFIRMATION)
        self.assertTrue(second.already_retired)
        connection = self.factory.connect()
        try:
            cursor = connection.execute("SELECT checksum,status,started_at_utc,applied_at_utc,error_code FROM manager_schema_migrations WHERE migration_version=?", (V2,))
            row = tuple(cursor.fetchone()); cursor.close()
            self.assertEqual((checksum, "retired_test", before[0], None, before[1]), row)
            cursor = connection.execute("SELECT migration_version,migration_checksum,previous_status,action,original_error_code,retired_at_utc,retired_by,reason FROM manager_schema_migration_retirement_audit WHERE migration_version=?", (V2,))
            audit = tuple(cursor.fetchone()); cursor.close()
            self.assertEqual((V2, checksum, "failed", "retire_test", before[1], audit[5], "admin", "Controlled test retired"), audit)
            self.assertTrue(audit[5])
            cursor = connection.execute("SELECT COUNT(*) FROM manager_schema_migration_retirement_audit WHERE migration_version=?", (V2,))
            self.assertEqual(1, cursor.fetchone()[0]); cursor.close()
            cursor = connection.execute("SELECT COUNT(*) FROM manager_schema_migration_recovery_audit WHERE migration_version=?", (V2,))
            self.assertEqual(prior_recovery_count, cursor.fetchone()[0]); cursor.close()
        finally:
            connection.close()

    def test_retire_rejects_applied_migration(self):
        path, _ = write_test_only_migration(self.migrations, V2, "already_applied_test", "CREATE TABLE applied_test(id INTEGER);\n")
        runner = MigrationRunner(self.migrations, include_test_only=True);self.apply(runner)
        with self.assertRaises(MigrationRecoveryRequired):
            runner.retire_test(self.factory, version=V2, actor="admin", reason="not failed", confirmation=APPLY_CONFIRMATION)
        connection=self.factory.connect()
        try:
            cursor=connection.execute("SELECT status,applied_at_utc FROM manager_schema_migrations WHERE migration_version=?",(V2,));row=tuple(cursor.fetchone());cursor.close()
            self.assertEqual("applied",row[0]);self.assertTrue(row[1])
        finally:connection.close()

    def test_retire_rejects_normal_failed_migration(self):
        runner, _, _ = self._prepare_retireable_test(test_only=False)
        with self.assertRaises(MigrationAuthorizationError):
            runner.retire_test(self.factory, version=V2, actor="admin", reason="not test-only", confirmation=APPLY_CONFIRMATION)

    def test_retire_rejects_retry_authorized_state(self):
        runner, _, _ = self._prepare_retireable_test()
        runner.recover(self.factory, version=V2, actor="reviewer", reason="authorize retry", confirmation=APPLY_CONFIRMATION)
        with self.assertRaises(MigrationRecoveryRequired):
            runner.retire_test(self.factory, version=V2, actor="admin", reason="state not failed", confirmation=APPLY_CONFIRMATION)

    def test_retire_rejects_changed_checksum_and_missing_version(self):
        runner, path, checksum = self._prepare_retireable_test()
        write_test_only_migration(self.migrations, V2, "controlled_failure", "CREATE TABLE changed_test(id INTEGER);\n")
        with self.assertRaises(MigrationChecksumMismatch):
            runner.retire_test(self.factory, version=V2, actor="admin", reason="changed", confirmation=APPLY_CONFIRMATION)
        with self.assertRaises(MigrationHistoryError):
            runner.retire_test(self.factory, version="20261003000400", actor="admin", reason="missing", confirmation=APPLY_CONFIRMATION)

    def test_retire_requires_actor_reason_and_confirmation_before_connect(self):
        _, path, checksum = self._prepare_retireable_test()
        runner=MigrationRunner(self.migrations, include_test_only=True)
        class NoConnect:
            backend="sqlite";environment="test"
            def connect(self):raise AssertionError("validation must precede connection")
        with self.assertRaises(MigrationAuthorizationError):runner.retire_test(NoConnect(),version=V2,actor="",reason="reason",confirmation=APPLY_CONFIRMATION)
        with self.assertRaises(MigrationAuthorizationError):runner.retire_test(NoConnect(),version=V2,actor="actor",reason="  ",confirmation=APPLY_CONFIRMATION)
        with self.assertRaises(MigrationAuthorizationError):runner.retire_test(NoConnect(),version=V2,actor="actor",reason="reason")

    def test_retire_test_cli_requires_confirmation_and_rejects_unapproved_target(self):
        fixture_dir = str(Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "migrations_test_only")
        argv = ["retire-test", "--version", V2, "--actor", "admin", "--reason", "CLI gate test",
                "--test-only-fixtures", "--migrations-dir", fixture_dir]
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = migration_cli.main(argv)
        self.assertEqual(1, result)
        self.assertIn("TEST-ONLY fixtures require --confirm-nonprod", stderr.getvalue())

        stderr = io.StringIO()
        with patch.dict(os.environ, {"TRACCAR_MANAGER_DB_ENVIRONMENT": "invalid"}), contextlib.redirect_stderr(stderr):
            result = migration_cli.main(argv + ["--confirm-nonprod"])
        self.assertEqual(1, result)
        self.assertIn("explicit nonproduction/test environment", stderr.getvalue())

    def test_retire_respects_migration_lock(self):
        runner, _, _ = self._prepare_retireable_test()
        held=self.factory.connect();held.acquire_migration_lock("traccar_manager_schema_migrations",0.1)
        try:
            with self.assertRaises(MigrationLockUnavailable):
                runner.retire_test(self.factory,version=V2,actor="admin",reason="lock test",confirmation=APPLY_CONFIRMATION,lock_timeout=0.05)
        finally:
            held.release_migration_lock();held.close()
        connection=self.factory.connect()
        try:
            cursor=connection.execute("SELECT status FROM manager_schema_migrations WHERE migration_version=?",(V2,));self.assertEqual("failed",cursor.fetchone()[0]);cursor.close()
        finally:connection.close()

    def test_apply_skips_audited_retired_test_and_applies_later_migration(self):
        runner, _, _ = self._prepare_retireable_test(include_later=True)
        runner.retire_test(self.factory,version=V2,actor="admin",reason="retire controlled failure",confirmation=APPLY_CONFIRMATION)
        result=self.apply(runner)
        self.assertEqual((V3,),result.applied_versions)
        connection=self.factory.connect()
        try:
            cursor=connection.execute("SELECT status,applied_at_utc FROM manager_schema_migrations WHERE migration_version=?",(V2,));row=tuple(cursor.fetchone());cursor.close()
            self.assertEqual(("retired_test",None),row)
            cursor=connection.execute("SELECT status,applied_at_utc FROM manager_schema_migrations WHERE migration_version=?",(V3,));row=tuple(cursor.fetchone());cursor.close()
            self.assertEqual("applied",row[0]);self.assertTrue(row[1])
            cursor=connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='later_technical_table'");self.assertIsNotNone(cursor.fetchone());cursor.close()
        finally:connection.close()

    def test_apply_still_blocks_failed_normal_migration(self):
        runner, _, _ = self._prepare_retireable_test(include_later=True,test_only=False)
        with self.assertRaises(MigrationRecoveryRequired):self.apply(runner)
        connection=self.factory.connect()
        try:
            cursor=connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='later_technical_table'");self.assertIsNone(cursor.fetchone());cursor.close()
        finally:connection.close()

    def test_plan_displays_valid_retired_test_state(self):
        runner, _, _ = self._prepare_retireable_test()
        runner.retire_test(self.factory,version=V2,actor="admin",reason="plan test",confirmation=APPLY_CONFIRMATION)
        entries=runner.plan(self.factory)
        retired=next(entry for entry in entries if entry.version==V2)
        self.assertEqual("RETIRED_TEST",retired.status)

    def test_fake_mysql_retirement_is_audited_and_not_applied(self):
        base_path=write_migration(self.migrations,V1,"base","SELECT 1;\n")
        failed_path,checksum=write_test_only_migration(self.migrations,V2,"controlled_failure","SELECT 1;\n")
        raw=_FakeMySQLRaw()
        raw.tracking_rows=[
            (V1,"base",hashlib.sha256(base_path.read_bytes()).hexdigest(),"applied","2026-10-01T00:00:00+00:00","2026-10-01T00:00:01+00:00",None),
            (V2,"controlled_failure",checksum,"failed","2026-10-01T00:01:00+00:00",None,"ProgrammingError"),
        ]
        runner=MigrationRunner(self.migrations, include_test_only=True)
        result=runner.retire_test(_FakeMySQLFactory(raw),version=V2,actor="fake-admin",reason="fake retirement",confirmation=APPLY_CONFIRMATION)
        self.assertEqual("retired_test",result.status)
        self.assertTrue(raw.retirement_exists);self.assertEqual(1,len(raw.retirement_rows))
        self.assertEqual("ProgrammingError",raw.retirement_rows[0][4]);self.assertEqual("retired_test",raw.tracking_rows[1][3])
        apply_result=runner.apply(_FakeMySQLFactory(raw),confirmation=APPLY_CONFIRMATION)
        self.assertEqual((),apply_result.applied_versions);self.assertFalse(raw.lock_held)

    def test_modified_applied_migration_fails_checksum_validation(self):
        path = write_migration(self.migrations, V1, "create_sample", "CREATE TABLE sample(id INTEGER);")
        runner = MigrationRunner(self.migrations)
        self.apply(runner)
        path.write_text("CREATE TABLE sample(id INTEGER, label TEXT);", encoding="utf-8")
        with self.assertRaises(MigrationChecksumMismatch):
            self.apply(runner)

    def test_missing_applied_migration_fails_closed(self):
        path = write_migration(self.migrations, V1, "create_sample", "CREATE TABLE sample(id INTEGER);")
        write_migration(self.migrations, V2, "pending_second", "CREATE TABLE second(id INTEGER);")
        runner = MigrationRunner(self.migrations)
        self.apply(runner)
        path.unlink()
        with self.assertRaises(MigrationHistoryError):
            self.apply(runner)

    def test_sql_failure_rolls_back_current_sqlite_transaction_and_blocks_retry(self):
        write_migration(self.migrations, V1, "fails_safely",
                        "CREATE TABLE transient_table(id INTEGER); INSERT INTO missing_table VALUES (1);")
        runner = MigrationRunner(self.migrations)
        with self.assertRaises(MigrationExecutionError):
            self.apply(runner)
        connection = self.factory.connect()
        try:
            cursor = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='transient_table'")
            self.assertIsNone(cursor.fetchone()); cursor.close()
            cursor = connection.execute("SELECT status FROM manager_schema_migrations WHERE migration_version=?", (V1,))
            self.assertEqual("failed", cursor.fetchone()[0]); cursor.close()
        finally:
            connection.close()
        with self.assertRaises(MigrationRecoveryRequired):
            self.apply(runner)

    def test_migration_lock_rejects_concurrent_runner(self):
        first = self.factory.connect(); second = self.factory.connect()
        try:
            first.acquire_migration_lock("manager-test-lock", 0.2)
            with self.assertRaises(MigrationLockUnavailable):
                second.acquire_migration_lock("manager-test-lock", 0.05)
        finally:
            first.release_migration_lock(); second.close(); first.close()

    def test_unit_of_work_commits_and_rolls_back(self):
        with UnitOfWork(self.factory) as work:
            cursor = work.connection.execute("CREATE TABLE uow_sample(id INTEGER)"); cursor.close()
        with self.assertRaises(RuntimeError):
            with UnitOfWork(self.factory) as work:
                cursor = work.connection.execute("INSERT INTO uow_sample VALUES (1)"); cursor.close()
                raise RuntimeError("fixture failure")
        connection = self.factory.connect()
        try:
            cursor = connection.execute("SELECT COUNT(*) FROM uow_sample")
            self.assertEqual(0, cursor.fetchone()[0]); cursor.close()
        finally:
            connection.close()

    def test_settings_require_nonprod_marker_and_hide_password(self):
        with self.assertRaises(ConfigurationError):
            DatabaseSettings.from_environment({})
        values = {
            "TRACCAR_MANAGER_DB_ENVIRONMENT": "nonprod",
            "TRACCAR_MANAGER_DB_HOST": "db-test.invalid",
            "TRACCAR_MANAGER_DB_NAME": "manager_test",
            "TRACCAR_MANAGER_DB_USER": "manager_test_user",
            "TRACCAR_MANAGER_DB_PASSWORD": "fixture-not-a-secret",
        }
        settings = DatabaseSettings.from_environment(values)
        self.assertNotIn("fixture-not-a-secret", repr(settings))
        self.assertEqual("nonprod", settings.environment)

    def test_mysql_adapter_refuses_nonprod_unmarked_target_before_import_or_connect(self):
        settings = DatabaseSettings(environment="production", host="invalid", database="invalid",
                                   username="fixture", password="fixture")
        with self.assertRaises(ConnectionUnavailable):
            MySQLConnectionFactory(settings).connect()

    def _prepare_sqlite_failed_v2(self):
        write_migration(self.migrations, V1, "base", "CREATE TABLE base_table(id INTEGER);")
        runner = MigrationRunner(self.migrations); self.apply(runner)
        failed_path = write_migration(self.migrations, V2, "controlled_failure", "CREATE TABLE transient_table(id INTEGER); INSERT INTO missing_table VALUES (1);")
        with self.assertRaises(MigrationExecutionError): self.apply(runner)
        return runner, failed_path

    def _prepare_fake_mysql_failed_v2(self):
        m1=write_migration(self.migrations,V1,"base","SELECT 1;");m2=write_migration(self.migrations,V2,"controlled_failure","SELECT 2;")
        raw=_FakeMySQLRaw();raw.tracking_rows=[
            (V1,"base",hashlib.sha256(m1.read_bytes()).hexdigest(),"applied","2026-10-01T00:00:00+00:00","2026-10-01T00:00:01+00:00",None),
            (V2,"controlled_failure",hashlib.sha256(m2.read_bytes()).hexdigest(),"failed","2026-10-01T00:01:00+00:00",None,"InternalError")]
        return raw,m2

    def test_recover_failed_migration_preserves_error_and_audits_action(self):
        runner,path=self._prepare_sqlite_failed_v2();checksum=hashlib.sha256(path.read_bytes()).hexdigest()
        c=self.factory.connect()
        try:
            cur=c.execute("SELECT started_at_utc,error_code FROM manager_schema_migrations WHERE migration_version=?",(V2,));started,error=cur.fetchone();cur.close()
        finally:c.close()
        result=runner.recover(self.factory,version=V2,actor="test-operator",reason="Reviewed isolated test failure",confirmation=APPLY_CONFIRMATION)
        self.assertEqual((V2,"retry_authorized",False),(result.version,result.status,result.already_authorized))
        c=self.factory.connect()
        try:
            cur=c.execute("SELECT checksum,status,started_at_utc,applied_at_utc,error_code FROM manager_schema_migrations WHERE migration_version=?",(V2,));row=cur.fetchone();cur.close()
            self.assertEqual((checksum,"retry_authorized",started,None,error),tuple(row))
            cur=c.execute("SELECT migration_version,migration_checksum,previous_status,action,original_error_code,recovered_at_utc,recovered_by,reason FROM manager_schema_migration_recovery_audit");audit=cur.fetchone();cur.close()
            self.assertEqual((V2,checksum,"failed","authorize_retry",error,audit[5],"test-operator","Reviewed isolated test failure"),tuple(audit));self.assertTrue(audit[5])
        finally:c.close()

    def test_recover_rejects_applied_migration(self):
        write_migration(self.migrations,V1,"base","CREATE TABLE base_table(id INTEGER);");runner=MigrationRunner(self.migrations);self.apply(runner)
        with self.assertRaises(MigrationRecoveryRequired):runner.recover(self.factory,version=V1,actor="operator",reason="not applicable",confirmation=APPLY_CONFIRMATION)

    def test_recover_rejects_missing_version(self):
        write_migration(self.migrations,V1,"base","CREATE TABLE base_table(id INTEGER);");runner=MigrationRunner(self.migrations);self.apply(runner)
        with self.assertRaises(MigrationHistoryError):runner.recover(self.factory,version=V2,actor="operator",reason="missing",confirmation=APPLY_CONFIRMATION)

    def test_recover_rejects_changed_local_checksum(self):
        runner,path=self._prepare_sqlite_failed_v2();path.write_text("SELECT 99;",encoding="utf-8")
        with self.assertRaises(MigrationChecksumMismatch):runner.recover(self.factory,version=V2,actor="operator",reason="checksum test",confirmation=APPLY_CONFIRMATION)

    def test_recover_requires_explicit_confirmation_before_connect(self):
        write_migration(self.migrations,V1,"base","SELECT 1;");runner=MigrationRunner(self.migrations)
        with self.assertRaises(MigrationAuthorizationError):runner.recover(self.factory,version=V1,actor="operator",reason="no confirmation")
        self.assertFalse(self.db_path.exists())

    def test_recover_rejects_unapproved_environment_before_connect(self):
        write_migration(self.migrations,V1,"base","SELECT 1;")
        class WrongTarget:
            environment="production";backend="mysql"
            def connect(self):raise AssertionError("connection must not be attempted")
        with self.assertRaises(MigrationAuthorizationError):MigrationRunner(self.migrations).recover(WrongTarget(),version=V1,actor="operator",reason="wrong target",confirmation=APPLY_CONFIRMATION)
        self.assertFalse(self.db_path.exists())

    def test_recover_is_idempotent_for_identical_audit_request(self):
        runner,_=self._prepare_sqlite_failed_v2();first=runner.recover(self.factory,version=V2,actor="test-operator",reason="same request",confirmation=APPLY_CONFIRMATION);second=runner.recover(self.factory,version=V2,actor="test-operator",reason="same request",confirmation=APPLY_CONFIRMATION)
        self.assertFalse(first.already_authorized);self.assertTrue(second.already_authorized)
        c=self.factory.connect()
        try:
            cur=c.execute("SELECT COUNT(*) FROM manager_schema_migration_recovery_audit WHERE migration_version=?",(V2,));self.assertEqual(1,cur.fetchone()[0]);cur.close()
        finally:c.close()

    def test_recover_fake_mysql_keeps_lock_and_transaction_boundaries(self):
        raw,path=self._prepare_fake_mysql_failed_v2();result=MigrationRunner(self.migrations).recover(_FakeMySQLFactory(raw),version=V2,actor="fake-operator",reason="fake mysql review",confirmation=APPLY_CONFIRMATION)
        self.assertEqual("retry_authorized",result.status);self.assertTrue(raw.audit_exists);self.assertEqual(1,len(raw.audit_rows))
        self.assertEqual("InternalError",raw.audit_rows[0][4]);self.assertEqual("retry_authorized",raw.tracking_rows[1][3]);self.assertEqual("InternalError",raw.tracking_rows[1][6])
        self.assertEqual(1,raw.lock_acquisitions);self.assertEqual(1,raw.lock_releases);self.assertFalse(raw.lock_held);self.assertEqual(1,raw.begin_calls);self.assertFalse(raw.in_transaction);self.assertTrue(raw.closed)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),raw.tracking_rows[1][2])

    def test_recover_sqlite_lock_is_exclusive(self):
        runner,_=self._prepare_sqlite_failed_v2();held=self.factory.connect()
        try:
            held.acquire_migration_lock("traccar_manager_schema_migrations",0.2)
            with self.assertRaises(MigrationLockUnavailable):runner.recover(self.factory,version=V2,actor="operator",reason="lock test",confirmation=APPLY_CONFIRMATION,lock_timeout=0.05)
        finally:held.release_migration_lock();held.close()

    def test_recover_rejects_earlier_pending_migration(self):
        write_migration(self.migrations,V1,"earlier_pending","SELECT 1;");failed=write_migration(self.migrations,V2,"failed_target","SELECT 2;");raw=_FakeMySQLRaw()
        raw.tracking_rows=[(V2,"failed_target",hashlib.sha256(failed.read_bytes()).hexdigest(),"failed","2026-10-01T00:01:00+00:00",None,"InternalError")]
        with self.assertRaises(MigrationRecoveryRequired):MigrationRunner(self.migrations).recover(_FakeMySQLFactory(raw),version=V2,actor="operator",reason="must not skip",confirmation=APPLY_CONFIRMATION)
        self.assertEqual(0,raw.ddl_calls);self.assertEqual(0,len(raw.audit_rows))

if __name__ == "__main__":
    unittest.main()
