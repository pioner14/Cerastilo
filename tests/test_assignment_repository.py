"""Tests for core/repositories/assignment_repository.py."""

import os
import tempfile
from datetime import date, datetime
from unittest.mock import MagicMock, Mock

import pytest

from core.database import DatabaseManager
from core.models import Assignment, AssignmentStatus, Participant, Week
from core.repositories.assignment_repository import AssignmentRepository


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
    """Create an AssignmentRepository instance."""
    return AssignmentRepository(db_manager)


@pytest.fixture
def sample_week(db_manager):
    """Create a sample week in the database."""
    with db_manager.get_session() as session:
        week = Week(start_date=date(2026, 3, 2), week_title="Неделя 1 марта")
        session.add(week)
        session.commit()
        week_id = week.id
    return week_id


@pytest.fixture
def sample_participant(db_manager):
    """Create a sample participant in the database."""
    with db_manager.get_session() as session:
        participant = Participant(name="Иван Иванов", gender="male", family_group_id=1)
        session.add(participant)
        session.commit()
        participant_id = participant.id
    return participant_id


@pytest.fixture
def sample_assistant(db_manager):
    """Create a sample assistant in the database."""
    with db_manager.get_session() as session:
        assistant = Participant(name="Пётр Петров", gender="male", family_group_id=1)
        session.add(assistant)
        session.commit()
        assistant_id = assistant.id
    return assistant_id


@pytest.fixture
def sample_assignment(db_manager, sample_week):
    """Create a sample assignment in the database."""
    with db_manager.get_session() as session:
        assignment = Assignment(
            week_id=sample_week,
            assignment_text="Председатель",
            assignment_type="chairman",
            assignment_number="1",
            section="treasures",
            section_position=1,
            duration=5,
            status=AssignmentStatus.EMPTY.value,
        )
        session.add(assignment)
        session.commit()
        assignment_id = assignment.id
    return assignment_id


# =================================================================
#  ТЕСТЫ ИНИЦИАЛИЗАЦИИ
# =================================================================


class TestAssignmentRepositoryInit:
    """Tests for AssignmentRepository initialization."""

    def test_init_success(self, db_manager):
        """Test successful initialization."""
        repo = AssignmentRepository(db_manager)
        assert repo.db == db_manager
        assert repo.model_class == Assignment

    def test_inherits_from_base_repository(self, repository):
        """Test that AssignmentRepository inherits from BaseRepository."""
        assert hasattr(repository, "find")
        assert hasattr(repository, "get_by_id")
        assert hasattr(repository, "get_session")


# =================================================================
#  ТЕСТЫ get_by_week
# =================================================================


class TestGetByWeek:
    """Tests for get_by_week method."""

    def test_get_by_week_returns_assignments(self, repository, sample_week, sample_assignment):
        """Test that get_by_week returns assignments for a week."""
        result = repository.get_by_week(sample_week)

        assert len(result) == 1
        assert result[0].assignment_text == "Председатель"

    def test_get_by_week_empty_week(self, repository, sample_week):
        """Test get_by_week for week with no assignments."""
        result = repository.get_by_week(sample_week)

        assert len(result) == 0

    def test_get_by_week_multiple_assignments(self, repository, db_manager, sample_week):
        """Test get_by_week with multiple assignments."""
        with db_manager.get_session() as session:
            for i in range(3):
                assignment = Assignment(
                    week_id=sample_week,
                    assignment_text=f"Задание {i+1}",
                    assignment_type="reading",
                    assignment_number=i + 1,
                    duration=5,
                    status=AssignmentStatus.EMPTY.value,
                )
                session.add(assignment)
            session.commit()

        result = repository.get_by_week(sample_week)

        assert len(result) == 3


# =================================================================
#  ТЕСТЫ get_by_participant
# =================================================================


class TestGetByParticipant:
    """Tests for get_by_participant method."""

    def test_get_by_participant_as_participant(
        self, repository, sample_assignment, sample_participant, db_manager
    ):
        """Test getting assignments where participant is main participant."""
        with db_manager.get_session() as session:
            assignment = session.get(Assignment, sample_assignment)
            assignment.participant_id = sample_participant
            assignment.status = AssignmentStatus.ASSIGNED.value
            session.commit()

        result = repository.get_by_participant(sample_participant)

        assert len(result) == 1
        assert result[0].participant_id == sample_participant

    def test_get_by_participant_as_assistant(
        self, repository, sample_assignment, sample_assistant, db_manager
    ):
        """Test getting assignments where participant is assistant."""
        with db_manager.get_session() as session:
            assignment = session.get(Assignment, sample_assignment)
            assignment.assistant_id = sample_assistant
            session.commit()

        result = repository.get_by_participant(sample_assistant)

        assert len(result) == 1
        assert result[0].assistant_id == sample_assistant

    def test_get_by_participant_with_status_filter(
        self, repository, sample_assignment, sample_participant, db_manager
    ):
        """Test getting assignments with status filter."""
        with db_manager.get_session() as session:
            assignment = session.get(Assignment, sample_assignment)
            assignment.participant_id = sample_participant
            assignment.status = AssignmentStatus.ASSIGNED.value
            session.commit()

        result = repository.get_by_participant(
            sample_participant, status=AssignmentStatus.ASSIGNED.value
        )

        assert len(result) == 1

    def test_get_by_participant_no_assignments(self, repository, sample_participant):
        """Test getting assignments for participant with no assignments."""
        result = repository.get_by_participant(sample_participant)

        assert len(result) == 0


