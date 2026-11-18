"""
Tests for core/services.py - ParticipantService and ScheduleService.
"""

from datetime import date
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.events import Event, EventBus
from core.models import Assignment, AssignmentConfig, Base, Participant, Week
from core.services import ParticipantService, ScheduleService


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

    class SessionContext:
        def __enter__(self):
            return db_session

        def __exit__(self, *args):
            pass

    db_manager.get_session.return_value = SessionContext()
    return db_manager


@pytest.fixture
def event_bus():
    """Create event bus."""
    return EventBus()


@pytest.fixture
def participant_service(mock_db_manager, event_bus):
    """Create ParticipantService instance."""
    return ParticipantService(mock_db_manager, event_bus)


@pytest.fixture
def schedule_service(mock_db_manager, event_bus):
    """Create ScheduleService instance."""
    return ScheduleService(mock_db_manager, event_bus)


# =============================================================================
# ParticipantService Tests
# =============================================================================


class TestParticipantServiceAddParticipant:
    """Tests for ParticipantService.add_participant method."""

    def test_add_participant_success(self, db_session, mock_db_manager, event_bus):
        """Test successful participant addition."""
        # Setup mock
        event_bus.emit = Mock()

        participant_service = ParticipantService(mock_db_manager, event_bus)

        # Execute
        result = participant_service.add_participant(
            name="Иван Петров",
            gender="male",
            service_type="publisher",
            quals=["chairman", "reader"],
        )

        # Verify
        assert result is not None
        assert isinstance(result, int)

        # Check participant in DB
        p = db_session.get(Participant, result)
        assert p is not None
        assert p.name == "Иван Петров"
        assert p.gender == "male"
        assert p.service_type == "publisher"

        # Check event was emitted
        event_bus.emit.assert_called_once_with(Event.PARTICIPANT_CHANGED, p_id=result)

    def test_add_participant_duplicate_name(self, db_session, mock_db_manager, event_bus):
        """Test that duplicate name returns None."""
        participant_service = ParticipantService(mock_db_manager, event_bus)

        # Add first participant
        participant_service.add_participant(
            name="Иван Петров", gender="male", service_type="publisher", quals=[]
        )

        # Try to add duplicate
        result = participant_service.add_participant(
            name="Иван Петров", gender="male", service_type="publisher", quals=[]
        )

        assert result is None

    def test_add_participant_with_family_id(self, db_session, mock_db_manager, event_bus):
        """Test participant with family group."""
        participant_service = ParticipantService(mock_db_manager, event_bus)

        result = participant_service.add_participant(
            name="Анна Иванова",
            gender="female",
            service_type="publisher",
            quals=["reader"],
            family_id=5,
        )

        p = db_session.get(Participant, result)
        assert p.family_group_id == 5

    def test_add_participant_empty_quals(self, db_session, mock_db_manager, event_bus):
        """Test participant with no qualifications."""
        participant_service = ParticipantService(mock_db_manager, event_bus)

        result = participant_service.add_participant(
            name="Пётр Сидоров", gender="male", service_type="elder", quals=[]
        )

        assert result is not None
        p = db_session.get(Participant, result)
        assert p.name == "Пётр Сидоров"


class TestParticipantServiceUpdateParticipant:
    """Tests for ParticipantService.update_participant method."""

    def test_update_participant_success(self, db_session, mock_db_manager, event_bus):
        """Test successful participant update."""
        event_bus.emit = Mock()
        participant_service = ParticipantService(mock_db_manager, event_bus)

        # Create participant
        p = Participant(name="Старое Имя", gender="male", service_type="publisher")
        db_session.add(p)
        db_session.commit()
        p_id = p.id

        # Update
        result = participant_service.update_participant(
            p_id=p_id,
            name="Новое Имя",
            gender="male",
            service_type="elder",
            quals=["chairman", "reader", "speaker"],
        )

        assert result is True

        # Verify changes
        db_session.expire_all()
        updated = db_session.get(Participant, p_id)
        assert updated.name == "Новое Имя"
        assert updated.service_type == "elder"

        event_bus.emit.assert_called_once_with(Event.PARTICIPANT_CHANGED, p_id=p_id)

    def test_update_participant_not_found(self, mock_db_manager, event_bus):
        """Test update of non-existent participant."""
        participant_service = ParticipantService(mock_db_manager, event_bus)

        result = participant_service.update_participant(
            p_id=9999, name="Имя", gender="male", service_type="publisher", quals=[]
        )

        assert result is False

    def test_update_participant_change_gender(self, db_session, mock_db_manager, event_bus):
        """Test changing participant gender."""
        participant_service = ParticipantService(mock_db_manager, event_bus)

        p = Participant(name="Тест", gender="male", service_type="publisher")
        db_session.add(p)
        db_session.commit()

        result = participant_service.update_participant(
            p_id=p.id, name="Тест", gender="female", service_type="publisher", quals=[]
        )

        assert result is True
        db_session.expire_all()
        updated = db_session.get(Participant, p.id)
        assert updated.gender == "female"


