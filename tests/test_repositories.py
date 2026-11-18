"""
Tests for core/repositories/ - ParticipantRepository, WeekRepository, AssignmentRepository.
"""

from datetime import date
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import (
    Assignment,
    AssignmentStatus,
    Base,
    Participant,
    Week,
    participant_qualifications,
)
from core.repositories.assignment_repository import AssignmentRepository
from core.repositories.participant_repository import ParticipantRepository
from core.repositories.week_repository import WeekRepository


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
def mock_db_manager(db_session):
    """Create mock database manager that returns our session."""
    db_manager = Mock()

    # Make session not actually close when close() is called
    # This allows the same session to be reused across multiple operations in a test
    db_session.close
    db_session.close = Mock(side_effect=lambda: None)

    # Return session directly - SQLAlchemy sessions are context managers
    db_manager.get_session.return_value = db_session

    return db_manager


# =============================================================================
# ParticipantRepository Tests
# =============================================================================


class TestParticipantRepositoryGetByName:
    """Tests for ParticipantRepository.get_by_name method."""

    def test_get_by_name_found(self, db_session, mock_db_manager):
        """Test finding participant by name."""
        p = Participant(name="Иван Петров", gender="male", service_type="elder")
        db_session.add(p)
        db_session.commit()

        repo = ParticipantRepository(mock_db_manager)
        result = repo.get_by_name("Иван Петров")

        assert result is not None
        assert result.name == "Иван Петров"

    def test_get_by_name_not_found(self, mock_db_manager):
        """Test finding non-existent participant."""
        repo = ParticipantRepository(mock_db_manager)
        result = repo.get_by_name("Несуществующий")

        assert result is None

    def test_get_by_name_case_sensitive(self, db_session, mock_db_manager):
        """Test that name search is case sensitive."""
        p = Participant(name="Иван Петров", gender="male", service_type="elder")
        db_session.add(p)
        db_session.commit()

        repo = ParticipantRepository(mock_db_manager)
        result = repo.get_by_name("иван петров")

        assert result is None


class TestParticipantRepositoryGetActive:
    """Tests for ParticipantRepository.get_active method."""

    def test_get_active_only_active(self, db_session, mock_db_manager):
        """Test getting only active participants."""
        p1 = Participant(name="Активный", gender="male", service_type="publisher", is_active=True)
        p2 = Participant(
            name="Неактивный", gender="female", service_type="publisher", is_active=False
        )
        db_session.add_all([p1, p2])
        db_session.commit()

        repo = ParticipantRepository(mock_db_manager)
        result = repo.get_active()

        assert len(result) == 1
        assert result[0].name == "Активный"

    def test_get_active_all_inactive(self, mock_db_manager):
        """Test getting active when all are inactive."""
        repo = ParticipantRepository(mock_db_manager)
        result = repo.get_active()

        assert result == []


class TestParticipantRepositoryGetByFamily:
    """Tests for ParticipantRepository.get_by_family method."""

    def test_get_by_family_found(self, db_session, mock_db_manager):
        """Test getting participants by family group."""
        p1 = Participant(name="Отец", gender="male", service_type="elder", family_group_id=1)
        p2 = Participant(name="Мать", gender="female", service_type="publisher", family_group_id=1)
        p3 = Participant(name="Другой", gender="male", service_type="publisher", family_group_id=2)
        db_session.add_all([p1, p2, p3])
        db_session.commit()

        repo = ParticipantRepository(mock_db_manager)
        result = repo.get_by_family(1)

        assert len(result) == 2

    def test_get_by_family_not_found(self, mock_db_manager):
        """Test getting participants for non-existent family."""
        repo = ParticipantRepository(mock_db_manager)
        result = repo.get_by_family(999)

        assert result == []


