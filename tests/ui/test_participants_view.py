"""
Тесты для ParticipantsView.

См. spec://ui/participants_view
См. plans/ui_testing_plan.md Phase 1
"""

import os
import sys

# Добавляем корень проекта в sys.path для импорта ui модулей
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest
from PySide6.QtWidgets import QTableWidget, QPushButton, QLabel
from PySide6.QtCore import Qt

from ui.participants_view import ParticipantsView


class TestParticipantsViewInit:
    """Тесты инициализации view."""

    def test_view_creates_with_mock_facade(self, qapp, mock_facade):
        """View создаётся с mock facade."""
        view = ParticipantsView(mock_facade)

        assert view is not None
        assert view.facade is mock_facade

    def test_view_has_required_widgets(self, qapp, mock_facade):
        """View содержит все необходимые виджеты."""
        view = ParticipantsView(mock_facade)

        assert hasattr(view, "table")
        assert hasattr(view, "btn_add")
        assert hasattr(view, "title")
        assert isinstance(view.table, QTableWidget)

    def test_table_has_correct_columns(self, qapp, mock_facade):
        """Таблица имеет правильные колонки."""
        view = ParticipantsView(mock_facade)

        headers = [
            view.table.horizontalHeaderItem(i).text() for i in range(view.table.columnCount())
        ]
        assert headers == ["ФИО", "Пол", "Роль", "Последнее", "Всего"]
        assert "ФИО" in headers
        assert "Пол" in headers
        assert "Роль" in headers

    def test_table_is_read_only(self, qapp, mock_facade):
        """Таблица не редактируется напрямую."""
        view = ParticipantsView(mock_facade)

        # Проверяем, что редактирование отключено
        from PySide6.QtWidgets import QAbstractItemView

        triggers = view.table.editTriggers()
        assert triggers == QAbstractItemView.EditTrigger.NoEditTriggers

    def test_table_has_sorting_enabled(self, qapp, mock_facade):
        """В таблице включена сортировка."""
        view = ParticipantsView(mock_facade)

        assert view.table.isSortingEnabled()