class TestParticipantServiceDeleteParticipant:
    """Tests for ParticipantService.delete_participant method."""

    def test_delete_participant_success(self, db_session, mock_db_manager, event_bus):
        """Test successful participant deletion."""
        event_bus.emit = Mock()
        participant_service = ParticipantService(mock_db_manager, event_bus)

        p = Participant(name="Для Удаления", gender="male", service_type="publisher")
        db_session.add(p)
        db_session.commit()
        p_id = p.id

        result = participant_service.delete_participant(p_id)

        assert result is True
        assert db_session.get(Participant, p_id) is None
        event_bus.emit.assert_called_once_with(Event.PARTICIPANT_CHANGED, p_id=p_id)

    def test_delete_participant_not_found(self, mock_db_manager, event_bus):
        """Test deletion of non-existent participant."""
        participant_service = ParticipantService(mock_db_manager, event_bus)

        result = participant_service.delete_participant(9999)
        assert result is False


class TestParticipantServiceGetParticipant:
    """Tests for ParticipantService.get_participant method."""

    def test_get_participant_success(self, db_session, mock_db_manager, event_bus):
        """Test getting existing participant."""
        participant_service = ParticipantService(mock_db_manager, event_bus)

        p = Participant(name="Тестовый", gender="male", service_type="elder")
        db_session.add(p)
        db_session.commit()

        result = participant_service.get_participant(p.id)

        assert result is not None
        assert result["name"] == "Тестовый"
        assert result["gender"] == "male"

    def test_get_participant_not_found(self, mock_db_manager, event_bus):
        """Test getting non-existent participant."""
        participant_service = ParticipantService(mock_db_manager, event_bus)

        result = participant_service.get_participant(9999)
        assert result is None


class TestParticipantServiceGetAllParticipants:
    """Tests for ParticipantService.get_all_participants method."""

    def test_get_all_participants_empty(self, mock_db_manager, event_bus):
        """Test getting participants from empty database."""
        participant_service = ParticipantService(mock_db_manager, event_bus)

        result = participant_service.get_all_participants()
        assert result == []

    def test_get_all_participants_with_data(self, db_session, mock_db_manager, event_bus):
        """Test getting all participants."""
        participant_service = ParticipantService(mock_db_manager, event_bus)

        # Add participants
        p1 = Participant(name="Алексей", gender="male", service_type="elder", is_active=True)
        p2 = Participant(name="Мария", gender="female", service_type="publisher", is_active=True)
        p3 = Participant(
            name="Неактивный", gender="male", service_type="publisher", is_active=False
        )
        db_session.add_all([p1, p2, p3])
        db_session.commit()

        # Get active only
        result = participant_service.get_all_participants(active_only=True)
        assert len(result) == 2

        # Get all
        result = participant_service.get_all_participants(active_only=False)
        assert len(result) == 3


# =============================================================================
# ScheduleService Tests
# =============================================================================


class TestScheduleServiceGetWeekData:
    """Tests for ScheduleService.get_week_data method."""

    def test_get_week_data_success(self, db_session, mock_db_manager, event_bus):
        """Test getting week data."""
        schedule_service = ScheduleService(mock_db_manager, event_bus)

        # Create week with assignments
        week = Week(week_title="Неделя 1", start_date=date(2024, 1, 1), month="1", year=2024)
        db_session.add(week)
        db_session.commit()

        with patch("core.schedule_service.ScheduleDomainService.get_week_data") as mock_get_week:
            mock_get_week.return_value = {"id": week.id, "title": "Неделя 1"}
            result = schedule_service.get_week_data(week.id)

            assert result is not None

    def test_get_week_data_not_found(self, mock_db_manager, event_bus):
        """Test getting non-existent week."""
        schedule_service = ScheduleService(mock_db_manager, event_bus)

        with patch("core.schedule_service.ScheduleDomainService.get_week_data") as mock_get_week:
            mock_get_week.return_value = None
            result = schedule_service.get_week_data(9999)
            assert result is None