class TestParticipantRepositoryQualifications:
    """Tests for ParticipantRepository qualifications methods."""

    def test_get_qualifications(self, db_session, mock_db_manager):
        """Test getting participant qualifications."""
        p = Participant(name="Тест", gender="male", service_type="elder")
        db_session.add(p)
        db_session.commit()

        # Add qualifications
        db_session.execute(
            participant_qualifications.insert().values(
                participant_id=p.id, qualification_name="chairman"
            )
        )
        db_session.execute(
            participant_qualifications.insert().values(
                participant_id=p.id, qualification_name="reader"
            )
        )
        db_session.commit()

        repo = ParticipantRepository(mock_db_manager)
        result = repo.get_qualifications(p.id)

        assert len(result) == 2
        assert "chairman" in result
        assert "reader" in result

    def test_get_qualifications_empty(self, db_session, mock_db_manager):
        """Test getting qualifications for participant without any."""
        p = Participant(name="Без Квалификаций", gender="male", service_type="publisher")
        db_session.add(p)
        db_session.commit()

        repo = ParticipantRepository(mock_db_manager)
        result = repo.get_qualifications(p.id)

        assert result == []

    def test_set_qualifications(self, db_session, mock_db_manager):
        """Test setting participant qualifications."""
        p = Participant(name="Тест", gender="male", service_type="elder")
        db_session.add(p)
        db_session.commit()

        repo = ParticipantRepository(mock_db_manager)
        result = repo.set_qualifications(p.id, ["speaker", "reader"])

        assert result is True

        # Verify
        quals = repo.get_qualifications(p.id)
        assert len(quals) == 2
        assert "speaker" in quals
        assert "reader" in quals

    def test_set_qualifications_replaces_existing(self, db_session, mock_db_manager):
        """Test that set_qualifications replaces existing qualifications."""
        p = Participant(name="Тест", gender="male", service_type="elder")
        db_session.add(p)
        db_session.commit()

        # Add initial qualification
        db_session.execute(
            participant_qualifications.insert().values(
                participant_id=p.id, qualification_name="old_qual"
            )
        )
        db_session.commit()

        repo = ParticipantRepository(mock_db_manager)
        repo.set_qualifications(p.id, ["new_qual"])

        quals = repo.get_qualifications(p.id)
        assert len(quals) == 1
        assert "new_qual" in quals
        assert "old_qual" not in quals

    def test_add_qualification_new(self, db_session, mock_db_manager):
        """Test adding new qualification."""
        p = Participant(name="Тест", gender="male", service_type="elder")
        db_session.add(p)
        db_session.commit()

        repo = ParticipantRepository(mock_db_manager)
        result = repo.add_qualification(p.id, "chairman")

        assert result is True

        quals = repo.get_qualifications(p.id)
        assert "chairman" in quals

    def test_add_qualification_duplicate(self, db_session, mock_db_manager):
        """Test adding duplicate qualification."""
        p = Participant(name="Тест", gender="male", service_type="elder")
        db_session.add(p)
        db_session.commit()

        repo = ParticipantRepository(mock_db_manager)
        repo.add_qualification(p.id, "chairman")
        result = repo.add_qualification(p.id, "chairman")

        assert result is False

        quals = repo.get_qualifications(p.id)
        assert quals.count("chairman") == 1


class TestParticipantRepositoryGetWithStats:
    """Tests for ParticipantRepository.get_with_stats method."""

    def test_get_with_stats_basic(self, db_session, mock_db_manager):
        """Test getting participants with statistics."""
        p = Participant(name="Тест", gender="male", service_type="elder", is_active=True)
        db_session.add(p)
        db_session.commit()

        repo = ParticipantRepository(mock_db_manager)
        result = repo.get_with_stats()

        assert len(result) >= 1
        found = next((r for r in result if r["name"] == "Тест"), None)
        assert found is not None
        assert "total_assignments" in found

    def test_get_with_stats_includes_inactive(self, db_session, mock_db_manager):
        """Test that get_with_stats only returns active participants."""
        p_active = Participant(
            name="Активный", gender="male", service_type="publisher", is_active=True
        )
        p_inactive = Participant(
            name="Неактивный", gender="male", service_type="publisher", is_active=False
        )
        db_session.add_all([p_active, p_inactive])
        db_session.commit()

        repo = ParticipantRepository(mock_db_manager)
        result = repo.get_with_stats()

        names = [r["name"] for r in result]
        assert "Активный" in names
        assert "Неактивный" not in names


# =============================================================================
# WeekRepository Tests
# =============================================================================


