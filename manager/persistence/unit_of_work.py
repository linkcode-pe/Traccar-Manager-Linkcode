"""Explicit transaction boundary for application services."""
from manager.errors import TransactionError

class UnitOfWork:
    """Owns one connection and commits on success, rolls back on exception."""
    def __init__(self, connection_factory):
        self._factory = connection_factory
        self.connection = None
        self._closed = False

    def __enter__(self):
        if self.connection is not None:
            raise TransactionError("UnitOfWork instances cannot be re-entered")
        self.connection = self._factory.connect()
        try:
            self.connection.begin()
        except Exception:
            self.connection.close()
            self._closed = True
            raise TransactionError("Could not begin the Manager transaction") from None
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self.connection is None or self._closed:
            return False
        try:
            if exc_type is None:
                self.connection.commit()
            else:
                self.connection.rollback()
        except Exception:
            try:
                self.connection.rollback()
            except Exception:
                pass
            raise TransactionError("Could not finish the Manager transaction") from None
        finally:
            self.connection.close()
            self._closed = True
        return False
