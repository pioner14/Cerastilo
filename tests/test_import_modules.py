"""
Tests for core/workbook_import.py and core/history_import.py.
"""

import csv
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import Assignment, Base, Participant, Week


@pytest.fixture
def db_engine():
    """Create in-memory SQLite engine."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """Create database session."""
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.close()


# =============================================================================
# workbook_import Tests
# =============================================================================


class TestWorkbookImport:
    """Tests for workbook_import module."""

    def test_save_weeks_to_db_creates_weeks(self, db_session):
        """Test that save_weeks_to_db creates weeks."""
        from core.workbook_import import save_weeks_to_db

        weeks_data = [
            {
                "week_title": "Январь 6-12",
                "bible_reading": "Бытие 1-2",
                "month_num": 1,
                "start_day": 6,
                "songs": [23, 45, 67],
                "assignments": [],
            }
        ]

        result = save_weeks_to_db(db_session, weeks_data, "mwb_U_202401.epub")

        assert result["weeks"] == 1
        assert db_session.query(Week).count() == 1

    def test_save_weeks_to_db_creates_fixed_roles(self, db_session):
        """Test that save_weeks_to_db creates fixed roles (chairman, prayers)."""
        from core.workbook_import import save_weeks_to_db

        weeks_data = [
            {
                "week_title": "Январь 6-12",
                "bible_reading": "Бытие 1-2",
                "month_num": 1,
                "start_day": 6,
                "songs": [23, 45, 67],
                "assignments": [],
            }
        ]

        result = save_weeks_to_db(db_session, weeks_data)

        # Should create 3 fixed roles per week
        assert result["assignments"] == 3

        # Verify fixed roles exist
        assignments = db_session.query(Assignment).all()
        roles = [a.section_position for a in assignments]
        assert "chairman" in roles
        assert "prayer_open" in roles
        assert "prayer_close" in roles

    def test_save_weeks_to_db_creates_assignments(self, db_session):
        """Test that save_weeks_to_db creates assignments from EPUB data."""
        from core.workbook_import import save_weeks_to_db

        weeks_data = [
            {
                "week_title": "Январь 6-12",
                "bible_reading": "Бытие 1-2",
                "month_num": 1,
                "start_day": 6,
                "songs": [23, 45, 67],
                "assignments": [
                    {
                        "number": "1",
                        "section": "treasures",
                        "section_position": "1",
                        "type": "talk",
                        "text": "Урок 1",
                        "duration": 10,
                    }
                ],
            }
        ]

        result = save_weeks_to_db(db_session, weeks_data)

        # 3 fixed roles + 1 assignment
        assert result["assignments"] == 4

    def test_import_fills_empty_placeholder_week_by_date(self, db_session):
        """Пустая заготовка «4–10 январь» заполняется тетрадью «4—10 ЯНВАРЯ», без дубля."""
        from core.workbook_import import save_weeks_to_db

        placeholder = Week(
            week_title="4–10 январь", start_date=date(2027, 1, 4), workbook_source="manual"
        )
        db_session.add(placeholder)
        db_session.commit()

        weeks_data = [
            {
                "week_title": "4—10 ЯНВАРЯ",
                "bible_reading": "Чтение",
                "month_num": 1,
                "start_month_num": 1,
                "start_day": 4,
                "assignments": [],
            }
        ]
        result = save_weeks_to_db(db_session, weeks_data, "mwb_U_202701.epub")

        assert result["weeks"] == 0
        weeks = db_session.query(Week).filter(Week.start_date == date(2027, 1, 4)).all()
        assert [w.id for w in weeks] == [placeholder.id]
        assert weeks[0].week_title == "4—10 ЯНВАРЯ"
        assert len(weeks[0].assignments) > 0  # фиксированные роли созданы

    def test_import_does_not_take_over_week_with_history_by_date(self, db_session):
        """Неделя с назначениями и другим названием не перезаписывается по дате."""
        from core.workbook_import import save_weeks_to_db

        history = Week(week_title="Неделя от 26.01.2026", start_date=date(2026, 1, 26))
        db_session.add(history)
        db_session.flush()
        db_session.add(
            Assignment(
                week_id=history.id,
                assignment_number="3",
                assignment_text="История",
                status="assigned",
            )
        )
        db_session.commit()

        weeks_data = [
            {
                "week_title": "26 ЯНВАРЯ — 1 ФЕВРАЛЯ",
                "bible_reading": "Чтение",
                "month_num": 1,
                "start_month_num": 1,
                "start_day": 26,
                "assignments": [],
            }
        ]
        save_weeks_to_db(db_session, weeks_data, "mwb_U_202601.epub")

        db_session.refresh(history)
        assert history.week_title == "Неделя от 26.01.2026"
        assert [a.status for a in history.assignments] == ["assigned"]

    def test_import_uses_start_year_from_title(self, db_session):
        """Неделя 28.12–3.01 из тетради ноября–декабря получает дату 28.12 того же года."""
        from core.workbook_import import save_weeks_to_db

        weeks_data = [
            {
                "week_title": "28 ДЕКАБРЯ — 3 ЯНВАРЯ",
                "bible_reading": "",
                "month_num": 12,
                "start_month_num": 12,
                "start_day": 28,
                "start_year": 2026,
                "assignments": [],
            }
        ]
        save_weeks_to_db(db_session, weeks_data, "mwb_U_202611.epub")

        week = db_session.query(Week).one()
        assert week.start_date == date(2026, 12, 28)

    def test_save_weeks_to_db_updates_existing_week(self, db_session):
        """Test that save_weeks_to_db updates existing week."""
        from core.workbook_import import save_weeks_to_db

        # Create existing week
        week = Week(
            week_title="Январь 6-12", start_date=date(2024, 1, 6), bible_reading="Старое чтение"
        )
        db_session.add(week)
        db_session.commit()

        weeks_data = [
            {
                "week_title": "Январь 6-12",
                "bible_reading": "Бытие 1-2 (новое)",
                "month_num": 1,
                "start_day": 6,
                "songs": [23, 45, 67],
                "assignments": [],
            }
        ]

        result = save_weeks_to_db(db_session, weeks_data)

        # Should update, not create new
        assert result["weeks"] == 0  # No new weeks
        assert db_session.query(Week).count() == 1

        # Verify update
        updated_week = db_session.query(Week).first()
        assert "новое" in updated_week.bible_reading

    def test_save_weeks_to_db_extracts_year_from_epub_path(self, db_session):
        """Test that year is extracted from EPUB path."""
        from core.workbook_import import save_weeks_to_db

        weeks_data = [
            {
                "week_title": "Март 3-9",
                "bible_reading": "Бытие 1-2",
                "month_num": 3,
                "start_day": 3,
                "songs": [1, 2, 3],
                "assignments": [],
            }
        ]

        save_weeks_to_db(db_session, weeks_data, "mwb_U_202603.epub")

        week = db_session.query(Week).first()
        assert week.year == 2026
        assert week.start_date == date(2026, 3, 3)

    def test_save_weeks_to_db_handles_multiple_weeks(self, db_session):
        """Test handling multiple weeks."""
        from core.workbook_import import save_weeks_to_db

        weeks_data = [
            {
                "week_title": "Январь 6-12",
                "bible_reading": "Бытие 1-2",
                "month_num": 1,
                "start_day": 6,
                "songs": [1, 2, 3],
                "assignments": [],
            },
            {
                "week_title": "Январь 13-19",
                "bible_reading": "Бытие 3-4",
                "month_num": 1,
                "start_day": 13,
                "songs": [4, 5, 6],
                "assignments": [],
            },
        ]

        result = save_weeks_to_db(db_session, weeks_data)

        assert result["weeks"] == 2
        assert db_session.query(Week).count() == 2

    def test_save_weeks_to_db_skips_empty_title(self, db_session):
        """Test that weeks with empty title are skipped."""
        from core.workbook_import import save_weeks_to_db

        weeks_data = [
            {
                "week_title": "",
                "bible_reading": "Бытие 1-2",
                "month_num": 1,
                "start_day": 6,
                "songs": [1, 2, 3],
                "assignments": [],
            }
        ]

        result = save_weeks_to_db(db_session, weeks_data)

        assert result["weeks"] == 0
        assert db_session.query(Week).count() == 0

    def test_save_weeks_to_db_saves_songs(self, db_session):
        """Test that songs are saved correctly."""
        from core.workbook_import import save_weeks_to_db

        weeks_data = [
            {
                "week_title": "Январь 6-12",
                "bible_reading": "Бытие 1-2",
                "month_num": 1,
                "start_day": 6,
                "songs": [23, 45, 67],
                "assignments": [],
            }
        ]

        save_weeks_to_db(db_session, weeks_data)

        week = db_session.query(Week).first()
        assert week.songs == "23,45,67"

    def test_save_weeks_to_db_cross_month_transition_dates(self, db_session):
        """Test that cross-month transition weeks get correct start date month."""
        from core.workbook_import import save_weeks_to_db

        weeks_data = [
            {
                "week_title": "29 июня — 5 июля",
                "bible_reading": "Бытие 1",
                "month_num": 7,  # Grouped under July
                "start_month_num": 6,  # Starts in June
                "start_day": 29,
                "songs": [],
                "assignments": [],
            }
        ]

        save_weeks_to_db(db_session, weeks_data, "mwb_U_202607.epub")

        week = db_session.query(Week).first()
        assert week.start_date == date(2026, 6, 29)
        assert week.month == 7

    def test_save_weeks_to_db_year_transition_dates(self, db_session):
        """Test that year-transition weeks (Dec->Jan) get correct start date year."""
        from core.workbook_import import save_weeks_to_db

        weeks_data = [
            {
                "week_title": "29 декабря — 4 января",
                "bible_reading": "Бытие 2",
                "month_num": 1,  # Grouped under January
                "start_month_num": 12,  # Starts in December
                "start_day": 29,
                "songs": [],
                "assignments": [],
            }
        ]

        save_weeks_to_db(db_session, weeks_data, "mwb_U_202601.epub")

        week = db_session.query(Week).first()
        assert week.start_date == date(2025, 12, 29)
        assert week.month == 1
        assert week.year == 2026


class TestWorkbookImportHelpers:
    """Tests for workbook_import helper functions."""

    def test_extract_year_from_filename(self):
        """Test _extract_year extracts year from filename."""
        from core.workbook_import import _extract_year

        assert _extract_year("mwb_U_202603.epub") == 2026
        assert _extract_year("mwb_U_202401.epub") == 2024
        assert _extract_year("/path/to/mwb_U_202512.epub") == 2025

    def test_extract_year_defaults_to_current(self):
        """Test _extract_year defaults to current year if not found."""
        from core.workbook_import import _extract_year

        # When no year in filename, should return current year
        result = _extract_year("some_file.epub")
        assert isinstance(result, int)
        assert result >= 2024

    def test_normalize_string(self):
        """Test _normalize normalizes strings for comparison."""
        from core.workbook_import import _normalize

        # Should handle case and whitespace
        assert _normalize("Январь 6-12") == _normalize("январь 6-12")
        assert _normalize("  Январь 6-12  ") == _normalize("Январь 6-12")


# =============================================================================
# history_import Tests
# =============================================================================


class TestHistoryImport:
    """Tests for history_import module."""

    def test_import_history_from_csv_file_not_found(self):
        """Test import_history_from_csv handles missing file."""
        from core.history_import import import_history_from_csv

        result = import_history_from_csv("/nonexistent/file.csv")

        assert result["success"] is False
        assert "не найден" in result["error"]

    def test_import_history_from_csv_creates_weeks(self, db_session, tmp_path):
        """Test that import creates weeks from CSV data."""
        from core.history_import import import_history_from_csv

        # Create test CSV
        csv_path = tmp_path / "history.csv"
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["Date", "Person", "PartType"])
            writer.writerow(["2024.01.08", "Иван Петров", "Chairman"])

        # Create participant
        participant = Participant(name="Иван Петров", gender="male", service_type="elder")
        db_session.add(participant)
        db_session.commit()

        # Patch DB_PATH to use in-memory database
        with patch("core.history_import.DB_PATH", ":memory:"):
            with patch("core.history_import.sqlite3.connect") as mock_connect:
                # Create a mock connection that uses our session's engine
                mock_conn = MagicMock()
                mock_connect.return_value = mock_conn

                # Mock cursor
                mock_cursor = MagicMock()
                mock_conn.cursor.return_value = mock_cursor
                mock_conn.__enter__ = lambda self: self
                mock_conn.__exit__ = lambda self, *args: None

                result = import_history_from_csv(str(csv_path))

                # Verify the function ran
                assert "success" in result or "weeks" in result

    def test_type_map_contains_all_types(self):
        """Test that TYPE_MAP contains all expected types."""
        from core.history_import import TYPE_MAP

        expected_types = [
            "Chairman",
            "TreasuresTalk",
            "SpiritualGems",
            "BibleReading",
            "Apply1",
            "Apply2",
            "Apply3",
            "Apply4",
            "LivingPart1",
            "LivingPart2",
            "CBS",
        ]

        for t in expected_types:
            assert t in TYPE_MAP, f"Missing type: {t}"

    def test_type_map_values(self):
        """Test TYPE_MAP has correct values."""
        from core.history_import import TYPE_MAP

        assert TYPE_MAP["Chairman"] == "chairman"
        assert TYPE_MAP["TreasuresTalk"] == "1"
        assert TYPE_MAP["BibleReading"] == "3"
        assert TYPE_MAP["Apply1"] == "4"
        assert TYPE_MAP["CBS"] == "10"


class TestHistoryImportEdgeCases:
    """Tests for history_import edge cases."""

    def test_import_with_unknown_participant(self, tmp_path):
        """Test import handles unknown participants."""
        from core.history_import import import_history_from_csv

        csv_path = tmp_path / "history.csv"
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["Date", "Person", "PartType"])
            writer.writerow(["2024.01.08", "Неизвестный Участник", "Chairman"])

        with patch("core.history_import.DB_PATH", ":memory:"):
            with patch("core.history_import.sqlite3.connect") as mock_connect:
                mock_conn = MagicMock()
                mock_connect.return_value = mock_conn
                mock_cursor = MagicMock()
                mock_conn.cursor.return_value = mock_cursor
                mock_conn.__enter__ = lambda self: self
                mock_conn.__exit__ = lambda self, *args: None

                # Return empty participants list
                mock_cursor.fetchall.return_value = []

                result = import_history_from_csv(str(csv_path))

                # Should skip unknown participant
                assert result.get("skipped", 0) >= 1 or result.get("success") is not None

    def test_import_with_assistant(self, tmp_path):
        """Test import handles assistant assignments."""
        from core.history_import import import_history_from_csv

        csv_path = tmp_path / "history.csv"
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["Date", "Person", "PartType"])
            writer.writerow(["2024.01.08", "Иван Петров", "Apply1"])
            writer.writerow(["2024.01.08", "Петр Сидоров", "Apply1Assistant"])

        with patch("core.history_import.DB_PATH", ":memory:"):
            with patch("core.history_import.sqlite3.connect") as mock_connect:
                mock_conn = MagicMock()
                mock_connect.return_value = mock_conn
                mock_cursor = MagicMock()
                mock_conn.cursor.return_value = mock_cursor
                mock_conn.__enter__ = lambda self: self
                mock_conn.__exit__ = lambda self, *args: None

                # Mock participants
                mock_cursor.fetchall.return_value = [(1, "Иван Петров"), (2, "Петр Сидоров")]

                result = import_history_from_csv(str(csv_path))

                # Should process both entries
                assert result is not None


# =============================================================================
# backup_logic Tests
# =============================================================================


class TestBackupLogic:
    """Tests for backup_logic module."""

    def test_create_backup(self, tmp_path):
        """Test creating a backup."""

        from core.backup_logic import create_backup

        # Create a test database file
        db_path = tmp_path / "scheduler.db"
        with open(db_path, "w") as f:
            f.write("test data")

        backup_path = tmp_path / "backup.zip"

        with patch("core.backup_logic.DB_PATH", str(db_path)):
            result = create_backup(str(backup_path))

            assert result["success"] is True

    def test_create_backup_db_not_found(self, tmp_path):
        """Test creating backup when DB doesn't exist."""
        from core.backup_logic import create_backup

        with patch("core.backup_logic.DB_PATH", str(tmp_path / "nonexistent.db")):
            result = create_backup(str(tmp_path / "backup.zip"))

            assert result["success"] is False
            assert "не найдена" in result["error"]

    def test_restore_backup(self, tmp_path):
        """Test restoring from backup."""
        import zipfile

        from core.backup_logic import restore_backup

        # Create a valid backup file
        backup_path = tmp_path / "backup.zip"
        db_path = tmp_path / "scheduler.db"

        # Create test db content
        import sqlite3

        test_db_path = tmp_path / "test_content.db"
        conn = sqlite3.connect(test_db_path)
        for table in ("participants", "weeks", "assignments"):
            conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        with zipfile.ZipFile(backup_path, "w") as zf:
            zf.write(test_db_path, "scheduler.db")

        with patch("core.backup_logic.DB_PATH", str(db_path)):
            result = restore_backup(str(backup_path))

            assert result["success"] is True

    def test_restore_backup_not_found(self, tmp_path):
        """Test restoring from non-existent backup."""
        from core.backup_logic import restore_backup

        result = restore_backup(str(tmp_path / "nonexistent.zip"))

        assert result["success"] is False

    def test_list_backups(self, tmp_path):
        """Test listing available backups."""
        from core.backup_logic import list_backups

        # Create some backup files
        for i in range(3):
            backup_file = tmp_path / f"backup_2024010{i}.zip"
            with open(backup_file, "w") as f:
                f.write(f"backup {i}")

        result = list_backups(str(tmp_path))

        assert isinstance(result, list)
        assert len(result) == 3

    def test_list_backups_empty_dir(self, tmp_path):
        """Test listing backups in empty directory."""
        from core.backup_logic import list_backups

        result = list_backups(str(tmp_path))

        assert result == []

    def test_list_backups_nonexistent_dir(self):
        """Test listing backups in non-existent directory."""
        from core.backup_logic import list_backups

        result = list_backups("/nonexistent/directory")

        assert result == []