class TestWeekRepositoryGetByYearMonth:
    """Tests for WeekRepository.get_by_year_month method."""

    def test_get_by_year(self, db_session, mock_db_manager):
        """Test getting weeks by year."""
        w1 = Week(week_title="W1", start_date=date(2024, 1, 1), month="1", year=2024)
        w2 = Week(week_title="W2", start_date=date(2024, 2, 1), month="2", year=2024)
        w3 = Week(week_title="W3", start_date=date(2023, 1, 1), month="1", year=2023)
        db_session.add_all([w1, w2, w3])
        db_session.commit()

        repo = WeekRepository(mock_db_manager)
        result = repo.get_by_year_month(2024)

        assert len(result) == 2

    def test_get_by_year_and_month(self, db_session, mock_db_manager):
        """Test getting weeks by year and month."""
        w1 = Week(week_title="W1", start_date=date(2024, 1, 1), month=1, year=2024)
        w2 = Week(week_title="W2", start_date=date(2024, 2, 1), month=2, year=2024)
        db_session.add_all([w1, w2])
        db_session.commit()

        repo = WeekRepository(mock_db_manager)
        result = repo.get_by_year_month(2024, month=1)

        assert len(result) == 1
        assert result[0].month == 1

    def test_get_by_year_not_found(self, mock_db_manager):
        """Test getting weeks for non-existent year."""
        repo = WeekRepository(mock_db_manager)
        result = repo.get_by_year_month(2030)

        assert result == []


class TestWeekRepositoryGetByDateRange:
    """Tests for WeekRepository.get_by_date_range method."""

    def test_get_by_date_range_found(self, db_session, mock_db_manager):
        """Test getting weeks within date range."""
        w1 = Week(week_title="W1", start_date=date(2024, 1, 1), month="1", year=2024)
        w2 = Week(week_title="W2", start_date=date(2024, 1, 8), month="1", year=2024)
        w3 = Week(week_title="W3", start_date=date(2024, 1, 15), month="1", year=2024)
        w4 = Week(week_title="W4", start_date=date(2024, 2, 1), month="2", year=2024)
        db_session.add_all([w1, w2, w3, w4])
        db_session.commit()

        repo = WeekRepository(mock_db_manager)
        result = repo.get_by_date_range(date(2024, 1, 1), date(2024, 1, 15))

        assert len(result) == 3

    def test_get_by_date_range_no_match(self, db_session, mock_db_manager):
        """Test getting weeks outside date range."""
        w = Week(week_title="W", start_date=date(2024, 1, 1), month="1", year=2024)
        db_session.add(w)
        db_session.commit()

        repo = WeekRepository(mock_db_manager)
        result = repo.get_by_date_range(date(2024, 3, 1), date(2024, 3, 31))

        assert result == []


class TestWeekRepositorySpecialEvent:
    """Tests for WeekRepository special event methods."""

    def test_get_special_event(self, db_session, mock_db_manager):
        """Test getting special event for week."""
        w = Week(
            week_title="W",
            start_date=date(2024, 1, 1),
            month="1",
            year=2024,
            special_event="memorial",
        )
        db_session.add(w)
        db_session.commit()

        repo = WeekRepository(mock_db_manager)
        result = repo.get_special_event(w.id)

        assert result == "memorial"

    def test_get_special_event_none(self, db_session, mock_db_manager):
        """Test getting special event for week without event."""
        w = Week(week_title="W", start_date=date(2024, 1, 1), month="1", year=2024)
        db_session.add(w)
        db_session.commit()

        repo = WeekRepository(mock_db_manager)
        result = repo.get_special_event(w.id)

        assert result is None

    def test_get_special_event_week_not_found(self, mock_db_manager):
        """Test getting special event for non-existent week."""
        repo = WeekRepository(mock_db_manager)
        result = repo.get_special_event(999)

        assert result is None


