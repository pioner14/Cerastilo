"""Tests for core/repositories/week_repository.py."""

import os
import tempfile
from datetime import date

import pytest

from core.database import DatabaseManager
from core.models import Assignment, AssignmentStatus, Participant, Week
from core.repositories.week_repository import WeekRepository


@pytest.fixture
def db_manager():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        manager = DatabaseManager(db_path=db_path)
        try:
            yield manager
        finally:
            manager.close()


@pytest.fixture
def repository(db_manager):
    """Create a WeekRepository instance."""
    return WeekRepository(db_manager)


@pytest.fixture
def sample_week(db_manager):
    """Create a sample week in the database."""
    with db_manager.get_session() as session:
        week = Week(start_date=date(2026, 3, 2), week_title="Неделя 2 марта", year=2026, month="3")
        session.add(week)
        session.commit()
        week_id = week.id
    return week_id


@pytest.fixture
def sample_weeks(db_manager):
    """Create multiple weeks for testing."""
    with db_manager.get_session() as session:
        weeks = [
            Week(start_date=date(2026, 1, 6), week_title="Неделя 6 января", year=2026, month="1"),
            Week(start_date=date(2026, 2, 2), week_title="Неделя 2 февраля", year=2026, month="2"),
            Week(start_date=date(2026, 3, 2), week_title="Неделя 2 марта", year=2026, month="3"),
            Week(
                start_date=date(2025, 12, 1), week_title="Неделя 1 декабря", year=2025, month="12"
            ),
        ]
        session.add_all(weeks)
        session.commit()
        return [w.id for w in weeks]


@pytest.fixture
def sample_participant(db_manager):
    """Create a sample participant."""
    with db_manager.get_session() as session:
        participant = Participant(name="Иван Иванов", gender="male")
        session.add(participant)
        session.commit()
        return participant.id


@pytest.fixture
def sample_assignment(db_manager, sample_week, sample_participant):
    """Create a sample assignment."""
    with db_manager.get_session() as session:
        assignment = Assignment(
            week_id=sample_week,
            assignment_text="Председатель",
            assignment_type="chairman",
            assignment_number="1",
            section="treasures",
            section_position=1,
            participant_id=sample_participant,
            status=AssignmentStatus.ASSIGNED.value,
        )
        session.add(assignment)
        session.commit()
        return assignment.id


# =================================================================
#  ТЕСТЫ ИНИЦИАЛИЗАЦИИ
# =================================================================


class TestWeekRepositoryInit:
    """Tests for WeekRepository initialization."""

    def test_init_success(self, db_manager):
        """Test successful initialization."""
        repo = WeekRepository(db_manager)
        assert repo.db == db_manager
        assert repo.model_class == Week

    def test_inherits_from_base_repository(self, repository):
        """Test that WeekRepository inherits from BaseRepository."""
        assert hasattr(repository, "find")
        assert hasattr(repository, "get_by_id")
        assert hasattr(repository, "get_session")


# =================================================================
#  ТЕСТЫ get_by_year_month
# =================================================================


class TestGetByYearMonth:
    """Tests for get_by_year_month method."""

    def test_get_by_year_returns_weeks(self, repository, sample_weeks):
        """Test getting weeks by year."""
        result = repository.get_by_year_month(2026)

        assert len(result) == 3
        titles = [w.week_title for w in result]
        assert "Неделя 6 января" in titles
        assert "Неделя 2 февраля" in titles
        assert "Неделя 2 марта" in titles

    def test_get_by_year_and_month(self, repository, sample_weeks):
        """Test getting weeks by year and month."""
        result = repository.get_by_year_month(2026, 3)

        assert len(result) == 1
        assert result[0].week_title == "Неделя 2 марта"

    def test_get_by_year_no_results(self, repository):
        """Test getting weeks for year with no weeks."""
        result = repository.get_by_year_month(2030)

        assert result == []

    def test_get_by_month_as_string(self, repository, sample_weeks):
        """Test that month is converted to string in filter."""
        # Month stored as string in database
        result = repository.get_by_year_month(2026, 2)

        assert len(result) == 1
        assert result[0].month == "2"


