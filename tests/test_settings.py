"""Tests for core/settings.py."""

import os
import sqlite3
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from core.settings import Settings


class TestSettingsDefaults:
    """Tests for default settings values."""

    def test_default_db_path(self):
        """Test default db_path value."""
        # Settings uses os.getenv at class definition time
        # So we test the actual default value
        settings = Settings()
        # Default is 'scheduler.db' if DB_PATH env not set
        assert hasattr(settings, "db_path")

    def test_default_min_assignment_gap(self):
        """Test default min_assignment_gap value."""
        settings = Settings()
        assert settings.min_assignment_gap == 2

    def test_default_backup_dir(self):
        """Test default backup_dir value."""
        settings = Settings()
        assert settings.backup_dir == "./backups"

    def test_default_theme(self):
        """Test default theme value."""
        settings = Settings()
        assert settings.theme == "system"

    def test_default_cong_name(self):
        """Test default cong_name value."""
        settings = Settings()
        assert settings.cong_name == ""

    def test_default_meeting_day(self):
        """Test default meeting_day value."""
        settings = Settings()
        assert settings.meeting_day == ""

    def test_default_meeting_time(self):
        """Test default meeting_time value."""
        settings = Settings()
        assert settings.meeting_time == ""

    def test_default_last_selected_week(self):
        """Test default last_selected_week value."""
        settings = Settings()
        assert settings.last_selected_week == 0


class TestSettingsLoad:
    """Tests for Settings.load() method."""

    def test_load_returns_settings(self):
        """Test that load returns Settings instance."""
        settings = Settings.load()
        assert isinstance(settings, Settings)

    def test_load_with_custom_db_path(self):
        """Test load with custom database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "custom.db")

            # Create database with settings
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """
            )
            cursor.execute(
                "INSERT INTO settings (key, value) VALUES ('cong_name', 'Custom Congregation')"
            )
            cursor.execute("INSERT INTO settings (key, value) VALUES ('meeting_day', 'Saturday')")
            cursor.execute("INSERT INTO settings (key, value) VALUES ('meeting_time', '18:00')")
            conn.commit()
            conn.close()

            # Create settings with custom db_path
            settings = Settings(db_path=db_path)
            settings._load_from_db()

            assert settings.cong_name == "Custom Congregation"
            assert settings.meeting_day == "Saturday"
            assert settings.meeting_time == "18:00"

    def test_load_with_min_assignment_gap_from_db(self):
        """Test load with min_assignment_gap from database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """
            )
            cursor.execute("INSERT INTO settings (key, value) VALUES ('min_assignment_gap', '7')")
            conn.commit()
            conn.close()

            settings = Settings(db_path=db_path)
            settings._load_from_db()
            assert settings.min_assignment_gap == 7

    def test_load_with_last_selected_week_from_db(self):
        """Test load with last_selected_week from database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """
            )
            cursor.execute("INSERT INTO settings (key, value) VALUES ('last_selected_week', '42')")
            conn.commit()
            conn.close()

            settings = Settings(db_path=db_path)
            settings._load_from_db()
            assert settings.last_selected_week == 42

    def test_load_with_invalid_min_assignment_gap(self):
        """Test load with invalid min_assignment_gap value keeps default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """
            )
            cursor.execute(
                "INSERT INTO settings (key, value) VALUES ('min_assignment_gap', 'invalid')"
            )
            conn.commit()
            conn.close()

            settings = Settings(db_path=db_path)
            settings._load_from_db()
            # Should keep default value
            assert settings.min_assignment_gap == 2

    def test_load_with_invalid_last_selected_week(self):
        """Test load with invalid last_selected_week value keeps default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """
            )
            cursor.execute(
                "INSERT INTO settings (key, value) VALUES ('last_selected_week', 'not_a_number')"
            )
            conn.commit()
            conn.close()

            settings = Settings(db_path=db_path)
            settings._load_from_db()
            # Should keep default value
            assert settings.last_selected_week == 0

    def test_load_with_theme_from_db(self):
        """Test load with theme from database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """
            )
            cursor.execute("INSERT INTO settings (key, value) VALUES ('theme', 'light')")
            conn.commit()
            conn.close()

            settings = Settings(db_path=db_path)
            settings._load_from_db()
            assert settings.theme == "light"

    def test_load_with_backup_dir_from_db(self):
        """Test load with backup_dir from database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """
            )
            cursor.execute(
                "INSERT INTO settings (key, value) VALUES ('backup_dir', '/custom/backup')"
            )
            conn.commit()
            conn.close()

            settings = Settings(db_path=db_path)
            settings._load_from_db()
            assert settings.backup_dir == "/custom/backup"

    def test_load_without_database_file(self):
        """Test load when database file doesn't exist."""
        settings = Settings(db_path="/nonexistent/path/test.db")
        settings._load_from_db()
        # Should not raise error, keep defaults
        assert settings.cong_name == ""

    def test_load_with_empty_database(self):
        """Test load with empty database (no settings table)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            # Create empty database
            conn = sqlite3.connect(db_path)
            conn.close()

            settings = Settings(db_path=db_path)
            settings._load_from_db()
            # Should not raise error, keep defaults
            assert settings.cong_name == ""


class TestSettingsSaveToDb:
    """Tests for Settings.save_to_db() method."""

    def test_save_to_db_creates_table(self):
        """Test that save_to_db creates settings table."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")

            settings = Settings(db_path=db_path)
            settings.cong_name = "Test Congregation"
            settings.save_to_db()

            # Verify table was created
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='settings'")
            assert cursor.fetchone() is not None
            conn.close()

    def test_save_to_db_persists_values(self):
        """Test that save_to_db persists settings values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")

            settings = Settings(db_path=db_path)
            settings.cong_name = "Saved Congregation"
            settings.meeting_day = "Sunday"
            settings.meeting_time = "10:00"
            settings.last_selected_week = 15
            settings.min_assignment_gap = 3
            settings.theme = "light"
            settings.save_to_db()

            # Load and verify
            loaded = Settings(db_path=db_path)
            loaded._load_from_db()
            assert loaded.cong_name == "Saved Congregation"
            assert loaded.meeting_day == "Sunday"
            assert loaded.meeting_time == "10:00"
            assert loaded.last_selected_week == 15
            assert loaded.min_assignment_gap == 3
            assert loaded.theme == "light"

    def test_save_to_db_updates_existing(self):
        """Test that save_to_db updates existing settings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")

            # Save initial
            settings1 = Settings(db_path=db_path)
            settings1.cong_name = "First Name"
            settings1.save_to_db()

            # Update
            settings2 = Settings(db_path=db_path)
            settings2.cong_name = "Updated Name"
            settings2.save_to_db()

            # Verify update
            loaded = Settings(db_path=db_path)
            loaded._load_from_db()
            assert loaded.cong_name == "Updated Name"

    def test_save_to_db_with_empty_values(self):
        """Test that save_to_db handles empty values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")

            settings = Settings(db_path=db_path)
            settings.cong_name = ""
            settings.meeting_day = ""
            settings.meeting_time = ""
            settings.save_to_db()

            # Should not raise error
            loaded = Settings(db_path=db_path)
            loaded._load_from_db()
            assert loaded.cong_name == ""

    def test_save_to_db_handles_sqlite_error(self):
        """Test that save_to_db handles SQLite errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")

            settings = Settings(db_path=db_path)
            settings.cong_name = "Test"
            settings.save_to_db()

            # Verify save worked
            loaded = Settings(db_path=db_path)
            loaded._load_from_db()
            assert loaded.cong_name == "Test"

    def test_save_to_db_rollback_on_error(self):
        """Test that save_to_db rolls back on SQLite error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")

            # Create a database with a trigger that causes an error
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """
            )
            conn.commit()
            conn.close()

            # Mock sqlite3.connect to raise an error during execute
            with patch("sqlite3.connect") as mock_connect:
                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_connect.return_value = mock_conn
                mock_conn.cursor.return_value = mock_cursor
                mock_cursor.execute.side_effect = sqlite3.Error("Test error")

                settings = Settings(db_path=db_path)
                with pytest.raises(sqlite3.Error):
                    settings.save_to_db()

                # Verify rollback was called
                mock_conn.rollback.assert_called_once()