class TestScheduleServiceSetSpecialEvent:
    """Tests for ScheduleService.set_special_event method."""

    def test_set_special_event_success(self, db_session, mock_db_manager, event_bus):
        """Test setting special event."""
        event_bus.emit = Mock()
        schedule_service = ScheduleService(mock_db_manager, event_bus)

        week = Week(week_title="Тест", start_date=date(2024, 1, 1), month="1", year=2024)
        db_session.add(week)
        db_session.commit()

        # Mock db method
        schedule_service.db.set_week_special_event = Mock(return_value=True)

        result = schedule_service.set_special_event(week.id, "memorial")

        assert result is True
        event_bus.emit.assert_called_once()


class TestScheduleServiceAssignParticipant:
    """Tests for ScheduleService.assign_participant method."""

    def test_assign_participant_success(self, db_session, mock_db_manager, event_bus):
        """Test assigning participant to assignment."""
        event_bus.emit = Mock()
        schedule_service = ScheduleService(mock_db_manager, event_bus)

        week = Week(week_title="Тест", start_date=date(2024, 1, 1), month="1", year=2024)
        db_session.add(week)
        db_session.commit()

        assignment = Assignment(
            week_id=week.id,
            assignment_text="Задание 1",
            assignment_type="treasures",
            assignment_number="1",
        )
        db_session.add(assignment)
        db_session.commit()

        participant = Participant(name="Иван", gender="male", service_type="elder")
        db_session.add(participant)
        db_session.commit()

        # Mock the domain service instance directly (lazy property)
        mock_domain = Mock()
        mock_domain.assign_participant.return_value = True
        schedule_service._schedule_domain_service = mock_domain

        result = schedule_service.assign_participant(assignment.id, participant.id)

        assert result is True
        mock_domain.assign_participant.assert_called_once()


class TestScheduleServiceUpdateAssignmentDuration:
    def test_update_assignment_duration(self, db_session, mock_db_manager, event_bus):
        event_bus.emit = Mock()
        service = ScheduleService(mock_db_manager, event_bus)
        week = Week(
            week_title="Неделя",
            start_date=date(2026, 9, 28),
            month="Сентябрь",
            year=2026,
        )
        db_session.add(week)
        db_session.flush()
        assignment = Assignment(
            week_id=week.id,
            assignment_text="Пункт",
            assignment_number="1",
            section="ministry",
            duration=5,
        )
        db_session.add(assignment)
        db_session.commit()

        result = service.update_assignment_duration(assignment.id, 12)

        assert result is True
        db_session.expire_all()
        assert db_session.get(Assignment, assignment.id).duration == 12
        event_bus.emit.assert_called_once_with(
            Event.ASSIGNMENT_CHANGED,
            week_id=week.id,
        )

    def test_update_assignment_duration_rejects_missing_assignment(
        self, mock_db_manager, event_bus
    ):
        service = ScheduleService(mock_db_manager, event_bus)

        assert service.update_assignment_duration(999, 10) is False


class TestScheduleServiceReplaceWeekAssignments:
    def test_restore_snapshot_preserves_assignment_ids(
        self, db_session, mock_db_manager, event_bus
    ):
        service = ScheduleService(mock_db_manager, event_bus)
        week = Week(week_title="Неделя", start_date=date(2026, 9, 28), month="Сентябрь", year=2026)
        db_session.add(week)
        db_session.flush()
        assignment = Assignment(
            week_id=week.id,
            assignment_text="Исходный пункт",
            assignment_type="custom",
            assignment_number="10",
            section="ministry",
            duration=7,
        )
        db_session.add(assignment)
        db_session.commit()
        assignment_id = assignment.id
        assignment.assignment_text = "Изменённый пункт"
        db_session.commit()
        snapshot = [
            {
                "id": assignment_id,
                "assignment_text": "Исходный пункт",
                "assignment_type": "custom",
                "assignment_number": "10",
                "section": "ministry",
                "section_position": "custom_10",
                "duration": 7,
                "sort_order": 0,
                "discussion_marker": None,
                "participant_id": None,
                "assistant_id": None,
                "status": "empty",
            }
        ]

        result = service.replace_week_assignments(week.id, snapshot)

        assert result is True
        db_session.expire_all()
        restored = db_session.get(Assignment, assignment_id)
        assert restored.assignment_text == "Исходный пункт"
        assert restored.duration == 7


