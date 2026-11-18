"""
Tests for notification status indicators and notification log dialog.
"""

from datetime import datetime
from unittest.mock import Mock, patch

import pytest
from PySide6.QtWidgets import QLabel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.error_service import ErrorService
from core.events import EventBus
from core.facade import ApplicationFacade
from core.models import Base, NotificationHistory, Participant, Week
from core.services import ParticipantService, ScheduleService
from ui.notification_log_dialog import NotificationLogDialog
from ui.schedule_view import AssignmentCell


@pytest.fixture
def db_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def mock_db_manager(db_session):
    db_manager = Mock()

    class SessionContext:
        def __enter__(self):
            return db_session

        def __exit__(self, *args):
            pass

    db_manager.get_session.return_value = SessionContext()
    return db_manager


@pytest.fixture
def facade(mock_db_manager):
    bus = EventBus()
    p_service = ParticipantService(mock_db_manager, bus)
    s_service = ScheduleService(mock_db_manager, bus)
    errors = ErrorService(bus)
    return ApplicationFacade(
        participant_service=p_service,
        schedule_service=s_service,
        error_service=errors,
        event_bus=bus,
    )


def test_get_week_notification_statuses(facade, db_session):
    # Setup test data
    p1 = Participant(id=10, name="Иван Иванов", email="ivan@example.com")
    p2 = Participant(id=20, name="Петр Петров", email="petr@example.com")
    w1 = Week(id=100, week_title="1-7 Марта 2026")
    db_session.add_all([p1, p2, w1])
    db_session.commit()

    # History entries
    h1 = NotificationHistory(
        participant_id=10,
        week_id=100,
        sent_at=datetime(2026, 3, 1, 10, 0),
        status="success",
        subject="Уведомление 1",
    )
    # Older entry for p2 (error) then newer entry for p2 (success)
    h2_old = NotificationHistory(
        participant_id=20,
        week_id=100,
        sent_at=datetime(2026, 3, 1, 9, 0),
        status="error",
        error_message="SMTP timeout",
    )
    h2_new = NotificationHistory(
        participant_id=20,
        week_id=100,
        sent_at=datetime(2026, 3, 1, 11, 0),
        status="success",
        subject="Уведомление 2",
    )
    db_session.add_all([h1, h2_old, h2_new])
    db_session.commit()

    statuses = facade.get_week_notification_statuses(100)
    assert 10 in statuses
    assert statuses[10]["status"] == "success"

    assert 20 in statuses
    # Should get latest status (success, at 11:00)
    assert statuses[20]["status"] == "success"
    assert statuses[20]["sent_at"] == datetime(2026, 3, 1, 11, 0)


def test_get_notification_log(facade, db_session):
    p1 = Participant(id=1, name="Брат А", email="a@test.com")
    p2 = Participant(id=2, name="Брат Б", email="b@test.com")
    w1 = Week(id=1, week_title="Неделя 1")
    w2 = Week(id=2, week_title="Неделя 2")
    db_session.add_all([p1, p2, w1, w2])
    db_session.commit()

    h1 = NotificationHistory(
        participant_id=1,
        week_id=1,
        sent_at=datetime(2026, 3, 1, 10, 0),
        status="success",
        subject="Задание 1",
    )
    h2 = NotificationHistory(
        participant_id=2,
        week_id=1,
        sent_at=datetime(2026, 3, 1, 10, 5),
        status="error",
        error_message="Invalid recipient",
    )
    h3 = NotificationHistory(
        participant_id=1,
        week_id=2,
        sent_at=datetime(2026, 3, 2, 12, 0),
        status="success",
        subject="Задание 2",
    )
    db_session.add_all([h1, h2, h3])
    db_session.commit()

    # All logs
    logs = facade.get_notification_log()
    assert len(logs) == 3
    # Sorted desc by sent_at: h3 first, then h2, then h1
    assert logs[0]["participant_name"] == "Брат А"
    assert logs[0]["week_id"] == 2
    assert logs[0]["participant_email"] == "a@test.com"

    # Filter by participant_id
    p2_logs = facade.get_notification_log(participant_id=2)
    assert len(p2_logs) == 1
    assert p2_logs[0]["status"] == "error"
    assert p2_logs[0]["error"] == "Invalid recipient"

    # Filter by status
    err_logs = facade.get_notification_log(status_filter="error")
    assert len(err_logs) == 1
    assert err_logs[0]["participant_name"] == "Брат Б"

    # Filter by week_id
    w1_logs = facade.get_notification_log(week_id=1)
    assert len(w1_logs) == 2


