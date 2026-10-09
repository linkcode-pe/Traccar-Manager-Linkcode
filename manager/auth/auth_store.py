"""Root-owned JSON account store for the Traccar Manager Web bootstrap.

The Web process only reads this file. Initial provisioning is a separate
root-only CLI; a missing store intentionally means that no account can log in.
"""
from __future__ import annotations

from dataclasses import dataclass
import base64
import grp
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Any

AUTH_STORE_PATH = Path("/etc/traccar-manager/auth-store.json")
AUTH_STORE_DIRECTORY = AUTH_STORE_PATH.parent
SERVICE_GROUP = "traccar-manager-web"
STORE_VERSION = 1
PBKDF2_ITERATIONS = 600_000
MIN_PBKDF2_ITERATIONS = 100_000
MAX_PBKDF2_ITERATIONS = 2_000_000
MAX_STORE_BYTES = 64 * 1024
MAX_PASSWORD_CHARS = 1024
_USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,63}$")
_SUBJECT_RE = re.compile(r"^[0-9a-f]{32}$")
_ALLOWED_ROLES = frozenset({"dashboard.read", "traccar.status.read", "maintenance.logs.preview", "maintenance.logs.prepare", "maintenance.logs.execute"})


class AuthStoreError(RuntimeError):
    """The protected authentication store is malformed or unsafe."""


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    subject_id: str
    username: str
    roles: tuple[str, ...]


def valid_username(value: Any) -> bool:
    return isinstance(value, str) and _USERNAME_RE.fullmatch(value) is not None


def derive_password_hash(password: str, salt: bytes, iterations: int = PBKDF2_ITERATIONS) -> bytes:
    if not isinstance(password, str) or not 1 <= len(password) <= MAX_PASSWORD_CHARS:
        raise ValueError("invalid password input")
    if not isinstance(salt, bytes) or len(salt) != 16:
        raise ValueError("invalid salt")
    if not isinstance(iterations, int) or not MIN_PBKDF2_ITERATIONS <= iterations <= MAX_PBKDF2_ITERATIONS:
        raise ValueError("invalid PBKDF2 work factor")
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)


def make_password_record(password: str) -> dict[str, Any]:
    """Create a salt+PBKDF2 record; used only by the separate provisioner/tests."""
    salt = secrets.token_bytes(16)
    digest = derive_password_hash(password, salt, PBKDF2_ITERATIONS)
    return {
        "salt_b64": base64.b64encode(salt).decode("ascii"),
        "password_hash_b64": base64.b64encode(digest).decode("ascii"),
        "iterations": PBKDF2_ITERATIONS,
    }


class AuthStore:
    def __init__(self, path: str | os.PathLike[str] = AUTH_STORE_PATH):
        self.path = Path(path)

    @staticmethod
    def _service_gid() -> int:
        try:
            return grp.getgrnam(SERVICE_GROUP).gr_gid
        except KeyError:
            raise AuthStoreError("authentication store group unavailable") from None

    def _read_accounts(self) -> tuple[dict[str, Any], ...]:
        try:
            parent = self.path.parent.lstat()
        except FileNotFoundError:
            return ()
        except OSError:
            raise AuthStoreError("authentication store unavailable") from None
        service_gid = self._service_gid()
        if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or
                parent.st_gid != service_gid or stat.S_IMODE(parent.st_mode) != 0o750):
            raise AuthStoreError("authentication store directory permissions invalid")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self.path, flags)
        except FileNotFoundError:
            return ()
        except OSError:
            raise AuthStoreError("authentication store unavailable") from None
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != service_gid or
                    stat.S_IMODE(info.st_mode) != 0o640 or info.st_size > MAX_STORE_BYTES):
                raise AuthStoreError("authentication store file permissions invalid")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                raw = stream.read(MAX_STORE_BYTES + 1)
        finally:
            os.close(fd)
        if len(raw) > MAX_STORE_BYTES:
            raise AuthStoreError("authentication store size invalid")
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AuthStoreError("authentication store format invalid") from None
        if not isinstance(document, dict) or set(document) != {"version", "users"} or document.get("version") != STORE_VERSION:
            raise AuthStoreError("authentication store schema invalid")
        users = document.get("users")
        if not isinstance(users, list) or len(users) > 100:
            raise AuthStoreError("authentication store users invalid")
        seen_usernames: set[str] = set()
        seen_subjects: set[str] = set()
        parsed: list[dict[str, Any]] = []
        required = {"username", "subject_id", "salt_b64", "password_hash_b64", "iterations", "roles", "enabled"}
        for item in users:
            if not isinstance(item, dict) or set(item) != required:
                raise AuthStoreError("authentication account schema invalid")
            username = item["username"]
            subject = item["subject_id"]
            if not valid_username(username) or not isinstance(subject, str) or not _SUBJECT_RE.fullmatch(subject):
                raise AuthStoreError("authentication account identity invalid")
            if username in seen_usernames or subject in seen_subjects:
                raise AuthStoreError("authentication account identity duplicated")
            seen_usernames.add(username)
            seen_subjects.add(subject)
            if not isinstance(item["enabled"], bool):
                raise AuthStoreError("authentication account state invalid")
            roles = item["roles"]
            if (not isinstance(roles, list) or len(roles) > len(_ALLOWED_ROLES) or
                    any(not isinstance(role, str) or role not in _ALLOWED_ROLES for role in roles) or
                    len(set(roles)) != len(roles)):
                raise AuthStoreError("authentication account roles invalid")
            iterations = item["iterations"]
            if (not isinstance(iterations, int) or isinstance(iterations, bool) or
                    not MIN_PBKDF2_ITERATIONS <= iterations <= MAX_PBKDF2_ITERATIONS):
                raise AuthStoreError("authentication account work factor invalid")
            try:
                salt = base64.b64decode(item["salt_b64"], validate=True)
                digest = base64.b64decode(item["password_hash_b64"], validate=True)
            except (TypeError, ValueError):
                raise AuthStoreError("authentication account hash invalid") from None
            if len(salt) != 16 or len(digest) != 32:
                raise AuthStoreError("authentication account hash invalid")
            parsed.append({**item, "_salt": salt, "_digest": digest})
        return tuple(parsed)

    def authenticate(self, username: str, password: str) -> AuthenticatedUser | None:
        if not isinstance(password, str) or not 1 <= len(password) <= MAX_PASSWORD_CHARS:
            return None
        accounts = self._read_accounts()
        account = next((row for row in accounts if row["username"] == username), None) if valid_username(username) else None
        if account is None:
            # Keep unknown users and absent stores on a bounded PBKDF2 path too.
            dummy_salt = bytes(16)
            supplied = derive_password_hash(password, dummy_salt, PBKDF2_ITERATIONS)
            hmac.compare_digest(supplied, bytes(32))
            return None
        salt, digest, iterations = account["_salt"], account["_digest"], account["iterations"]
        try:
            from manager.account_profile import read_password_record
            override = read_password_record()
            if override is not None:
                salt, digest, iterations = override
        except Exception:
            pass
        supplied = derive_password_hash(password, salt, iterations)
        if not hmac.compare_digest(supplied, digest) or not account["enabled"]:
            return None
        return AuthenticatedUser(account["subject_id"], account["username"], tuple(sorted(account["roles"])))
