"""
Unit of Work pattern for transaction management.
"""

from types import TracebackType
from typing import Optional, Type

from sqlalchemy.orm import Session

from core.database import DatabaseManager


class UnitOfWork:
    """Manage a single transactional session."""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self._session: Optional[Session] = None
        self._session_context: Optional[Session] = None
        self._is_completed = False

    def __enter__(self) -> "UnitOfWork":
        if self._session is not None:
            raise RuntimeError("UnitOfWork already started")
        session = self.db_manager.get_session()
        self._session_context = session
        self._session = session.__enter__()
        self._is_completed = False
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        try:
            if not self._is_completed:
                if exc_type is None:
                    self.commit()
                else:
                    self.rollback()
        finally:
            if self._session_context is not None:
                self._session_context.__exit__(exc_type, exc_val, exc_tb)
            elif self._session is not None:
                self._session.close()
            self._session = None
            self._session_context = None

    @property
    def session(self) -> Session:
        if self._session is None:
            raise RuntimeError("UnitOfWork not started")
        return self._session

    def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("UnitOfWork not started")
        if self._is_completed:
            raise RuntimeError("UnitOfWork transaction already completed")
        self._session.commit()
        self._is_completed = True

    def rollback(self) -> None:
        if self._session is None:
            raise RuntimeError("UnitOfWork not started")
        if self._is_completed:
            raise RuntimeError("UnitOfWork transaction already completed")
        self._session.rollback()
        self._is_completed = True


class UnitOfWorkManager:
    """Create UnitOfWork instances bound to a database manager."""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    def start(self) -> UnitOfWork:
        return UnitOfWork(self.db_manager)
