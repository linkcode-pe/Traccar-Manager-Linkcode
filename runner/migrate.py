"""Administrative CLI for Manager schema migrations; never auto-invoked."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MIGRATIONS_DIR = ROOT / "migrations"
TEST_ONLY_MIGRATIONS_DIR = ROOT / "tests" / "fixtures" / "migrations_test_only"
sys.path.insert(0, str(ROOT))

from manager.config import DatabaseSettings
from manager.errors import ConfigurationError, ManagerInfrastructureError
from manager.migrations.discovery import discover_migrations
from manager.migrations.runner import APPLY_CONFIRMATION, MigrationRunner
from manager.persistence.connection import MySQLConnectionFactory, SQLiteConnectionFactory

def _require_project_directory(path):
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        raise ConfigurationError("Path must remain inside the Manager checkout") from None
    return resolved

def _migration_directory(args):
    requested = getattr(args, "migrations_dir", None)
    if getattr(args, "test_only_fixtures", False):
        if requested is None:
            raise ConfigurationError("TEST-ONLY mode requires an explicit fixture directory")
        resolved = _require_project_directory(requested)
        if resolved != TEST_ONLY_MIGRATIONS_DIR.resolve():
            raise ConfigurationError("TEST-ONLY mode is restricted to the dedicated fixture directory")
        return resolved
    resolved = _require_project_directory(requested or DEFAULT_MIGRATIONS_DIR)
    if resolved == TEST_ONLY_MIGRATIONS_DIR.resolve():
        raise ConfigurationError("The TEST-ONLY fixture directory requires --test-only-fixtures")
    return resolved

def _validate_test_only_gate(args):
    if not getattr(args, "test_only_fixtures", False):
        return
    if not getattr(args, "confirm_nonprod", False):
        raise ConfigurationError("TEST-ONLY fixtures require --confirm-nonprod")
    environment = os.environ.get("TRACCAR_MANAGER_DB_ENVIRONMENT", "").strip().lower()
    if environment not in ("nonprod", "test"):
        raise ConfigurationError("TEST-ONLY fixtures require an explicit nonproduction/test environment")
    if getattr(args, "migrations_dir", None) is None:
        raise ConfigurationError("TEST-ONLY mode requires --migrations-dir with the fixture directory")

def _connection_factory(args):
    environment = os.environ.get("TRACCAR_MANAGER_DB_ENVIRONMENT", "").strip().lower()
    if environment == "nonprod":
        if getattr(args, "sqlite_test_db", None) is not None:
            raise ConfigurationError("--sqlite-test-db is allowed only with the test environment")
        return MySQLConnectionFactory(DatabaseSettings.from_environment())
    if environment == "test":
        path_arg = getattr(args, "sqlite_test_db", None)
        if path_arg is None:
            raise ConfigurationError("The test environment requires --sqlite-test-db")
        path = _require_project_directory(path_arg)
        if not path.is_file():
            raise ConfigurationError("The isolated SQLite test database must already exist")
        return SQLiteConnectionFactory(str(path))
    raise ConfigurationError("Database operations are restricted to allowlisted nonprod MySQL or isolated test SQLite")

def _add_migration_directory_args(parser):
    parser.add_argument("--migrations-dir", type=Path,
                        help="Migration source directory; TEST-ONLY mode requires its dedicated fixture path")
    parser.add_argument("--test-only-fixtures", action="store_true",
                        help="Explicitly include the dedicated TEST-ONLY fixtures in a nonproduction/test run")
    parser.add_argument("--sqlite-test-db", type=Path,
                        help="Existing file-backed SQLite database inside the checkout; only with environment=test")

def main(argv=None):
    parser = argparse.ArgumentParser(description="Traccar Manager schema migration administrator")
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="Inspect product migrations; optionally query explicit target status")
    _add_migration_directory_args(plan)
    plan.add_argument("--with-status", action="store_true", help="Read tracking status from the configured target")
    plan.add_argument("--confirm-nonprod", action="store_true")
    apply = sub.add_parser("apply", help="Apply pending migrations to an authorized target")
    _add_migration_directory_args(apply)
    apply.add_argument("--lock-timeout", type=int, default=10)
    apply.add_argument("--confirm-nonprod", action="store_true")
    recover = sub.add_parser("recover", help="Authorize a reviewed retry; does not execute SQL")
    _add_migration_directory_args(recover)
    recover.add_argument("--version", required=True, help="Exact 14-digit migration version")
    recover.add_argument("--actor", required=True, help="Audited operator identity")
    recover.add_argument("--reason", required=True, help="Audited recovery rationale")
    recover.add_argument("--lock-timeout", type=int, default=10)
    recover.add_argument("--confirm-nonprod", action="store_true")
    retire = sub.add_parser("retire-test", help="Auditably retire one failed TEST-ONLY migration without applying it")
    _add_migration_directory_args(retire)
    retire.add_argument("--version", required=True, help="Exact 14-digit migration version")
    retire.add_argument("--actor", required=True, help="Audited operator identity")
    retire.add_argument("--reason", required=True, help="Audited retirement rationale")
    retire.add_argument("--lock-timeout", type=int, default=10)
    retire.add_argument("--confirm-nonprod", action="store_true")
    verify = sub.add_parser("verify-target", help="Verify the allowlisted TLS MySQL destination using read-only metadata")
    verify.add_argument("--confirm-nonprod", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "verify-target":
            if not args.confirm_nonprod:
                print("Refusing target verification without --confirm-nonprod.", file=sys.stderr)
                return 2
            connection = MySQLConnectionFactory(DatabaseSettings.from_environment()).connect()
            try:
                metadata = connection.destination_metadata
                print("Verified destination " + metadata["destination_id"] +
                      "; host=" + metadata["hostname"] +
                      "; database=" + metadata["database"] +
                      "; effective_user=" + metadata["effective_user"] +
                      "; mysql=" + metadata["server_version"] +
                      "; tls_cipher=" + metadata["tls_cipher"] +
                      "; certificate_and_hostname_verified=yes")
            finally:
                connection.close()
            return 0

        _validate_test_only_gate(args)
        if args.command == "retire-test" and not args.test_only_fixtures:
            raise ConfigurationError("retire-test requires --test-only-fixtures and its explicit fixture directory")
        migrations_dir = _migration_directory(args)
        runner = MigrationRunner(migrations_dir, include_test_only=args.test_only_fixtures)
        if args.command == "plan":
            if args.with_status:
                if not args.confirm_nonprod:
                    print("Refusing to query status without --confirm-nonprod.", file=sys.stderr)
                    return 2
                entries = runner.plan(_connection_factory(args))
            else:
                entries = runner.plan()
            if not entries:
                print("No migration files found; no database connection was opened.")
            for item in entries:
                print(item.version + "  " + item.name + "  sha256=" + item.checksum + "  status=" + item.status)
            return 0

        migrations = discover_migrations(migrations_dir, include_test_only=args.test_only_fixtures)
        if args.command == "apply":
            if not args.confirm_nonprod:
                print("Refusing to apply without --confirm-nonprod.", file=sys.stderr)
                return 2
            if not migrations:
                print("No migration files found; no database connection was opened.")
                return 0
            result = runner.apply(_connection_factory(args), confirmation=APPLY_CONFIRMATION,
                                  lock_timeout=args.lock_timeout)
            for version in result.applied_versions:
                print("Applied " + version)
            if not result.applied_versions:
                print("No pending migrations.")
            return 0

        if args.command in ("recover", "retire-test"):
            if not args.confirm_nonprod:
                print("Refusing administrative action without --confirm-nonprod.", file=sys.stderr)
                return 2
            factory = _connection_factory(args)
            if args.command == "recover":
                result = runner.recover(factory, version=args.version, actor=args.actor, reason=args.reason,
                                        confirmation=APPLY_CONFIRMATION, lock_timeout=args.lock_timeout)
                if result.already_authorized:
                    print("Recovery authorization already recorded for " + result.version + "; no changes made.")
                else:
                    print("Recovery authorization recorded for " + result.version +
                          "; migration remains unapplied and requires a separate confirmed apply.")
                return 0
            result = runner.retire_test(factory, version=args.version, actor=args.actor, reason=args.reason,
                                        confirmation=APPLY_CONFIRMATION, lock_timeout=args.lock_timeout)
            if result.already_retired:
                print("Test migration " + result.version + " is already retired; no changes made.")
            else:
                print("Test migration " + result.version + " retired; it remains unapplied and will be skipped by apply.")
            return 0
    except ManagerInfrastructureError as exc:
        print("Migration operation stopped: " + str(exc), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