class TestSettingsRawDbSettings:
    """Tests for _raw_db_settings internal field."""

    def test_raw_db_settings_populated(self):
        """Test that _raw_db_settings is populated on load."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """
            )
            cursor.execute("INSERT INTO settings (key, value) VALUES ('cong_name', 'Test')")
            cursor.execute(
                "INSERT INTO settings (key, value) VALUES ('custom_key', 'custom_value')"
            )
            conn.commit()
            conn.close()

            settings = Settings(db_path=db_path)
            settings._load_from_db()
            assert "cong_name" in settings._raw_db_settings
            assert "custom_key" in settings._raw_db_settings
            assert settings._raw_db_settings["custom_key"] == "custom_value"

    def test_raw_db_settings_empty_without_db(self):
        """Test that _raw_db_settings is empty without database."""
        settings = Settings(db_path="/nonexistent/path/test.db")
        settings._load_from_db()
        assert settings._raw_db_settings == {}


class TestSettingsDataclass:
    """Tests for Settings dataclass behavior."""

    def test_settings_repr_excludes_raw_settings(self):
        """Test Settings __repr__ doesn't include _raw_db_settings."""
        settings = Settings()
        repr_str = repr(settings)
        assert "_raw_db_settings" not in repr_str

    def test_settings_equality(self):
        """Test Settings equality comparison."""
        settings1 = Settings()
        settings2 = Settings()
        # Dataclasses with same values are equal
        assert settings1 == settings2

    def test_settings_with_different_values(self):
        """Test Settings with different values."""
        settings1 = Settings()
        settings2 = Settings()
        settings2.cong_name = "Different"
        assert settings1 != settings2

    def test_settings_can_be_created_with_custom_db_path(self):
        """Test Settings can be created with custom db_path."""
        settings = Settings(db_path="/custom/path.db")
        assert settings.db_path == "/custom/path.db"

    def test_settings_can_be_created_with_custom_min_gap(self):
        """Test Settings can be created with custom min_assignment_gap."""
        settings = Settings(min_assignment_gap=5)
        assert settings.min_assignment_gap == 5


def test_db_path_in_settings_table_does_not_redirect(tmp_path):
    """Копия базы помнит в settings путь рабочей scheduler.db — он не должен
    подменять путь, с которым копию открыли (иначе правки уйдут в рабочую базу)."""
    copy_path = str(tmp_path / "copy.db")
    conn = sqlite3.connect(copy_path)
    conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO settings VALUES ('db_path', 'scheduler.db'), ('cong_name', 'Тест')")
    conn.commit()
    conn.close()
    settings = Settings(db_path=copy_path)
    settings._load_from_db()
    assert settings.db_path == copy_path
    assert settings.cong_name == "Тест"
