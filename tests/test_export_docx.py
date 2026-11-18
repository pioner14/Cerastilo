"""
Tests for core/export_schedule_docx.py, core/export_s89.py.
"""

import os
import tempfile
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import Assignment, Base, Participant, Setting, Week


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


@pytest.fixture
def sample_week(db_session):
    """Create a sample week with assignments."""
    week = Week(
        week_title="Тестовая неделя",
        start_date=date(2024, 1, 8),
        bible_reading="Бытие 1-2",
        songs="23,45,67",
    )
    db_session.add(week)
    db_session.commit()
    return week


@pytest.fixture
def sample_participants(db_session):
    """Create sample participants."""
    participants = [
        Participant(name="Иван Петров", gender="male", service_type="elder", is_active=True),
        Participant(
            name="Петр Сидоров", gender="male", service_type="ministerial_servant", is_active=True
        ),
        Participant(name="Анна Иванова", gender="female", service_type="publisher", is_active=True),
        Participant(
            name="Мария Сидорова", gender="female", service_type="publisher", is_active=True
        ),
    ]
    db_session.add_all(participants)
    db_session.commit()
    return participants


@pytest.fixture
def sample_assignments(db_session, sample_week, sample_participants):
    """Create sample assignments for a week."""
    assignments = [
        Assignment(
            week_id=sample_week.id,
            participant_id=sample_participants[0].id,
            section="treasures",
            section_position="1",
            assignment_type="talk",
            assignment_text="Урок 1: Что такое Библия?",
            assignment_number="1",
            duration=10,
        ),
        Assignment(
            week_id=sample_week.id,
            participant_id=sample_participants[1].id,
            section="treasures",
            section_position="2",
            assignment_type="talk",
            assignment_text="Духовные жемчужины (10 мин.)",
            assignment_number="2",
            duration=10,
        ),
        Assignment(
            week_id=sample_week.id,
            participant_id=sample_participants[2].id,
            section="treasures",
            section_position="3",
            assignment_type="reading",
            assignment_text="Чтение Библии (4 мин.)",
            assignment_number="3",
            duration=4,
        ),
        Assignment(
            week_id=sample_week.id,
            participant_id=sample_participants[0].id,
            section="ministry",
            section_position="4",
            assignment_type="demonstration",
            assignment_text="Первое посещение (2 мин.)",
            assignment_number="4",
            duration=2,
        ),
        Assignment(
            week_id=sample_week.id,
            participant_id=sample_participants[1].id,
            assistant_id=sample_participants[3].id,
            section="ministry",
            section_position="5",
            assignment_type="demonstration",
            assignment_text="Повторное посещение (3 мин.)",
            assignment_number="5",
            duration=3,
        ),
        Assignment(
            week_id=sample_week.id,
            participant_id=sample_participants[2].id,
            assistant_id=sample_participants[3].id,
            section="ministry",
            section_position="6",
            assignment_type="demonstration",
            assignment_text="Изучение Библии (4 мин.)",
            assignment_number="6",
            duration=4,
        ),
        Assignment(
            week_id=sample_week.id,
            participant_id=sample_participants[0].id,
            section="living",
            section_position="chairman",
            assignment_type="chairman",
            assignment_text="Председатель",
            duration=0,
        ),
        Assignment(
            week_id=sample_week.id,
            participant_id=sample_participants[1].id,
            section="living",
            section_position="prayer_open",
            assignment_type="prayer",
            assignment_text="Открывающая молитва",
            duration=0,
        ),
        Assignment(
            week_id=sample_week.id,
            participant_id=sample_participants[2].id,
            section="living",
            section_position="prayer_close",
            assignment_type="prayer",
            assignment_text="Закрывающая молитва",
            duration=0,
        ),
    ]
    db_session.add_all(assignments)
    db_session.commit()
    return assignments


@pytest.fixture
def sample_settings(db_session):
    """Create sample settings."""
    settings = [
        Setting(key="cong_name", value="Тестовое собрание"),
        Setting(key="meeting_time", value="19:00"),
        Setting(key="meeting_day", value="Среда"),
    ]
    db_session.add_all(settings)
    db_session.commit()
    return settings


# =============================================================================
# CustomScheduleExporter Tests
# =============================================================================


