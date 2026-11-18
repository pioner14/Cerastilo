"""
Тесты для AssignmentConfigView.

См. spec://ui/views#assignment-config-view
См. plans/ui_testing_plan.md
"""

import os
import sys
from unittest.mock import Mock, MagicMock

# Добавляем корень проекта в sys.path для импорта ui модулей
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest
from PySide6.QtWidgets import QMessageBox, QComboBox, QCheckBox, QTableWidgetItem
from PySide6.QtCore import Qt

from ui.assignment_config_view import AssignmentConfigView


@pytest.fixture
def config_facade(mock_facade):
    """Настроенный mock-фасад для AssignmentConfigView."""
    # Пример данных конфигурации заданий
    config_store = [
        {
            "section": "treasures",
            "position": 1,
            "assignment_name": "Председатель собрания",
            "required_qualification": "chairman",
            "is_brothers_only": 1,
            "needs_assistant": 0,
        },
        {
            "section": "student",
            "position": 2,
            "assignment_name": "Чтение Библии",
            "required_qualification": "bible_reading",
            "is_brothers_only": 0,
            "needs_assistant": 1,
        },
    ]

    mock_facade.get_assignment_config.return_value = config_store
    mock_facade.save_assignment_config = MagicMock(return_value=True)

    return mock_facade


class TestAssignmentConfigViewInit:
    """Тесты инициализации и загрузки конфигурации."""

    def test_init_without_facade_raises_value_error(self):
        """Конструктор бросает ValueError, если фасад равен None."""
        with pytest.raises(ValueError, match="facade is required for AssignmentConfigView"):
            AssignmentConfigView(None)

    def test_init_loads_data(self, qapp, config_facade):
        """Конфигурация успешно загружается в таблицу при создании."""
        view = AssignmentConfigView(config_facade)

        assert view.table.rowCount() == 2
        assert view.table.columnCount() == 5

        # Проверка заголовков колонок
        headers = [view.table.horizontalHeaderItem(i).text() for i in range(5)]
        assert headers == [
            "Секция / Поз.",
            "Название задания",
            "Квалификация",
            "Братья",
            "Напарник",
        ]

    def test_table_items_populated_correctly(self, qapp, config_facade):
        """Значения в ячейках таблицы соответствуют загруженной конфигурации."""
        view = AssignmentConfigView(config_facade)

        # Проверяем первую строку
        item_id_0 = view.table.item(0, 0)
        assert item_id_0.text() == "treasures / 1"
        assert item_id_0.data(Qt.ItemDataRole.UserRole) == {"section": "treasures", "position": 1}
        assert view.table.item(0, 1).text() == "Председатель собрания"

        # Квалификация (Комбобокс)
        combo_0 = view.table.cellWidget(0, 2)
        assert isinstance(combo_0, QComboBox)
        assert combo_0.currentText() == "chairman"

        # Чекбокс Братья
        container_b_0 = view.table.cellWidget(0, 3)
        check_b_0 = container_b_0.findChild(QCheckBox)
        assert check_b_0 is not None
        assert check_b_0.isChecked() is True

        # Чекбокс Напарник
        container_a_0 = view.table.cellWidget(0, 4)
        check_a_0 = container_a_0.findChild(QCheckBox)
        assert check_a_0 is not None
        assert check_a_0.isChecked() is False

        # Проверяем вторую строку
        item_id_1 = view.table.item(1, 0)
        assert item_id_1.text() == "student / 2"
        assert view.table.item(1, 1).text() == "Чтение Библии"

        combo_1 = view.table.cellWidget(1, 2)
        assert combo_1.currentText() == "bible_reading"

        check_b_1 = view.table.cellWidget(1, 3).findChild(QCheckBox)
        assert check_b_1.isChecked() is False

        check_a_1 = view.table.cellWidget(1, 4).findChild(QCheckBox)
        assert check_a_1.isChecked() is True


class TestAssignmentConfigViewSave:
    """Тесты сохранения конфигурации."""

    def test_save_data_success(self, qapp, config_facade, qtbot, monkeypatch):
        """Успешное сохранение изменённой конфигурации."""
        view = AssignmentConfigView(config_facade)
        qtbot.addWidget(view)

        # Модифицируем данные в таблице
        view.table.item(0, 1).setText("Новый Председатель")
        view.table.cellWidget(0, 2).setCurrentText("student_4")

        # Меняем чекбоксы
        check_b_0 = view.table.cellWidget(0, 3).findChild(QCheckBox)
        check_b_0.setChecked(False)

        check_a_0 = view.table.cellWidget(0, 4).findChild(QCheckBox)
        check_a_0.setChecked(True)

        # Мокаем информационное окно
        info_called = []
        monkeypatch.setattr(
            QMessageBox,
            "information",
            lambda parent, title, text: info_called.append(text) or QMessageBox.StandardButton.Ok,
        )

        # Нажимаем кнопку Сохранить
        view.btn_save.click()

        # Проверяем, что метод сохранения вызван с корректными измененными данными
        config_facade.save_assignment_config.assert_called_once()
        saved_arg = config_facade.save_assignment_config.call_args[0][0]

        assert len(saved_arg) == 2
        # Первая строка должна быть изменена
        assert saved_arg[0] == {
            "section": "treasures",
            "position": 1,
            "assignment_name": "Новый Председатель",
            "required_qualification": "student_4",
            "is_brothers_only": 0,
            "needs_assistant": 1,
        }
        # Вторая строка осталась прежней
        assert saved_arg[1] == {
            "section": "student",
            "position": 2,
            "assignment_name": "Чтение Библии",
            "required_qualification": "bible_reading",
            "is_brothers_only": 0,
            "needs_assistant": 1,
        }

        assert len(info_called) == 1
        assert "успешно сохранена" in info_called[0]

    def test_save_data_failure(self, qapp, config_facade, qtbot, monkeypatch):
        """Ошибка сохранения вызывает QMessageBox.critical."""
        view = AssignmentConfigView(config_facade)
        qtbot.addWidget(view)

        # Имитируем ошибку сохранения
        config_facade.save_assignment_config.return_value = False

        # Мокаем критическое окно
        critical_called = []
        monkeypatch.setattr(
            QMessageBox,
            "critical",
            lambda parent, title, text: critical_called.append(text)
            or QMessageBox.StandardButton.Ok,
        )

        view.btn_save.click()

        assert len(critical_called) == 1
        assert "Не удалось сохранить конфигурацию" in critical_called[0]
