"""Stable, secret-safe error types for Manager infrastructure."""

class ManagerInfrastructureError(Exception):
    """Base class for infrastructure failures safe to present to an operator."""

class ConfigurationError(ManagerInfrastructureError):
    pass

class PersistenceError(ManagerInfrastructureError):
    pass

class ConnectionUnavailable(PersistenceError):
    pass

class TransactionError(PersistenceError):
    pass

class MigrationError(ManagerInfrastructureError):
    pass

class MigrationAuthorizationError(MigrationError):
    pass

class MigrationDiscoveryError(MigrationError):
    pass

class MigrationHistoryError(MigrationError):
    pass

class MigrationChecksumMismatch(MigrationHistoryError):
    pass

class MigrationRecoveryRequired(MigrationHistoryError):
    pass

class MigrationLockUnavailable(MigrationError):
    pass

class MigrationExecutionError(MigrationError):
    pass