class TestParticipantsViewDisplay:
    """Тесты отображения списка участников."""

    def test_load_participants_calls_facade(self, qapp, mock_facade):
        """Загрузка участников вызывает get_all_participants."""
        view = ParticipantsView(mock_facade)

        mock_facade.get_all_participants.assert_called()

    def test_table_populates_with_participants(self, qapp, mock_facade):
        """Таблица заполняется участниками."""
        view = ParticipantsView(mock_facade)

        # mock_facade возвращает 3 участников
        assert view.table.rowCount() == 3

    def test_table_displays_participant_name(self, qapp, mock_facade):
        """Таблица отображает имя участника."""
        view = ParticipantsView(mock_facade)

        # Первый участник - Иванов Иван
        name_item = view.table.item(0, 0)
        assert name_item is not None
        assert name_item.text() == "Иванов Иван"

    def test_table_displays_gender_male(self, qapp, mock_facade):
        """Таблица отображает мужской пол как 'М'."""
        view = ParticipantsView(mock_facade)

        gender_item = view.table.item(0, 1)
        assert gender_item.text() == "М"

    def test_table_displays_gender_female(self, qapp, mock_facade):
        """Таблица отображает женский пол как 'Ж'."""
        view = ParticipantsView(mock_facade)

        # Третий участник - женщина
        gender_item = view.table.item(2, 1)
        assert gender_item.text() == "Ж"

    def test_table_displays_role_elder(self, qapp, mock_facade):
        """Таблица отображает роль 'Старейшина'."""
        view = ParticipantsView(mock_facade)

        role_item = view.table.item(0, 2)
        assert role_item.text() == "Старейшина"

    def test_table_displays_role_ministerial_servant(self, qapp, mock_facade):
        """Таблица отображает роль 'Помощник'."""
        view = ParticipantsView(mock_facade)

        role_item = view.table.item(1, 2)
        assert role_item.text() == "Помощник"

    def test_table_displays_last_assignment_date(self, qapp, mock_facade):
        """Таблица отображает дату последнего назначения."""
        view = ParticipantsView(mock_facade)

        # Первый участник имеет last_assignment_date_real = "15.02.2026"
        date_item = view.table.item(0, 3)
        assert date_item.text() == "15.02.2026"

    def test_table_displays_no_date_as_dash(self, qapp, mock_facade):
        """Таблица отображает отсутствие даты как '—'."""
        view = ParticipantsView(mock_facade)

        # Второй участник не имеет даты
        date_item = view.table.item(1, 3)
        assert date_item.text() == "—"

    def test_table_displays_total_assignments(self, qapp, mock_facade):
        """Таблица отображает общее количество назначений."""
        view = ParticipantsView(mock_facade)

        total_item = view.table.item(0, 4)
        assert total_item.text() == "5"

    def test_title_updates_with_count(self, qapp, mock_facade):
        """Заголовок обновляется с количеством участников."""
        view = ParticipantsView(mock_facade)

        title_text = view.title.text()
        assert "3" in title_text
        assert "Возвещатели" in title_text

    def test_no_actions_column(self, qapp, mock_facade):
        """Кнопки действий вынесены из строк в панель над таблицей."""
        view = ParticipantsView(mock_facade)

        assert view.table.cellWidget(0, view.table.columnCount() - 1) is None
        assert not view.table.verticalHeader().isVisible()

    def test_numbers_and_dates_sort_by_value(self, qapp, mock_facade):
        """«Всего» и «Последнее» сортируются как числа и даты, а не как текст."""
        mock_facade.get_all_participants.return_value = [
            {
                "id": i,
                "name": f"N{i}",
                "gender": "male",
                "service_type": "PUB",
                "last_assignment_date_real": d,
                "total_assignments": t,
            }
            for i, (d, t) in enumerate([("21.04.2026", 14), ("02.11.2026", 2), (None, 0)], 1)
        ]
        view = ParticipantsView(mock_facade)

        view.table.sortItems(4, Qt.SortOrder.AscendingOrder)
        assert [view.table.item(r, 4).text() for r in range(3)] == ["0", "2", "14"]
        view.table.sortItems(3, Qt.SortOrder.AscendingOrder)
        assert [view.table.item(r, 3).text() for r in range(3)] == ["—", "21.04.2026", "02.11.2026"]

    @staticmethod
    def _person(pid, last, quals=("prayer",), **extra):
        return {
            "id": pid,
            "name": f"Человек {pid}",
            "gender": "male",
            "service_type": "PUB",
            "last_assignment_date_real": last,
            "total_assignments": 1,
            "qualifications": list(quals),
            **extra,
        }

    def test_stale_highlight_only_for_people_with_roles(self, qapp, mock_facade):
        """Оранжевым — только те, у кого есть роли, но давно (или ни разу) не было заданий."""
        from datetime import date, timedelta

        old = (date.today() - timedelta(days=90)).strftime("%d.%m.%Y")
        fresh = (date.today() - timedelta(days=10)).strftime("%d.%m.%Y")
        mock_facade.get_all_participants.return_value = [
            self._person(1, old),
            self._person(2, fresh),
            self._person(3, None),
            self._person(4, old, quals=()),
        ]
        view = ParticipantsView(mock_facade)
        tips = {
            view.table.item(r, 0).data(Qt.ItemDataRole.UserRole): view.table.item(r, 3).toolTip()
            for r in range(4)
        }

        assert "давно" in tips[1]
        assert tips[2] == ""
        assert "ещё не было" in tips[3]
        assert tips[4] == ""

    def test_people_without_roles_are_muted(self, qapp, mock_facade):
        mock_facade.get_all_participants.return_value = [self._person(1, None, quals=())]
        view = ParticipantsView(mock_facade)

        assert "Нет ролей" in view.table.item(0, 0).toolTip()

    def test_unavailable_person_is_not_flagged_as_stale(self, qapp, mock_facade):
        from datetime import date, timedelta

        today = date.today()
        mock_facade.get_all_participants.return_value = [
            self._person(
                1,
                None,
                unavailable_from=today - timedelta(days=5),
                unavailable_to=today + timedelta(days=20),
            ),
        ]
        view = ParticipantsView(mock_facade)

        assert view.table.item(0, 0).toolTip().startswith("Недоступен до")
        assert view.table.item(0, 0).font().italic()
        assert view.table.item(0, 3).toolTip() == ""

    def test_search_hides_non_matching_rows(self, qapp, mock_facade):
        """Поиск по имени скрывает остальных."""
        view = ParticipantsView(mock_facade)

        view.search_edit.setText("петр")
        hidden = [view.table.isRowHidden(r) for r in range(view.table.rowCount())]
        names = [view.table.item(r, 0).text() for r in range(view.table.rowCount())]
        assert [n for n, h in zip(names, hidden) if not h] == ["Петров Пётр"]
        view.search_edit.clear()
        assert not any(view.table.isRowHidden(r) for r in range(view.table.rowCount()))