# =================================================================
#  ТЕСТЫ get_unassigned
# =================================================================


class TestGetUnassigned:
    """Tests for get_unassigned method."""

    def test_get_unassigned_returns_unassigned(self, repository, sample_assignment):
        """Test that get_unassigned returns assignments without participants."""
        result = repository.get_unassigned()

        assert len(result) == 1
        assert result[0].participant_id is None

    def test_get_unassigned_for_week(self, repository, sample_week, sample_assignment):
        """Test get_unassigned for specific week."""
        result = repository.get_unassigned(week_id=sample_week)

        assert len(result) == 1

    def test_get_unassigned_excludes_assigned(
        self, repository, sample_assignment, sample_participant, db_manager
    ):
        """Test that get_unassigned excludes assigned assignments."""
        with db_manager.get_session() as session:
            assignment = session.get(Assignment, sample_assignment)
            assignment.participant_id = sample_participant
            assignment.status = AssignmentStatus.ASSIGNED.value
            session.commit()

        result = repository.get_unassigned()

        assert len(result) == 0


# =================================================================
#  ТЕСТЫ assign_participant
# =================================================================


class TestAssignParticipant:
    """Tests for assign_participant method."""

    def test_assign_participant_success(self, repository, sample_assignment, sample_participant):
        """Test successful participant assignment."""
        result = repository.assign_participant(
            sample_assignment, sample_participant, role="participant"
        )

        assert result is True

    def test_assign_participant_updates_status(
        self, repository, sample_assignment, sample_participant, db_manager
    ):
        """Test that assignment status is updated."""
        repository.assign_participant(sample_assignment, sample_participant, role="participant")

        with db_manager.get_session() as session:
            assignment = session.get(Assignment, sample_assignment)
            assert assignment.status == AssignmentStatus.ASSIGNED.value

    def test_assign_assistant(self, repository, sample_assignment, sample_assistant):
        """Test assigning an assistant."""
        result = repository.assign_participant(
            sample_assignment, sample_assistant, role="assistant"
        )

        assert result is True

    def test_assign_participant_nonexistent_assignment(self, repository, sample_participant):
        """Test assigning to non-existent assignment."""
        result = repository.assign_participant(99999, sample_participant)

        assert result is False

    def test_assign_participant_rolls_back_when_commit_fails(self, sample_participant):
        session = MagicMock()
        session.__enter__.return_value = session
        session.get.return_value = MagicMock()
        session.commit.side_effect = RuntimeError("commit failed")
        db_manager = Mock()
        db_manager.get_session.return_value = session
        repository = AssignmentRepository(db_manager=db_manager)

        result = repository.assign_participant(1, sample_participant)

        assert result is False
        session.rollback.assert_called_once_with()

    def test_assign_participant_propagates_external_session_failure(self, sample_participant):
        session = MagicMock()
        session.get.return_value = MagicMock()
        session.flush.side_effect = RuntimeError("flush failed")
        repository = AssignmentRepository(db_manager=None, session=session)

        with pytest.raises(RuntimeError, match="flush failed"):
            repository.assign_participant(1, sample_participant)

        session.rollback.assert_not_called()

    def test_clear_participant(self, repository, sample_assignment, sample_participant, db_manager):
        """Test clearing participant from assignment."""
        # First assign
        repository.assign_participant(sample_assignment, sample_participant)

        # Then clear
        result = repository.assign_participant(sample_assignment, None)

        assert result is True
        with db_manager.get_session() as session:
            assignment = session.get(Assignment, sample_assignment)
            assert assignment.participant_id is None
            assert assignment.status == AssignmentStatus.EMPTY.value


# =================================================================
#  ТЕСТЫ clear_week_assignments
# =================================================================