class TestScheduleServiceReorderWeekAssignments:
    def test_reorder_week_assignments(self, db_session, mock_db_manager, event_bus):
        service = ScheduleService(mock_db_manager, event_bus)
        week = Week(week_title="Неделя", start_date=date(2026, 9, 28), month="Сентябрь", year=2026)
        db_session.add(week)
        db_session.flush()
        assignments = [
            Assignment(
                week_id=week.id,
                assignment_text=f"Пункт {index}",
                assignment_type="custom",
                section="ministry",
            )
            for index in range(3)
        ]
        db_session.add_all(assignments)
        db_session.commit()
        ordered_ids = [assignments[2].id, assignments[0].id, assignments[1].id]

        result = service.reorder_week_assignments(week.id, ordered_ids)

        assert result is True
        db_session.expire_all()
        stored = {
            assignment.id: assignment.sort_order
            for assignment in db_session.query(Assignment).filter_by(week_id=week.id).all()
        }
        assert stored == {
            assignments[2].id: 0,
            assignments[0].id: 1,
            assignments[1].id: 2,
        }

    def test_reorder_rejects_foreign_assignment(self, mock_db_manager, event_bus):
        service = ScheduleService(mock_db_manager, event_bus)

        assert service.reorder_week_assignments(1, [999]) is False


