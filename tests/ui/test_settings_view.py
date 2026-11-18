"""
Тесты для SettingsView.

См. spec://ui/views#settings-view
См. plans/ui_testing_plan.md
"""

import os
import sys
from unittest.mock import Mock, MagicMock

# Добавляем корень проекта в sys.path для импорта ui модулей
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest
from PySide6.QtWidgets import QMessageBox, QFileDialog, QCheckBox, QPushButton
from PySide6.QtCore import Qt

from ui.settings_view import SettingsView


@pytest.fixture
def mock_module():
    """Mock-модуль для тестирования."""
    module = Mock()
    module.id = "test_module"
    module.name = "Тестовый модуль"
    return module


@pytest.fixture
def settings_facade(mock_facade, mock_module):
    """Настроенный mock-фасад для SettingsView."""
    registry = Mock()
    registry.get_all.return_value = [mock_module]
    mock_facade.registry = registry

    # Дефолтные настройки
    settings_store = {
        "cong_name": "Тестовое Собрание",
        "meeting_day": "Четверг",
        "meeting_time": "18:30",
        "min_assignment_gap": "3",
        "module_test_module": "true",
    }

    def get_setting_mock(key, default=""):
        return settings_store.get(key, default)

    def save_setting_mock(key, value):
        settings_store[key] = str(value)

    mock_facade.get_setting.side_effect = get_setting_mock
    mock_facade.save_setting.side_effect = save_setting_mock

    return mock_facade


class TestSettingsViewInit:
    """Тесты инициализации и загрузки настроек."""

    def test_init_without_facade_raises_value_error(self):
        """Конструктор бросает ValueError, если фасад равен None."""
        with pytest.raises(ValueError, match="facade is required for SettingsView"):
            SettingsView(None)

    def test_init_loads_settings(self, qapp, settings_facade):
        """Настройки корректно загружаются в поля при создании."""
        view = SettingsView(settings_facade)

        assert view.cong_name.text() == "Тестовое Собрание"
        assert view.meeting_day.text() == "Четверг"
        assert view.meeting_time.text() == "18:30"
        # Индекс 2 соответствует перерыву в 3 недели (3 - 1)
        assert view.min_gap.currentIndex() == 2

    def test_init_creates_module_checkboxes(self, qapp, settings_facade, mock_module):
        """Чекбоксы модулей создаются и устанавливаются в соответствии с настройками."""
        view = SettingsView(settings_facade)

        assert mock_module.id in view.module_checks
        chk = view.module_checks[mock_module.id]
        assert isinstance(chk, QCheckBox)
        assert chk.text() == mock_module.name
        assert chk.isChecked() is True


class TestSettingsViewSave:
    """Тесты сохранения настроек."""

    def test_save_settings_saves_via_facade(self, qapp, settings_facade, qtbot, monkeypatch):
        """Настройки успешно сохраняются через фасад при клике на кнопку сохранения."""
        view = SettingsView(settings_facade)
        qtbot.addWidget(view)

        # Изменяем значения полей
        view.cong_name.setText("Новое Собрание")
        view.meeting_day.setText("Вторник")
        view.meeting_time.setText("19:00")
        view.min_gap.setCurrentIndex(1)  # 2 недели

        # Мокаем QMessageBox.information
        info_called = []
        monkeypatch.setattr(
            QMessageBox,
            "information",
            lambda parent, title, text: info_called.append(text) or QMessageBox.StandardButton.Ok,
        )

        # Находим кнопку сохранения и нажимаем
        btn_save = view.findChild(QPushButton, "btnSaveSettings")
        assert btn_save is not None
        btn_save.click()

        # Проверяем, что фасад был вызван для сохранения
        assert settings_facade.save_setting.called
        assert settings_facade.get_setting("cong_name") == "Новое Собрание"
        assert settings_facade.get_setting("meeting_day") == "Вторник"
        assert settings_facade.get_setting("meeting_time") == "19:00"
        assert settings_facade.get_setting("min_assignment_gap") == "2"

        # Проверяем, что показано сообщение об успехе
        assert len(info_called) == 1
        assert "успешно сохранены" in info_called[0]


class TestSettingsViewModules:
    """Тесты управления модулями."""

    def test_toggle_module_saves_setting_immediately(
        self, qapp, settings_facade, mock_module, qtbot
    ):
        """Переключение чекбокса модуля мгновенно вызывает сохранение в фасаде."""
        view = SettingsView(settings_facade)
        qtbot.addWidget(view)

        chk = view.module_checks[mock_module.id]

        # Снимаем флажок
        chk.setChecked(False)
        assert settings_facade.get_setting(f"module_{mock_module.id}") == "false"

        # Снова ставим флажок
        chk.setChecked(True)
        assert settings_facade.get_setting(f"module_{mock_module.id}") == "true"