class TestWeekRepositoryGetWeeksTree:
    """Tests for WeekRepository.get_weeks_tree method."""

    def test_get_weeks_tree_basic(self, db_session, mock_db_manager):
        """Test getting weeks tree structure."""
        w1 = Week(week_title="Неделя 1", start_date=date(2024, 1, 1), month="1", year=2024)
        w2 = Week(week_title="Неделя 2", start_date=date(2024, 1, 8), month="1", year=2024)
        w3 = Week(week_title="Неделя 3", start_date=date(2024, 2, 1), month="2", year=2024)
        db_session.add_all([w1, w2, w3])
        db_session.commit()

        repo = WeekRepository(mock_db_manager)
        result = repo.get_weeks_tree()

        assert "2024" in result
        assert "Январь" in result["2024"]
        assert "Февраль" in result["2024"]
        assert len(result["2024"]["Январь"]) == 2
        assert len(result["2024"]["Февраль"]) == 1

    def test_get_weeks_tree_empty(self, mock_db_manager):
        """Test getting weeks tree when no weeks exist."""
        repo = WeekRepository(mock_db_manager)
        result = repo.get_weeks_tree()

        assert result == {}

    def test_get_weeks_tree_multiple_years(self, db_session, mock_db_manager):
        """Test getting weeks tree with multiple years."""
        w1 = Week(week_title="W1", start_date=date(2023, 1, 1), month="1", year=2023)
        w2 = Week(week_title="W2", start_date=date(2024, 1, 1), month="1", year=2024)
        db_session.add_all([w1, w2])
        db_session.commit()

        repo = WeekRepository(mock_db_manager)
        result = repo.get_weeks_tree()

        assert "2023" in result
        assert "2024" in result


class TestWeekRepositoryDeleteWithAssignments:
    """Tests for WeekRepository.delete_with_assignments method."""

    def test_delete_with_assignments_success(self, db_session, mock_db_manager):
        """Test deleting week with assignments."""
        w = Week(week_title="W", start_date=date(2024, 1, 1), month="1", year=2024)
        db_session.add(w)
        db_session.commit()

        a = Assignment(
            week_id=w.id,
            assignment_text="Задание",
            assignment_type="treasures",
            assignment_number="1",
        )
        db_session.add(a)
        db_session.commit()

        repo = WeekRepository(mock_db_manager)
        result = repo.delete_with_assignments(w.id)

        assert result is True
        assert db_session.get(Week, w.id) is None

    def test_delete_with_assignments_not_found(self, mock_db_manager):
        """Test deleting non-existent week."""
        repo = WeekRepository(mock_db_manager)
        result = repo.delete_with_assignments(999)

        assert result is False


# =============================================================================
# AssignmentRepository Tests
# =============================================================================


class TestAssignmentRepositoryGetByWeek:
    """Tests for AssignmentRepository.get_by_week method."""

    def test_get_by_week_found(self, db_session, mock_db_manager):
        """Test getting assignments for a week."""
        w = Week(week_title="W", start_date=date(2024, 1, 1), month="1", year=2024)
        db_session.add(w)
        db_session.commit()

        a1 = Assignment(
            week_id=w.id, assignment_text="A1", assignment_type="treasures", assignment_number="1"
        )
        a2 = Assignment(
            week_id=w.id, assignment_text="A2", assignment_type="ministry", assignment_number="4"
        )
        db_session.add_all([a1, a2])
        db_session.commit()

        repo = AssignmentRepository(mock_db_manager)
        result = repo.get_by_week(w.id)

        assert len(result) == 2

    def test_get_by_week_empty(self, db_session, mock_db_manager):
        """Test getting assignments for week without assignments."""
        w = Week(week_title="W", start_date=date(2024, 1, 1), month="1", year=2024)
        db_session.add(w)
        db_session.commit()

        repo = AssignmentRepository(mock_db_manager)
        result = repo.get_by_week(w.id)

        assert result == []