class TestCustomScheduleExporter:
    """Tests for CustomScheduleExporter class."""

    def test_export_creates_file(
        self, db_session, sample_week, sample_assignments, sample_settings
    ):
        """Test that export creates a DOCX file."""
        from core.export_schedule_docx import CustomScheduleExporter

        exporter = CustomScheduleExporter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_schedule.docx")
            result = exporter.export([sample_week.id], output_path, db_session, mode="compact")

            assert result["success"] is True
            assert os.path.exists(result["path"])

    def test_export_compact_mode(
        self, db_session, sample_week, sample_assignments, sample_settings
    ):
        """Test export in compact mode."""
        from core.export_schedule_docx import CustomScheduleExporter

        exporter = CustomScheduleExporter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_schedule.docx")
            result = exporter.export([sample_week.id], output_path, db_session, mode="compact")

            assert result["success"] is True
            assert result["path"] == output_path  # без метки режима в имени

    def test_export_full_mode(self, db_session, sample_week, sample_assignments, sample_settings):
        """Test export in full mode."""
        from core.export_schedule_docx import CustomScheduleExporter

        exporter = CustomScheduleExporter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_schedule.docx")
            result = exporter.export([sample_week.id], output_path, db_session, mode="full")

            assert result["success"] is True

    def test_export_compact_modern_mode(
        self, db_session, sample_week, sample_assignments, sample_settings
    ):
        """Test export in compact_modern mode."""
        from core.export_schedule_docx import CustomScheduleExporter

        exporter = CustomScheduleExporter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_schedule.docx")
            result = exporter.export(
                [sample_week.id], output_path, db_session, mode="compact_modern"
            )

            assert result["success"] is True
            assert result["path"] == output_path  # без «_новый» в имени

    def test_export_full_modern_mode(
        self, db_session, sample_week, sample_assignments, sample_settings
    ):
        """Test export in full_modern mode."""
        from core.export_schedule_docx import CustomScheduleExporter

        exporter = CustomScheduleExporter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_schedule.docx")
            result = exporter.export([sample_week.id], output_path, db_session, mode="full_modern")

            assert result["success"] is True
            # Имя файла — то, что выбрал пользователь, без метки режима
            assert result["path"] == output_path
            assert os.path.exists(output_path)

    def test_export_multiple_weeks(self, db_session, sample_participants, sample_settings):
        """Test exporting multiple weeks."""
        from core.export_schedule_docx import CustomScheduleExporter

        # Create two weeks
        week1 = Week(
            week_title="Неделя 1",
            start_date=date(2024, 1, 8),
            bible_reading="Бытие 1-2",
            songs="23,45,67",
        )
        week2 = Week(
            week_title="Неделя 2",
            start_date=date(2024, 1, 15),
            bible_reading="Бытие 3-4",
            songs="24,46,68",
        )
        db_session.add_all([week1, week2])
        db_session.commit()

        # Add assignments for both weeks
        for week in [week1, week2]:
            Assignment(
                week_id=week.id,
                participant_id=sample_participants[0].id,
                section="treasures",
                section_position="1",
                assignment_type="talk",
                assignment_text="Урок 1",
                assignment_number="1",
                duration=10,
            )
        db_session.commit()

        exporter = CustomScheduleExporter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_schedule.docx")
            result = exporter.export([week1.id, week2.id], output_path, db_session, mode="compact")

            assert result["success"] is True
            assert result["count"] == 2

    def test_export_empty_weeks(self, db_session):
        """Test export with no weeks."""
        from core.export_schedule_docx import CustomScheduleExporter

        exporter = CustomScheduleExporter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_schedule.docx")
            result = exporter.export([], output_path, db_session, mode="compact")

            assert result["success"] is True
            assert result["count"] == 0

    def test_export_handles_invalid_time(self, db_session, sample_week, sample_assignments):
        """Test export handles invalid meeting time gracefully."""
        from core.export_schedule_docx import CustomScheduleExporter

        # Add invalid time setting
        setting = Setting(key="meeting_time", value="invalid")
        db_session.add(setting)
        db_session.commit()

        exporter = CustomScheduleExporter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_schedule.docx")
            result = exporter.export([sample_week.id], output_path, db_session, mode="compact")

            assert result["success"] is True

    def test_fetch_data_returns_correct_structure(
        self, db_session, sample_week, sample_assignments, sample_settings
    ):
        """Test _fetch_data returns correct data structure."""
        from core.export_schedule_docx import CustomScheduleExporter

        exporter = CustomScheduleExporter()
        data = exporter._fetch_data(db_session, [sample_week.id])

        assert len(data) == 1
        assert "week" in data[0]
        assert "assignments" in data[0]
        assert "settings" in data[0]
        assert data[0]["week"].week_title == "Тестовая неделя"

    def test_fetch_data_includes_participant_names(
        self, db_session, sample_week, sample_assignments, sample_settings
    ):
        """Test _fetch_data includes participant names."""
        from core.export_schedule_docx import CustomScheduleExporter

        exporter = CustomScheduleExporter()
        data = exporter._fetch_data(db_session, [sample_week.id])

        assignments = data[0]["assignments"]
        assert any(a["participant"] == "Иван Петров" for a in assignments)

    def test_fetch_data_includes_assistant_names(
        self, db_session, sample_week, sample_assignments, sample_settings
    ):
        """Test _fetch_data includes assistant names."""
        from core.export_schedule_docx import CustomScheduleExporter

        exporter = CustomScheduleExporter()
        data = exporter._fetch_data(db_session, [sample_week.id])

        assignments = data[0]["assignments"]
        ministry_assignments = [a for a in assignments if a["section"] == "ministry"]
        assert any(a["assistant"] is not None for a in ministry_assignments)

    def test_export_handles_exception(self, db_session):
        """Test export handles exceptions gracefully."""
        from core.export_schedule_docx import CustomScheduleExporter

        exporter = CustomScheduleExporter()

        # Pass invalid session to trigger error
        result = exporter.export([999], "/invalid/path/test.docx", db_session, mode="compact")

        # Should handle error gracefully
        assert "success" in result