class TestSettingsViewTheme:
    """Выбор темы в «Оформлении»."""

    def test_theme_defaults_to_system(self, qapp, settings_facade, qtbot):
        view = SettingsView(settings_facade)
        qtbot.addWidget(view)

        assert view.theme_combo.currentData() == "system"

    def test_select_dark_applies_and_saves(self, qapp, settings_facade, qtbot):
        from core.styles import Theme, apply_theme, current_theme

        view = SettingsView(settings_facade)
        qtbot.addWidget(view)
        try:
            view.theme_combo.setCurrentIndex(view.theme_combo.findData("dark"))

            assert settings_facade.get_setting("theme") == "dark"
            assert current_theme() == Theme.DARK
        finally:
            apply_theme(qapp, Theme.LIGHT)  # не протекать глобальной темой в другие тесты


class TestSettingsViewBackupRestore:
    """Тесты создания и восстановления бэкапов."""

    def test_create_backup_success(self, qapp, settings_facade, qtbot, monkeypatch):
        """Успешное создание бэкапа вызывает QMessageBox.information."""
        view = SettingsView(settings_facade)
        qtbot.addWidget(view)

        # Мокаем выбор пути сохранения файла
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            lambda *args, **kwargs: ("/path/to/backup.zip", "ZIP Files (*.zip)"),
        )

        # Мокаем вызов создания бэкапа
        backup_mock = MagicMock(return_value={"success": True})
        monkeypatch.setattr("core.backup_logic.create_backup", backup_mock)

        # Мокаем диалог успеха
        info_called = []
        monkeypatch.setattr(
            QMessageBox,
            "information",
            lambda parent, title, text: info_called.append(text) or QMessageBox.StandardButton.Ok,
        )

        view.btn_backup.click()

        backup_mock.assert_called_once_with("/path/to/backup.zip")
        assert len(info_called) == 1
        assert "Резервная копия создана" in info_called[0]

    def test_create_backup_failure(self, qapp, settings_facade, qtbot, monkeypatch):
        """Ошибка при бэкапе вызывает QMessageBox.critical."""
        view = SettingsView(settings_facade)
        qtbot.addWidget(view)

        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            lambda *args, **kwargs: ("/path/to/backup.zip", "ZIP Files (*.zip)"),
        )

        backup_mock = MagicMock(return_value={"success": False, "error": "Disk failure"})
        monkeypatch.setattr("core.backup_logic.create_backup", backup_mock)

        critical_called = []
        monkeypatch.setattr(
            QMessageBox,
            "critical",
            lambda parent, title, text: critical_called.append(text)
            or QMessageBox.StandardButton.Ok,
        )

        view.btn_backup.click()

        assert len(critical_called) == 1
        assert "Disk failure" in critical_called[0]

    def test_restore_backup_success(self, qapp, settings_facade, qtbot, monkeypatch):
        """Успешное восстановление из бэкапа."""
        view = SettingsView(settings_facade)
        qtbot.addWidget(view)

        # Предупреждение: Да, продолжить
        monkeypatch.setattr(
            QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
        )

        # Выбор файла
        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: ("/path/to/backup.zip", "ZIP Files (*.zip)"),
        )

        restore_mock = MagicMock(return_value={"success": True})
        monkeypatch.setattr("core.backup_logic.restore_backup", restore_mock)

        info_called = []
        monkeypatch.setattr(
            QMessageBox,
            "information",
            lambda parent, title, text: info_called.append(text) or QMessageBox.StandardButton.Ok,
        )

        view.btn_restore.click()

        restore_mock.assert_called_once_with("/path/to/backup.zip")
        assert len(info_called) == 1
        assert "успешно восстановлена" in info_called[0]

    def test_restore_backup_cancelled_by_user(self, qapp, settings_facade, qtbot, monkeypatch):
        """Если пользователь нажимает Нет в предупреждении, восстановление не происходит."""
        view = SettingsView(settings_facade)
        qtbot.addWidget(view)

        # Ответ Нет
        monkeypatch.setattr(
            QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.No
        )

        open_called = []
        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: open_called.append(True) or ("", ""),
        )

        view.btn_restore.click()

        assert not open_called


class TestSettingsViewImportHistory:
    """Тесты импорта истории."""

    def test_import_history_success(self, qapp, settings_facade, qtbot, monkeypatch):
        """Успешный импорт истории выводит информацию о добавленных неделях."""
        view = SettingsView(settings_facade)
        qtbot.addWidget(view)

        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: ("/path/to/import.csv", "CSV Files (*.csv)"),
        )

        import_mock = MagicMock(
            return_value={"success": True, "stats": {"weeks": 5, "assignments": 15, "skipped": 1}}
        )
        monkeypatch.setattr("core.history_import.import_history_from_csv", import_mock)

        info_called = []
        monkeypatch.setattr(
            QMessageBox,
            "information",
            lambda parent, title, text: info_called.append(text) or QMessageBox.StandardButton.Ok,
        )

        view.btn_import_nws.click()

        import_mock.assert_called_once_with("/path/to/import.csv")
        assert len(info_called) == 1
        assert "Импорт успешно завершён" in info_called[0]
        assert "Добавлено недель: 5" in info_called[0]
        assert "Импортировано заданий: 15" in info_called[0]
        assert "Пропущено (не найдены в базе): 1" in info_called[0]


