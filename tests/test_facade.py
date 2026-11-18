"""
Tests for core/facade.py - ApplicationFacade.
"""

import pytest
from unittest.mock import Mock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import Base
from core.facade import ApplicationFacade
from core.services import ParticipantService, ScheduleService
from core.error_service import ErrorService
from core.events import EventBus


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
    """Create mock database manager."""
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


@pytest.fixture
def error_service(event_bus):
    """Create ErrorService instance."""
    return ErrorService(event_bus)


@pytest.fixture
def facade(participant_service, schedule_service, error_service, event_bus):
    """Create ApplicationFacade instance."""
    return ApplicationFacade(
        participant_service=participant_service,
        schedule_service=schedule_service,
        error_service=error_service,
        event_bus=event_bus,
    )


# =============================================================================
# Participant Facade Tests
# =============================================================================


class TestFacadeParticipants:
    """Tests for ApplicationFacade participant methods."""

    def test_get_participants_list(self, facade, participant_service):
        """Test getting participants list."""
        participant_service.get_all_participants = Mock(return_value=[])

        result = facade.get_participants_list()

        participant_service.get_all_participants.assert_called_once()
        assert result == []

    def test_get_all_participants(self, facade, participant_service):
        """Test getting all participants."""
        participant_service.get_all_participants = Mock(return_value=[{"id": 1, "name": "Иван"}])

        result = facade.get_all_participants()

        participant_service.get_all_participants.assert_called_once_with(active_only=True)
        assert len(result) == 1

    def test_get_all_participants_include_inactive(self, facade, participant_service):
        """Test getting all participants including inactive."""
        participant_service.get_all_participants = Mock(return_value=[])

        facade.get_all_participants(active_only=False)

        participant_service.get_all_participants.assert_called_once_with(active_only=False)

    def test_get_participant(self, facade, participant_service):
        """Test getting single participant."""
        participant_service.get_participant = Mock(return_value={"id": 1, "name": "Иван"})

        result = facade.get_participant(1)

        participant_service.get_participant.assert_called_once_with(1)
        assert result["name"] == "Иван"

    def test_add_participant(self, facade, participant_service):
        """Test adding participant through facade."""
        participant_service.add_participant = Mock(return_value=1)

        result = facade.add_participant(
            name="Новый", gender="male", service_type="publisher", quals=["reader"]
        )

        participant_service.add_participant.assert_called_once()
        assert result == 1

    def test_add_participant_with_family(self, facade, participant_service):
        """Test adding participant with family group."""
        participant_service.add_participant = Mock(return_value=1)

        facade.add_participant(
            name="Новый", gender="male", service_type="publisher", quals=[], family_id=5
        )

        call_args = participant_service.add_participant.call_args
        assert call_args.kwargs.get("family_id") == 5 or call_args.args[4] == 5

    def test_update_participant(self, facade, participant_service):
        """Test updating participant through facade."""
        participant_service.update_participant = Mock(return_value=True)

        result = facade.update_participant(
            p_id=1, name="Обновлённый", gender="male", service_type="elder", quals=["chairman"]
        )

        participant_service.update_participant.assert_called_once()
        assert result is True

    def test_delete_participant(self, facade, participant_service):
        """Test deleting participant through facade."""
        participant_service.delete_participant = Mock(return_value=True)

        result = facade.delete_participant(1)

        participant_service.delete_participant.assert_called_once_with(1)
        assert result is True

    def test_get_participant_history(self, facade, participant_service):
        """Test getting participant history."""
        participant_service.get_participant_history = Mock(return_value=[])

        result = facade.get_participant_history(1)

        participant_service.get_participant_history.assert_called_once_with(1)
        assert result == []


# =============================================================================
# Schedule Facade Tests
# =============================================================================


