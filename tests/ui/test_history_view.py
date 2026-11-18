"""
Тесты для HistoryView.

См. spec://ui/history_view
См. plans/ui_testing_plan.md Phase 2
"""

import os
import sys

# Добавляем корень проекта в sys.path для импорта ui модулей
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest
from PySide6.QtWidgets import QLabel, QListWidget, QTableWidget, QLineEdit
from PySide6.QtCore import Qt

from ui.history_view import HistoryView


class TestHistoryViewInit:
    """Тесты инициализации view."""

    def test_view_creates_with_mock_facade(self, qapp, mock_facade):
        """View создаётся с mock facade."""
        view = HistoryView(mock_facade)

        assert view is not None
        assert view.facade is mock_facade

    def test_view_has_required_widgets(self, qapp, mock_facade):
        """View содержит все необходимые виджеты."""
        view = HistoryView(mock_facade)

        assert hasattr(view, "list_widget")
        assert hasattr(view, "table")
        assert hasattr(view, "search_input")
        assert hasattr(view, "name_label")
        assert hasattr(view, "stats_label")
        assert isinstance(view.list_widget, QListWidget)
        assert isinstance(view.table, QTableWidget)
        assert isinstance(view.search_input, QLineEdit)

    def test_table_has_correct_columns(self, qapp, mock_facade):
        """Таблица имеет правильные колонки."""
        view = HistoryView(mock_facade)

        assert view.table.columnCount() == 4

        headers = [
            view.table.horizontalHeaderItem(i).text() for i in range(view.table.columnCount())
        ]
        assert "Дата" in headers
        assert "Неделя" in headers
        assert "Задание" in headers
        assert "Роль / Напарник" in headers

    def test_search_input_has_placeholder(self, qapp, mock_facade):
        """Поиск имеет placeholder."""
        view = HistoryView(mock_facade)

        assert view.search_input.placeholderText() == "🔍 Поиск участника..."


class TestHistoryViewDisplay:
    """Тесты отображения списка участников."""

    def test_load_participants_calls_facade(self, qapp, mock_facade):
        """Загрузка участников вызывает get_participants_list."""
        view = HistoryView(mock_facade)

        mock_facade.get_participants_list.assert_called()

    def test_list_populates_with_participants(self, qapp, mock_facade):
        """Список заполняется участниками."""
        view = HistoryView(mock_facade)

        # mock_facade возвращает 3 участников
        assert view.list_widget.count() == 3

    def test_list_item_shows_participant_name(self, qapp, mock_facade):
        """Элемент списка отображает имя участника."""
        view = HistoryView(mock_facade)

        item = view.list_widget.item(0)
        assert item is not None
        assert "Иванов Иван" in item.text()

    def test_first_participant_selected_by_default(self, qapp, mock_facade):
        """Первый участник выбран по умолчанию (если есть)."""
        view = HistoryView(mock_facade)

        # Проверяем, что name_label обновлён
        assert view.name_label.text() != "Выберите участника слева"


class TestHistoryViewSearch:
    """Тесты поиска участников."""

    def test_search_filters_list(self, qapp, mock_facade, qtbot):
        """Поиск фильтрует список участников."""
        view = HistoryView(mock_facade)
        qtbot.addWidget(view)

        # Вводим "Иванов"
        view.search_input.setText("Иванов")

        # Проверяем, что фильтрация скрыла несовпадающие элементы
        # Иванов Иван должен быть видим, остальные скрыты
        visible_count = sum(
            1 for i in range(view.list_widget.count()) if not view.list_widget.item(i).isHidden()
        )
        assert visible_count == 1

    def test_search_case_insensitive(self, qapp, mock_facade, qtbot):
        """Поиск регистронезависимый."""
        view = HistoryView(mock_facade)
        qtbot.addWidget(view)

        # Вводим "иванов" в нижнем регистре
        view.search_input.setText("иванов")

        # Должен быть виден 1 участник
        visible_count = sum(
            1 for i in range(view.list_widget.count()) if not view.list_widget.item(i).isHidden()
        )
        assert visible_count == 1

    def test_search_empty_shows_all(self, qapp, mock_facade, qtbot):
        """Пустой поиск показывает всех участников."""
        view = HistoryView(mock_facade)
        qtbot.addWidget(view)

        # Очищаем поиск
        view.search_input.setText("")

        # Должны быть видны все 3 участника
        visible_count = sum(
            1 for i in range(view.list_widget.count()) if not view.list_widget.item(i).isHidden()
        )
        assert visible_count == 3

    def test_search_no_results_shows_empty(self, qapp, mock_facade, qtbot):
        """Поиск без результатов показывает пустой список."""
        view = HistoryView(mock_facade)
        qtbot.addWidget(view)

        # Вводим несуществующее имя
        view.search_input.setText("Несуществующий")

        # Все элементы должны быть скрыты
        visible_count = sum(
            1 for i in range(view.list_widget.count()) if not view.list_widget.item(i).isHidden()
        )
        assert visible_count == 0


