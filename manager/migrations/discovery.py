"""Versioned SQL migration discovery, validation, and checksum calculation."""
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
from pathlib import Path
import re
from typing import Tuple

from manager.errors import MigrationDiscoveryError

_FILENAME = re.compile(r"^V(?P<version>\d{14})__(?P<name>[a-z0-9]+(?:[a-z0-9_-]*[a-z0-9])?)\.sql$")

_TEST_ONLY_MARKER = re.compile(
    rb"^-- manager:migration=test-only version=(?P<version>\d{14}) checksum=(?P<checksum>[0-9a-f]{64})\r?\n$"
)
_TEST_ONLY_PREFIX = b"-- manager:migration="

@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    path: Path
    checksum: str
    sql: str = field(repr=False)
    test_only: bool = False

def discover_migrations(directory, *, include_test_only=False) -> Tuple[Migration, ...]:
    """Validate local SQL files; normal discovery omits TEST-ONLY fixtures."""
    root = Path(directory)
    if not root.is_dir():
        raise MigrationDiscoveryError("Migration directory does not exist")
    found = []
    seen = set()
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if path.is_dir() or path.name == "README.md" or path.name.startswith("."):
            continue
        if path.suffix.lower() != ".sql":
            continue
        match = _FILENAME.fullmatch(path.name)
        if not match or path.is_symlink():
            raise MigrationDiscoveryError("Invalid migration filename or symlink in migration directory")
        version = match.group("version")
        try:
            datetime.strptime(version, "%Y%m%d%H%M%S")
        except ValueError:
            raise MigrationDiscoveryError("Migration version must be a valid UTC timestamp") from None
        if version in seen:
            raise MigrationDiscoveryError("Duplicate migration version detected")
        seen.add(version)
        try:
            raw = path.read_bytes()
            lines = raw.splitlines(keepends=True)
            marker_lines = [i for i, line in enumerate(lines) if line.startswith(_TEST_ONLY_PREFIX)]
            test_only = False
            canonical = raw
            if marker_lines:
                if marker_lines != [0]:
                    raise MigrationDiscoveryError("Test-only metadata must appear exactly once on the first line")
                marker = _TEST_ONLY_MARKER.fullmatch(lines[0])
                if marker is None:
                    raise MigrationDiscoveryError("Malformed test-only migration metadata")
                canonical = b"".join(lines[1:])
                canonical_checksum = hashlib.sha256(canonical).hexdigest()
                if marker.group("version").decode("ascii") != version:
                    raise MigrationDiscoveryError("Test-only metadata version does not match its filename")
                if marker.group("checksum").decode("ascii") != canonical_checksum:
                    raise MigrationDiscoveryError("Test-only metadata checksum does not match migration content")
                test_only = True
            sql = canonical.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            raise MigrationDiscoveryError("Could not safely read migration file") from None
        if not sql.strip():
            raise MigrationDiscoveryError("Migration file is empty")
        checksum = hashlib.sha256(canonical).hexdigest()
        if test_only and not include_test_only:
            continue
        found.append(Migration(version, match.group("name"), path, checksum, sql, test_only))
    return tuple(sorted(found, key=lambda migration: migration.version))
