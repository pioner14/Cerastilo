"""Tests for core/repositories/participant_repository.py."""

import os
import tempfile
from datetime import date

import pytest

from core.database import DatabaseManager
from core.models import Assignment, AssignmentStatus, Participant, Week
from core.repositories.participant_repository import ParticipantRepository


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
    """Create a ParticipantRepository instance."""
    return ParticipantRepository(db_manager)


@pytest.fixture
def sample_participant(db_manager):
    """Create a sample participant in the database."""
    with db_manager.get_session() as session:
        participant = Participant(
            name="Иван Иванов",
            gender="male",
            service_type="publisher",
            family_group_id=1,
            is_active=True,
        )
        session.add(participant)
        session.commit()
        participant_id = participant.id
    return participant_id


@pytest.fixture
def sample_participants(db_manager):
    """Create multiple participants for testing."""
    with db_manager.get_session() as session:
        participants = [
            Participant(name="Алексей Алексеев", gender="male", is_active=True, family_group_id=1),
            Participant(name="Борис Борисов", gender="male", is_active=True, family_group_id=2),
            Participant(
                name="Виктория Викторова", gender="female", is_active=False, family_group_id=1
            ),
        ]
        session.add_all(participants)
        session.commit()
        return [p.id for p in participants]


@pytest.fixture
def sample_week(db_manager):
    """Create a sample week."""
    with db_manager.get_session() as session:
        week = Week(start_date=date(2026, 3, 2), week_title="Неделя 2 марта", year=2026, month="3")
        session.add(week)
        session.commit()
        return week.id


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


class TestParticipantRepositoryInit:
    """Tests for ParticipantRepository initialization."""

    def test_init_success(self, db_manager):
        """Test successful initialization."""
        repo = ParticipantRepository(db_manager)
        assert repo.db == db_manager
        assert repo.model_class == Participant

    def test_inherits_from_base_repository(self, repository):
        """Test that ParticipantRepository inherits from BaseRepository."""
        assert hasattr(repository, "find")
        assert hasattr(repository, "get_by_id")
        assert hasattr(repository, "get_session")


# =================================================================
#  ТЕСТЫ get_by_name
# =================================================================


class TestGetByName:
    """Tests for get_by_name method."""

    def test_get_by_name_found(self, repository, sample_participant):
        """Test finding participant by name."""
        result = repository.get_by_name("Иван Иванов")

        assert result is not None
        assert result.id == sample_participant
        assert result.name == "Иван Иванов"

    def test_get_by_name_not_found(self, repository):
        """Test finding nonexistent participant."""
        result = repository.get_by_name("Несуществующий")

        assert result is None

    def test_get_by_name_case_sensitive(self, repository, sample_participant):
        """Test that name search is case sensitive."""
        result = repository.get_by_name("иван иванов")

        assert result is None


# =================================================================
#  ТЕСТЫ get_active
# =================================================================


class TestGetActive:
    """Tests for get_active method."""

    def test_get_active_returns_only_active(self, repository, sample_participants):
        """Test that only active participants are returned."""
        result = repository.get_active()

        assert len(result) == 2
        names = [p.name for p in result]
        assert "Алексей Алексеев" in names
        assert "Борис Борисов" in names
        assert "Виктория Викторова" not in names

    def test_get_active_empty(self, repository):
        """Test get_active with no active participants."""
        result = repository.get_active()

        assert result == []


# =================================================================
#  ТЕСТЫ get_by_family
# =================================================================


class TestGetByFamily:
    """Tests for get_by_family method."""

    def test_get_by_family_found(self, repository, sample_participants):
        """Test getting participants by family group."""
        result = repository.get_by_family(1)

        assert len(result) == 2
        names = [p.name for p in result]
        assert "Алексей Алексеев" in names
        assert "Виктория Викторова" in names

    def test_get_by_family_not_found(self, repository):
        """Test getting participants for nonexistent family."""
        result = repository.get_by_family(999)

        assert result == []


# =================================================================
#  ТЕСТЫ QUALIFICATIONS
# =================================================================