class TestHistoryViewSelection:
    """Тесты выбора участника."""

    def test_select_participant_updates_info(self, qapp, mock_facade, qtbot):
        """Выбор участника обновляет инфо-блок."""
        view = HistoryView(mock_facade)
        qtbot.addWidget(view)

        # Выбираем первого участника
        view.list_widget.setCurrentRow(0)

        assert "Иванов Иван" in view.name_label.text()

    def test_select_participant_loads_history(self, qapp, mock_facade, qtbot):
        """Выбор участника загружает историю."""
        view = HistoryView(mock_facade)
        qtbot.addWidget(view)

        # Выбираем первого участника
        view.list_widget.setCurrentRow(0)

        # get_participant_history должен быть вызван с ID=1
        mock_facade.get_participant_history.assert_called_with(1)

    def test_select_participant_populates_table(self, qapp, mock_facade, qtbot):
        """Выбор участника заполняет таблицу истории."""
        # Настраиваем mock для возврата истории
        mock_facade.get_participant_history.return_value = [
            {
                "date": "2026-02-15",
                "week_title": "1-7 февраля",
                "assignment_text": "Председатель",
                "role": "Председатель",
            },
            {
                "date": "2026-02-08",
                "week_title": "25-31 января",
                "assignment_text": "Чтец",
                "role": "Чтец",
            },
        ]

        view = HistoryView(mock_facade)
        qtbot.addWidget(view)

        # Выбираем участника
        view.list_widget.setCurrentRow(0)

        # Таблица должна иметь 2 строки
        assert view.table.rowCount() == 2

    def test_history_table_populates_correctly(self, qapp, mock_facade, qtbot):
        """Таблица истории заполняется корректно."""
        mock_facade.get_participant_history.return_value = [
            {
                "date": "2026-02-15",
                "week_title": "1-7 февраля",
                "assignment_text": "Председатель",
                "role": "Председатель",
            }
        ]

        view = HistoryView(mock_facade)
        qtbot.addWidget(view)
        view.list_widget.setCurrentRow(0)

        # Проверяем первую строку
        date_item = view.table.item(0, 0)
        week_item = view.table.item(0, 1)
        assignment_item = view.table.item(0, 2)
        role_item = view.table.item(0, 3)

        assert date_item.text() == "2026-02-15"
        assert week_item.text() == "1-7 февраля"
        assert assignment_item.text() == "Председатель"
        assert role_item.text() == "Председатель"


class TestHistoryViewEmpty:
    """Тесты пустого списка."""

    def test_empty_participants_list(self, qapp):
        """Пустой список участников."""
        mock_facade_empty = type(
            "Mock",
            (),
            {
                "get_participants_list": lambda self: [],
                "get_participant_history": lambda self, p_id: [],
            },
        )()

        view = HistoryView(mock_facade_empty)

        assert view.list_widget.count() == 0
        assert view.name_label.text() == "Выберите участника слева"


class TestHistoryViewStats:
    """Тесты статистики участника."""

    def test_stats_label_updates_on_selection(self, qapp, mock_facade, qtbot):
        """Статистика обновляется при выборе участника."""
        mock_facade.get_participant.return_value = {
            "id": 1,
            "name": "Иванов Иван",
            "gender": "male",
            "service_type": "elder",
            "is_active": True,
            "qualifications": ["chairman", "prayer"],
            "last_assignment_date": "2026-02-15",
            "last_assignment_date_real": "15.02.2026",
            "total_assignments": 5,
            "family_group_id": None,
        }

        view = HistoryView(mock_facade)
        qtbot.addWidget(view)
        view.list_widget.setCurrentRow(0)

        # Проверяем, что stats_label не пустой
        stats_text = view.stats_label.text()
        assert stats_text != ""
        # Должна содержать информацию о назначениях
        assert "5" in stats_text or "назначений" in stats_text.lower()


class TestHistoryViewIntegration:
    """Интеграционные тесты с реальным фасадом."""

    def test_view_loads_real_participants(self, qapp, facade, qtbot):
        """View загружает участников из реальной БД."""
        view = HistoryView(facade)
        qtbot.addWidget(view)

        # БД пустая, поэтому 0 участников
        assert view.list_widget.count() == 0

    def test_add_participant_shows_in_list(self, qapp, facade, qtbot):
        """Добавление участника отображается в списке."""
        view = HistoryView(facade)
        qtbot.addWidget(view)

        # Добавляем участника напрямую через facade
        facade.add_participant("Тестовый Участник", "male", "E", ["chairman"], None)

        # Перезагружаем список
        view._load_participants()

        assert view.list_widget.count() == 1
        assert "Тестовый Участник" in view.list_widget.item(0).text()


def test_load_participants_rereads_and_keeps_selection(qapp, mock_facade):
    """Переход на вкладку (main._on_tab_changed → load_participants) перечитывает
    участников и историю, выбранный участник и фильтр остаются."""
    mock_facade.get_participants_list.return_value = [
        {"id": 1, "name": "Иванов"},
        {"id": 2, "name": "Петров"},
    ]
    mock_facade.get_participant_history.return_value = []
    view = HistoryView(mock_facade)
    view.list_widget.setCurrentRow(1)
    view.search_input.setText("Пет")
    mock_facade.get_participants_list.return_value = [
        {"id": 3, "name": "Алексеев"},
        {"id": 1, "name": "Иванов"},
        {"id": 2, "name": "Петров"},
    ]
    mock_facade.get_participant_history.reset_mock()

    view.load_participants()

    assert view.list_widget.count() == 3
    assert view.list_widget.currentItem().data(Qt.ItemDataRole.UserRole) == 2
    mock_facade.get_participant_history.assert_called_with(2)
    assert view.list_widget.item(0).isHidden()  # «Алексеев» не подходит под «Пет»