class TestScheduleServiceAddManualAssignment:
    def test_add_manual_assignment_creates_custom_item(
        self, db_session, mock_db_manager, event_bus
    ):
        event_bus.emit = Mock()
        service = ScheduleService(mock_db_manager, event_bus)
        week = Week(
            week_title="Неделя",
            start_date=date(2026, 9, 28),
            month="Сентябрь",
            year=2026,
        )
        participant = Participant(name="Иван Петров", gender="male", service_type="PUB")
        db_session.add_all([week, participant])
        db_session.flush()
        db_session.add(
            Assignment(
                week_id=week.id,
                assignment_text="Существующий пункт",
                assignment_number="9",
                section="ministry",
                section_position="9",
            )
        )
        db_session.commit()

        assignment_id = service.add_manual_assignment(
            week.id,
            "Внеочередное выступление",
            "ministry",
            7,
            participant.id,
        )

        assert assignment_id is not None
        assignment = db_session.get(Assignment, assignment_id)
        assert assignment.assignment_type == "custom"
        assert assignment.assignment_number == "10"
        assert assignment.section == "ministry"
        assert assignment.section_position == "custom_10"
        assert assignment.duration == 7
        assert assignment.participant_id == participant.id
        event_bus.emit.assert_called_once_with(
            Event.ASSIGNMENT_CHANGED,
            week_id=week.id,
        )

    def test_add_manual_assignment_uses_section_number_and_order(
        self, db_session, mock_db_manager, event_bus
    ):
        service = ScheduleService(mock_db_manager, event_bus)
        week = Week(week_title="Неделя", start_date=date(2026, 10, 5), month="Октябрь", year=2026)
        db_session.add(week)
        db_session.flush()
        ministry = Assignment(
            week_id=week.id,
            assignment_text="Служение",
            assignment_number="4",
            section="ministry",
            sort_order=0,
        )
        living = Assignment(
            week_id=week.id,
            assignment_text="Жизнь",
            assignment_number="8",
            section="living",
            sort_order=1,
        )
        db_session.add_all([ministry, living])
        db_session.commit()

        assignment_id = service.add_manual_assignment(
            week.id,
            "Дополнительный пункт",
            "living",
            5,
        )

        assert assignment_id is not None
        db_session.expire_all()
        created = db_session.get(Assignment, assignment_id)
        assert created.assignment_number == "9"
        assert created.sort_order == 2
        assert db_session.get(Assignment, living.id).sort_order == 1
        assert db_session.get(Assignment, ministry.id).sort_order == 0

    def test_add_manual_assignment_rejects_unknown_week(self, mock_db_manager, event_bus):
        service = ScheduleService(mock_db_manager, event_bus)

        result = service.add_manual_assignment(999, "Пункт", "ministry", 5)

        assert result is None

    def test_update_manual_assignment(self, db_session, mock_db_manager, event_bus):
        service = ScheduleService(mock_db_manager, event_bus)
        week = Week(week_title="Неделя", start_date=date(2026, 9, 28), month="Сентябрь", year=2026)
        db_session.add(week)
        db_session.flush()
        assignment = Assignment(
            week_id=week.id,
            assignment_text="Старый пункт",
            assignment_type="custom",
            assignment_number="10",
            section="ministry",
            section_position="custom_10",
            duration=5,
        )
        db_session.add(assignment)
        db_session.commit()

        result = service.update_manual_assignment(assignment.id, "Новый пункт", "living", 9)

        assert result is True
        db_session.expire_all()
        updated = db_session.get(Assignment, assignment.id)
        assert updated.assignment_text == "Новый пункт"
        assert updated.section == "living"
        assert updated.duration == 9

    def test_delete_manual_assignment(self, db_session, mock_db_manager, event_bus):
        service = ScheduleService(mock_db_manager, event_bus)
        week = Week(week_title="Неделя", start_date=date(2026, 9, 28), month="Сентябрь", year=2026)
        db_session.add(week)
        db_session.flush()
        assignment = Assignment(
            week_id=week.id,
            assignment_text="Пункт",
            assignment_type="custom",
            assignment_number="10",
            section="ministry",
        )
        db_session.add(assignment)
        db_session.commit()
        assignment_id = assignment.id

        assert service.delete_manual_assignment(assignment_id) is True
        assert db_session.get(Assignment, assignment_id) is None

    def test_duplicate_manual_assignment(self, db_session, mock_db_manager, event_bus):
        service = ScheduleService(mock_db_manager, event_bus)
        week = Week(week_title="Неделя", start_date=date(2026, 9, 28), month="Сентябрь", year=2026)
        db_session.add(week)
        db_session.flush()
        source = Assignment(
            week_id=week.id,
            assignment_text="Пункт",
            assignment_type="custom",
            assignment_number="10",
            section="ministry",
            section_position="custom_10",
            duration=7,
        )
        db_session.add(source)
        db_session.commit()

        duplicate_id = service.duplicate_manual_assignment(source.id)

        assert duplicate_id is not None
        duplicate = db_session.get(Assignment, duplicate_id)
        assert duplicate.assignment_text == "Пункт"
        assert duplicate.assignment_number == "11"
        assert duplicate.participant_id is None


class TestScheduleServiceClearWeekAssignments:
    """Tests for ScheduleService.clear_week_assignments method."""

    def test_clear_week_assignments_success(self, db_session, mock_db_manager, event_bus):
        """Test clearing all assignments for a week."""
        event_bus.emit = Mock()
        schedule_service = ScheduleService(mock_db_manager, event_bus)

        week = Week(week_title="Тест", start_date=date(2024, 1, 1), month="1", year=2024)
        db_session.add(week)
        db_session.commit()

        # Mock the domain service instance directly (lazy property)
        mock_domain = Mock()
        mock_domain.clear_week_assignments.return_value = True
        schedule_service._schedule_domain_service = mock_domain

        result = schedule_service.clear_week_assignments(week.id)

        assert result is True
        mock_domain.clear_week_assignments.assert_called_once_with(week.id)


class TestScheduleServiceSettings:
    """Tests for ScheduleService settings methods."""

    def test_get_setting_existing(self, mock_db_manager, event_bus):
        """Test getting existing setting."""
        schedule_service = ScheduleService(mock_db_manager, event_bus)
        schedule_service.db.get_setting = Mock(return_value="value")

        result = schedule_service.get_setting("test_key")

        assert result == "value"

    def test_get_setting_default(self, mock_db_manager, event_bus):
        """Test getting setting with default."""
        schedule_service = ScheduleService(mock_db_manager, event_bus)
        schedule_service.db.get_setting = Mock(return_value="default_value")

        result = schedule_service.get_setting("missing_key", "default_value")

        assert result == "default_value"

    def test_save_setting(self, mock_db_manager, event_bus):
        """Test saving setting."""
        schedule_service = ScheduleService(mock_db_manager, event_bus)
        schedule_service.db.save_setting = Mock(return_value=True)

        result = schedule_service.save_setting("key", "value")

        assert result is True