class TestClearWeekAssignments:
    """Tests for clear_week_assignments method."""

    def test_clear_week_assignments_success(
        self, repository, sample_week, sample_assignment, sample_participant, db_manager
    ):
        """Test successful week assignments clearing."""
        # Assign participant first
        with db_manager.get_session() as session:
            assignment = session.get(Assignment, sample_assignment)
            assignment.participant_id = sample_participant
            assignment.status = AssignmentStatus.ASSIGNED.value
            session.commit()

        result = repository.clear_week_assignments(sample_week)

        assert result is True
        with db_manager.get_session() as session:
            assignment = session.get(Assignment, sample_assignment)
            assert assignment.participant_id is None
            assert assignment.status == AssignmentStatus.EMPTY.value

    def test_clear_week_assignments_clears_assistant(
        self, repository, sample_week, sample_assignment, sample_assistant, db_manager
    ):
        """Test that assistant is also cleared."""
        with db_manager.get_session() as session:
            assignment = session.get(Assignment, sample_assignment)
            assignment.assistant_id = sample_assistant
            session.commit()

        repository.clear_week_assignments(sample_week)

        with db_manager.get_session() as session:
            assignment = session.get(Assignment, sample_assignment)
            assert assignment.assistant_id is None


# =================================================================
#  ТЕСТЫ get_conflicts
# =================================================================


class TestGetConflicts:
    """Tests for get_conflicts method."""

    def test_get_conflicts_no_conflicts(self, repository, sample_week, sample_assignment):
        """Test get_conflicts when there are no conflicts."""
        result = repository.get_conflicts(sample_week)

        assert len(result) == 0

    def test_get_conflicts_detects_duplicate_participant(
        self, repository, sample_week, sample_participant, db_manager
    ):
        """Test that conflicts are detected for duplicate participants."""
        # Create two assignments with same participant
        with db_manager.get_session() as session:
            for i in range(2):
                assignment = Assignment(
                    week_id=sample_week,
                    assignment_text=f"Задание {i+1}",
                    assignment_type="reading",
                    assignment_number=i + 1,
                    duration=5,
                    participant_id=sample_participant,
                    status=AssignmentStatus.ASSIGNED.value,
                )
                session.add(assignment)
            session.commit()

        result = repository.get_conflicts(sample_week)

        assert sample_participant in result

    def test_get_conflicts_detects_participant_as_assistant(
        self, repository, sample_week, sample_participant, db_manager
    ):
        """Test conflict when participant is both participant and assistant."""
        with db_manager.get_session() as session:
            # Assignment 1: participant
            a1 = Assignment(
                week_id=sample_week,
                assignment_text="Задание 1",
                assignment_type="reading",
                assignment_number=1,
                duration=5,
                participant_id=sample_participant,
                status=AssignmentStatus.ASSIGNED.value,
            )
            # Assignment 2: same person as assistant
            a2 = Assignment(
                week_id=sample_week,
                assignment_text="Задание 2",
                assignment_type="reading",
                assignment_number=2,
                duration=5,
                assistant_id=sample_participant,
                status=AssignmentStatus.ASSIGNED.value,
            )
            session.add_all([a1, a2])
            session.commit()

        result = repository.get_conflicts(sample_week)

        assert sample_participant in result


# =================================================================
#  ТЕСТЫ get_assignments_with_names
# =================================================================


class TestGetAssignmentsWithNames:
    """Tests for get_assignments_with_names method."""

    def test_get_assignments_with_names_empty(self, repository, sample_week):
        """Test get_assignments_with_names for empty week."""
        result = repository.get_assignments_with_names(sample_week)

        assert len(result) == 0

    def test_get_assignments_with_names_includes_names(
        self,
        repository,
        sample_week,
        sample_assignment,
        sample_participant,
        sample_assistant,
        db_manager,
    ):
        """Test that participant and assistant names are included."""
        with db_manager.get_session() as session:
            assignment = session.get(Assignment, sample_assignment)
            assignment.participant_id = sample_participant
            assignment.assistant_id = sample_assistant
            session.commit()

        result = repository.get_assignments_with_names(sample_week)

        assert len(result) == 1
        assert result[0]["participant_name"] == "Иван Иванов"
        assert result[0]["assistant_name"] == "Пётр Петров"

    def test_get_assignments_with_names_null_participant(
        self, repository, sample_week, sample_assignment
    ):
        """Test that null participant name is handled."""
        result = repository.get_assignments_with_names(sample_week)

        assert len(result) == 1
        assert result[0]["participant_name"] is None


# =================================================================
#  ТЕСТЫ has_assignments
# =================================================================


class TestHasAssignments:
    """Tests for has_assignments method."""

    def test_has_assignments_false(self, repository, sample_week, sample_assignment):
        """Test has_assignments returns False for unassigned week."""
        result = repository.has_assignments(sample_week)

        assert result is False

    def test_has_assignments_true(
        self, repository, sample_week, sample_assignment, sample_participant, db_manager
    ):
        """Test has_assignments returns True for assigned week."""
        with db_manager.get_session() as session:
            assignment = session.get(Assignment, sample_assignment)
            assignment.participant_id = sample_participant
            session.commit()

        result = repository.has_assignments(sample_week)

        assert result is True


