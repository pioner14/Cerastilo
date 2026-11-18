"""
Тесты для WorkbookView (📚 Импорт рабочей тетради).

См. spec://ui/views#workbook-view
См. plans/ui_testing_plan.md
"""

import os
import sys
from unittest.mock import Mock, MagicMock

# Добавляем корень проекта в sys.path для импорта ui модулей
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest
from PySide6.QtWidgets import QMessageBox, QFileDialog
from PySide6.QtCore import Qt

from ui.workbook_view import WorkbookView
from core.workers import TaskWorker


@pytest.fixture
def workbook_facade(mock_facade):
    """Mock-фасад для тестирования WorkbookView."""
    mock_facade.import_workbook = MagicMock(
        return_value={"success": True, "weeks": 4, "assignments": 16}
    )
    mock_facade.errors = Mock()
    mock_facade.errors.handle_exception = Mock(
        return_value={"success": False, "error": "Mocked exception"}
    )

    # Добавляем __name__ для логирования в TaskWorker
    mock_facade.import_workbook.__name__ = "import_workbook"

    return mock_facade


@pytest.fixture(autouse=True)
def mock_task_worker_start(monkeypatch):
    """Синхронный запуск TaskWorker в тестах без реальных QThread."""

    def synchronous_start(self):
        self.run()

    monkeypatch.setattr(TaskWorker, "start", synchronous_start)


class TestWorkbookViewInit:
    """Тесты инициализации WorkbookView."""

    def test_init_creates_all_widgets(self, qapp, workbook_facade):
        """Проверяем создание всех обязательных виджетов на экране."""
        view = WorkbookView(workbook_facade)

        assert view is not None
        assert view.btn_import is not None
        assert view.progress is not None
        assert view.log is not None
        assert view.file_label is not None

        # Кнопка активна, прогресс скрыт, лог пустой
        assert view.btn_import.isEnabled() is True
        assert view.progress.isVisible() is False
        assert view.log.toPlainText() == ""


class TestWorkbookViewImportFlow:
    """Тесты процесса импорта EPUB файлов."""

    def test_select_and_import_cancelled_by_user(self, qapp, workbook_facade, qtbot, monkeypatch):
        """Если пользователь отменил диалог выбора файла, ничего не происходит."""
        view = WorkbookView(workbook_facade)
        qtbot.addWidget(view)

        # Мокаем отмену выбора
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: ("", ""))

        view.btn_import.click()

        # Импорт не вызывался, лог пуст
        workbook_facade.import_workbook.assert_not_called()
        assert view.log.toPlainText() == ""

    def test_select_and_import_success(self, qapp, workbook_facade, qtbot, monkeypatch):
        """Успешный импорт EPUB файла."""
        view = WorkbookView(workbook_facade)
        qtbot.addWidget(view)

        # Выбираем тестовый файл
        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: ("/path/to/mwb_2026.epub", "EPUB Files (*.epub)"),
        )

        # Проверяем, что сигнал импорта будет испущен
        signal_emitted = []
        view.import_finished.connect(lambda: signal_emitted.append(True))

        view.btn_import.click()

        # Фасад вызван с переданным файлом
        workbook_facade.import_workbook.assert_called_once_with("/path/to/mwb_2026.epub")

        # UI обновился
        assert "mwb_2026.epub" in view.file_label.text()
        log_text = view.log.toPlainText()
        assert "Импорт завершён" in log_text
        assert "Импортировано: 4 недель, 16 заданий" in log_text
        assert len(signal_emitted) == 1
        assert view.btn_import.isEnabled() is True

    def test_select_and_import_failure(self, qapp, workbook_facade, qtbot, monkeypatch):
        """Ошибка импорта EPUB файла выводит критический месседжбокс."""
        view = WorkbookView(workbook_facade)
        qtbot.addWidget(view)

        # Возвращаем ошибку из фасада
        workbook_facade.import_workbook.return_value = {
            "success": False,
            "error": "Неверный формат EPUB",
        }

        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: ("/path/to/mwb_2026.epub", "EPUB Files (*.epub)"),
        )

        critical_called = []
        monkeypatch.setattr(
            QMessageBox,
            "critical",
            lambda parent, title, text: critical_called.append(text)
            or QMessageBox.StandardButton.Ok,
        )

        view.btn_import.click()

        # Проверяем, что выведено сообщение об ошибке
        assert len(critical_called) == 1
        assert "Неверный формат EPUB" in critical_called[0]

        log_text = view.log.toPlainText()
        assert "Ошибка: Неверный формат EPUB" in log_text
        assert view.btn_import.isEnabled() is True