class TestQualifications:
    """Tests for qualification methods."""

    def test_get_qualifications_empty(self, repository, sample_participant):
        """Test getting qualifications for participant without any."""
        result = repository.get_qualifications(sample_participant)

        assert result == []

    def test_set_qualifications(self, repository, sample_participant, db_manager):
        """Test setting qualifications."""
        success = repository.set_qualifications(sample_participant, ["chairman", "reader"])

        assert success is True
        quals = repository.get_qualifications(sample_participant)
        assert set(quals) == {"chairman", "reader"}

    def test_set_qualifications_replaces(self, repository, sample_participant):
        """Test that set_qualifications replaces existing ones."""
        repository.set_qualifications(sample_participant, ["chairman"])
        repository.set_qualifications(sample_participant, ["reader", "prayer"])

        quals = repository.get_qualifications(sample_participant)
        assert set(quals) == {"reader", "prayer"}

    def test_add_qualification(self, repository, sample_participant):
        """Test adding a single qualification."""
        repository.add_qualification(sample_participant, "chairman")

        quals = repository.get_qualifications(sample_participant)
        assert "chairman" in quals

    def test_add_qualification_duplicate(self, repository, sample_participant):
        """Test that adding duplicate qualification returns False."""
        repository.add_qualification(sample_participant, "chairman")
        result = repository.add_qualification(sample_participant, "chairman")

        assert result is False
        quals = repository.get_qualifications(sample_participant)
        assert quals.count("chairman") == 1

    def test_get_qualifications_batch(self, repository, sample_participants, db_manager):
        """Test getting qualifications for multiple participants."""
        # Set qualifications for first two participants
        repository.set_qualifications(sample_participants[0], ["chairman"])
        repository.set_qualifications(sample_participants[1], ["reader", "prayer"])

        result = repository.get_qualifications_batch(sample_participants[:2])

        assert sample_participants[0] in result
        assert sample_participants[1] in result
        assert result[sample_participants[0]] == ["chairman"]
        assert set(result[sample_participants[1]]) == {"reader", "prayer"}

    def test_get_qualifications_batch_empty(self, repository):
        """Test batch qualifications with empty list."""
        result = repository.get_qualifications_batch([])

        assert result == {}


# =================================================================
#  ТЕСТЫ get_with_stats
# =================================================================


class TestGetWithStats:
    """Tests for get_with_stats method."""

    def test_get_with_stats(self, repository, sample_participants, sample_assignment):
        """Test getting participants with statistics."""
        result = repository.get_with_stats()

        # sample_participants creates 2 active + sample_assignment
        # creates 1 more via sample_participant
        assert len(result) == 3  # 3 active participants total
        for p in result:
            assert "id" in p
            assert "name" in p
            assert "total_assignments" in p

    def test_get_with_stats_counts_assignments(
        self, repository, sample_participant, sample_assignment
    ):
        """Test that assignment count is correct."""
        result = repository.get_with_stats()

        participant = next(p for p in result if p["id"] == sample_participant)
        assert participant["total_assignments"] == 1

    def test_get_with_stats_ordered_by_name(self, repository, sample_participants):
        """Test that results are ordered by name."""
        result = repository.get_with_stats()

        names = [p["name"] for p in result]
        assert names == sorted(names)


# =================================================================
#  ТЕСТЫ get_assignment_dates_map
# =================================================================


class TestGetAssignmentDatesMap:
    """Tests for get_assignment_dates_map method."""

    def test_get_assignment_dates_map(
        self, repository, sample_participant, sample_week, db_manager
    ):
        """Test getting assignment dates map."""
        # Create assignment
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

        result = repository.get_assignment_dates_map()

        assert sample_participant in result
        assert len(result[sample_participant]) == 1

    def test_get_assignment_dates_map_includes_assistant(
        self, repository, sample_week, sample_participant, db_manager
    ):
        """Test that assistant is included in dates map."""
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
                participant_id=sample_participant,
                assistant_id=assistant_id,
                status=AssignmentStatus.ASSIGNED.value,
            )
            session.add(assignment)
            session.commit()

        result = repository.get_assignment_dates_map()

        assert sample_participant in result
        assert assistant_id in result

    def test_get_assignment_dates_map_empty(self, repository):
        """Test dates map with no assignments."""
        result = repository.get_assignment_dates_map()

        assert result == {}


# =================================================================
#  ТЕСТЫ get_position_dates_map
# =================================================================


class TestGetPositionDatesMap:
    """Tests for get_position_dates_map method."""

    def test_get_position_dates_map(self, repository, sample_participant, sample_week, db_manager):
        """Test getting position dates map."""
        # Create assignment
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

        result = repository.get_position_dates_map()

        # Key format: (participant_id, section, position)
        key = (sample_participant, "treasures", "1")
        assert key in result

    def test_get_position_dates_map_empty(self, repository):
        """Test position dates map with no assignments."""
        result = repository.get_position_dates_map()

        assert result == {}


# =================================================================
#  ТЕСТЫ БАЗОВЫХ МЕТОДОВ
# =================================================================


class TestBaseMethods:
    """Tests for inherited base repository methods."""

    def test_get_by_id(self, repository, sample_participant):
        """Test get_by_id method."""
        result = repository.get_by_id(sample_participant)

        assert result is not None
        assert result.id == sample_participant
        assert result.name == "Иван Иванов"

    def test_get_by_id_nonexistent(self, repository):
        """Test get_by_id for nonexistent participant."""
        result = repository.get_by_id(999)

        assert result is None

    def test_find(self, repository, sample_participants):
        """Test find method."""
        result = repository.find(gender="male")

        assert len(result) == 2

    def test_count(self, repository, sample_participants):
        """Test count method."""
        result = repository.count()

        assert result == 3

    def test_get_all(self, repository, sample_participants):
        """Test get_all method."""
        result = repository.get_all()

        assert len(result) == 3
