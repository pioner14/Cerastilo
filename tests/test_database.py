"""Tests for core/database.py."""

import os
import tempfile
from datetime import date

import pytest

from core.database import DatabaseManager
from core.models import AssignmentConfig, Group, Setting, Week


@pytest.fixture(autouse=True)
def close_database_managers(monkeypatch):
    managers = []
    original_init = DatabaseManager.__init__

    def tracked_init(self, *args, **kwargs):
        managers.append(self)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(DatabaseManager, "__init__", tracked_init)
    yield
    for manager in managers:
        manager.close()


class TestDatabaseManagerInit:
    """Tests for DatabaseManager initialization."""

    def test_init_creates_database(self):
        """Test that init creates database file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db_manager = DatabaseManager(db_path=db_path)

            assert os.path.exists(db_path)

    def test_init_creates_tables(self):
        """Test that init creates all tables."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db_manager = DatabaseManager(db_path=db_path)

            # Check tables exist by querying
            with db_manager.get_session() as session:
                # Should not raise error
                session.query(Setting).all()
                session.query(Group).all()
                session.query(AssignmentConfig).all()

    def test_get_session_returns_session(self):
        """Test that get_session returns a session."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db_manager = DatabaseManager(db_path=db_path)

            session = db_manager.get_session()
            assert session is not None

    def test_init_default_settings(self):
        """Test that init creates default settings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db_manager = DatabaseManager(db_path=db_path)

            # Check default setting
            with db_manager.get_session() as session:
                setting = session.get(Setting, "min_assignment_gap")
                assert setting is not None
                assert setting.value == "2"

    def test_init_default_groups(self):
        """Test that init creates default groups."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db_manager = DatabaseManager(db_path=db_path)

            with db_manager.get_session() as session:
                groups = session.query(Group).all()
                assert len(groups) == 6
                assert groups[0].name == "Группа 1"

    def test_init_default_config(self):
        """Test that init creates default assignment configs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db_manager = DatabaseManager(db_path=db_path)

            with db_manager.get_session() as session:
                configs = session.query(AssignmentConfig).all()
                assert len(configs) > 0
                # Check some configs
                chairman = (
                    session.query(AssignmentConfig)
                    .filter_by(section="fixed", position="chairman")
                    .first()
                )
                assert chairman is not None
                assert chairman.assignment_name == "Председатель"


