"""Tests for Unit of Work pattern."""

from unittest.mock import MagicMock, Mock

import pytest

from core.unit_of_work import UnitOfWork, UnitOfWorkManager


class TestUnitOfWork:
    """Tests for UnitOfWork class."""

    @pytest.fixture
    def mock_db_manager(self):
        """Create mock database manager."""
        db_manager = Mock()
        mock_session = MagicMock()
        mock_session.__enter__.return_value = mock_session
        db_manager.get_session.return_value = mock_session
        return db_manager, mock_session

    def test_uow_creates_session_on_enter(self, mock_db_manager):
        """Test that UnitOfWork creates session on enter."""
        db_manager, mock_session = mock_db_manager

        uow = UnitOfWork(db_manager)
        assert uow._session is None

        with uow:
            assert uow._session is not None
            db_manager.get_session.assert_called_once()

    def test_uow_session_property_raises_when_not_started(self, mock_db_manager):
        """Test that accessing session without starting raises error."""
        db_manager, _ = mock_db_manager

        uow = UnitOfWork(db_manager)

        # getattr — явный вызов: свойство session должно бросить ошибку
        with pytest.raises(RuntimeError, match="UnitOfWork not started"):
            getattr(uow, "session")
        with pytest.raises(RuntimeError, match="UnitOfWork not started"):
            uow.commit()
        with pytest.raises(RuntimeError, match="UnitOfWork not started"):
            uow.rollback()
        db_manager.get_session.assert_not_called()

    def test_uow_session_property_returns_session(self, mock_db_manager):
        """Test that session property returns current session."""
        db_manager, mock_session = mock_db_manager

        uow = UnitOfWork(db_manager)
        with uow:
            assert uow.session is mock_session

    def test_uow_supports_real_database_manager(self):
        import os
        import tempfile

        from sqlalchemy import text

        from core.database import DatabaseManager

        with tempfile.TemporaryDirectory() as directory:
            db_manager = DatabaseManager(db_path=os.path.join(directory, "unit_of_work.db"))
            try:
                with UnitOfWork(db_manager) as uow:
                    assert uow.session.execute(text("SELECT 1")).scalar() == 1
            finally:
                db_manager.close()

    def test_uow_commits_on_success(self, mock_db_manager):
        """Test that UnitOfWork commits on successful exit."""
        db_manager, mock_session = mock_db_manager

        with UnitOfWork(db_manager):
            pass  # No exception

        mock_session.commit.assert_called_once()
        mock_session.__exit__.assert_called_once()

    def test_uow_rollback_on_exception(self, mock_db_manager):
        """Test that UnitOfWork rolls back on exception."""
        db_manager, mock_session = mock_db_manager

        with pytest.raises(ValueError):
            with UnitOfWork(db_manager):
                raise ValueError("Test error")

        mock_session.rollback.assert_called_once()
        mock_session.commit.assert_not_called()
        mock_session.__exit__.assert_called_once()

    def test_uow_manual_commit(self, mock_db_manager):
        """Test manual commit within UnitOfWork."""
        db_manager, mock_session = mock_db_manager

        with UnitOfWork(db_manager) as uow:
            uow.commit()

        mock_session.commit.assert_called_once()
        mock_session.__exit__.assert_called_once()

    def test_uow_manual_rollback(self, mock_db_manager):
        """Test manual rollback within UnitOfWork."""
        db_manager, mock_session = mock_db_manager

        with UnitOfWork(db_manager) as uow:
            uow.rollback()

        mock_session.rollback.assert_called_once()
        mock_session.commit.assert_not_called()
        mock_session.__exit__.assert_called_once()


class TestUnitOfWorkManager:
    """Tests for UnitOfWorkManager class."""

    @pytest.fixture
    def mock_db_manager(self):
        """Create mock database manager."""
        db_manager = Mock()
        mock_session = MagicMock()
        mock_session.__enter__.return_value = mock_session
        db_manager.get_session.return_value = mock_session
        return db_manager, mock_session

    def test_uow_manager_creates_uow(self, mock_db_manager):
        """Test that manager creates UnitOfWork instances."""
        db_manager, _ = mock_db_manager

        manager = UnitOfWorkManager(db_manager)

        with manager.start() as uow:
            assert isinstance(uow, UnitOfWork)
            assert uow.db_manager is db_manager

    def test_uow_manager_context_manager(self, mock_db_manager):
        """Test that manager's start is a proper context manager."""
        db_manager, mock_session = mock_db_manager

        manager = UnitOfWorkManager(db_manager)

        with manager.start() as uow:
            assert uow.session is mock_session

        mock_session.commit.assert_called_once()
        mock_session.__exit__.assert_called_once()


