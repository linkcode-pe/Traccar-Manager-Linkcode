"""Persistence base for repositories; no domain-specific repository is defined."""
from manager.errors import PersistenceError

class Repository:
    def __init__(self, connection):
        if connection is None:
            raise PersistenceError("A database connection is required")
        self._connection = connection

    @property
    def connection(self):
        return self._connection