# =============================================================================
# S89Exporter Tests
# =============================================================================


class TestS89Exporter:
    """Tests for S89Exporter class."""

    def test_export_creates_file(
        self, db_session, sample_week, sample_assignments, sample_settings
    ):
        """Test that S-89 export creates a DOCX file."""
        from core.export_s89 import S89Exporter

        exporter = S89Exporter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_s89.docx")
            result = exporter.export(db_session, [sample_week.id], output_path)

            assert result["success"] is True
            assert os.path.exists(result["path"])

    def test_export_no_student_assignments(self, db_session, sample_week, sample_settings):
        """Test export when there are no student assignments."""
        from core.export_s89 import S89Exporter

        # Create only non-student assignments (chairman, prayers)
        assignments = [
            Assignment(
                week_id=sample_week.id,
                section="living",
                section_position="chairman",
                assignment_type="chairman",
                assignment_text="Председатель",
            ),
        ]
        db_session.add_all(assignments)
        db_session.commit()

        exporter = S89Exporter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_s89.docx")
            result = exporter.export(db_session, [sample_week.id], output_path)

            assert result["success"] is False
            assert "Нет назначений" in result["error"]

    def test_fetch_student_data_ministry_only(self, db_session, sample_week, sample_participants):
        """Test _fetch_student_data returns ministry assignments."""
        from core.export_s89 import S89Exporter

        # Create ministry assignments
        assignments = [
            Assignment(
                week_id=sample_week.id,
                participant_id=sample_participants[0].id,
                section="ministry",
                section_position="4",
                assignment_type="demonstration",
                assignment_text="Первое посещение",
                assignment_number="4",
            ),
        ]
        db_session.add_all(assignments)
        db_session.commit()

        exporter = S89Exporter()
        data = exporter._fetch_student_data(db_session, [sample_week.id])

        assert len(data) == 1
        assert data[0]["student_name"] == "Иван Петров"

    def test_fetch_student_data_bible_reading(self, db_session, sample_week, sample_participants):
        """Test _fetch_student_data includes Bible reading."""
        from core.export_s89 import S89Exporter

        # Create Bible reading assignment (treasures, position 3)
        assignments = [
            Assignment(
                week_id=sample_week.id,
                participant_id=sample_participants[0].id,
                section="treasures",
                section_position="3",
                assignment_type="reading",
                assignment_text="Чтение Библии",
                assignment_number="3",
            ),
        ]
        db_session.add_all(assignments)
        db_session.commit()

        exporter = S89Exporter()
        data = exporter._fetch_student_data(db_session, [sample_week.id])

        assert len(data) == 1

    def test_fetch_student_data_with_assistant(self, db_session, sample_week, sample_participants):
        """Test _fetch_student_data includes assistant."""
        from core.export_s89 import S89Exporter

        # Create assignment with assistant
        assignments = [
            Assignment(
                week_id=sample_week.id,
                participant_id=sample_participants[0].id,
                assistant_id=sample_participants[1].id,
                section="ministry",
                section_position="5",
                assignment_type="demonstration",
                assignment_text="Повторное посещение",
                assignment_number="5",
            ),
        ]
        db_session.add_all(assignments)
        db_session.commit()

        exporter = S89Exporter()
        data = exporter._fetch_student_data(db_session, [sample_week.id])

        assert len(data) == 1
        assert data[0]["assistant_name"] == "Петр Сидоров"

    def test_export_multiple_weeks(self, db_session, sample_participants):
        """Test S-89 export with multiple weeks."""
        from core.export_s89 import S89Exporter

        # Create two weeks with student assignments
        week1 = Week(week_title="Неделя 1", start_date=date(2024, 1, 8), songs="1,2,3")
        week2 = Week(week_title="Неделя 2", start_date=date(2024, 1, 15), songs="4,5,6")
        db_session.add_all([week1, week2])
        db_session.commit()

        for week in [week1, week2]:
            assignment = Assignment(
                week_id=week.id,
                participant_id=sample_participants[0].id,
                section="ministry",
                section_position="4",
                assignment_type="demonstration",
                assignment_text="Задание",
                assignment_number="4",
            )
            db_session.add(assignment)
        db_session.commit()

        exporter = S89Exporter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_s89.docx")
            result = exporter.export(db_session, [week1.id, week2.id], output_path)

            assert result["success"] is True
            assert result["count"] == 2


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================