class TestAssignmentRepositoryGetByParticipant:
    """Tests for AssignmentRepository.get_by_participant method."""

    def test_get_by_participant_as_participant(self, db_session, mock_db_manager):
        """Test getting assignments where person is participant."""
        w = Week(week_title="W", start_date=date(2024, 1, 1), month="1", year=2024)
        db_session.add(w)
        db_session.commit()

        p = Participant(name="Иван", gender="male", service_type="elder")
        db_session.add(p)
        db_session.commit()

        a = Assignment(
            week_id=w.id,
            assignment_text="Задание",
            assignment_type="treasures",
            assignment_number="1",
            participant_id=p.id,
        )
        db_session.add(a)
        db_session.commit()

        repo = AssignmentRepository(mock_db_manager)
        result = repo.get_by_participant(p.id)

        assert len(result) == 1

    def test_get_by_participant_as_assistant(self, db_session, mock_db_manager):
        """Test getting assignments where person is assistant."""
        w = Week(week_title="W", start_date=date(2024, 1, 1), month="1", year=2024)
        db_session.add(w)
        db_session.commit()

        p = Participant(name="Иван", gender="male", service_type="elder")
        db_session.add(p)
        db_session.commit()

        a = Assignment(
            week_id=w.id,
            assignment_text="Задание",
            assignment_type="ministry",
            assignment_number="4",
            assistant_id=p.id,
        )
        db_session.add(a)
        db_session.commit()

        repo = AssignmentRepository(mock_db_manager)
        result = repo.get_by_participant(p.id)

        assert len(result) == 1

    def test_get_by_participant_with_status_filter(self, db_session, mock_db_manager):
        """Test getting assignments with status filter."""
        w = Week(week_title="W", start_date=date(2024, 1, 1), month="1", year=2024)
        db_session.add(w)
        db_session.commit()

        p = Participant(name="Иван", gender="male", service_type="elder")
        db_session.add(p)
        db_session.commit()

        a1 = Assignment(
            week_id=w.id,
            assignment_text="A1",
            assignment_type="treasures",
            assignment_number="1",
            participant_id=p.id,
            status=AssignmentStatus.ASSIGNED.value,
        )
        a2 = Assignment(
            week_id=w.id,
            assignment_text="A2",
            assignment_type="ministry",
            assignment_number="4",
            participant_id=p.id,
            status=AssignmentStatus.EMPTY.value,
        )
        db_session.add_all([a1, a2])
        db_session.commit()

        repo = AssignmentRepository(mock_db_manager)
        result = repo.get_by_participant(p.id, status=AssignmentStatus.ASSIGNED.value)

        assert len(result) == 1


class TestAssignmentRepositoryAssignParticipant:
    """Tests for AssignmentRepository.assign_participant method."""

    def test_assign_participant_as_participant(self, db_session, mock_db_manager):
        """Test assigning participant to assignment."""
        w = Week(week_title="W", start_date=date(2024, 1, 1), month="1", year=2024)
        db_session.add(w)
        db_session.commit()

        p = Participant(name="Иван", gender="male", service_type="elder")
        db_session.add(p)
        db_session.commit()

        a = Assignment(
            week_id=w.id,
            assignment_text="Задание",
            assignment_type="treasures",
            assignment_number="1",
            status=AssignmentStatus.EMPTY.value,
        )
        db_session.add(a)
        db_session.commit()

        repo = AssignmentRepository(mock_db_manager)
        result = repo.assign_participant(a.id, p.id, role="participant")

        assert result is True
        db_session.expire_all()
        updated = db_session.get(Assignment, a.id)
        assert updated.participant_id == p.id
        assert updated.status == AssignmentStatus.ASSIGNED.value

    def test_assign_participant_as_assistant(self, db_session, mock_db_manager):
        """Test assigning assistant to assignment."""
        w = Week(week_title="W", start_date=date(2024, 1, 1), month="1", year=2024)
        db_session.add(w)
        db_session.commit()

        p = Participant(name="Пётр", gender="male", service_type="publisher")
        db_session.add(p)
        db_session.commit()

        a = Assignment(
            week_id=w.id,
            assignment_text="Задание",
            assignment_type="ministry",
            assignment_number="4",
        )
        db_session.add(a)
        db_session.commit()

        repo = AssignmentRepository(mock_db_manager)
        result = repo.assign_participant(a.id, p.id, role="assistant")

        assert result is True
        db_session.expire_all()
        updated = db_session.get(Assignment, a.id)
        assert updated.assistant_id == p.id

    def test_assign_participant_clear(self, db_session, mock_db_manager):
        """Test clearing participant from assignment."""
        w = Week(week_title="W", start_date=date(2024, 1, 1), month="1", year=2024)
        db_session.add(w)
        db_session.commit()

        p = Participant(name="Иван", gender="male", service_type="elder")
        db_session.add(p)
        db_session.commit()

        a = Assignment(
            week_id=w.id,
            assignment_text="Задание",
            assignment_type="treasures",
            assignment_number="1",
            participant_id=p.id,
            status=AssignmentStatus.ASSIGNED.value,
        )
        db_session.add(a)
        db_session.commit()

        repo = AssignmentRepository(mock_db_manager)
        result = repo.assign_participant(a.id, None, role="participant")

        assert result is True
        db_session.expire_all()
        updated = db_session.get(Assignment, a.id)
        assert updated.participant_id is None
        assert updated.status == AssignmentStatus.EMPTY.value

    def test_assign_participant_not_found(self, mock_db_manager):
        """Test assigning to non-existent assignment."""
        repo = AssignmentRepository(mock_db_manager)
        result = repo.assign_participant(999, 1)

        assert result is False