class TestDatabaseManagerSettings:
    """Tests for DatabaseManager settings methods."""

    def test_get_setting_existing(self):
        """Test getting an existing setting."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db_manager = DatabaseManager(db_path=db_path)

            # Default setting exists
            value = db_manager.get_setting("min_assignment_gap")
            assert value == "2"

    def test_get_setting_nonexistent(self):
        """Test getting a non-existent setting."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db_manager = DatabaseManager(db_path=db_path)

            value = db_manager.get_setting("nonexistent_key")
            assert value is None

    def test_get_setting_with_default(self):
        """Test getting a setting with default value."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db_manager = DatabaseManager(db_path=db_path)

            value = db_manager.get_setting("nonexistent_key", default="default_value")
            assert value == "default_value"

    def test_save_setting_new(self):
        """Test saving a new setting."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db_manager = DatabaseManager(db_path=db_path)

            db_manager.save_setting("new_key", "new_value")

            value = db_manager.get_setting("new_key")
            assert value == "new_value"

    def test_save_setting_update_existing(self):
        """Test updating an existing setting."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db_manager = DatabaseManager(db_path=db_path)

            # Create initial
            db_manager.save_setting("test_key", "initial_value")

            # Update
            db_manager.save_setting("test_key", "updated_value")

            value = db_manager.get_setting("test_key")
            assert value == "updated_value"


class TestDatabaseManagerSpecialEvent:
    """Tests for DatabaseManager special event methods."""

    def test_get_week_special_event_none(self):
        """Test getting special event for week without event."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db_manager = DatabaseManager(db_path=db_path)

            # Create a week
            with db_manager.get_session() as session:
                week = Week(week_title="Test Week", start_date=date(2024, 1, 1), songs="1,2,3")
                session.add(week)
                session.commit()
                week_id = week.id

            event = db_manager.get_week_special_event(week_id)
            assert event is None

    def test_get_week_special_event_with_event(self):
        """Test getting special event for week with event."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db_manager = DatabaseManager(db_path=db_path)

            # Create a week with event
            with db_manager.get_session() as session:
                week = Week(
                    week_title="Test Week",
                    start_date=date(2024, 1, 1),
                    songs="1,2,3",
                    special_event="memorial",
                )
                session.add(week)
                session.commit()
                week_id = week.id

            event = db_manager.get_week_special_event(week_id)
            assert event == "memorial"

    def test_get_week_special_event_nonexistent_week(self):
        """Test getting special event for non-existent week."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db_manager = DatabaseManager(db_path=db_path)

            event = db_manager.get_week_special_event(999)
            assert event is None

    def test_set_week_special_event(self):
        """Test setting special event for a week."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db_manager = DatabaseManager(db_path=db_path)

            # Create a week
            with db_manager.get_session() as session:
                week = Week(week_title="Test Week", start_date=date(2024, 1, 1), songs="1,2,3")
                session.add(week)
                session.commit()
                week_id = week.id

            # Set event
            result = db_manager.set_week_special_event(week_id, "assembly")
            assert result is True

            # Verify
            event = db_manager.get_week_special_event(week_id)
            assert event == "assembly"

    def test_set_week_special_event_clear(self):
        """Test clearing special event for a week."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db_manager = DatabaseManager(db_path=db_path)

            # Create a week with event
            with db_manager.get_session() as session:
                week = Week(
                    week_title="Test Week",
                    start_date=date(2024, 1, 1),
                    songs="1,2,3",
                    special_event="memorial",
                )
                session.add(week)
                session.commit()
                week_id = week.id

            # Clear event
            result = db_manager.set_week_special_event(week_id, None)
            assert result is True

            # Verify
            event = db_manager.get_week_special_event(week_id)
            assert event is None

    def test_set_week_special_event_nonexistent_week(self):
        """Test setting special event for non-existent week."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db_manager = DatabaseManager(db_path=db_path)

            result = db_manager.set_week_special_event(999, "memorial")
            assert result is False

    def test_set_week_special_event_empty_string(self):
        """Test setting special event with empty string."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db_manager = DatabaseManager(db_path=db_path)

            # Create a week
            with db_manager.get_session() as session:
                week = Week(week_title="Test Week", start_date=date(2024, 1, 1), songs="1,2,3")
                session.add(week)
                session.commit()
                week_id = week.id

            # Set with empty string (should clear)
            result = db_manager.set_week_special_event(week_id, "")
            assert result is True


class TestDatabaseManagerDefaultConfig:
    """Tests for default assignment config initialization."""

    def test_default_config_not_recreated(self):
        """Test that default configs are not recreated if exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db_manager = DatabaseManager(db_path=db_path)

            # Get initial count
            with db_manager.get_session() as session:
                initial_count = session.query(AssignmentConfig).count()

            # Create new manager (simulates restart)
            db_manager2 = DatabaseManager(db_path=db_path)

            # Count should be same
            with db_manager.get_session() as session:
                final_count = session.query(AssignmentConfig).count()

            assert initial_count == final_count


class TestDatabaseManagerDefaultGroups:
    """Tests for default groups initialization."""

    def test_default_groups_not_recreated(self):
        """Test that default groups are not recreated if exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db_manager = DatabaseManager(db_path=db_path)

            # Get initial count
            with db_manager.get_session() as session:
                initial_count = session.query(Group).count()

            # Create new manager (simulates restart)
            db_manager2 = DatabaseManager(db_path=db_path)

            # Count should be same
            with db_manager.get_session() as session:
                final_count = session.query(Group).count()

            assert initial_count == final_count

    def test_groups_are_active_by_default(self):
        """Test that all default groups are active."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db_manager = DatabaseManager(db_path=db_path)

            with db_manager.get_session() as session:
                groups = session.query(Group).all()
                for group in groups:
                    assert group.is_active is True