class TestExportEdgeCases:
    """Tests for edge cases in export modules."""

    def test_export_week_without_assignments(self, db_session):
        """Test export week without assignments."""
        from core.export_schedule_docx import CustomScheduleExporter

        week = Week(week_title="Пустая неделя", start_date=date(2024, 1, 8), songs="1,2,3")
        db_session.add(week)
        db_session.commit()

        exporter = CustomScheduleExporter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test.docx")
            result = exporter.export([week.id], output_path, db_session, mode="compact")

            assert result["success"] is True

    def test_export_week_without_participant(self, db_session, sample_week):
        """Test export assignment without participant."""
        from core.export_schedule_docx import CustomScheduleExporter

        # Assignment without participant
        assignment = Assignment(
            week_id=sample_week.id,
            section="treasures",
            section_position="1",
            assignment_type="talk",
            assignment_text="Урок без участника",
            assignment_number="1",
        )
        db_session.add(assignment)
        db_session.commit()

        exporter = CustomScheduleExporter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test.docx")
            result = exporter.export([sample_week.id], output_path, db_session, mode="compact")

            assert result["success"] is True

    def test_export_with_special_characters(self, db_session, sample_participants):
        """Test export handles special characters in text."""
        from core.export_schedule_docx import CustomScheduleExporter

        week = Week(
            week_title="Неделя со спецсимволами <>&\"'",
            start_date=date(2024, 1, 8),
            bible_reading="Бытие 1-2",
            songs="1,2,3",
        )
        db_session.add(week)
        db_session.commit()

        assignment = Assignment(
            week_id=week.id,
            participant_id=sample_participants[0].id,
            section="treasures",
            section_position="1",
            assignment_type="talk",
            assignment_text='Текст с <спецсимволами> & "кавычками"',
            assignment_number="1",
        )
        db_session.add(assignment)
        db_session.commit()

        exporter = CustomScheduleExporter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test.docx")
            result = exporter.export([week.id], output_path, db_session, mode="compact")

            assert result["success"] is True

    def test_export_with_cyrillic_names(self, db_session, sample_week):
        """Test export handles Cyrillic participant names."""
        from core.export_schedule_docx import CustomScheduleExporter

        participant = Participant(
            name="Александр Александрович Александров", gender="male", service_type="elder"
        )
        db_session.add(participant)
        db_session.commit()

        assignment = Assignment(
            week_id=sample_week.id,
            participant_id=participant.id,
            section="treasures",
            section_position="1",
            assignment_type="talk",
            assignment_text="Урок",
            assignment_number="1",
        )
        db_session.add(assignment)
        db_session.commit()

        exporter = CustomScheduleExporter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test.docx")
            result = exporter.export([sample_week.id], output_path, db_session, mode="compact")

            assert result["success"] is True

    def test_export_with_long_text(self, db_session, sample_week, sample_participants):
        """Test export handles long assignment text."""
        from core.export_schedule_docx import CustomScheduleExporter

        long_text = "Очень длинный текст задания " * 20
        assignment = Assignment(
            week_id=sample_week.id,
            participant_id=sample_participants[0].id,
            section="treasures",
            section_position="1",
            assignment_type="talk",
            assignment_text=long_text,
            assignment_number="1",
        )
        db_session.add(assignment)
        db_session.commit()

        exporter = CustomScheduleExporter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test.docx")
            result = exporter.export([sample_week.id], output_path, db_session, mode="compact")

            assert result["success"] is True
