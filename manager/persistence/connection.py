"""DB-API connection adapters. SQLite is intended for isolated tests only."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
import socket
import sqlite3
import threading
import time
from typing import Any, Optional, Protocol, Sequence, runtime_checkable

from manager.config import DatabaseSettings, authorize_nonprod_destination
from manager.errors import ConnectionUnavailable, MigrationLockUnavailable

_resolution_lock = threading.RLock()

@contextmanager
def _scoped_hostname_resolution(hostname: str, address: str):
    """Map only one validated TLS hostname during this connection's pure-Python DNS lookup.

    The hostname passed to MySQL Connector remains unchanged for TLS identity
    verification. The resolver is restored immediately after connect().
    """
    with _resolution_lock:
        original = socket.getaddrinfo
        def resolve(requested_host, *args, **kwargs):
            if requested_host == hostname:
                requested_host = address
            return original(requested_host, *args, **kwargs)
        socket.getaddrinfo = resolve
        try:
            yield
        finally:
            socket.getaddrinfo = original

@runtime_checkable
class ConnectionFactory(Protocol):
    def connect(self) -> "DatabaseConnection": ...

class DatabaseConnection:
    """Small dialect-aware wrapper; application code receives no raw DSN."""
    def __init__(self, raw: Any, backend: str, sqlite_path: Optional[str] = None,
                 destination_metadata: Optional[dict] = None):
        self._raw = raw
        self.backend = backend
        self._sqlite_path = sqlite_path
        self.destination_metadata = destination_metadata or {}
        self._lock_fd: Optional[int] = None
        self._mysql_lock_name: Optional[str] = None

    @property
    def placeholder(self) -> str:
        return "?" if self.backend == "sqlite" else "%s"

    def execute(self, sql: str, params: Sequence[Any] = ()):
        cursor = self._raw.cursor()
        try:
            cursor.execute(sql, params)
            return cursor
        except Exception:
            cursor.close()
            raise

    def begin(self) -> None:
        if self.backend == "sqlite":
            self._raw.execute("BEGIN IMMEDIATE")
        else:
            self._raw.start_transaction()

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def acquire_migration_lock(self, name: str, timeout: float) -> None:
        if self.backend == "mysql":
            cursor = self.execute("SELECT GET_LOCK(%s, %s)", (name, int(timeout)))
            try:
                row = cursor.fetchone()
            finally:
                cursor.close()
            if not row or row[0] != 1:
                raise MigrationLockUnavailable("Could not acquire the Manager migration lock")
            self._mysql_lock_name = name
            return
        if not self._sqlite_path or self._sqlite_path == ":memory:":
            raise MigrationLockUnavailable("SQLite migration locking requires a file-backed test database")
        lock_path = self._sqlite_path + ".migration.lock"
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        except OSError:
            raise MigrationLockUnavailable("Could not open the isolated SQLite migration lock") from None
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._lock_fd = fd
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise MigrationLockUnavailable("Timed out waiting for the SQLite migration lock") from None
                time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
            except OSError:
                os.close(fd)
                raise MigrationLockUnavailable("Could not acquire the SQLite migration lock") from None

    def release_migration_lock(self) -> None:
        if self._mysql_lock_name is not None:
            name = self._mysql_lock_name
            self._mysql_lock_name = None
            cursor = self.execute("SELECT RELEASE_LOCK(%s)", (name,))
            try:
                row = cursor.fetchone()
            finally:
                cursor.close()
            if not row or row[0] != 1:
                raise MigrationLockUnavailable("Could not release the Manager migration lock")
        if self._lock_fd is not None:
            fd = self._lock_fd
            self._lock_fd = None
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def close(self) -> None:
        try:
            if self._mysql_lock_name is not None or self._lock_fd is not None:
                self.release_migration_lock()
        finally:
            self._raw.close()

class SQLiteConnectionFactory:
    """File-backed SQLite adapter; usable only through explicit test targets."""
    backend = "sqlite"
    environment = "test"
    def __init__(self, path: str, timeout: float = 2.0):
        self.path = path
        self.timeout = timeout

    def connect(self) -> DatabaseConnection:
        try:
            raw = sqlite3.connect(self.path, timeout=self.timeout, isolation_level=None)
            raw.execute("PRAGMA foreign_keys = ON")
            return DatabaseConnection(raw, "sqlite", self.path)
        except sqlite3.Error:
            raise ConnectionUnavailable("Could not open the isolated SQLite test database") from None

class MySQLConnectionFactory:
    """Strict-TLS MySQL adapter restricted to reviewed nonproduction identities."""
    backend = "mysql"

    def __init__(self, settings: DatabaseSettings):
        self._settings = settings
        self.environment = settings.environment

    def connect(self) -> DatabaseConnection:
        if self.environment != "nonprod":
            raise ConnectionUnavailable("Refusing MySQL connection without an explicit nonprod marker")
        target = authorize_nonprod_destination(self._settings)
        if not os.path.isfile(target.ca_path) or not os.access(target.ca_path, os.R_OK):
            raise ConnectionUnavailable("The approved Manager DB CA file is unavailable")
        try:
            import mysql.connector
        except ImportError:
            raise ConnectionUnavailable("MySQL connector dependency is not installed") from None
        raw = None
        try:
            with _scoped_hostname_resolution(target.hostname, target.resolve_address):
                raw = mysql.connector.connect(
                    host=target.hostname, port=target.port, database=target.database,
                    user=target.username, password=self._settings.password,
                    connection_timeout=self._settings.connect_timeout, autocommit=False,
                    charset="utf8mb4", ssl_ca=target.ca_path,
                    ssl_verify_cert=True, ssl_verify_identity=True,
                    use_pure=True,
                )
            cursor = raw.cursor()
            try:
                cursor.execute("SELECT DATABASE(), CURRENT_USER(), VERSION()")
                identity = cursor.fetchone()
            finally:
                cursor.close()
            cursor = raw.cursor()
            try:
                cursor.execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'")
                cipher_row = cursor.fetchone()
            finally:
                cursor.close()
            if (not identity or identity[0] != target.database or
                    identity[1] != target.effective_user or not cipher_row or not cipher_row[1]):
                raise ConnectionUnavailable("Connected MySQL destination identity or TLS state is not authorized")
            # The factory performs metadata-only reads under autocommit=False.
            # End that read-only transaction before handing the connection to callers.
            raw.commit()
            metadata = {
                "destination_id": target.destination_id,
                "hostname": target.hostname,
                "database": identity[0],
                "effective_user": identity[1],
                "server_version": identity[2],
                "tls_cipher": cipher_row[1],
                "tls_verified": True,
            }
            return DatabaseConnection(raw, "mysql", destination_metadata=metadata)
        except ConnectionUnavailable:
            if raw is not None:
                try: raw.close()
                except Exception: pass
            raise
        except Exception:
            if raw is not None:
                try: raw.close()
                except Exception: pass
            raise ConnectionUnavailable("Could not establish the authorized strict-TLS Manager DB connection") from None