class TestScheduleServiceWeekAnnouncement:
    """Tests for ScheduleService week announcement methods."""

    def test_get_week_announcement_existing(self, db_session, mock_db_manager, event_bus):
        """Test getting week announcement."""
        schedule_service = ScheduleService(mock_db_manager, event_bus)

        week = Week(
            week_title="Тест",
            start_date=date(2024, 1, 1),
            month="1",
            year=2024,
            announcement="Важное объявление",
        )
        db_session.add(week)
        db_session.commit()

        result = schedule_service.get_week_announcement(week.id)

        assert result == "Важное объявление"

    def test_get_week_announcement_empty(self, db_session, mock_db_manager, event_bus):
        """Test getting empty announcement."""
        schedule_service = ScheduleService(mock_db_manager, event_bus)

        week = Week(week_title="Тест", start_date=date(2024, 1, 1), month="1", year=2024)
        db_session.add(week)
        db_session.commit()

        result = schedule_service.get_week_announcement(week.id)

        assert result == ""

    def test_save_week_announcement(self, db_session, mock_db_manager, event_bus):
        """Test saving week announcement."""
        schedule_service = ScheduleService(mock_db_manager, event_bus)

        week = Week(week_title="Тест", start_date=date(2024, 1, 1), month="1", year=2024)
        db_session.add(week)
        db_session.commit()

        result = schedule_service.save_week_announcement(week.id, "Новое объявление")

        assert result is True
        db_session.expire_all()
        updated = db_session.get(Week, week.id)
        assert updated.announcement == "Новое объявление"


class TestScheduleServiceAssignmentConfig:
    """Tests for ScheduleService assignment config methods."""

    def test_get_assignment_config_all(self, db_session, mock_db_manager, event_bus):
        """Test getting all assignment configs."""
        schedule_service = ScheduleService(mock_db_manager, event_bus)

        config = AssignmentConfig(
            section="treasures",
            position="1",
            assignment_name="Задание 1",
            required_qualification="reader",
            is_brothers_only=True,
        )
        db_session.add(config)
        db_session.commit()

        result = schedule_service.get_assignment_config()

        assert len(result) >= 1
        found = next((c for c in result if c["section"] == "treasures"), None)
        assert found is not None

    def test_get_assignment_config_specific(self, db_session, mock_db_manager, event_bus):
        """Test getting specific assignment config."""
        schedule_service = ScheduleService(mock_db_manager, event_bus)

        config = AssignmentConfig(
            section="ministry",
            position="4",
            assignment_name="Задание",
            required_qualification="speaker",
        )
        db_session.add(config)
        db_session.commit()

        result = schedule_service.get_assignment_config("ministry", "4")

        assert result is not None
        assert result.section == "ministry"
        assert result.position == "4"


class TestScheduleServiceWeeksDateRange:
    """Tests for ScheduleService.get_weeks_date_range method."""

    def test_get_weeks_date_range_success(self, db_session, mock_db_manager, event_bus):
        """Test getting date range for weeks."""
        schedule_service = ScheduleService(mock_db_manager, event_bus)

        w1 = Week(week_title="W1", start_date=date(2024, 1, 1), month="1", year=2024)
        w2 = Week(week_title="W2", start_date=date(2024, 1, 8), month="1", year=2024)
        w3 = Week(week_title="W3", start_date=date(2024, 1, 15), month="1", year=2024)
        db_session.add_all([w1, w2, w3])
        db_session.commit()

        result = schedule_service.get_weeks_date_range([w1.id, w2.id, w3.id])

        assert result is not None
        min_date, max_date = result
        assert min_date == date(2024, 1, 1)
        assert max_date == date(2024, 1, 15)

    def test_get_weeks_date_range_empty(self, mock_db_manager, event_bus):
        """Test getting date range for empty list."""
        schedule_service = ScheduleService(mock_db_manager, event_bus)

        result = schedule_service.get_weeks_date_range([])

        assert result == (None, None)

    def test_get_weeks_date_range_not_found(self, mock_db_manager, event_bus):
        """Test getting date range for non-existent weeks."""
        schedule_service = ScheduleService(mock_db_manager, event_bus)

        result = schedule_service.get_weeks_date_range([9999])

        assert result == (None, None)