def test_assignment_cell_indicators(qapp):
    # Success indicator
    cell_ok = AssignmentCell(
        assignment_id=1,
        participant_name="Сергей Смирнов",
        on_click=None,
        notif_status="success",
        notif_info={"sent_at": datetime(2026, 3, 1, 14, 30), "status": "success"},
    )
    assert "✉️" in cell_ok.text()
    assert "Сергей Смирнов" in cell_ok.text()
    assert "✉️ Уведомление отправлено 01.03.2026 14:30" in cell_ok.toolTip()

    # Error indicator
    cell_err = AssignmentCell(
        assignment_id=2,
        participant_name="Алексей Попов",
        on_click=None,
        notif_status="error",
        notif_info={
            "sent_at": datetime(2026, 3, 1, 14, 35),
            "status": "error",
            "error": "Connection refused",
        },
    )
    assert "⚠️" in cell_err.text()
    assert "Ошибка отправки" in cell_err.toolTip()
    assert "Connection refused" in cell_err.toolTip()


def test_notification_log_dialog_ui(qapp, facade, db_session):
    p = Participant(id=5, name="Михаил Иванов", email="mikhail@test.com")
    w = Week(id=10, week_title="10-16 Марта 2026")
    db_session.add_all([p, w])
    db_session.commit()

    h = NotificationHistory(
        participant_id=5,
        week_id=10,
        sent_at=datetime(2026, 3, 4, 15, 0),
        status="success",
        subject="Уведомление",
    )
    db_session.add(h)
    db_session.commit()

    dialog = NotificationLogDialog(facade)
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 1).text() == "Михаил Иванов"
    assert dialog.table.item(0, 2).text() == "mikhail@test.com"
    assert "✉️ Отправлено" in dialog.table.item(0, 4).text()

    # Test search filter
    dialog.search_input.setText("ненайденный")
    assert dialog.table.rowCount() == 0

    dialog.search_input.setText("михаил")
    assert dialog.table.rowCount() == 1


def test_email_preview_edit_dialog_ui(qapp, facade, db_session):
    from datetime import date

    from core.models import Assignment
    from ui.email_preview_dialog import EmailPreviewEditDialog

    p = Participant(id=50, name="Николай Сидоров", email="nikolay@test.com")
    w = Week(id=20, week_title="20-26 Марта 2026", start_date=date(2026, 3, 20))
    a = Assignment(
        id=101, week_id=20, participant_id=50, assignment_text="Чтение Библии", status="assigned"
    )
    db_session.add_all([p, w, a])
    db_session.commit()

    dialog = EmailPreviewEditDialog(
        facade=facade,
        participant_id=50,
        participant_name="Николай Сидоров",
        participant_email=None,
        week_ids=[20],
    )

    # Initial state
    assert dialog.subject_edit.text() == "Ваши задания на встрече собрания"
    assert dialog.radio_template.isChecked()
    assert dialog.participant_email == "nikolay@test.com"
    assert "nikolay@test.com" in dialog.findChild(QLabel, "emailRecipientLabel").text()
    assert "Чтение Библии" in dialog.preview_browser.toPlainText()

    # Enter custom note
    dialog.note_edit.setText("Не забудь микрофон 1")
    dialog._update_preview()
    assert "Не забудь микрофон 1" in dialog.preview_browser.toHtml()

    # Save
    dialog._save_and_close()
    data = dialog.get_custom_data()
    assert data is not None
    assert data["note"] == "Не забудь микрофон 1"
    assert data["subject"] == "Ваши задания на встрече собрания"