class TestParticipantsViewEmpty:
    """Тесты отображения пустого списка."""

    def test_empty_table_shows_zero_rows(self, qapp):
        """Пустой список показывает 0 строк."""
        mock_facade_empty = pytest.fixture_value = type(
            "Mock", (), {"get_all_participants": lambda self: []}
        )()

        view = ParticipantsView(mock_facade_empty)

        assert view.table.rowCount() == 0

    def test_empty_title_shows_zero_count(self, qapp):
        """Заголовок показывает 0 участников."""
        mock_facade_empty = type("Mock", (), {"get_all_participants": lambda self: []})()

        view = ParticipantsView(mock_facade_empty)

        assert view.title.text().endswith("· 0")


class TestParticipantsViewAddParticipant:
    """Тесты добавления участника."""

    def test_add_button_exists(self, qapp, mock_facade):
        """Кнопка добавления существует."""
        view = ParticipantsView(mock_facade)

        assert hasattr(view, "btn_add")
        assert view.btn_add.text() == "➕ Добавить"

    def test_add_button_click_opens_dialog(self, qapp, mock_facade, qtbot, monkeypatch):
        """Клик на кнопку добавления открывает диалог."""
        view = ParticipantsView(mock_facade)
        qtbot.addWidget(view)

        # Флаг для проверки, что диалог был открыт
        dialog_opened = []

        original_exec = lambda self: dialog_opened.append(True) or 0

        # Подменяем exec диалога
        from ui.participant_dialog import ParticipantEditDialog

        monkeypatch.setattr(ParticipantEditDialog, "exec", original_exec)

        view.btn_add.click()

        assert dialog_opened, "Диалог должен был открыться"


class TestParticipantsViewEditParticipant:
    """Тесты редактирования участника."""

    def test_edit_buttons_follow_selection(self, qapp, mock_facade):
        """«Изменить» и «Удалить» активны только при выбранной строке."""
        view = ParticipantsView(mock_facade)

        assert not view.btn_edit.isEnabled()
        assert not view.btn_delete.isEnabled()
        view.table.selectRow(0)
        assert view.btn_edit.isEnabled()
        assert view.btn_delete.isEnabled()

    def test_double_click_opens_edit_dialog(self, qapp, mock_facade, monkeypatch):
        """Двойной клик по строке открывает редактирование этого человека."""
        view = ParticipantsView(mock_facade)
        opened = []
        monkeypatch.setattr(view, "open_edit_dialog", opened.append)

        view.table.selectRow(1)
        view.table.cellDoubleClicked.emit(1, 0)

        assert opened == [view.table.item(1, 0).data(Qt.ItemDataRole.UserRole)]


class TestParticipantsViewDeleteParticipant:
    """Тесты удаления участника."""

    def test_delete_selected_asks_with_name(self, qapp, mock_facade, monkeypatch):
        """Удаление выбранного спрашивает подтверждение с именем."""
        view = ParticipantsView(mock_facade)
        calls = []
        monkeypatch.setattr(view, "confirm_delete", lambda pid, name: calls.append((pid, name)))

        view.table.selectRow(0)
        view.btn_delete.click()

        row_item = view.table.item(0, 0)
        assert calls == [(row_item.data(Qt.ItemDataRole.UserRole), row_item.text())]

    def test_confirm_delete_calls_facade_on_yes(self, qapp, mock_facade, qtbot, monkeypatch):
        """Подтверждение удаления вызывает delete_participant."""
        view = ParticipantsView(mock_facade)
        qtbot.addWidget(view)

        # Подменяем QMessageBox.question на возврат Yes
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)

        view.confirm_delete(1, "Иванов Иван")

        mock_facade.delete_participant.assert_called_with(1)

    def test_confirm_delete_does_not_call_on_no(self, qapp, mock_facade, qtbot, monkeypatch):
        """Отмена удаления не вызывает delete_participant."""
        view = ParticipantsView(mock_facade)
        qtbot.addWidget(view)

        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)

        view.confirm_delete(1, "Иванов Иван")

        mock_facade.delete_participant.assert_not_called()


class TestParticipantsViewIntegration:
    """Интеграционные тесты с реальным фасадом."""

    def test_view_loads_real_participants(self, qapp, facade, qtbot):
        """View загружает участников из реальной БД."""
        view = ParticipantsView(facade)
        qtbot.addWidget(view)

        # БД пустая, поэтому 0 участников
        assert view.table.rowCount() == 0

    def test_add_participant_updates_table(self, qapp, facade, qtbot):
        """Добавление участника обновляет таблицу."""
        view = ParticipantsView(facade)
        qtbot.addWidget(view)

        # Добавляем участника напрямую через facade
        facade.add_participant("Тестовый Участник", "male", "E", ["chairman"], None)

        # Перезагружаем таблицу
        view.load_participants()

        assert view.table.rowCount() == 1
        assert view.table.item(0, 0).text() == "Тестовый Участник"

    def test_delete_participant_updates_table(self, qapp, facade, qtbot):
        """Удаление участника обновляет таблицу."""
        view = ParticipantsView(facade)
        qtbot.addWidget(view)

        # Добавляем участника
        p_id = facade.add_participant("Для Удаления", "male", "PUB", [], None)
        view.load_participants()

        assert view.table.rowCount() == 1

        # Удаляем
        facade.delete_participant(p_id)
        view.load_participants()

        assert view.table.rowCount() == 0