# =============================================================================
# Parametrized Tests
# =============================================================================


class TestParticipantServiceParametrized:
    """Parametrized tests for ParticipantService."""

    @pytest.mark.parametrize(
        "gender,service_type,expected_valid",
        [
            ("male", "publisher", True),
            ("female", "publisher", True),
            ("male", "elder", True),
            ("male", "servant", True),
            ("female", "pioneer", True),
        ],
    )
    def test_add_participant_various_types(
        self, db_session, mock_db_manager, event_bus, gender, service_type, expected_valid
    ):
        """Test adding participants with various types."""
        participant_service = ParticipantService(mock_db_manager, event_bus)

        result = participant_service.add_participant(
            name=f"Тест_{gender}_{service_type}", gender=gender, service_type=service_type, quals=[]
        )

        if expected_valid:
            assert result is not None
        else:
            assert result is None

    @pytest.mark.parametrize("quals_count", [0, 1, 3, 5])
    def test_add_participant_various_quals_count(
        self, db_session, mock_db_manager, event_bus, quals_count
    ):
        """Test adding participants with various qualification counts."""
        participant_service = ParticipantService(mock_db_manager, event_bus)

        quals = [f"qual_{i}" for i in range(quals_count)]

        result = participant_service.add_participant(
            name=f"Тест_quals_{quals_count}", gender="male", service_type="publisher", quals=quals
        )

        assert result is not None


class TestParticipantExcludedWeeks:
    """Tests for excluded weeks functionality in ParticipantService."""

    def test_excluded_weeks_flow(self, db_session, mock_db_manager, event_bus):
        participant_service = ParticipantService(mock_db_manager, event_bus)

        # Create participant
        p_id = participant_service.add_participant(
            name="Иван Исключенный", gender="male", service_type="publisher", quals=[]
        )
        assert p_id is not None

        # Add single excluded week
        d1 = date(2026, 6, 8)
        assert participant_service.add_excluded_week(p_id, d1) is True

        # Check in DB
        weeks = participant_service.get_excluded_weeks(p_id)
        assert len(weeks) == 1
        assert weeks[0] == d1

        # Try duplicate add
        assert participant_service.add_excluded_week(p_id, d1) is True
        assert len(participant_service.get_excluded_weeks(p_id)) == 1

        # Add string date
        d2 = "2026-06-15"
        assert participant_service.add_excluded_week(p_id, d2) is True
        weeks = participant_service.get_excluded_weeks(p_id)
        assert len(weeks) == 2
        assert weeks[1] == date(2026, 6, 15)

        # Remove single week
        assert participant_service.remove_excluded_week(p_id, d1) is True
        weeks = participant_service.get_excluded_weeks(p_id)
        assert len(weeks) == 1
        assert weeks[0] == date(2026, 6, 15)

        # Set all excluded weeks
        dates_list = [date(2026, 7, 6), date(2026, 7, 13)]
        assert participant_service.set_excluded_weeks(p_id, dates_list) is True
        weeks = participant_service.get_excluded_weeks(p_id)
        assert len(weeks) == 2
        assert weeks == dates_list

        # Set pattern
        # every 2 weeks, count=3 starting 2026-08-03
        # should generate: Aug 3, Aug 17, Aug 31
        added = participant_service.set_excluded_weeks_from_pattern(
            p_id, "2026-08-03", interval_weeks=2, count=3, replace=True
        )
        assert added == 3
        weeks = participant_service.get_excluded_weeks(p_id)
        assert len(weeks) == 3
        assert weeks == [date(2026, 8, 3), date(2026, 8, 17), date(2026, 8, 31)]

        # Clear all
        assert participant_service.clear_excluded_weeks(p_id) is True
        assert len(participant_service.get_excluded_weeks(p_id)) == 0