class TestAssignmentRepositoryClearWeekAssignments:
    """Tests for AssignmentRepository.clear_week_assignments method."""

    def test_clear_week_assignments_success(self, db_session, mock_db_manager):
        """Test clearing all assignments for a week."""
        w = Week(week_title="W", start_date=date(2024, 1, 1), month="1", year=2024)
        db_session.add(w)
        db_session.commit()

        p = Participant(name="Иван", gender="male", service_type="elder")
        db_session.add(p)
        db_session.commit()

        a1 = Assignment(
            week_id=w.id,
            assignment_text="A1",
            assignment_type="treasures",
            assignment_number="1",
            participant_id=p.id,
            status=AssignmentStatus.ASSIGNED.value,
        )
        a2 = Assignment(
            week_id=w.id,
            assignment_text="A2",
            assignment_type="ministry",
            assignment_number="4",
            assistant_id=p.id,
        )
        db_session.add_all([a1, a2])
        db_session.commit()

        repo = AssignmentRepository(mock_db_manager)
        result = repo.clear_week_assignments(w.id)

        assert result is True
        db_session.expire_all()

        assignments = db_session.query(Assignment).filter(Assignment.week_id == w.id).all()
        for a in assignments:
            assert a.participant_id is None
            assert a.assistant_id is None
            assert a.status == AssignmentStatus.EMPTY.value


class TestAssignmentRepositoryGetConflicts:
    """Tests for AssignmentRepository.get_conflicts method."""

    def test_get_conflicts_found(self, db_session, mock_db_manager):
        """Test detecting conflicts in week assignments."""
        w = Week(week_title="W", start_date=date(2024, 1, 1), month="1", year=2024)
        db_session.add(w)
        db_session.commit()

        p = Participant(name="Иван", gender="male", service_type="elder")
        db_session.add(p)
        db_session.commit()

        # Same participant in two assignments
        a1 = Assignment(
            week_id=w.id,
            assignment_text="A1",
            assignment_type="treasures",
            assignment_number="1",
            participant_id=p.id,
        )
        a2 = Assignment(
            week_id=w.id,
            assignment_text="A2",
            assignment_type="ministry",
            assignment_number="4",
            participant_id=p.id,
        )
        db_session.add_all([a1, a2])
        db_session.commit()

        repo = AssignmentRepository(mock_db_manager)
        result = repo.get_conflicts(w.id)

        assert p.id in result

    def test_get_conflicts_none(self, db_session, mock_db_manager):
        """Test no conflicts in week assignments."""
        w = Week(week_title="W", start_date=date(2024, 1, 1), month="1", year=2024)
        db_session.add(w)
        db_session.commit()

        p1 = Participant(name="Иван", gender="male", service_type="elder")
        p2 = Participant(name="Пётр", gender="male", service_type="elder")
        db_session.add_all([p1, p2])
        db_session.commit()

        a1 = Assignment(
            week_id=w.id,
            assignment_text="A1",
            assignment_type="treasures",
            assignment_number="1",
            participant_id=p1.id,
        )
        a2 = Assignment(
            week_id=w.id,
            assignment_text="A2",
            assignment_type="ministry",
            assignment_number="4",
            participant_id=p2.id,
        )
        db_session.add_all([a1, a2])
        db_session.commit()

        repo = AssignmentRepository(mock_db_manager)
        result = repo.get_conflicts(w.id)

        assert result == []


class TestAssignmentRepositoryGetAssignmentsWithNames:
    """Tests for AssignmentRepository.get_assignments_with_names method."""

    def test_get_assignments_with_names(self, db_session, mock_db_manager):
        """Test getting assignments with participant names."""
        w = Week(week_title="W", start_date=date(2024, 1, 1), month="1", year=2024)
        db_session.add(w)
        db_session.commit()

        p1 = Participant(name="Иван", gender="male", service_type="elder")
        p2 = Participant(name="Пётр", gender="male", service_type="publisher")
        db_session.add_all([p1, p2])
        db_session.commit()

        a = Assignment(
            week_id=w.id,
            assignment_text="Задание",
            assignment_type="ministry",
            assignment_number="4",
            participant_id=p1.id,
            assistant_id=p2.id,
        )
        db_session.add(a)
        db_session.commit()

        repo = AssignmentRepository(mock_db_manager)
        result = repo.get_assignments_with_names(w.id)

        assert len(result) >= 1
        found = next((r for r in result if r["id"] == a.id), None)
        assert found is not None
        assert found["participant_name"] == "Иван"
        assert found["assistant_name"] is not None


