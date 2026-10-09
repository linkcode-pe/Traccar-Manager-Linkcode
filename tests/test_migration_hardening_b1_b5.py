"""Focused B1-B5 hardening tests; no live database connections are made."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

import mysql.connector

from manager.config import DatabaseSettings, authorize_nonprod_destination
from manager.errors import (
    ConfigurationError, ConnectionUnavailable, MigrationChecksumMismatch,
    MigrationDiscoveryError, MigrationHistoryError, MigrationRecoveryRequired,
)
from manager.migrations.discovery import discover_migrations
from manager.migrations.runner import APPLY_CONFIRMATION, MigrationRunner
from manager.persistence.connection import DatabaseConnection, MySQLConnectionFactory
from runner import migrate as migration_cli

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "migrations_test_only"
HOST = "MySQL_Server_8.0.42_Auto_Generated_Server_Certificate"
CA = "/var/lib/mysql/ca.pem"
V1 = "20261003000100"
V2 = "20261003000200"
V3 = "20261003000300"
STAMP = "2026-10-03T00:00:00+00:00"


def approved_settings(**changes):
    values = dict(
        environment="nonprod", host=HOST, database="traccar-tem", username="linkcode2",
        password="fixture-secret-never-printed", port=3306, connect_timeout=5, ssl_ca=CA,
    )
    values.update(changes)
    return DatabaseSettings(**values)


class _MetadataCursor:
    def __init__(self, raw):
        self.raw = raw
        self.rows = []

    def execute(self, sql, params=()):
        if sql == "SELECT DATABASE(), CURRENT_USER(), VERSION()":
            self.rows = [] if self.raw.identity is None else [self.raw.identity]
        elif sql == "SHOW SESSION STATUS LIKE 'Ssl_cipher'":
            self.rows = [] if self.raw.cipher is None else [("Ssl_cipher", self.raw.cipher)]
        else:
            raise AssertionError("Unexpected metadata SQL")

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def close(self):
        pass


class _MetadataRaw:
    def __init__(self, identity=("traccar-tem", "linkcode2@localhost", "8.0.42"), cipher="TLS_AES_256_GCM_SHA384"):
        self.identity = identity
        self.cipher = cipher
        self.commits = 0
        self.closed = False

    def cursor(self):
        return _MetadataCursor(self)

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


class _HistoryCursor:
    def __init__(self, raw):
        self.raw = raw
        self.rows = []
        self.rowcount = -1
        self.with_rows = False

    def _rows(self, rows):
        self.rows = list(rows)
        self.with_rows = True

    def execute(self, sql, params=()):
        stmt = " ".join(sql.split()).upper()
        self.rowcount = -1
        self.with_rows = False
        if stmt.startswith("SELECT GET_LOCK("):
            self.raw.lock_held = True
            self._rows([(1,)])
        elif stmt.startswith("SELECT RELEASE_LOCK("):
            was_held = self.raw.lock_held
            self.raw.lock_held = False
            self._rows([(1 if was_held else None,)])
        elif stmt.startswith("CREATE TABLE IF NOT EXISTS MANAGER_SCHEMA_MIGRATIONS"):
            self.raw.tracking_ddl_calls += 1
        elif stmt.startswith("SELECT MIGRATION_VERSION, MIGRATION_NAME, CHECKSUM, STATUS, STARTED_AT_UTC, APPLIED_AT_UTC, ERROR_CODE FROM MANAGER_SCHEMA_MIGRATIONS"):
            self._rows(self.raw.tracking_rows)
        elif stmt.startswith("SELECT MIGRATION_CHECKSUM, PREVIOUS_STATUS, ACTION, ORIGINAL_ERROR_CODE, RETIRED_AT_UTC, RETIRED_BY, REASON FROM MANAGER_SCHEMA_MIGRATION_RETIREMENT_AUDIT"):
            matches = [r for r in self.raw.retirement_rows if r[0] == params[0]]
            self._rows([matches[-1][1:]] if matches else [])
        elif stmt.startswith("INSERT INTO MANAGER_SCHEMA_MIGRATIONS"):
            self.raw.tracking_rows.append(tuple(params))
            self.rowcount = 1
        elif stmt.startswith("UPDATE MANAGER_SCHEMA_MIGRATIONS SET STATUS="):
            if "APPLIED_AT_UTC=" in stmt:
                status, applied_at, version, expected_status, checksum = params
                for index, old in enumerate(self.raw.tracking_rows):
                    if old[0] == version and old[3] == expected_status and old[2] == checksum and old[5] is None:
                        row = list(old); row[3] = status; row[5] = applied_at; row[6] = None
                        self.raw.tracking_rows[index] = tuple(row); self.rowcount = 1
            else:
                raise AssertionError("Unexpected tracking update")
        elif stmt == "SELECT 1":
            self.raw.migration_sql_calls += 1
            self._rows([(1,)])
        else:
            self.raw.migration_sql_calls += 1
            raise AssertionError("Unexpected SQL reached migration executor")

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        rows = list(self.rows); self.rows.clear(); return rows

    def fetchmany(self, size=1000):
        rows = self.rows[:size]; self.rows = self.rows[size:]; return rows

    def close(self):
        pass


class _HistoryRaw:
    def __init__(self, rows=(), retirement_rows=()):
        self.tracking_rows = list(rows)
        self.retirement_rows = list(retirement_rows)
        self.tracking_ddl_calls = 0
        self.migration_sql_calls = 0
        self.lock_held = False
        self.closed = False
        self.in_transaction = False

    def cursor(self):
        return _HistoryCursor(self)

    def start_transaction(self):
        self.in_transaction = True

    def commit(self):
        self.in_transaction = False

    def rollback(self):
        self.in_transaction = False

    def close(self):
        self.closed = True


class _HistoryFactory:
    backend = "mysql"
    environment = "nonprod"

    def __init__(self, raw):
        self.raw = raw

    def connect(self):
        return DatabaseConnection(self.raw, "mysql")


def _row(version, name, checksum, status="applied", started=STAMP, applied=STAMP, error=None):
    return (version, name, checksum, status, started, applied, error)


def _write_migration(directory, version, name, sql="SELECT 1;\n", *, test_only=False):
    body = sql.encode("utf-8")
    checksum = hashlib.sha256(body).hexdigest()
    prefix = b""
    if test_only:
        prefix = ("-- manager:migration=test-only version=" + version + " checksum=" + checksum + "\n").encode("ascii")
    path = directory / ("V" + version + "__" + name + ".sql")
    path.write_bytes(prefix + body)
    return path, checksum


class MigrationHardeningB1B5Tests(unittest.TestCase):
    def test_b1_a_allowlisted_tuple_is_accepted(self):
        destination = authorize_nonprod_destination(approved_settings())
        self.assertEqual("manager-nonprod-traccar-tem-v1", destination.destination_id)
        self.assertEqual("linkcode2@localhost", destination.effective_user)

    def test_b1_b_bad_hostname_is_rejected_before_connector_or_lock(self):
        self._assert_rejected_before_connect_or_lock(host="production.example")

    def test_b1_c_bad_database_is_rejected_before_connector_or_lock(self):
        self._assert_rejected_before_connect_or_lock(database="traccar-production")

    def test_b1_d_inconsistent_user_port_or_ca_tuple_is_rejected(self):
        for changes in ({"username": "other_user"}, {"port": 3307}, {"ssl_ca": "/wrong/ca.pem"}):
            with self.subTest(changes=changes):
                self._assert_rejected_before_connect_or_lock(**changes)

    def test_b1_e_missing_or_wrong_connected_identity_is_rejected_and_closed(self):
        for identity in (None, ("other_db", "linkcode2@localhost", "8.0.42"),
                         ("traccar-tem", "linkcode2@%", "8.0.42")):
            raw = _MetadataRaw(identity=identity)
            with patch("mysql.connector.connect", return_value=raw) as connector, \
                 patch("manager.persistence.connection.os.path.isfile", return_value=True), \
                 patch("manager.persistence.connection.os.access", return_value=True):
                with self.assertRaises(ConnectionUnavailable):
                    MySQLConnectionFactory(approved_settings()).connect()
            connector.assert_called_once()
            self.assertTrue(raw.closed)

    def test_b1_f_production_target_cannot_be_labeled_nonprod(self):
        self._assert_rejected_before_connect_or_lock(
            host="homecargps.com", database="traccar", username="production_user"
        )

    def _assert_rejected_before_connect_or_lock(self, **changes):
        factory = MySQLConnectionFactory(approved_settings(**changes))
        with tempfile.TemporaryDirectory() as temp:
            runner = MigrationRunner(temp)
            with patch("mysql.connector.connect") as connector, \
                 patch.object(DatabaseConnection, "acquire_migration_lock", side_effect=AssertionError("lock must not be acquired")) as lock:
                with self.assertRaises(ConfigurationError):
                    runner.plan(factory)
            connector.assert_not_called()
            lock.assert_not_called()

    def test_b4_standard_connection_uses_strict_tls_and_scoped_resolution(self):
        raw = _MetadataRaw()
        observed = []
        original = socket.getaddrinfo

        def resolver(host, *args, **kwargs):
            observed.append(host)
            return [(host, args, kwargs)]

        def connect(**kwargs):
            mapped = socket.getaddrinfo(HOST, 3306)
            untouched = socket.getaddrinfo("unrelated.example", 3306)
            self.assertEqual("127.0.0.1", mapped[0][0])
            self.assertEqual("unrelated.example", untouched[0][0])
            return raw

        with patch("socket.getaddrinfo", side_effect=resolver) as resolver_mock, \
             patch("mysql.connector.connect", side_effect=connect) as connector, \
             patch("manager.persistence.connection.os.path.isfile", return_value=True), \
             patch("manager.persistence.connection.os.access", return_value=True):
            connection = MySQLConnectionFactory(approved_settings()).connect()
            self.assertIs(socket.getaddrinfo, resolver_mock)
            self.assertIsNotNone(connection.destination_metadata["tls_cipher"])
            self.assertTrue(connection.destination_metadata["tls_verified"])
            connection.close()
        self.assertIs(socket.getaddrinfo, original)
        self.assertEqual(["127.0.0.1", "unrelated.example"], observed)
        connector.assert_called_once()
        kwargs = connector.call_args.kwargs
        self.assertEqual(HOST, kwargs["host"])
        self.assertEqual(CA, kwargs["ssl_ca"])
        self.assertIs(kwargs["ssl_verify_cert"], True)
        self.assertIs(kwargs["ssl_verify_identity"], True)
        self.assertIs(kwargs["use_pure"], True)
        self.assertEqual(1, raw.commits)
        self.assertTrue(raw.closed)
        self.assertIsNot(original, resolver_mock)

    def test_b4_missing_approved_ca_stops_before_connector(self):
        with patch("mysql.connector.connect") as connector, \
             patch("manager.persistence.connection.os.path.isfile", return_value=False), \
             patch("manager.persistence.connection.os.access", return_value=True):
            with self.assertRaises(ConnectionUnavailable):
                MySQLConnectionFactory(approved_settings()).connect()
        connector.assert_not_called()

    def test_b4_ssl_certificate_or_hostname_failure_has_no_fallback(self):
        for failure in (RuntimeError("certificate verification failed"), RuntimeError("hostname mismatch")):
            with self.subTest(failure=str(failure)), \
                 patch("mysql.connector.connect", side_effect=failure) as connector, \
                 patch("manager.persistence.connection.os.path.isfile", return_value=True), \
                 patch("manager.persistence.connection.os.access", return_value=True):
                with self.assertRaises(ConnectionUnavailable):
                    MySQLConnectionFactory(approved_settings()).connect()
                connector.assert_called_once()
                kwargs = connector.call_args.kwargs
                self.assertTrue(kwargs["ssl_verify_cert"])
                self.assertTrue(kwargs["ssl_verify_identity"])
                self.assertTrue(kwargs["use_pure"])

    def test_b2_default_source_and_normal_apply_exclude_test_only_fixtures(self):
        self.assertEqual((), discover_migrations(FIXTURES))
        self.assertEqual((), MigrationRunner(FIXTURES).plan())

        class NoConnect:
            backend = "sqlite"
            environment = "test"
            def connect(self):
                raise AssertionError("excluded fixture files must not open a database")

        result = MigrationRunner(FIXTURES).apply(NoConnect(), confirmation=APPLY_CONFIRMATION)
        self.assertTrue(result.no_migrations)
        self.assertEqual((), result.applied_versions)

    def test_b2_explicit_fixture_mode_needs_designated_directory_and_gates(self):
        fixtures = discover_migrations(FIXTURES, include_test_only=True)
        self.assertEqual([V1, V2, V3], [migration.version for migration in fixtures])
        self.assertTrue(all(migration.test_only for migration in fixtures))
        runner = MigrationRunner(FIXTURES, include_test_only=True)
        self.assertEqual([V1, V2, V3], [entry.version for entry in runner.plan()])
        args = type("Args", (), {"test_only_fixtures": True, "migrations_dir": FIXTURES})()
        self.assertEqual(FIXTURES.resolve(), migration_cli._migration_directory(args))
        args.migrations_dir = ROOT / "migrations"
        with self.assertRaises(ConfigurationError):
            migration_cli._migration_directory(args)
        args.test_only_fixtures = False
        with self.assertRaises(ConfigurationError):
            migration_cli._migration_directory(type("Args", (), {"test_only_fixtures": False, "migrations_dir": FIXTURES})())
        gate_args = type("Args", (), {"test_only_fixtures": True, "migrations_dir": FIXTURES,
                                       "confirm_nonprod": False})()
        with patch.dict(os.environ, {"TRACCAR_MANAGER_DB_ENVIRONMENT": "test"}):
            with self.assertRaises(ConfigurationError):
                migration_cli._validate_test_only_gate(gate_args)
        gate_args.confirm_nonprod = True
        with patch.dict(os.environ, {"TRACCAR_MANAGER_DB_ENVIRONMENT": "production"}):
            with self.assertRaises(ConfigurationError):
                migration_cli._validate_test_only_gate(gate_args)
        with patch.dict(os.environ, {"TRACCAR_MANAGER_DB_ENVIRONMENT": "nonprod"}):
            migration_cli._validate_test_only_gate(gate_args)

    def test_b3_apply_preflight_rejects_gaps_unknown_rows_checksums_and_bad_states(self):
        cases = (
            ("missing-earlier", [(V2, "later", "unused", "applied", STAMP, STAMP, None)], MigrationRecoveryRequired),
            ("unknown-tracking", [("20261003000900", "unknown", "unused", "applied", STAMP, STAMP, None)], MigrationHistoryError),
            ("checksum-mismatch", [(V1, "first", "0" * 64, "applied", STAMP, STAMP, None)], MigrationChecksumMismatch),
            ("applied-without-timestamp", [(V1, "first", None, "applied", STAMP, None, None)], MigrationHistoryError),
            ("applied-with-error", [(V1, "first", None, "applied", STAMP, STAMP, "OldError")], MigrationHistoryError),
            ("failed-with-timestamp", [(V1, "first", None, "failed", STAMP, STAMP, "ProgrammingError")], MigrationHistoryError),
            ("failed-blocks-later", [(V1, "first", None, "failed", STAMP, None, "ProgrammingError")], MigrationRecoveryRequired),
        )
        with tempfile.TemporaryDirectory() as base:
            for name, status_rows, exception in cases:
                with self.subTest(case=name):
                    directory = Path(base) / name
                    directory.mkdir()
                    _, checksum1 = _write_migration(directory, V1, "first")
                    _, checksum2 = _write_migration(directory, V2, "later")
                    rows = []
                    for row in status_rows:
                        version, migration_name, checksum, status, started, applied, error = row
                        if version == V1 and checksum is None:
                            checksum = checksum1
                        if version == V2 and checksum == "unused":
                            checksum = checksum2
                        rows.append((version, migration_name, checksum, status, started, applied, error))
                    raw = _HistoryRaw(rows)
                    runner = MigrationRunner(directory)
                    with self.assertRaises(exception):
                        runner.apply(_HistoryFactory(raw), confirmation=APPLY_CONFIRMATION)
                    self.assertEqual(0, raw.migration_sql_calls)
                    self.assertEqual(1, raw.tracking_ddl_calls)
                    self.assertFalse(raw.lock_held)
                    self.assertTrue(raw.closed)

    def test_b3_versions_are_sorted_and_duplicate_versions_fail_discovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write_migration(root, V3, "third")
            _write_migration(root, V1, "first")
            self.assertEqual([V1, V3], [m.version for m in discover_migrations(root)])
            _write_migration(root, V1, "duplicate")
            with self.assertRaises(MigrationDiscoveryError):
                discover_migrations(root)

    def test_b3_explicit_valid_retired_test_is_skipped_and_later_fixture_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, c1 = _write_migration(root, V1, "first", test_only=True)
            _, c2 = _write_migration(root, V2, "controlled_failure", test_only=True)
            _, c3 = _write_migration(root, V3, "third", test_only=True)
            audit = (V2, c2, "failed", "retire_test", "ProgrammingError", STAMP, "admin", "controlled retirement")
            raw = _HistoryRaw(
                rows=[_row(V1, "first", c1), _row(V2, "controlled_failure", c2, "retired_test", STAMP, None, "ProgrammingError")],
                retirement_rows=[audit],
            )
            runner = MigrationRunner(root, include_test_only=True)
            result = runner.apply(_HistoryFactory(raw), confirmation=APPLY_CONFIRMATION)
            self.assertEqual((V3,), result.applied_versions)
            self.assertEqual("retired_test", next(row for row in raw.tracking_rows if row[0] == V2)[3])
            self.assertEqual("applied", next(row for row in raw.tracking_rows if row[0] == V3)[3])
            self.assertEqual(1, raw.migration_sql_calls)

    def test_b3_plan_rejects_later_applied_while_earlier_is_pending(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write_migration(root, V1, "first")
            _, checksum2 = _write_migration(root, V2, "later")
            raw = _HistoryRaw([_row(V2, "later", checksum2)])
            with self.assertRaises(MigrationRecoveryRequired):
                MigrationRunner(root).plan(_HistoryFactory(raw))
            self.assertEqual(0, raw.migration_sql_calls)
            self.assertFalse(raw.lock_held)


if __name__ == "__main__":
    unittest.main()