class TestFacadeSchedule:
    """Tests for ApplicationFacade schedule methods."""

    def test_get_week_data(self, facade, schedule_service):
        """Test getting week data."""
        schedule_service.get_week_data = Mock(return_value={"id": 1})

        result = facade.get_week_data(1)

        schedule_service.get_week_data.assert_called_once_with(1)
        assert result["id"] == 1

    def test_get_week_conflicts(self, facade, schedule_service):
        """Test getting week conflicts."""
        schedule_service.get_week_conflicts = Mock(return_value=[])

        result = facade.get_week_conflicts(1)

        schedule_service.get_week_conflicts.assert_called_once_with(1)
        assert result == []

    def test_generate_preview_html(self, facade, schedule_service):
        """Test generating preview HTML."""
        schedule_service.generate_preview_html = Mock(return_value="<html></html>")

        result = facade.generate_preview_html(1)

        schedule_service.generate_preview_html.assert_called_once_with(1)
        assert "<html>" in result

    def test_auto_assign_week(self, facade, schedule_service):
        """Test auto-assigning week."""
        schedule_service.auto_assign_week = Mock(return_value={"success": True})

        result = facade.auto_assign_week(1)

        schedule_service.auto_assign_week.assert_called_once_with(
            1, only_empty=True
        )  # ручные назначения не перезаписываются
        assert result["success"] is True

    def test_auto_assign_all(self, facade, schedule_service):
        """Test auto-assigning all weeks."""
        schedule_service.auto_assign_all = Mock(return_value={"success": True})

        result = facade.auto_assign_all()

        schedule_service.auto_assign_all.assert_called_once()
        assert result["success"] is True

    def test_assign_participant(self, facade, schedule_service):
        """Test assigning participant to assignment."""
        schedule_service.assign_participant = Mock(return_value=True)

        result = facade.assign_participant(1, 2)

        schedule_service.assign_participant.assert_called_once_with(1, 2, "participant")
        assert result is True

    def test_assign_participant_as_assistant(self, facade, schedule_service):
        """Test assigning assistant to assignment."""
        schedule_service.assign_participant = Mock(return_value=True)

        facade.assign_participant(1, 2, role="assistant")

        schedule_service.assign_participant.assert_called_once_with(1, 2, "assistant")

    def test_clear_week_assignments(self, facade, schedule_service):
        """Test clearing week assignments."""
        schedule_service.clear_week_assignments = Mock(return_value=True)

        result = facade.clear_week_assignments(1)

        schedule_service.clear_week_assignments.assert_called_once_with(1)
        assert result is True

    def test_has_assignments(self, facade, schedule_service):
        """Test checking if week has assignments."""
        schedule_service.has_assignments = Mock(return_value=True)

        result = facade.has_assignments(1)

        schedule_service.has_assignments.assert_called_once_with(1)
        assert result is True

    def test_set_special_event(self, facade, schedule_service):
        """Test setting special event."""
        schedule_service.set_special_event = Mock(return_value=True)

        result = facade.set_special_event(1, "memorial")

        schedule_service.set_special_event.assert_called_once_with(1, "memorial")
        assert result is True

    def test_get_weeks_tree(self, facade, schedule_service):
        """Test getting weeks tree."""
        schedule_service.get_weeks_tree = Mock(return_value={})

        result = facade.get_weeks_tree()

        schedule_service.get_weeks_tree.assert_called_once()
        assert result == {}

    def test_prepare_future_year(self, facade, schedule_service):
        """Test preparing future year."""
        schedule_service.prepare_future_year = Mock(return_value={"success": True})

        result = facade.prepare_future_year(2025)

        schedule_service.prepare_future_year.assert_called_once_with(2025)
        assert result["success"] is True


# =============================================================================
# Import/Export Facade Tests
# =============================================================================


class TestFacadeImportExport:
    """Tests for ApplicationFacade import/export methods."""

    def test_import_workbook(self, facade, schedule_service):
        """Test importing workbook."""
        schedule_service.import_workbook = Mock(return_value={"success": True})

        result = facade.import_workbook("/path/to/file.epub")

        schedule_service.import_workbook.assert_called_once_with("/path/to/file.epub")
        assert result["success"] is True

    def test_export_custom_docx(self, facade, schedule_service):
        """Test exporting custom DOCX."""
        schedule_service.export_custom_docx = Mock(return_value=True)

        result = facade.export_custom_docx([1], "/output.docx", mode="full")

        schedule_service.export_custom_docx.assert_called_once_with([1], "/output.docx", "full")
        assert result is True

    def test_export_to_s89(self, facade, schedule_service):
        """Test exporting to S-89 form."""
        schedule_service.export_to_s89 = Mock(return_value=True)

        result = facade.export_to_s89([1, 2], "/output/s89.docx")

        schedule_service.export_to_s89.assert_called_once_with([1, 2], "/output/s89.docx")
        assert result is True


# =============================================================================
# Settings Facade Tests
# =============================================================================