# =============================================================================
# BaseRepository Tests
# =============================================================================


class TestBaseRepositoryCRUD:
    """Tests for BaseRepository CRUD operations."""

    def test_get_by_id_found(self, db_session, mock_db_manager):
        """Test getting entity by ID."""
        p = Participant(name="Тест", gender="male", service_type="publisher")
        db_session.add(p)
        db_session.commit()

        repo = ParticipantRepository(mock_db_manager)
        result = repo.get_by_id(p.id)

        assert result is not None
        assert result.name == "Тест"

    def test_get_by_id_not_found(self, mock_db_manager):
        """Test getting non-existent entity."""
        repo = ParticipantRepository(mock_db_manager)
        result = repo.get_by_id(999)

        assert result is None

    def test_get_all(self, db_session, mock_db_manager):
        """Test getting all entities."""
        p1 = Participant(name="P1", gender="male", service_type="publisher")
        p2 = Participant(name="P2", gender="female", service_type="publisher")
        db_session.add_all([p1, p2])
        db_session.commit()

        repo = ParticipantRepository(mock_db_manager)
        result = repo.get_all()

        assert len(result) == 2

    def test_get_all_with_limit(self, db_session, mock_db_manager):
        """Test getting entities with limit."""
        for i in range(5):
            p = Participant(name=f"P{i}", gender="male", service_type="publisher")
            db_session.add(p)
        db_session.commit()

        repo = ParticipantRepository(mock_db_manager)
        result = repo.get_all(limit=3)

        assert len(result) == 3

    def test_delete(self, db_session, mock_db_manager):
        """Test deleting entity."""
        p = Participant(name="Для удаления", gender="male", service_type="publisher")
        db_session.add(p)
        db_session.commit()
        p_id = p.id

        repo = ParticipantRepository(mock_db_manager)
        result = repo.delete(p_id)

        assert result is True
        assert db_session.get(Participant, p_id) is None

    def test_delete_not_found(self, mock_db_manager):
        """Test deleting non-existent entity."""
        repo = ParticipantRepository(mock_db_manager)
        result = repo.delete(999)

        assert result is False

    def test_count(self, db_session, mock_db_manager):
        """Test counting entities."""
        p1 = Participant(name="P1", gender="male", service_type="publisher")
        p2 = Participant(name="P2", gender="female", service_type="publisher")
        db_session.add_all([p1, p2])
        db_session.commit()

        repo = ParticipantRepository(mock_db_manager)
        result = repo.count()

        assert result == 2


# =============================================================================
# Parametrized Tests
# =============================================================================


class TestAssignmentRepositoryParametrized:
    """Parametrized tests for AssignmentRepository."""

    @pytest.mark.parametrize(
        "assignment_type,assignment_number",
        [
            ("treasures", "1"),
            ("treasures", "2"),
            ("treasures", "3"),
            ("ministry", "4"),
            ("ministry", "5"),
            ("ministry", "6"),
            ("living", "8"),
            ("living", "9"),
        ],
    )
    def test_get_by_week_various_types(
        self, db_session, mock_db_manager, assignment_type, assignment_number
    ):
        """Test getting assignments of various types."""
        w = Week(week_title="W", start_date=date(2024, 1, 1), month="1", year=2024)
        db_session.add(w)
        db_session.commit()

        a = Assignment(
            week_id=w.id,
            assignment_text=f"Задание {assignment_type}/{assignment_number}",
            assignment_type=assignment_type,
            assignment_number=assignment_number,
        )
        db_session.add(a)
        db_session.commit()

        repo = AssignmentRepository(mock_db_manager)
        result = repo.get_by_week(w.id)

        assert len(result) == 1
        assert result[0].assignment_type == assignment_type
        assert result[0].assignment_number == assignment_number