# =================================================================
#  ТЕСТЫ get_participant_history
# =================================================================


class TestGetParticipantHistory:
    """Tests for get_participant_history method."""

    def test_get_participant_history_empty(self, repository, sample_participant):
        """Test get_participant_history for participant with no history."""
        result = repository.get_participant_history(sample_participant)

        assert len(result) == 0

    def test_get_participant_history_as_participant(
        self, repository, sample_week, sample_assignment, sample_participant, db_manager
    ):
        """Test get_participant_history as participant."""
        with db_manager.get_session() as session:
            assignment = session.get(Assignment, sample_assignment)
            assignment.participant_id = sample_participant
            session.commit()

        result = repository.get_participant_history(sample_participant)

        assert len(result) == 1
        assert result[0]["role"] == "главный"

    def test_get_participant_history_as_assistant(
        self, repository, sample_week, sample_assignment, sample_assistant, db_manager
    ):
        """Test get_participant_history as assistant."""
        with db_manager.get_session() as session:
            assignment = session.get(Assignment, sample_assignment)
            assignment.assistant_id = sample_assistant
            session.commit()

        result = repository.get_participant_history(sample_assistant)

        assert len(result) == 1
        assert result[0]["role"] == "помощник"


# =================================================================
#  ТЕСТЫ clear_week_assignments_preserving_disabled
# =================================================================


class TestClearWeekAssignmentsPreservingDisabled:
    """Tests for clear_week_assignments_preserving_disabled method."""

    def test_clear_preserving_disabled_returns_success(
        self, repository, sample_week, sample_assignment, sample_participant, db_manager
    ):
        """Test that method returns success tuple."""
        with db_manager.get_session() as session:
            assignment = session.get(Assignment, sample_assignment)
            assignment.participant_id = sample_participant
            assignment.status = AssignmentStatus.ASSIGNED.value
            session.commit()

        success, affected = repository.clear_week_assignments_preserving_disabled(sample_week)

        assert success is True
        assert sample_participant in affected

    def test_clear_preserving_disabled_preserves_disabled(
        self, repository, sample_week, sample_participant, db_manager
    ):
        """Test that disabled assignments are preserved."""
        with db_manager.get_session() as session:
            # Create disabled assignment
            disabled = Assignment(
                week_id=sample_week,
                assignment_text="Disabled",
                assignment_type="reading",
                assignment_number=1,
                duration=5,
                participant_id=sample_participant,
                status=AssignmentStatus.DISABLED.value,
            )
            session.add(disabled)
            session.commit()

        repository.clear_week_assignments_preserving_disabled(sample_week)

        with db_manager.get_session() as session:
            assignment = (
                session.query(Assignment)
                .filter_by(week_id=sample_week, status=AssignmentStatus.DISABLED.value)
                .first()
            )
            assert assignment.participant_id == sample_participant

    def test_clear_preserving_disabled_clears_non_disabled(
        self, repository, sample_week, sample_assignment, sample_participant, db_manager
    ):
        """Test that non-disabled assignments are cleared."""
        with db_manager.get_session() as session:
            assignment = session.get(Assignment, sample_assignment)
            assignment.participant_id = sample_participant
            assignment.status = AssignmentStatus.ASSIGNED.value
            session.commit()

        repository.clear_week_assignments_preserving_disabled(sample_week)

        with db_manager.get_session() as session:
            assignment = session.get(Assignment, sample_assignment)
            assert assignment.participant_id is None
            assert assignment.status == AssignmentStatus.EMPTY.value


# =================================================================
#  ТЕСТЫ _parse_date
# =================================================================


class TestParseDate:
    """Tests for _parse_date static method."""

    def test_parse_date_iso_format(self):
        """Test parsing ISO 8601 date format."""
        result = AssignmentRepository._parse_date("2026-03-02")

        assert result == datetime(2026, 3, 2)

    def test_parse_date_european_format(self):
        """Test parsing European date format."""
        result = AssignmentRepository._parse_date("02.03.2026")

        assert result == datetime(2026, 3, 2)

    def test_parse_date_none(self):
        """Test parsing None value."""
        result = AssignmentRepository._parse_date(None)

        assert result is None

    def test_parse_date_invalid_format(self):
        """Test parsing invalid date format."""
        result = AssignmentRepository._parse_date("invalid")

        assert result is None

    def test_parse_date_empty_string(self):
        """Test parsing empty string."""
        result = AssignmentRepository._parse_date("")

        assert result is None
