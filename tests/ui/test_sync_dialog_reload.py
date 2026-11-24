"""После успешной синхронизации ПК перечитывает расписание без перезапуска."""

from unittest.mock import MagicMock, patch

from core.events import Event


def test_successful_sync_reloads_schedule(qapp, tmp_path):
    from ui.sync_dialog import SyncClientDialog

    facade = MagicMock()
    facade.get_setting.return_value = ""
    facade.schedule.db.db_path = str(tmp_path / "pc.db")
    dialog = SyncClientDialog(facade)
    with patch("ui.sync_dialog.QMessageBox.information"):
        dialog._on_done()
    facade.events.emit.assert_any_call(Event.SCHEDULE_IMPORTED)
    facade.events.emit.assert_any_call(Event.ASSIGNMENT_CHANGED)


def test_failure_after_merge_reloads_but_plain_failure_does_not(qapp, tmp_path):
    """База ПК уже объединена (планшет не получил) — перечитать; обычная ошибка — нет."""
    from ui.sync_dialog import SyncClientDialog

    facade = MagicMock()
    facade.get_setting.return_value = ""
    facade.schedule.db.db_path = str(tmp_path / "pc.db")
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


def test_tablet_rotates_saved_code_and_restarts_server(qtbot, tmp_path):
    from core.sync_code_store import load_sync_code, save_sync_code
    from ui.sync_dialog import SyncServerDialog

    facade = MagicMock()
    db_path = str(tmp_path / "tablet.db")
    facade.schedule.db.db_path = db_path
    save_sync_code(db_path, "ABCDEFGHJKMN")
    with (
        patch("ui.sync_dialog.SyncServer") as server_class,
        patch("ui.sync_dialog.generate_sync_code", return_value="23456789ABCD"),
        patch("ui.sync_dialog.get_local_ip", return_value="127.0.0.1"),
    ):
        dialog = SyncServerDialog(facade)
        assert dialog.code_label.text() == "ABCD-EFGH-JKMN"
        assert server_class.call_args.kwargs["auth_token"] == "ABCDEFGHJKMN"
        dialog.btn_new_code.click()
        qtbot.waitUntil(lambda: server_class.call_count == 2)
        server_class.return_value.stop.assert_called_once_with()
        assert server_class.call_args.kwargs["auth_token"] == "23456789ABCD"
        assert dialog.code_label.text() == "2345-6789-ABCD"
        assert load_sync_code(db_path) == "23456789ABCD"
        dialog.reject()


def test_pc_saves_code_only_after_success(qapp, tmp_path):
    from core.sync_code_store import load_sync_code, save_sync_code
    from core.sync_service import SyncClientError
    from ui.sync_dialog import SyncClientDialog, _SyncWorker

    facade = MagicMock()
    facade.get_setting.return_value = ""
    db_path = str(tmp_path / "pc.db")
    facade.schedule.db.db_path = db_path
    save_sync_code(db_path, "ABCDEFGHJKMN")
    dialog = SyncClientDialog(facade)
    assert dialog.code_edit.text() == "ABCD-EFGH-JKMN"

    worker = _SyncWorker("127.0.0.1", "2345-6789-abcd", db_path)
    with patch("ui.sync_dialog.sync_with_tablet", side_effect=SyncClientError("Неверный код")):
        worker.run()
    assert load_sync_code(db_path) == "ABCDEFGHJKMN"
    with patch("ui.sync_dialog.sync_with_tablet"):
        worker.run()
    assert load_sync_code(db_path) == "23456789ABCD"