class TestSettingsViewSmtpCheck:
    """«Проверить соединение» идёт в фоне: окно не зависает, пока сервер молчит."""

    def test_check_runs_in_background_and_reports(self, qapp, settings_facade, qtbot, monkeypatch):
        import threading

        main_thread = threading.get_ident()
        seen = {}

        def check():
            seen["thread"] = threading.get_ident()
            return True, "SMTP работает"

        settings_facade.test_smtp_connection = (
            check  # у Mock нет __name__, а TaskWorker его пишет в лог
        )
        shown = []
        monkeypatch.setattr(
            QMessageBox, "information", lambda parent, title, text: shown.append(text)
        )
        for name in ("warning", "critical"):
            monkeypatch.setattr(
                QMessageBox, name, lambda parent, title, text: shown.append(("!", text))
            )
        view = SettingsView(settings_facade)
        qtbot.addWidget(view)

        view._test_smtp()
        assert not view.btn_test_smtp.isEnabled()
        qtbot.waitUntil(lambda: view.btn_test_smtp.isEnabled(), timeout=5000)

        assert seen["thread"] != main_thread
        # Одно окно с результатом, без отдельного «Настройки сохранены»
        assert shown == ["SMTP работает"]


def test_mail_connections_have_timeout(monkeypatch):
    import smtplib

    from core.notification_service import NotificationService

    calls = {}

    class _Fake:
        def __init__(self, *args, **kwargs):
            calls.update(kwargs)
            raise OSError("stop")

    monkeypatch.setattr(smtplib, "SMTP_SSL", _Fake)
    service = NotificationService(smtp_host="h", smtp_port=465, smtp_user="u", smtp_password="p")
    with pytest.raises(OSError):
        service._connect_smtp()
    assert calls.get("timeout") == NotificationService.NETWORK_TIMEOUT


def test_section_nav_lists_groups_and_scrolls_to_them(qapp, settings_facade, qtbot):
    from PySide6.QtWidgets import QGroupBox

    view = SettingsView(settings_facade)
    qtbot.addWidget(view)
    view.resize(900, 400)
    view.show()
    qapp.processEvents()
    titles = [view.section_nav.item(i).text() for i in range(view.section_nav.count())]
    groups = [
        g.title() for g in view.findChildren(QGroupBox) if g.parent() is view.layout.parentWidget()
    ]
    assert titles == groups and "📧 Email-уведомления" in titles
    view.section_nav.setCurrentRow(titles.index("📧 Email-уведомления"))
    assert view.scroll.verticalScrollBar().value() > 0


class TestDonateSection:
    """Раздел «Поддержать проект»."""

    def test_section_exists_and_buttons_disabled_with_placeholder(
        self, qapp, settings_facade, monkeypatch
    ):
        from core import donate

        monkeypatch.setattr(
            donate,
            "PLATFORMS",
            [
                donate.DonatePlatform(
                    "p",
                    "P",
                    free_url="https://p/me",
                    fixed_url="https://p/me/{amount}",
                    configured=False,
                )
            ],
        )
        view = SettingsView(settings_facade)

        titles = [view.section_nav.item(i).text() for i in range(view.section_nav.count())]
        assert any("Поддержать проект" in t for t in titles)
        assert len(view.donate_buttons) == 2
        for btn in view.donate_buttons:
            assert not btn.isEnabled()
            assert "не настроена" in btn.toolTip()

    def test_buttons_built_per_platform_and_open_urls(self, qapp, settings_facade, monkeypatch):
        from core import donate

        monkeypatch.setattr(
            donate,
            "PLATFORMS",
            [
                donate.DonatePlatform(
                    "a", "A", free_url="https://a/me", fixed_url="https://a/me/{amount}EUR"
                ),
                donate.DonatePlatform("b", "B", free_url="https://b/me"),
            ],
        )
        opened = []
        monkeypatch.setattr(
            "ui.settings_view.QDesktopServices.openUrl", lambda u: opened.append(u.toString())
        )
        view = SettingsView(settings_facade)
        assert len(view.donate_buttons) == 3
        for btn in view.donate_buttons:
            assert btn.isEnabled()
            btn.click()
        assert opened == ["https://a/me/5EUR", "https://a/me", "https://b/me"]
