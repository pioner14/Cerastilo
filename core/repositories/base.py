"""
Base Repository class providing common CRUD operations.
"""

from contextlib import contextmanager
from typing import Generator, Generic, List, Optional, Type, TypeVar

from sqlalchemy.orm import Session

from core.database import DatabaseManager

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """Generic repository for SQLAlchemy models."""

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        model_class: Optional[Type[T]] = None,
        session: Optional[Session] = None,
    ):
        """
        Initialize repository.

        Args:
            db_manager: Database manager (optional if session is provided)
            model_class: SQLAlchemy model class
            session: External session for transaction participation
        """
        if model_class is None:
            raise ValueError("model_class must be provided")
        if db_manager is None and session is None:
            raise ValueError("Either db_manager or session must be provided")
        self.db = db_manager
        self.model_class: Type[T] = model_class
        self._external_session = session

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """Get database session - external or create new one."""
        if self._external_session is not None:
            yield self._external_session
        else:
            session_or_cm = self.db.get_session()
            # Support both plain sessions and context manager sessions
            if hasattr(session_or_cm, "__enter__"):
                with session_or_cm as session:
                    yield session
            else:
                try:
                    yield session_or_cm
                finally:
                    session_or_cm.close()

    def set_session(self, session: Optional[Session]) -> "BaseRepository[T]":
        """Set external session for transaction participation.

        Returns self for method chaining.
        """
        self._external_session = session
        return self

    def get_by_id(self, id: int) -> Optional[T]:
        """Retrieve entity by primary key."""
        with self.get_session() as session:
            return session.get(self.model_class, id)

    def get_all(self, limit: int = None, offset: int = None) -> List[T]:
        """Retrieve all entities."""
        from sqlalchemy import select

        with self.get_session() as session:
            query = select(self.model_class)
            if offset:
                query = query.offset(offset)
            if limit:
                query = query.limit(limit)
            return session.execute(query).scalars().all()

    def find(self, **filters) -> List[T]:
        """Find entities matching filters."""
        from sqlalchemy import and_, select

        with self.get_session() as session:
            query = select(self.model_class)
            conditions = []
            for key, value in filters.items():
                if hasattr(self.model_class, key):
                    conditions.append(getattr(self.model_class, key) == value)
            if conditions:
                query = query.where(and_(*conditions))
            return session.execute(query).scalars().all()

    def _persist(self, session: Session) -> None:
        if self._external_session is None:
            session.commit()
        else:
            session.flush()

    def _rollback(self, session: Session) -> None:
        if self._external_session is None:
            session.rollback()

    def create(self, **data) -> T:
        """Create a new entity."""
        with self.get_session() as session:
            instance = self.model_class(**data)
            session.add(instance)
            self._persist(session)
            session.refresh(instance)
            return instance

    def update(self, id: int, **data) -> Optional[T]:
        """Update an existing entity."""
        with self.get_session() as session:
            instance = session.get(self.model_class, id)
            if instance:
                for key, value in data.items():
                    if hasattr(instance, key):
                        setattr(instance, key, value)
                self._persist(session)
                session.refresh(instance)
            return instance

    def delete(self, id: int) -> bool:
        """Delete entity by id."""
        with self.get_session() as session:
            instance = session.get(self.model_class, id)
            if instance:
                session.delete(instance)
                self._persist(session)
                return True
            return False

    def count(self) -> int:
        """Count total entities."""
        from sqlalchemy import func, select

        with self.get_session() as session:
            query = select(func.count()).select_from(self.model_class)
            return session.execute(query).scalar()