class TestFacadeSettings:
    """Tests for ApplicationFacade settings methods."""

    def test_get_setting(self, facade, schedule_service):
        """Test getting setting."""
        schedule_service.get_setting = Mock(return_value="value")

        result = facade.get_setting("key")

        schedule_service.get_setting.assert_called_once_with("key", None)
        assert result == "value"

    def test_get_setting_with_default(self, facade, schedule_service):
        """Test getting setting with default."""
        schedule_service.get_setting = Mock(return_value="default")

        facade.get_setting("key", "default")

        schedule_service.get_setting.assert_called_once_with("key", "default")

    def test_save_setting(self, facade, schedule_service):
        """Test saving setting."""
        schedule_service.save_setting = Mock(return_value=True)

        result = facade.save_setting("key", "value")

        schedule_service.save_setting.assert_called_once_with("key", "value")
        assert result is True

    def test_get_week_special_event(self, facade, schedule_service):
        """Test getting week special event."""
        schedule_service.get_week_special_event = Mock(return_value="memorial")

        result = facade.get_week_special_event(1)

        schedule_service.get_week_special_event.assert_called_once_with(1)
        assert result == "memorial"

    def test_get_assignment_config(self, facade, schedule_service):
        """Test getting assignment config."""
        schedule_service.get_assignment_config = Mock(return_value=[])

        result = facade.get_assignment_config()

        schedule_service.get_assignment_config.assert_called_once()
        assert result == []

    def test_save_assignment_config(self, facade, schedule_service):
        """Test saving assignment config."""
        schedule_service.save_assignment_config = Mock(return_value=True)

        result = facade.save_assignment_config([{"section": "treasures"}])

        schedule_service.save_assignment_config.assert_called_once()
        assert result is True

    def test_get_weeks_date_range(self, facade, schedule_service):
        """Test getting weeks date range."""
        schedule_service.get_weeks_date_range = Mock(return_value=("2024-01-01", "2024-01-31"))

        result = facade.get_weeks_date_range([1, 2, 3])

        schedule_service.get_weeks_date_range.assert_called_once_with([1, 2, 3])
        assert result == ("2024-01-01", "2024-01-31")


# =============================================================================
# Error Handling Facade Tests
# =============================================================================


class TestFacadeErrors:
    """Tests for ApplicationFacade error handling methods."""

    def test_handle_error(self, facade, error_service):
        """Test handling exception."""
        error_service.handle_exception = Mock(return_value=None)

        exc = ValueError("Test error")
        facade.handle_error(exc, "Test context")

        error_service.handle_exception.assert_called_once_with(exc, "Test context")

    def test_report_error(self, facade, error_service):
        """Test reporting error."""
        error_service.report_error = Mock(return_value=None)

        facade.report_error("Error message", "Context")

        error_service.report_error.assert_called_once_with("Error message", "Context")


# =============================================================================
# Announcement Facade Tests
# =============================================================================


class TestFacadeAnnouncements:
    """Tests for ApplicationFacade announcement methods."""

    def test_get_week_announcement(self, facade, schedule_service):
        """Test getting week announcement."""
        schedule_service.get_week_announcement = Mock(return_value="Объявление")

        result = facade.get_week_announcement(1)

        schedule_service.get_week_announcement.assert_called_once_with(1)
        assert result == "Объявление"

    def test_save_week_announcement(self, facade, schedule_service):
        """Test saving week announcement."""
        schedule_service.save_week_announcement = Mock(return_value=True)

        result = facade.save_week_announcement(1, "Новое объявление")

        schedule_service.save_week_announcement.assert_called_once_with(1, "Новое объявление")
        assert result is True


# =============================================================================
# Module Registry Tests
# =============================================================================


class TestFacadeModules:
    """Tests for ApplicationFacade module methods."""

    def test_registry_initialized(self, facade):
        """Test that module registry is initialized."""
        assert facade.registry is not None

    def test_run_module_migrations(self, facade, db_session):
        """Test running module migrations."""
        facade.registry.migrate_all = Mock()

        facade.run_module_migrations(db_session)

        facade.registry.migrate_all.assert_called_once_with(db_session)


# =============================================================================
# Parametrized Tests
# =============================================================================


class TestFacadeParametrized:
    """Parametrized tests for ApplicationFacade."""

    @pytest.mark.parametrize(
        "event_type", ["memorial", "assembly", "circuit_overseer", "special_talk"]
    )
    def test_set_various_special_events(self, facade, schedule_service, event_type):
        """Test setting various special event types."""
        schedule_service.set_special_event = Mock(return_value=True)

        result = facade.set_special_event(1, event_type)

        schedule_service.set_special_event.assert_called_once_with(1, event_type)
        assert result is True

    @pytest.mark.parametrize("export_mode", ["compact", "full", "detailed"])
    def test_export_custom_docx_modes(self, facade, schedule_service, export_mode):
        """Test exporting with different modes."""
        schedule_service.export_custom_docx = Mock(return_value=True)

        result = facade.export_custom_docx([1], "/output.docx", mode=export_mode)

        schedule_service.export_custom_docx.assert_called_once_with(
            [1], "/output.docx", export_mode
        )
        assert result is True

    @pytest.mark.parametrize("service_type", ["publisher", "elder", "servant", "pioneer"])
    def test_add_participant_service_types(self, facade, participant_service, service_type):
        """Test adding participants with different service types."""
        participant_service.add_participant = Mock(return_value=1)

        facade.add_participant(
            name=f"Тест_{service_type}", gender="male", service_type=service_type, quals=[]
        )

        call_args = participant_service.add_participant.call_args
        assert (
            call_args.kwargs.get("service_type") == service_type
            or call_args.args[2] == service_type
        )


