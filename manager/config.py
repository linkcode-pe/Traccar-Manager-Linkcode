"""Explicit Manager DB settings and nonproduction destination identity policy."""
from dataclasses import dataclass, field
import os
from typing import Mapping, Optional

from manager.errors import ConfigurationError

@dataclass(frozen=True)
class AuthorizedNonprodDestination:
    hostname: str
    database: str
    username: str
    effective_user: str
    port: int
    ca_path: str
    resolve_address: str
    destination_id: str

# This exact tuple is the already-validated isolated Manager test target. New
# targets require a reviewed source change; environment labels alone are not trust.
AUTHORIZED_NONPROD_DESTINATIONS = (
    AuthorizedNonprodDestination(
        hostname="MySQL_Server_8.0.42_Auto_Generated_Server_Certificate",
        database="traccar-tem",
        username="linkcode2",
        effective_user="linkcode2@localhost",
        port=3306,
        ca_path="/var/lib/mysql/ca.pem",
        resolve_address="127.0.0.1",
        destination_id="manager-nonprod-traccar-tem-v1",
    ),
)

@dataclass(frozen=True)
class DatabaseSettings:
    """MySQL settings; credentials are excluded from representation."""
    environment: str
    host: str
    database: str
    username: str
    password: str = field(repr=False, compare=False)
    port: int = 3306
    connect_timeout: int = 5
    ssl_ca: Optional[str] = None

    @classmethod
    def from_environment(cls, environ: Optional[Mapping[str, str]] = None):
        source = os.environ if environ is None else environ
        environment = source.get("TRACCAR_MANAGER_DB_ENVIRONMENT", "").strip().lower()
        if environment != "nonprod":
            raise ConfigurationError("Manager DB environment must be explicitly marked nonprod")
        names = {
            "host": "TRACCAR_MANAGER_DB_HOST",
            "database": "TRACCAR_MANAGER_DB_NAME",
            "username": "TRACCAR_MANAGER_DB_USER",
            "password": "TRACCAR_MANAGER_DB_PASSWORD",
        }
        values = {key: source.get(env_name, "") for key, env_name in names.items()}
        missing = [env_name for key, env_name in names.items() if not values[key]]
        if missing:
            raise ConfigurationError("Missing required Manager DB environment settings: " + ", ".join(missing))
        try:
            port = int(source.get("TRACCAR_MANAGER_DB_PORT", "3306"))
            timeout = int(source.get("TRACCAR_MANAGER_DB_CONNECT_TIMEOUT", "5"))
        except (TypeError, ValueError):
            raise ConfigurationError("Manager DB port and timeout must be integers") from None
        if not 1 <= port <= 65535 or timeout < 1:
            raise ConfigurationError("Manager DB port or timeout is outside its allowed range")
        return cls(
            environment=environment, host=values["host"], database=values["database"],
            username=values["username"], password=values["password"], port=port,
            connect_timeout=timeout, ssl_ca=source.get("TRACCAR_MANAGER_DB_SSL_CA") or None,
        )

def authorize_nonprod_destination(settings: DatabaseSettings) -> AuthorizedNonprodDestination:
    if settings.environment != "nonprod":
        raise ConfigurationError("Manager DB environment must be explicitly marked nonprod")
    for target in AUTHORIZED_NONPROD_DESTINATIONS:
        if (settings.host, settings.database, settings.username, settings.port, settings.ssl_ca) == (
            target.hostname, target.database, target.username, target.port, target.ca_path
        ):
            return target
    raise ConfigurationError("Configured Manager DB destination is not in the nonproduction allowlist")
