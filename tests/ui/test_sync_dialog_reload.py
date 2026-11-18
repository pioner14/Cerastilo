"""После успешной синхронизации ПК перечитывает расписание без перезапуска."""

from unittest.mock import MagicMock, patch

from core.events import Event


def test_successful_sync_reloads_schedule(qapp):
    from ui.sync_dialog import SyncClientDialog

    facade = MagicMock()
    facade.get_setting.return_value = ""
    dialog = SyncClientDialog(facade)
    with patch("ui.sync_dialog.QMessageBox.information"):
        dialog._on_done()
    facade.events.emit.assert_any_call(Event.SCHEDULE_IMPORTED)
    facade.events.emit.assert_any_call(Event.ASSIGNMENT_CHANGED)


def test_failure_after_merge_reloads_but_plain_failure_does_not(qapp):
    """База ПК уже объединена (планшет не получил) — перечитать; обычная ошибка — нет."""
    from ui.sync_dialog import SyncClientDialog

    facade = MagicMock()
    facade.get_setting.return_value = ""
    dialog = SyncClientDialog(facade)
    dialog._on_failed("Неверный код", False)
    facade.events.emit.assert_not_called()
    dialog._on_failed("Планшет не получил", True)
    facade.events.emit.assert_any_call(Event.SCHEDULE_IMPORTED)


def test_tablet_window_reports_busy_port(qapp, tmp_path):
    """Второе окно синхронизации на планшете — понятное «уже запущена», без перескока порта."""
    from core.sync_service import SyncServerBusyError
    from ui.sync_dialog import SyncServerDialog

    facade = MagicMock()
    facade.schedule.db.db_path = str(tmp_path / "t.db")
    busy = SyncServerBusyError(98, "Синхронизация уже запущена: порт 8765 занят.")
    with patch("ui.sync_dialog.SyncServer.bind", side_effect=busy):
        dialog = SyncServerDialog(facade)
    assert "уже запущена" in dialog.status_label.text()
    assert dialog.sync_server is None
    dialog.reject()