def test_candidate_stats_marks_excluded_week_away(facade, db_session):
    """Отпуск (исключённая неделя) — «away» в подсказках выбора участника."""
    from datetime import date

    from core.models import Participant, ParticipantExcludedWeek, Week

    week = Week(week_title="2–8 ноября", start_date=date(2026, 11, 2))
    away = Participant(name="Белых Дмитрий", gender="male")
    db_session.add_all([week, away])
    db_session.flush()
    db_session.add(ParticipantExcludedWeek(participant_id=away.id, week_start=date(2026, 11, 2)))
    db_session.add(ParticipantExcludedWeek(participant_id=away.id, week_start=date(2026, 11, 9)))
    db_session.commit()

    stats = facade.get_candidate_stats(week.id)
    assert stats[away.id]["away"] is True


def test_candidate_hint_away_is_grey():
    from ui.candidates import candidate_hint

    text, _tip, kind = candidate_hint({"count": 1, "away": True}, 10)
    assert kind == "busy" and "недоступен" in text


def test_candidate_stats_marks_unavailable_week_away(facade, db_session):
    """Отпуск «с … по …» из карточки покрывает неделю — away True."""
    from datetime import date

    from core.models import Participant, Week

    week = Week(week_title="2–8 ноября", start_date=date(2026, 11, 2))
    on_vacation = Participant(
        name="Тарасюк Тимур",
        gender="male",
        unavailable_from=date(2026, 10, 30),
        unavailable_to=date(2026, 11, 10),
    )
    db_session.add_all([week, on_vacation])
    db_session.commit()

    stats = facade.get_candidate_stats(week.id)
    assert stats[on_vacation.id]["away"] is True


def test_candidate_stats_next_assignment_after_week(facade, db_session):
    """next_date/next_text — ближайшее задание после недели, last_date — до неё."""
    from datetime import date

    from core.models import Assignment, Participant, Week

    ref = Week(week_title="эта", start_date=date(2026, 11, 9))
    past = Week(week_title="прошлая", start_date=date(2026, 10, 26))
    near = Week(week_title="следующая", start_date=date(2026, 11, 16))
    far = Week(week_title="позже", start_date=date(2026, 11, 30))
    person = Participant(name="Белых Дмитрий", gender="male")
    db_session.add_all([ref, past, near, far, person])
    db_session.flush()
    db_session.add_all(
        [
            Assignment(
                week_id=past.id,
                participant_id=person.id,
                assignment_text="Чтение Библии",
                assignment_number="3",
                section="treasures",
                status="assigned",
            ),
            Assignment(
                week_id=far.id,
                participant_id=person.id,
                assignment_text="Речь",
                assignment_number="5",
                section="ministry",
                status="assigned",
            ),
            Assignment(
                week_id=near.id,
                participant_id=person.id,
                assignment_text="Молитва",
                assignment_number="prayer_close",
                section="fixed",
                status="assigned",
            ),
        ]
    )
    db_session.commit()

    stats = facade.get_candidate_stats(ref.id)[person.id]
    assert stats["last_date"] == date(2026, 10, 26)
    assert stats["last_text"] == "Чтение Библии"
    assert stats["next_date"] == date(2026, 11, 16)
    assert stats["next_text"] == "Молитва"


def test_get_month_board_marks_away_assigned(facade, db_session):
    """get_month_board помечает 'away' у назначенного в отпуске."""
    from datetime import date

    from core.models import Assignment, Participant, Week

    week = Week(week_title="эта", start_date=date(2026, 11, 2))
    person = Participant(
        name="Белых Ольга",
        gender="female",
        unavailable_from=date(2026, 11, 1),
        unavailable_to=date(2026, 11, 7),
    )
    db_session.add_all([week, person])
    db_session.flush()
    db_session.add(
        Assignment(
            week_id=week.id,
            participant_id=person.id,
            assignment_text="Председатель",
            assignment_number="chairman",
            section="fixed",
            status="assigned",
        )
    )
    db_session.commit()

    board = facade.get_month_board([week.id])
    cell = board["cells"][0][0]
    assert "away" in cell["people"][0]["flags"]
    assert "away" in cell["flags"]


def test_candidate_hint_shows_next_assignment():
    """candidate_hint с weeks_until выводит «дальше через N нед.» и tooltip."""
    from datetime import date

    from ui.candidates import candidate_hint

    stats = {
        "count": 5,
        "last_date": date(2026, 10, 19),
        "last_text": "Чтение Библии",
        "next_date": date(2026, 11, 16),
        "next_text": "Молитва",
    }
    text, tooltip, _kind = candidate_hint(stats, 3, 1)
    assert "дальше через 1 нед. (Молитва)" in text
    assert "Следующее:" in tooltip