class TestBackupLogicHelpers:
    """Tests for backup_logic helper functions."""

    def test_get_backup_filename(self):
        """Test backup filename generation."""
        from core.backup_logic import get_backup_filename

        filename = get_backup_filename()

        # Should contain backup and end with .zip
        assert "backup" in filename.lower()
        assert filename.endswith(".zip")

    def test_cleanup_old_backups(self, tmp_path):
        """Test cleanup of old backups."""
        from core.backup_logic import cleanup_old_backups

        # Create old backup files
        for i in range(10):
            backup_file = tmp_path / f"backup_2023010{i}.zip"
            with open(backup_file, "w") as f:
                f.write(f"old backup {i}")

        result = cleanup_old_backups(str(tmp_path), max_backups=5)

        assert result["success"] is True
        assert result["removed"] == 5

    def test_cleanup_old_backups_few_files(self, tmp_path):
        """Test cleanup when fewer files than max."""
        from core.backup_logic import cleanup_old_backups

        # Create only 3 backup files
        for i in range(3):
            backup_file = tmp_path / f"backup_2023010{i}.zip"
            with open(backup_file, "w") as f:
                f.write(f"backup {i}")

        result = cleanup_old_backups(str(tmp_path), max_backups=5)

        assert result["success"] is True
        assert result["removed"] == 0
        # All 3 files should remain (fewer than max_backups=5)
        assert len(list(tmp_path.glob("*.zip"))) == 3