class TestParticipantsViewScrollTo:
    """Тесты прокрутки к участнику."""

    def test_scroll_to_participant_after_edit(self, qapp, mock_facade, qtbot):
        """После редактирования таблица прокручивается к участнику."""
        view = ParticipantsView(mock_facade)
        qtbot.addWidget(view)

        # Вызываем load_participants с scroll_to_id
        view.load_participants(scroll_to_id=2)

        # Проверяем, что строка с ID=2 выбрана
        selected_rows = view.table.selectedItems()
        # Если есть выбранные элементы, проверяем ID
        assert view.selected_participant_id() == 2


def _press(button_text):
    """Подменяет QMessageBox.exec: «нажимает» кнопку с этим текстом."""
    from PySide6.QtWidgets import QMessageBox

    def fake_exec(box):
        for b in box.buttons():
            if b.text() == button_text:
                box._clicked = b
        return 0

    return fake_exec, (lambda box: getattr(box, "_clicked", None))


def test_away_offer_replaces_and_reports(qapp, mock_facade, monkeypatch):
    """Отпуск одним окном: «Снять и подобрать замену» вызывает замену с auto."""
    from datetime import date
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QMessageBox

    items = [
        {
            "assignment_id": 5,
            "week_id": 2,
            "start_date": date(2030, 3, 11),
            "text": "Жемчужины",
            "role": "participant",
        }
    ]
    mock_facade.get_away_assignments = MagicMock(return_value=items)
    mock_facade.replace_away_assignments = MagicMock(
        return_value={
            "released": 1,
            "replacements": [
                {"start_date": date(2030, 3, 11), "text": "Жемчужины", "name": "Брат 2"}
            ],
        }
    )
    view = ParticipantsView(mock_facade)
    fake_exec, fake_clicked = _press("Снять и подобрать замену")
    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", fake_clicked)
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: shown.append(a[2]))

    view.offer_away_replacements(1)

    mock_facade.replace_away_assignments.assert_called_once_with(items, auto=True)
    assert "Брат 2" in shown[0]


def test_away_offer_leave_as_is_changes_nothing(qapp, mock_facade, monkeypatch):
    from datetime import date
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QMessageBox

    mock_facade.get_away_assignments = MagicMock(
        return_value=[
            {
                "assignment_id": 5,
                "week_id": 2,
                "start_date": date(2030, 3, 11),
                "text": "Ж",
                "role": "assistant",
            }
        ]
    )
    mock_facade.replace_away_assignments = MagicMock()
    view = ParticipantsView(mock_facade)
    fake_exec, fake_clicked = _press("Оставить как есть")
    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", fake_clicked)

    view.offer_away_replacements(1)

    mock_facade.replace_away_assignments.assert_not_called()


def test_away_offer_for_several_people_lists_names(qapp, mock_facade, monkeypatch):
    from datetime import date
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QMessageBox

    by_pid = {
        1: [
            {
                "assignment_id": 5,
                "week_id": 2,
                "start_date": date(2030, 3, 11),
                "text": "Жемчужины",
                "role": "participant",
            }
        ],
        2: [
            {
                "assignment_id": 6,
                "week_id": 1,
                "start_date": date(2030, 3, 4),
                "text": "Чтение",
                "role": "participant",
            }
        ],
    }
    mock_facade.get_away_assignments = MagicMock(side_effect=lambda pid: by_pid[pid])
    mock_facade.get_participant = MagicMock(
        side_effect=lambda pid: {"name": {1: "Иванов", 2: "Петров"}[pid]}
    )
    mock_facade.replace_away_assignments = MagicMock()
    view = ParticipantsView(mock_facade)
    texts = []

    def fake_exec(box):
        texts.append(box.text())
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda box: None)

    view.offer_away_replacements([1, 2])

    assert "Петров" in texts[0] and "Иванов" in texts[0]
    assert texts[0].index("04.03") < texts[0].index("11.03")  # по датам
    mock_facade.replace_away_assignments.assert_not_called()