# =================================================================
#  ТЕСТЫ get_by_date_range
# =================================================================


class TestGetByDateRange:
    """Tests for get_by_date_range method."""

    def test_get_by_date_range(self, repository, sample_weeks):
        """Test getting weeks within date range."""
        result = repository.get_by_date_range("2026-02-01", "2026-03-31")

        assert len(result) == 2
        titles = [w.week_title for w in result]
        assert "Неделя 2 февраля" in titles
        assert "Неделя 2 марта" in titles

    def test_get_by_date_range_single_week(self, repository, sample_weeks):
        """Test getting weeks with narrow date range."""
        result = repository.get_by_date_range("2026-03-01", "2026-03-10")

        assert len(result) == 1
        assert result[0].week_title == "Неделя 2 марта"

    def test_get_by_date_range_no_results(self, repository, sample_weeks):
        """Test getting weeks for range with no weeks."""
        result = repository.get_by_date_range("2030-01-01", "2030-12-31")

        assert result == []

    def test_get_by_date_range_ordered(self, repository, sample_weeks):
        """Test that results are ordered by start_date."""
        result = repository.get_by_date_range("2026-01-01", "2026-12-31")

        dates = [w.start_date for w in result]
        assert dates == sorted(dates)


# =================================================================
#  ТЕСТЫ get_with_assignments
# =================================================================


class TestGetWithAssignments:
    """Tests for get_with_assignments method."""

    def test_get_with_assignments(self, repository, sample_week, sample_assignment):
        """Test getting week with assignments."""
        result = repository.get_with_assignments(sample_week)

        assert result is not None
        assert result.id == sample_week
        assert len(result.assignments) == 1
        assert result.assignments[0].assignment_text == "Председатель"

    def test_get_with_assignments_no_assignments(self, repository, sample_week):
        """Test getting week without assignments."""
        result = repository.get_with_assignments(sample_week)

        assert result is not None
        assert len(result.assignments) == 0

    def test_get_with_assignments_nonexistent_week(self, repository):
        """Test getting nonexistent week."""
        result = repository.get_with_assignments(999)

        assert result is None


# =================================================================
#  ТЕСТЫ get_special_event / set_special_event
# =================================================================


class TestSpecialEvent:
    """Tests for special event methods."""

    def test_get_special_event_none(self, repository, sample_week):
        """Test getting special event when none set."""
        result = repository.get_special_event(sample_week)

        assert result is None

    def test_set_special_event(self, repository, sample_week):
        """Test setting special event."""
        success = repository.set_special_event(sample_week, "memorial")

        assert success is True
        event = repository.get_special_event(sample_week)
        assert event == "memorial"

    def test_set_special_event_nonexistent_week(self, repository):
        """Test setting special event for nonexistent week."""
        success = repository.set_special_event(999, "memorial")

        assert success is False

    def test_get_special_event_nonexistent_week(self, repository):
        """Test getting special event for nonexistent week."""
        result = repository.get_special_event(999)

        assert result is None


# =================================================================
#  ТЕСТЫ get_weeks_tree
# =================================================================


class TestGetWeeksTree:
    """Tests for get_weeks_tree method."""

    def test_get_weeks_tree_structure(self, repository, sample_weeks):
        """Test the structure of weeks tree."""
        result = repository.get_weeks_tree()

        assert "2026" in result
        assert "2025" in result
        assert "Январь" in result["2026"]
        assert "Февраль" in result["2026"]
        assert "Март" in result["2026"]

    def test_get_weeks_tree_content(self, repository, sample_weeks):
        """Test the content of weeks tree."""
        result = repository.get_weeks_tree()

        # Check January 2026
        jan_weeks = result["2026"]["Январь"]
        assert len(jan_weeks) == 1
        assert jan_weeks[0]["title"] == "Неделя 6 января"
        assert jan_weeks[0]["date"] == "2026-01-06"

    def test_get_weeks_tree_empty(self, repository):
        """Test weeks tree with no weeks."""
        result = repository.get_weeks_tree()

        assert result == {}

    def test_get_weeks_tree_ordered_asc(self, repository, sample_weeks):
        """Test that years are ordered ascending (chronological)."""
        result = repository.get_weeks_tree()
        years = list(result.keys())

        assert years == ["2025", "2026"]