def test_assignment_cell_context_menu_email_action(qapp):
    from PySide6.QtCore import QPoint

    from ui.schedule_view import AssignmentCell

    email_called = []
    log_called = []

    cell = AssignmentCell(
        assignment_id=1,
        participant_name="Иван Иванов",
        on_click=None,
        notif_status="success",
        notif_info={
            "sent_at": "2026-09-04 12:00:00",
            "subject": "Задания на неделю",
            "status": "success",
        },
        on_send_email=lambda: email_called.append(True),
        on_open_log=lambda: log_called.append(True),
    )

    assert "✉️" in cell.text()
    assert "Задания на неделю" in cell.toolTip()
    assert "Правый клик" in cell.toolTip()

    with (
        patch("ui.schedule_view.QMenu.popup") as popup,
        patch("ui.schedule_view.QMenu.exec") as menu_exec,
    ):
        cell._show_context_menu(QPoint(1, 1))

    popup.assert_called_once()
    menu_exec.assert_not_called()


def test_email_preview_edit_dialog_send_now_mode(qapp, facade, db_session):
    from datetime import date

    from core.models import Assignment
    from ui.email_preview_dialog import EmailPreviewEditDialog

    p = Participant(id=55, name="Олег Петров", email="oleg@test.com")
    w = Week(id=25, week_title="25-31 Марта 2026", start_date=date(2026, 3, 25))
    a = Assignment(
        id=105, week_id=25, participant_id=55, assignment_text="Чтение", status="assigned"
    )
    db_session.add_all([p, w, a])
    db_session.commit()

    dialog = EmailPreviewEditDialog(
        facade=facade,
        participant_id=55,
        participant_name="Олег Петров",
        participant_email="oleg@test.com",
        week_ids=[25],
        allow_send_now=True,
    )

    assert hasattr(dialog, "btn_send_now")
    assert dialog.btn_send_now.text() == "📨 Отправить сейчас"
    assert dialog.btn_cancel.text() == "Закрыть"


def test_email_dialog_sends_only_checked_weeks(qapp, facade, db_session):
    """Письмо из меню участника: по умолчанию отмечена только первая неделя,
    в предпросмотр и отправку идут только отмеченные недели."""
    from datetime import date

    from core.models import Assignment
    from ui.email_preview_dialog import EmailPreviewEditDialog

    p = Participant(id=60, name="Сергей Грач", email="s@test.com")
    w1 = Week(id=30, week_title="1-7 Апреля 2026", start_date=date(2026, 4, 1))
    w2 = Week(id=31, week_title="8-14 Апреля 2026", start_date=date(2026, 4, 8))
    a1 = Assignment(
        id=130, week_id=30, participant_id=60, assignment_text="Чтение Библии", status="assigned"
    )
    a2 = Assignment(
        id=131, week_id=31, participant_id=60, assignment_text="Речь", status="assigned"
    )
    db_session.add_all([p, w1, w2, a1, a2])
    db_session.commit()

    dialog = EmailPreviewEditDialog(
        facade=facade,
        participant_id=60,
        participant_name="Сергей Грач",
        participant_email="s@test.com",
        week_ids=[30, 31],
        allow_send_now=True,
    )

    assert [cb.text() for cb in dialog.week_checkboxes] == ["1-7 Апреля 2026", "8-14 Апреля 2026"]
    assert dialog.selected_week_ids() == [30]
    assert "Чтение Библии" in dialog.preview_browser.toPlainText()
    assert "Речь" not in dialog.preview_browser.toPlainText()

    dialog.week_checkboxes[0].setChecked(False)
    assert dialog.selected_week_ids() == []
    assert not dialog.btn_send_now.isEnabled()

    dialog.week_checkboxes[1].setChecked(True)
    assert dialog.btn_send_now.isEnabled()
    with patch("ui.email_preview_dialog._SingleSendWorker") as worker:
        dialog._send_now()
    assert worker.call_args.args[2] == [31]