class TestRepositoryWithUnitOfWork:
    """Tests for BaseRepository integration with UnitOfWork."""

    @pytest.fixture
    def mock_db_manager(self):
        """Create mock database manager."""
        db_manager = Mock()
        mock_session = MagicMock()
        mock_session.__enter__.return_value = mock_session
        db_manager.get_session.return_value = mock_session
        return db_manager, mock_session

    def test_repository_uses_external_session(self, mock_db_manager):
        """Test that repository can use external session."""
        from core.models import Participant
        from core.repositories.base import BaseRepository

        db_manager, mock_session = mock_db_manager

        # Create repository with external session
        repo = BaseRepository(db_manager, Participant, session=mock_session)

        # get_session should yield the external session
        with repo.get_session() as session:
            assert session is mock_session

        # Should not create new session
        db_manager.get_session.assert_not_called()

    def test_repository_flushes_external_session_without_commit(self, mock_db_manager):
        from core.repositories.base import BaseRepository

        db_manager, mock_session = mock_db_manager
        model_class = Mock()
        instance = Mock()
        model_class.return_value = instance
        repository = BaseRepository(db_manager, model_class, session=mock_session)

        result = repository.create(name="Test")

        assert result is instance
        mock_session.add.assert_called_once_with(instance)
        mock_session.flush.assert_called_once_with()
        mock_session.commit.assert_not_called()
        mock_session.refresh.assert_called_once_with(instance)

    def test_repository_creates_own_session_without_external(self, mock_db_manager):
        """Test that repository creates its own session when no external provided."""
        from core.models import Participant
        from core.repositories.base import BaseRepository

        db_manager, mock_session = mock_db_manager

        # Create repository without external session
        repo = BaseRepository(db_manager, Participant)

        with repo.get_session() as session:
            assert session is mock_session

        db_manager.get_session.assert_called_once()

    def test_repository_commits_owned_session(self, mock_db_manager):
        from core.repositories.base import BaseRepository

        db_manager, mock_session = mock_db_manager
        model_class = Mock()
        instance = Mock()
        model_class.return_value = instance
        repository = BaseRepository(db_manager, model_class)

        repository.create(name="Test")

        mock_session.flush.assert_not_called()
        mock_session.commit.assert_called_once()
        mock_session.__exit__.assert_called_once()

    def test_set_session_method(self, mock_db_manager):
        """Test set_session method for chaining."""
        from core.models import Participant
        from core.repositories.base import BaseRepository

        db_manager, mock_session = mock_db_manager

        repo = BaseRepository(db_manager, Participant)

        # set_session should return self for chaining
        result = repo.set_session(mock_session)
        assert result is repo

        # Now get_session should use external session
        with repo.get_session() as session:
            assert session is mock_session


class TestUnitOfWorkIntegration:
    """Integration tests for UnitOfWork with repositories."""

    @pytest.fixture
    def mock_db_manager(self):
        """Create mock database manager."""
        db_manager = Mock()
        mock_session = MagicMock()
        mock_session.__enter__.return_value = mock_session
        db_manager.get_session.return_value = mock_session
        return db_manager, mock_session

    def test_multiple_repositories_same_transaction(self, mock_db_manager):
        """Test that multiple repositories can share the same transaction."""
        from core.models import Assignment, Participant
        from core.repositories.base import BaseRepository
        from core.unit_of_work import UnitOfWorkManager

        db_manager, mock_session = mock_db_manager

        manager = UnitOfWorkManager(db_manager)

        with manager.start() as uow:
            # Create repositories with shared session
            participant_repo = BaseRepository(db_manager, Participant, session=uow.session)
            assignment_repo = BaseRepository(db_manager, Assignment, session=uow.session)

            # Both should use the same session
            with participant_repo.get_session() as s1:
                with assignment_repo.get_session() as s2:
                    assert s1 is s2 is mock_session

        # Only one session should be created (by UnitOfWork)
        db_manager.get_session.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_repository_writes_are_committed_once_by_uow(self, mock_db_manager):
        from core.models import Assignment, Participant
        from core.repositories.base import BaseRepository
        from core.unit_of_work import UnitOfWorkManager

        db_manager, mock_session = mock_db_manager
        manager = UnitOfWorkManager(db_manager)

        with manager.start() as uow:
            participant_repo = BaseRepository(db_manager, Participant, session=uow.session)
            assignment_repo = BaseRepository(db_manager, Assignment, session=uow.session)
            participant_repo.create(name="Test", gender="male")
            assignment_repo.create(assignment_text="Test")
            mock_session.commit.assert_not_called()

        mock_session.commit.assert_called_once()
        assert mock_session.flush.call_count == 2