# =================================================================
#  ТЕСТЫ delete_with_assignments
# =================================================================


class TestDeleteWithAssignments:
    """Tests for delete_with_assignments method."""

    def test_delete_week_with_assignments(
        self, repository, db_manager, sample_week, sample_assignment
    ):
        """Test deleting week with assignments."""
        success = repository.delete_with_assignments(sample_week)

        assert success is True

        # Verify week is deleted
        with db_manager.get_session() as session:
            week = session.get(Week, sample_week)
            assert week is None

            # Verify assignment is also deleted (cascade)
            assignment = session.get(Assignment, sample_assignment)
            assert assignment is None

    def test_delete_week_without_assignments(self, repository, db_manager, sample_week):
        """Test deleting week without assignments."""
        success = repository.delete_with_assignments(sample_week)

        assert success is True

        with db_manager.get_session() as session:
            week = session.get(Week, sample_week)
            assert week is None

    def test_delete_nonexistent_week(self, repository):
        """Test deleting nonexistent week."""
        success = repository.delete_with_assignments(999)

        assert success is False


# =================================================================
#  ТЕСТЫ get_week_data
# =================================================================


class TestGetWeekData:
    """Tests for get_week_data method."""

    def test_get_week_data_with_assignment(
        self, repository, sample_week, sample_assignment, sample_participant
    ):
        """Test getting week data with assignment."""
        result = repository.get_week_data(sample_week)

        assert result is not None
        assert result["week"]["id"] == sample_week
        assert result["week"]["week_title"] == "Неделя 2 марта"
        assert len(result["assignments"]) == 1

        assignment = result["assignments"][0]
        assert assignment["assignment_text"] == "Председатель"
        assert assignment["participant_name"] == "Иван Иванов"

    def test_get_week_data_no_assignments(self, repository, sample_week):
        """Test getting week data without assignments."""
        result = repository.get_week_data(sample_week)

        assert result is not None
        assert result["week"]["id"] == sample_week
        assert result["assignments"] == []

    def test_get_week_data_nonexistent_week(self, repository):
        """Test getting data for nonexistent week."""
        result = repository.get_week_data(999)

        assert result is None

    def test_get_week_data_with_assistant(
        self, repository, db_manager, sample_week, sample_participant
    ):
        """Test getting week data with assistant."""
        # Create assistant
        with db_manager.get_session() as session:
            assistant = Participant(name="Пётр Петров", gender="male")
            session.add(assistant)
            session.commit()
            assistant_id = assistant.id

            # Create assignment with assistant
            assignment = Assignment(
                week_id=sample_week,
                assignment_text="Чтение Библии",
                assignment_type="bible_reading",
                assignment_number="2",
                section="ministry",
                section_position=2,
                participant_id=sample_participant,
                assistant_id=assistant_id,
                status=AssignmentStatus.ASSIGNED.value,
            )
            session.add(assignment)
            session.commit()

        result = repository.get_week_data(sample_week)

        assert len(result["assignments"]) == 1
        assert result["assignments"][0]["assistant_name"] == "Пётр Петров"


# =================================================================
#  ТЕСТЫ БАЗОВЫХ МЕТОДОВ
# =================================================================


class TestBaseMethods:
    """Tests for inherited base repository methods."""

    def test_get_by_id(self, repository, sample_week):
        """Test get_by_id method."""
        result = repository.get_by_id(sample_week)

        assert result is not None
        assert result.id == sample_week
        assert result.week_title == "Неделя 2 марта"

    def test_get_by_id_nonexistent(self, repository):
        """Test get_by_id for nonexistent week."""
        result = repository.get_by_id(999)

        assert result is None

    def test_find(self, repository, sample_weeks):
        """Test find method."""
        result = repository.find(year=2026)

        assert len(result) == 3

    def test_count(self, repository, sample_weeks):
        """Test count method."""
        result = repository.count()

        assert result == 4

    def test_get_all(self, repository, sample_weeks):
        """Test get_all method."""
        result = repository.get_all()

        assert len(result) == 4
