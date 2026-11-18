"""
Тесты для ScheduleView.

См. spec://ui/views#ScheduleView
См. plans/ui_testing_plan.md Phase 4

ScheduleView — критический компонент (38KB) с асинхронными операциями.
Тесты разделены на категории:
- Unit-тесты отдельных методов
- Widget-тесты UI компонентов
- Integration-тесты с моками TaskWorker
"""

import os
import sys
from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

# Добавляем корень проекта в sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest
from core.styles import Theme, get_palette
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
)

from modules.announcement import AnnouncementModule
from ui.schedule_view import (
    AssignmentCell,
    ManualAssignmentDialog,
    ParticipantSelectDialog,
    ReorderableTableWidget,
    ScheduleView,
)

# === Fixtures ===


@pytest.fixture
def mock_facade():
    """Mock ApplicationFacade для тестов ScheduleView."""
    facade = Mock()

    # Данные недель
    facade.get_weeks_tree.return_value = {
        2026: {
            "Март": [
                {"id": 1, "title": "3-9 марта", "bible_reading": "Матфея 5-7"},
                {"id": 2, "title": "10-16 марта", "bible_reading": "Матфея 8-10"},
            ],
            "Апрель": [
                {"id": 3, "title": "31 марта - 6 апреля", "bible_reading": "Матфея 11-13"},
            ],
        }
    }

    # Данные недели
    facade.get_week_data.return_value = {
        "week": {"id": 1, "week_title": "3-9 марта", "bible_reading": "Матфея 5-7"},
        "assignments": [
            {
                "id": 1,
                "assignment_number": "1",
                "assignment_text": "Председатель",
                "assignment_type": "chairman",
                "section": "fixed",
                "section_position": "chairman",
                "duration": 5,
                "participant_name": "Иванов Иван",
                "participant_id": 1,
                "status": "assigned",
            },
            {
                "id": 2,
                "assignment_number": "2",
                "assignment_text": "Молитва",
                "assignment_type": "prayer",
                "section": "fixed",
                "section_position": "prayer_open",
                "duration": 3,
                "participant_name": "Петров Пётр",
                "participant_id": 2,
                "status": "assigned",
            },
        ],
    }

    # Конфликты
    facade.get_week_conflicts.return_value = set()

    # Участники
    facade.get_all_participants.return_value = [
        {"id": 1, "name": "Иванов Иван", "gender": "male"},
        {"id": 2, "name": "Петров Пётр", "gender": "male"},
        {"id": 3, "name": "Сидорова Анна", "gender": "female"},
    ]

    # История назначений (пустой список по умолчанию)
    facade.get_participant_history.return_value = []

    # Назначения
    facade.get_assignment.return_value = None
    facade.get_assignment_config.return_value = None
    facade.assign_participant.return_value = True
    facade.update_assignment_duration.return_value = True
    facade.add_manual_assignment.return_value = 99
    facade.update_manual_assignment.return_value = True
    facade.delete_manual_assignment.return_value = True
    facade.duplicate_manual_assignment.return_value = 100
    facade.reorder_week_assignments.return_value = True
    facade.replace_week_assignments.return_value = True
    facade.clear_week_assignments.return_value = True
    facade.auto_assign_week.return_value = {"success": True, "count": 5}

    # Экспорт
    facade.export_custom_docx.return_value = {"success": True}
    facade.export_to_s89.return_value = {"success": True}
    facade.get_weeks_date_range.return_value = ("2026-03-03", "2026-03-09")

    # Special events
    facade.get_week_special_event.return_value = None
    facade.set_special_event.return_value = True

    # Settings
    facade.get_setting.return_value = None
    facade.save_setting.return_value = True

    # Events
    facade.events = Mock()
    facade.events.subscribe = Mock()

    # Registry (modules)
    facade.registry = Mock()
    facade.registry.get_enabled.return_value = []

    # Error service for TaskWorker
    facade.errors = Mock()
    facade.errors.handle_exception = Mock(return_value=None)

    # Добавляем __name__ для методов, которые могут использоваться в TaskWorker
    facade.auto_assign_week.__name__ = "auto_assign_week"
    facade.clear_week_assignments.__name__ = "clear_week_assignments"

    return facade


@pytest.fixture
def schedule_view(mock_facade, qapp):
    """Экземпляр ScheduleView для тестирования."""
    view = ScheduleView(mock_facade)
    return view


# ============================================================
# Announcement Widget Tests
# ============================================================


class TestAnnouncementWidget:
    def test_announcement_is_compact_and_can_expand(self, qapp):
        facade = Mock()
        facade.get_week_announcement.return_value = "Текст объявления"
        box = AnnouncementModule().get_week_widget(1, facade)
        editor = box.findChild(QTextEdit, "announcementEditor")
        toggle = box.findChild(QToolButton, "announcementExpandToggle")

        assert editor.height() == 70
        assert box.maximumHeight() == 120
        assert toggle.text() == "Развернуть"

        toggle.setChecked(True)

        assert editor.height() == 180
        assert box.maximumHeight() == 240
        assert toggle.text() == "Свернуть"

    def test_announcement_keeps_autosave(self, qapp):
        facade = Mock()
        facade.get_week_announcement.return_value = ""
        box = AnnouncementModule().get_week_widget(1, facade)
        editor = box.findChild(QTextEdit, "announcementEditor")

        editor.setPlainText("Новое объявление")

        facade.save_week_announcement.assert_called_once_with(1, "Новое объявление")


# ============================================================
# AssignmentCell Tests
# ============================================================


class TestAssignmentCell:
    """Тесты ячейки назначения."""

    def test_cell_creates_with_name(self, qapp):
        """Ячейка создаётся с именем."""
        cell = AssignmentCell(
            assignment_id=1, participant_name="Иванов Иван", on_click=lambda aid, role: None
        )

        assert cell.text() == "Иванов Иван"
        assert cell.assignment_id == 1

    def test_cell_creates_without_name(self, qapp):
        """Ячейка создаётся без имени (тире)."""
        cell = AssignmentCell(
            assignment_id=1, participant_name=None, on_click=lambda aid, role: None
        )

        assert cell.text() == "—"

    def test_cell_with_conflict_shows_warning(self, qapp):
        """Ячейка с конфликтом показывает ⚠️."""
        cell = AssignmentCell(
            assignment_id=1,
            participant_name="Иванов Иван",
            on_click=lambda aid, role: None,
            has_conflict=True,
        )

        assert cell.text() == "⚠️ Иванов Иван"

    def test_cell_has_minimum_size(self, qapp):
        """Ячейка имеет минимальный размер."""
        cell = AssignmentCell(
            assignment_id=1, participant_name="Иванов Иван", on_click=lambda aid, role: None
        )

        assert cell.minimumWidth() == 130
        assert cell.minimumHeight() == 26
        assert cell.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding

    def test_schedule_toolbar_starts_with_sidebar_toggle(self, schedule_view):
        first_item = schedule_view.toolbar_layout.itemAt(0)

        assert first_item.widget() is schedule_view.btn_toggle_sidebar

    def test_schedule_panel_receives_extra_width(self, schedule_view):
        sizes = schedule_view.splitter.sizes()

        assert sizes[0] < sizes[1]

    def test_cell_click_calls_callback(self, qapp, qtbot):
        """Клик на ячейку вызывает callback."""
        call_args = []

        def on_click(assignment_id, role):
            call_args.append((assignment_id, role))

        cell = AssignmentCell(assignment_id=1, participant_name="Иванов Иван", on_click=on_click)

        cell.click()

        assert len(call_args) == 1
        assert call_args[0] == (1, "participant")

    def test_cell_with_assistant_role(self, qapp):
        """Ячейка с ролью assistant."""
        cell = AssignmentCell(
            assignment_id=1,
            participant_name="Петров Пётр",
            on_click=lambda aid, role: None,
            role="assistant",
        )

        assert cell.role == "assistant"
        assert cell.text() == "Петров Пётр"


# ============================================================
# ParticipantSelectDialog Tests
# ============================================================


class TestParticipantSelectDialog:
    """Тесты диалога выбора участника."""

    def test_dialog_creates(self, qapp, mock_facade):
        """Диалог создаётся."""
        dialog = ParticipantSelectDialog(None, mock_facade)

        assert dialog is not None
        assert dialog.windowTitle() == "Выбор участника"

    def test_dialog_has_combo(self, qapp, mock_facade):
        """Диалог имеет combobox."""
        dialog = ParticipantSelectDialog(None, mock_facade)

        assert hasattr(dialog, "combo")
        assert dialog.combo.count() >= 1  # Хотя бы "Не назначен"

    def test_search_filters_and_selects_first_match(self, qapp, mock_facade):
        """Набрал часть фамилии — в списке только подходящие, первый выбран (Enter = OK)."""
        dialog = ParticipantSelectDialog(None, mock_facade)
        names = [dialog.combo.itemText(i) for i in range(1, dialog.combo.count())]
        target = names[1].split("  —  ")[0]
        dialog.search.setText(target[:4].upper())
        shown = [dialog.combo.itemText(i) for i in range(dialog.combo.count())]
        assert shown[0] == "— Не назначен —"
        assert all(target[:4].casefold() in t.casefold() for t in shown[1:])
        assert dialog.combo.currentIndex() == 1
        dialog.search.clear()
        assert dialog.combo.count() == len(names) + 1

    def test_dialog_populates_participants(self, qapp, mock_facade):
        """Диалог заполняется участниками."""
        dialog = ParticipantSelectDialog(None, mock_facade)

        # Mock возвращает 3 участников + 1 "Не назначен"
        assert dialog.combo.count() == 4

    def test_student_item_on_talk_position_lists_sisters(self, qapp):
        """Ученическое задание на позиции 4 («Речь, только братья» в настройках)
        открыто для сестёр с «Учебными заданиями» — как в автоназначении."""
        from types import SimpleNamespace

        facade = Mock()
        facade.get_assignment.return_value = {
            "id": 861,
            "section": "ministry",
            "section_position": "4",
            "assignment_type": "student",
            "assignment_text": "Подготавливайте учеников",
            "discussion_marker": None,
            "participant_id": None,
            "assistant_id": None,
        }
        talk = SimpleNamespace(is_brothers_only=True, required_qualification="ministry_speech")
        facade.get_assignment_config.return_value = talk
        facade.get_all_participants.return_value = [
            {"id": 1, "name": "Сестра", "gender": "female", "qualifications": ["ministry_item"]},
            {
                "id": 2,
                "name": "Брат-докладчик",
                "gender": "male",
                "qualifications": ["ministry_speech"],
            },
        ]
        facade.get_participant_history.return_value = []

        dialog = ParticipantSelectDialog(None, facade, assignment_id=861)
        listed = [dialog.combo.itemData(i) for i in range(1, dialog.combo.count())]
        assert listed == [1]

    def test_dialog_preselects_current_participant(self, qapp):
        """Уже назначенный участник выбран сразу — OK без выбора не стирает назначение."""
        facade = Mock()
        facade.get_assignment.return_value = {
            "id": 5,
            "section": None,
            "section_position": "",
            "participant_id": 2,
            "assistant_id": None,
        }
        facade.get_all_participants.return_value = [
            {"id": 1, "name": "Первый", "gender": "male", "qualifications": []},
            {"id": 2, "name": "Второй", "gender": "male", "qualifications": []},
        ]
        facade.get_participant_history.return_value = []

        dialog = ParticipantSelectDialog(None, facade, assignment_id=5)
        assert dialog.get_selected_id() == 2

    def test_dialog_first_item_is_empty(self, qapp, mock_facade):
        """Первый пункт — «Не назначен»."""
        dialog = ParticipantSelectDialog(None, mock_facade)

        assert dialog.combo.itemText(0) == "— Не назначен —"
        assert dialog.combo.itemData(0) is None

    def test_dialog_get_selected_id_returns_none(self, qapp, mock_facade):
        """get_selected_id возвращает None для пустого выбора."""
        dialog = ParticipantSelectDialog(None, mock_facade)

        assert dialog.get_selected_id() is None

    def test_dialog_get_selected_id_returns_id(self, qapp, mock_facade, qtbot):
        """get_selected_id возвращает ID выбранного участника."""
        dialog = ParticipantSelectDialog(None, mock_facade)
        qtbot.addWidget(dialog)

        dialog.combo.setCurrentIndex(1)  # Первый участник

        assert dialog.get_selected_id() == 1

    def test_dialog_with_assignment_id_filters_by_gender(self, qapp, mock_facade):
        """Диалог фильтрует по полу для заданий только для братьев."""
        # Настраиваем mock для задания только для братьев
        mock_facade.get_assignment.return_value = {"section": "ministry", "section_position": "1"}
        mock_facade.get_assignment_config.return_value = Mock(
            is_brothers_only=True, required_qualification=None
        )

        dialog = ParticipantSelectDialog(None, mock_facade, assignment_id=1)

        # Должны быть только мужчины + "Не назначен"
        # Иванов (male), Петров (male) = 2 + 1 empty = 3
        assert dialog.combo.count() == 3


# ============================================================
# _same_family helper Tests
# ============================================================


class TestSameFamily:
    """Тесты вспомогательной функции _same_family (S-38 §7-§10)."""

    def _p(self, pid, fid=None):
        return {"id": pid, "family_group_id": fid}

    def test_both_heads_different_families(self):
        """Два главы разных семей - не родственники."""
        from ui.schedule_view import _same_family

        assert _same_family(self._p(1), self._p(2)) is False

    def test_head_and_its_member(self):
        """Глава (id=1) и член его семьи (fid=1) - родственники."""
        from ui.schedule_view import _same_family

        assert _same_family(self._p(1), self._p(2, fid=1)) is True

    def test_member_and_its_head(self):
        """Симметрия: член и глава - тоже родственники."""
        from ui.schedule_view import _same_family

        assert _same_family(self._p(2, fid=1), self._p(1)) is True

    def test_two_members_same_family(self):
        """Два члена с одинаковым fid - одна семья."""
        from ui.schedule_view import _same_family

        assert _same_family(self._p(2, fid=1), self._p(3, fid=1)) is True

    def test_two_members_different_families(self):
        """Два члена с разными fid - разные семьи."""
        from ui.schedule_view import _same_family

        assert _same_family(self._p(2, fid=1), self._p(4, fid=5)) is False

    def test_member_and_unrelated_head(self):
        """Член семьи 1 и глава другой семьи - не родственники."""
        from ui.schedule_view import _same_family

        assert _same_family(self._p(2, fid=1), self._p(10)) is False


# ============================================================
# ParticipantSelectDialog - Assistant Role Filter Tests (S-38)
# ============================================================


class TestParticipantSelectDialogAssistantFilter:
    """Тесты фильтрации напарника по полу/семье (S-38 §7-§10)."""

    def _make_p(self, pid, name, gender, fid=None, qualifications=None):
        return {
            "id": pid,
            "name": name,
            "gender": gender,
            "family_group_id": fid,
            "qualifications": qualifications or [],
        }

    def _make_facade(self, participants, assignment, main_participant=None):
        facade = Mock()
        facade.get_all_participants.return_value = participants
        facade.get_participant_history.return_value = []
        facade.get_assignment.return_value = assignment
        facade.get_assignment_config.return_value = None
        facade.get_participant.return_value = main_participant
        facade.events = Mock()
        facade.events.subscribe = Mock()
        return facade

    def test_assistant_only_same_gender_shown(self, qapp):
        """При выборе напарника-мужчины показываются только мужчины с qual assistant."""
        main = self._make_p(1, "Мартышин Александр", "male")
        participants = [
            self._make_p(1, "Мартышин Александр", "male", qualifications=["assistant"]),
            self._make_p(2, "Соколов Юрий", "male", qualifications=["assistant"]),
            self._make_p(3, "Сидорова Анна", "female", qualifications=["assistant"]),
            self._make_p(4, "Кузнецов Дмитрий", "male", qualifications=[]),  # нет assistant
        ]
        assignment = {"id": 10, "section": "ministry", "section_position": 1, "participant_id": 1}
        facade = self._make_facade(participants, assignment, main_participant=main)

        dialog = ParticipantSelectDialog(None, facade, assignment_id=10, role="assistant")
        names = [dialog.combo.itemText(i) for i in range(dialog.combo.count())]

        # Соколов - male + assistant = включён
        # Сидорова - female, не из семьи = исключена
        # Кузнецов - нет квал assistant = исключён
        # Мартышин - сам главный = исключён
        assert dialog.combo.count() == 2  # "Не назначен" + Соколов
        assert any("Соколов" in n for n in names)
        assert not any("Сидорова" in n for n in names)
        assert not any("Кузнецов" in n for n in names)
        assert not any("Мартышин" in n for n in names)

    def test_assistant_same_family_bypasses_gender(self, qapp):
        """Член семьи главного включается в список, даже если другого пола."""
        main = self._make_p(1, "Мартышин Александр", "male", fid=None)
        participants = [
            self._make_p(1, "Мартышин Александр", "male", fid=None, qualifications=["assistant"]),
            self._make_p(2, "Мартышина Лариса", "female", fid=1, qualifications=["assistant"]),
            self._make_p(3, "Сидорова Анна", "female", fid=None, qualifications=["assistant"]),
        ]
        assignment = {"id": 10, "section": "ministry", "section_position": 1, "participant_id": 1}
        facade = self._make_facade(participants, assignment, main_participant=main)

        dialog = ParticipantSelectDialog(None, facade, assignment_id=10, role="assistant")
        names = [dialog.combo.itemText(i) for i in range(dialog.combo.count())]

        assert any("Мартышина" in n for n in names), "Жена из семьи должна быть в списке"
        assert not any("Сидорова" in n for n in names), "Чужая сестра должна быть исключена"

    def test_assistant_main_excluded_from_list(self, qapp):
        """Главный участник не появляется в списке напарников."""
        main = self._make_p(1, "Иванов Иван", "male")
        participants = [
            self._make_p(1, "Иванов Иван", "male", qualifications=["assistant"]),
            self._make_p(2, "Петров Пётр", "male", qualifications=["assistant"]),
        ]
        assignment = {"id": 10, "section": "ministry", "section_position": 1, "participant_id": 1}
        facade = self._make_facade(participants, assignment, main_participant=main)

        dialog = ParticipantSelectDialog(None, facade, assignment_id=10, role="assistant")
        names = [dialog.combo.itemText(i) for i in range(dialog.combo.count())]

        assert not any("Иванов" in n for n in names), "Главный не должен быть в списке напарников"
        assert any("Петров" in n for n in names)

    def test_assistant_no_main_shows_all_with_qualification(self, qapp):
        """Если главный не назначен, показываются все с квалификацией assistant."""
        participants = [
            self._make_p(1, "Иванов Иван", "male", qualifications=["assistant"]),
            self._make_p(2, "Сидорова Анна", "female", qualifications=["assistant"]),
            self._make_p(3, "Петров Пётр", "male", qualifications=[]),
        ]
        # participant_id=None - главный не назначен
        assignment = {
            "id": 10,
            "section": "ministry",
            "section_position": 1,
            "participant_id": None,
        }
        facade = self._make_facade(participants, assignment, main_participant=None)

        dialog = ParticipantSelectDialog(None, facade, assignment_id=10, role="assistant")
        names = [dialog.combo.itemText(i) for i in range(dialog.combo.count())]

        # Фильтр по полу не применяется (главный неизвестен), только квалификация
        assert any("Иванов" in n for n in names)
        assert any("Сидорова" in n for n in names)
        assert not any("Петров" in n for n in names)  # нет квалификации assistant


# ============================================================
# ScheduleView Init Tests
# ============================================================


class TestScheduleViewInit:
    """Тесты инициализации ScheduleView."""

    def test_view_creates_with_facade(self, mock_facade, qapp):
        """View создаётся с facade."""
        view = ScheduleView(mock_facade)

        assert view is not None
        assert view.facade is mock_facade

    def test_view_has_tree_widget(self, mock_facade, qapp):
        """View имеет дерево недель."""
        view = ScheduleView(mock_facade)

        assert hasattr(view, "tree")
        assert isinstance(view.tree, QTreeWidget)

    def test_view_has_auto_button(self, mock_facade, qapp):
        """View имеет кнопку авто-распределения."""
        view = ScheduleView(mock_facade)

        assert hasattr(view, "btn_auto")
        assert isinstance(view.btn_auto, QPushButton)
        assert "Авто-распределение" in view.btn_auto.text()

    def test_view_has_add_item_button(self, mock_facade, qapp):
        view = ScheduleView(mock_facade)

        assert view.btn_add_item.text() == "➕ Пункт"

    def test_meeting_time_setting_is_used_for_schedule(self, mock_facade, qapp):
        mock_facade.get_setting.side_effect = lambda key, default=None: (
            "19:15" if key == "meeting_time" else default
        )
        view = ScheduleView(mock_facade)
        view._load_week_editor(1)

        assert not hasattr(view, "meeting_start_edit")
        assert view.assignment_table.item(0, 3).text() == "19:15"
        assert view.assignment_table.item(1, 3).text() == "19:16"  # молитва — через 1 мин

    def test_manual_assignment_dialog_returns_values(self, mock_facade, qapp):
        dialog = ManualAssignmentDialog(mock_facade, 1)
        dialog.text_edit.setText("Внеочередное выступление")
        dialog.section_combo.setCurrentIndex(dialog.section_combo.findData("ministry"))
        dialog.duration_spin.setValue(7)
        dialog.participant_combo.setCurrentIndex(dialog.participant_combo.findData(1))

        assert dialog.get_values() == {
            "text": "Внеочередное выступление",
            "section": "ministry",
            "duration": 7,
            "participant_id": 1,
        }

    def test_add_item_saves_custom_assignment(self, mock_facade, qapp):
        view = ScheduleView(mock_facade)
        view._load_week_editor(1)
        values = {
            "text": "Внеочередное выступление",
            "section": "ministry",
            "duration": 7,
            "participant_id": 1,
        }

        with patch("ui.schedule_table_edit.ManualAssignmentDialog") as dialog_class:
            dialog = dialog_class.return_value
            dialog.exec.return_value = QDialog.DialogCode.Accepted
            dialog.get_values.return_value = values
            view._on_add_item()

        mock_facade.add_manual_assignment.assert_called_once_with(week_id=1, **values)

    def test_undo_and_redo_restore_assignment_snapshot(self, mock_facade, qapp):
        view = ScheduleView(mock_facade)
        view._load_week_editor(1)
        snapshot = view._capture_schedule_state()
        view._undo_stack.append(snapshot)

        view._on_undo()

        mock_facade.replace_week_assignments.assert_called_once_with(1, snapshot)
        assert view.btn_redo.isEnabled()

        view._on_redo()

        assert view.btn_undo.isEnabled()

    def test_mutation_records_undo_state(self, mock_facade, qapp):
        view = ScheduleView(mock_facade)
        view._load_week_editor(1)

        view._record_undo_state()

        assert len(view._undo_stack) == 1
        assert view.btn_undo.isEnabled()
        assert not view.btn_redo.isEnabled()

    def test_keyboard_shortcuts_are_registered(self, mock_facade, qapp):
        view = ScheduleView(mock_facade)

        assert view.shortcut_undo.key().toString() == "Ctrl+Z"
        assert view.shortcut_redo.key().toString() == "Ctrl+Shift+Z"
        assert view.shortcut_redo_alt.key().toString() == "Ctrl+Y"

    def test_delete_key_removes_selected_custom_row(self, mock_facade, qapp):
        view = ScheduleView(mock_facade)
        view._load_week_editor(1)
        view._table_assignments[1]["assignment_type"] = "custom"
        view.assignment_table.setCurrentCell(0, 1)

        with (
            patch.object(view.assignment_table, "hasFocus", return_value=True),
            patch.object(
                view,
                "_on_delete_manual_item",
            ) as delete_item,
        ):
            view._on_table_delete()

        delete_item.assert_called_once_with(1)

    def test_context_menu_uses_non_blocking_popup(self, mock_facade, qapp):
        view = ScheduleView(mock_facade)
        view._load_week_editor(1)
        view._table_assignments[1]["assignment_type"] = "custom"
        position = view.assignment_table.visualItemRect(view.assignment_table.item(0, 0)).center()

        with (
            patch("ui.schedule_view.QMenu.popup") as popup,
            patch("ui.schedule_view.QMenu.exec") as menu_exec,
        ):
            view._on_table_context_menu(position)

        popup.assert_called_once()
        menu_exec.assert_not_called()

    def test_context_menu_action_dispatch(self, mock_facade, qapp):
        view = ScheduleView(mock_facade)
        edit_action = object()
        duplicate_action = object()
        delete_action = object()

        with patch.object(view, "_on_duplicate_manual_item") as duplicate:
            view._handle_table_context_action(
                duplicate_action,
                1,
                edit_action,
                duplicate_action,
                delete_action,
            )

        duplicate.assert_called_once_with(1)

    def test_view_has_no_templates_button(self, mock_facade, qapp):
        view = ScheduleView(mock_facade)

        assert not hasattr(view, "btn_templates")

    def test_edit_manual_item_saves_values(self, mock_facade, qapp):
        view = ScheduleView(mock_facade)
        view.current_week_id = 1
        assignment = {
            "id": 50,
            "assignment_type": "custom",
            "assignment_text": "Старый пункт",
            "section": "ministry",
            "duration": 5,
            "participant_id": None,
        }
        view._table_assignments[50] = assignment
        values = {
            "text": "Изменённый пункт",
            "section": "living",
            "duration": 8,
            "participant_id": 1,
        }

        with patch("ui.schedule_table_edit.ManualAssignmentDialog") as dialog_class:
            dialog = dialog_class.return_value
            dialog.exec.return_value = QDialog.DialogCode.Accepted
            dialog.get_values.return_value = values
            view._on_edit_manual_item(50)

        mock_facade.update_manual_assignment.assert_called_once_with(50, **values)

    def test_edit_manual_item_error_does_not_escape(self, mock_facade, qapp):
        view = ScheduleView(mock_facade)
        view._table_assignments[50] = {"assignment_type": "custom"}

        with (
            patch(
                "ui.schedule_view.ManualAssignmentDialog.exec",
                side_effect=RuntimeError("boom"),
            ),
            patch.object(QMessageBox, "critical") as critical,
        ):
            view._on_edit_manual_item(50)

        critical.assert_called_once()

    def test_duplicate_and_delete_manual_item(self, mock_facade, qapp):
        view = ScheduleView(mock_facade)
        view.current_week_id = 1
        view._table_assignments[50] = {"assignment_type": "custom"}

        view._on_duplicate_manual_item(50)
        mock_facade.duplicate_manual_assignment.assert_called_once_with(50)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            view._on_delete_manual_item(50)
        mock_facade.delete_manual_assignment.assert_called_once_with(50)

    def test_view_has_sidebar_toggle(self, mock_facade, qapp):
        view = ScheduleView(mock_facade)

        assert view.btn_toggle_sidebar.isCheckable()
        assert not view.btn_toggle_sidebar.icon().isNull()
        assert "недель" in view.btn_toggle_sidebar.toolTip()

    def test_sidebar_toggle_changes_visibility(self, schedule_view):
        schedule_view.btn_toggle_sidebar.setChecked(False)
        schedule_view._toggle_sidebar()

        assert schedule_view.left_panel.isHidden()
        assert not schedule_view.btn_toggle_sidebar.icon().isNull()

        schedule_view.btn_toggle_sidebar.setChecked(True)
        schedule_view._toggle_sidebar()

        assert not schedule_view.left_panel.isHidden()
        assert not schedule_view.btn_toggle_sidebar.icon().isNull()

    def test_week_summary_is_updated(self, mock_facade, qapp):
        view = ScheduleView(mock_facade)

        view._load_week_editor(1)

        assert view.week_stats_label.text() == "Назначено 2 из 2"
        assert view.week_stats_label.property("complete") is True
        assert not [
            label
            for label in view.form_widget.findChildren(QLabel, "weekConflicts")
            if label.isVisibleTo(view.form_widget)
        ]

    def test_week_header_shows_conflicts(self, mock_facade, qapp):
        mock_facade.get_week_conflicts.return_value = {1}
        view = ScheduleView(mock_facade)

        view._load_week_editor(1)

        labels = [
            label
            for label in view.form_widget.findChildren(QLabel, "weekConflicts")
            if label.isVisibleTo(view.form_widget)
        ]
        assert [label.text() for label in labels] == ["⚠️ Конфликты: 1"]

    def test_service_keys_are_not_shown_as_numbers(self, mock_facade, qapp):
        """Ключи вроде «chairman» не попадают в колонку «№», а у председателя нет поля времени."""
        chairman = mock_facade.get_week_data.return_value["assignments"][0]
        chairman.update(assignment_number="chairman", duration=0)
        view = ScheduleView(mock_facade)

        view._load_week_editor(1)

        table = view.assignment_table
        numbers = [table.item(r, 1).text() for r in range(table.rowCount())]
        assert "chairman" not in numbers
        chairman_row = numbers.index("")
        assert table.cellWidget(chairman_row, 4) is None

    def test_week_with_sort_order_loads(self, mock_facade, qapp):
        """Неделя с ручным порядком пунктов (sort_order) открывается без NameError."""
        for order, assignment in enumerate(mock_facade.get_week_data.return_value["assignments"]):
            assignment["sort_order"] = order
        mock_facade.get_week_data.return_value["assignments"][1]["section"] = "unknown"
        view = ScheduleView(mock_facade)

        view._load_week_editor(1)

        assert view.assignment_table.rowCount() == 2

    def test_future_year_follows_last_year_in_tree(self, mock_facade, qapp):
        """«Будущий год» предлагает год, который выбрало ядро (plan_future_year).

        Сам выбор — после последнего года, а не после текущего — проверяет
        tests/test_future_year.py на настоящей базе.
        """
        mock_facade.plan_future_year.return_value = {"year": 2032, "missing": 52}
        view = ScheduleView(mock_facade)
        asked = []

        def fake_question(parent, title, text, *args, **kwargs):
            asked.append(text)
            return QMessageBox.StandardButton.No

        with patch.object(QMessageBox, "question", side_effect=fake_question):
            view._on_add_future_year()

        assert asked and "2032" in asked[0]

    def test_assignment_rows_can_be_dragged(self, mock_facade, qapp):
        """Перетаскивание строк включено: владелец решил его оставить."""
        from PySide6.QtWidgets import QAbstractItemView

        view = ScheduleView(mock_facade)
        view._load_week_editor(1)

        table = view.assignment_table
        assert table.acceptDrops()
        assert table.dragDropMode() == QAbstractItemView.DragDropMode.InternalMove

    def test_view_has_clear_button(self, mock_facade, qapp):
        """View имеет кнопку очистки."""
        view = ScheduleView(mock_facade)

        assert hasattr(view, "btn_clear")
        assert isinstance(view.btn_clear, QPushButton)
        assert "Очистить" in view.btn_clear.toolTip()

    def test_view_has_pdf_and_txt_export_buttons(self, mock_facade, qapp):
        """PDF и TXT экспортируются отдельными кнопками в один клик."""
        view = ScheduleView(mock_facade)

        assert isinstance(view.btn_export_pdf, QPushButton)
        assert "PDF" in view.btn_export_pdf.text()
        assert isinstance(view.btn_export_txt, QPushButton)
        assert "TXT" in view.btn_export_txt.text()

    def test_more_menu_has_docx_and_s89(self, mock_facade, qapp):
        """Word и S-89 спрятаны в меню «Ещё»."""
        view = ScheduleView(mock_facade)

        texts = [a.text() for a in view.btn_more.menu().actions()]
        assert any("Word" in t for t in texts)
        assert any("S-89" in t for t in texts)
        assert not hasattr(view, "btn_export_s89")

    def test_notify_menu_has_log(self, mock_facade, qapp):
        """Журнал уведомлений — в меню кнопки «Уведомить»."""
        view = ScheduleView(mock_facade)

        assert "Уведомить" in view.btn_notify.text()
        texts = [a.text() for a in view.btn_notify.menu().actions()]
        assert any("Журнал" in t for t in texts)
        assert not hasattr(view, "btn_notif_log")

    def test_toolbar_has_no_assignment_filter(self, mock_facade, qapp):
        """Фильтр пунктов убран из панели."""
        view = ScheduleView(mock_facade)

        assert not hasattr(view, "assignment_filter_combo")

    def test_view_has_add_year_button(self, mock_facade, qapp):
        """View имеет кнопку добавления года."""
        view = ScheduleView(mock_facade)

        assert hasattr(view, "btn_add_year")
        assert isinstance(view.btn_add_year, QPushButton)
        assert "Будущий год" in view.btn_add_year.text()

    def test_view_subscribes_to_events(self, mock_facade, qapp):
        """View подписывается на события."""
        view = ScheduleView(mock_facade)

        mock_facade.events.subscribe.assert_called()


# ============================================================
# ScheduleView Tree Tests
# ============================================================


class TestScheduleViewTree:
    """Тесты дерева недель."""

    def test_load_tree_populates_years(self, mock_facade, qapp):
        """load_tree загружает годы."""
        view = ScheduleView(mock_facade)

        assert view.tree.topLevelItemCount() > 0

    def test_load_tree_populates_months(self, mock_facade, qapp):
        """load_tree загружает месяцы."""
        view = ScheduleView(mock_facade)

        year_item = view.tree.topLevelItem(0)
        assert year_item.childCount() > 0

    def test_load_tree_populates_weeks(self, mock_facade, qapp):
        """load_tree загружает недели."""
        view = ScheduleView(mock_facade)

        year_item = view.tree.topLevelItem(0)
        month_item = year_item.child(0)
        assert month_item.childCount() > 0

    def test_week_item_has_user_role_id(self, mock_facade, qapp):
        """Элемент недели имеет ID в UserRole."""
        view = ScheduleView(mock_facade)

        year_item = view.tree.topLevelItem(0)
        month_item = year_item.child(0)
        week_item = month_item.child(0)

        week_id = week_item.data(0, Qt.ItemDataRole.UserRole)
        assert week_id is not None

    def test_on_tree_item_clicked_loads_week(self, mock_facade, qapp, qtbot):
        """Клик на элемент дерева загружает неделю."""
        view = ScheduleView(mock_facade)
        qtbot.addWidget(view)

        year_item = view.tree.topLevelItem(0)
        month_item = year_item.child(0)
        week_item = month_item.child(0)

        # Симулируем клик
        view._on_tree_item_clicked(week_item, 0)

        # get_week_data должен быть вызван
        mock_facade.get_week_data.assert_called()
        mock_facade.save_setting.assert_called_with(
            "last_selected_week", str(week_item.data(0, Qt.ItemDataRole.UserRole))
        )


# ============================================================
# ScheduleView Week Loading Tests
# ============================================================


class TestScheduleViewLoadWeek:
    """Тесты загрузки недели."""

    def test_load_week_editor_shows_special_event(self, mock_facade, qapp):
        """load_week_editor показывает особое событие."""
        mock_facade.get_week_special_event.return_value = "memorial"
        view = ScheduleView(mock_facade)

        view._load_week_editor(1)

        # Должен показать заглушку, а не форму
        mock_facade.get_week_data.assert_not_called()

    def test_load_week_form_clears_form(self, mock_facade, qapp):
        """load_week_form очищает форму."""
        view = ScheduleView(mock_facade)

        # Добавляем что-то в форму
        view.form_layout.addWidget(QLabel("Test"))
        assert view.form_layout.count() > 0

        view._load_week_form(1)

        # Форма должна быть очищена и заполнена заново
        # Проверяем, что есть заголовок недели
        found_header = any(
            "3-9 марта" in label.text()
            for label in view.form_widget.findChildren(QLabel)
            if label.isVisibleTo(view.form_widget)
        )

        assert found_header

    def test_load_week_form_shows_bible_reading(self, mock_facade, qapp):
        """load_week_form показывает чтение Библии."""
        view = ScheduleView(mock_facade)
        view._load_week_form(1)

        found_bible = any(
            "Матфея 5-7" in label.text()
            for label in view.form_widget.findChildren(QLabel)
            if label.isVisibleTo(view.form_widget)
        )

        assert found_bible

    def test_load_week_form_creates_assignment_table(self, mock_facade, qapp):
        """load_week_form создаёт таблицу назначений."""
        view = ScheduleView(mock_facade)
        view._load_week_form(1)

        assert isinstance(view.assignment_table, QTableWidget)
        assert view.assignment_table.columnCount() == 7
        assert view.assignment_table.rowCount() == 2
        assert view.assignment_table.horizontalHeaderItem(0).text() == "Раздел"
        assert view.assignment_table.horizontalHeaderItem(2).text() == "Назначение"
        assert view.assignment_table.horizontalHeaderItem(3).text() == "Начало"
        assert view.assignment_table.horizontalHeaderItem(4).text() == "Время"
        assert view.assignment_table.horizontalHeaderItem(6).text() == "Напарник"
        assert view.assignment_table.item(0, 0).text() == "Общие"
        assert isinstance(view.assignment_table.cellWidget(0, 5), AssignmentCell)


# ============================================================
# ScheduleView Auto Assign Tests
# ============================================================


class TestScheduleViewAutoAssign:
    """Тесты авто-распределения."""

    def test_auto_assign_button_exists(self, mock_facade, qapp):
        """Кнопка авто-распределения существует."""
        view = ScheduleView(mock_facade)

        assert view.btn_auto is not None

    def test_auto_assign_shows_confirmation(self, mock_facade, qapp, qtbot):
        """Авто-распределение показывает подтверждение."""
        view = ScheduleView(mock_facade)
        qtbot.addWidget(view)
        view.current_week_id = 1

        # Перехватываем QMessageBox.question через patch на уровне модуля
        with patch(
            "ui.schedule_view.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes
        ) as mock_question:
            # Mock TaskWorker чтобы избежать реального выполнения
            with patch("ui.schedule_auto.TaskWorker") as MockWorker:
                mock_worker = Mock()
                mock_worker.finished = Mock()
                mock_worker.start = Mock()
                MockWorker.return_value = mock_worker

                view._on_auto_assign()

                mock_question.assert_called_once()

    def test_auto_assign_creates_worker(self, mock_facade, qapp, qtbot):
        """Авто-распределение создаёт TaskWorker."""
        view = ScheduleView(mock_facade)
        qtbot.addWidget(view)
        view.current_week_id = 1

        with patch(
            "ui.schedule_view.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes
        ):
            with patch("ui.schedule_auto.TaskWorker") as MockWorker:
                mock_worker = Mock()
                mock_worker.finished = Mock()
                mock_worker.start = Mock()
                mock_worker.isRunning = Mock(return_value=False)
                MockWorker.return_value = mock_worker

                view._on_auto_assign()

                MockWorker.assert_called_once()
                mock_worker.start.assert_called_once()

    def test_auto_assign_without_week_id_does_nothing(self, mock_facade, qapp):
        """Авто-распределение без недели ничего не делает."""
        view = ScheduleView(mock_facade)
        view.current_week_id = None

        with patch("ui.schedule_auto.TaskWorker") as MockWorker:
            with patch("ui.schedule_view.QMessageBox.warning") as mock_warning:
                view._on_auto_assign()

                MockWorker.assert_not_called()
                mock_warning.assert_called_once()


# ============================================================
# ScheduleView Clear Week Tests
# ============================================================


class TestScheduleViewClearWeek:
    """Тесты очистки недели."""

    def test_clear_week_shows_confirmation(self, mock_facade, qapp, qtbot):
        """Очистка недели показывает подтверждение."""
        view = ScheduleView(mock_facade)
        qtbot.addWidget(view)
        view.current_week_id = 1

        with patch(
            "ui.schedule_view.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes
        ) as mock_question:
            view._on_clear_week()
            mock_question.assert_called_once()

    def test_clear_week_calls_facade(self, mock_facade, qapp, qtbot):
        """Очистка недели вызывает facade.clear_week_assignments."""
        view = ScheduleView(mock_facade)
        qtbot.addWidget(view)
        view.current_week_id = 1

        with patch(
            "ui.schedule_view.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes
        ):
            view._on_clear_week()

        mock_facade.clear_week_assignments.assert_called_with(1)

    def test_clear_week_without_week_id_shows_warning(self, mock_facade, qapp, qtbot):
        """Очистка без недели показывает предупреждение."""
        view = ScheduleView(mock_facade)
        view.current_week_id = None

        with patch("ui.schedule_view.QMessageBox.warning") as mock_warning:
            view._on_clear_week()
            mock_warning.assert_called_once()

        mock_facade.clear_week_assignments.assert_not_called()


# ============================================================
# ScheduleView Export Tests
# ============================================================


class TestScheduleViewExport:
    """Тесты экспорта."""

    def test_export_buttons_exist(self, mock_facade, qapp):
        """Кнопки экспорта существуют."""
        view = ScheduleView(mock_facade)

        assert view.btn_export_pdf is not None
        assert view.btn_export_txt is not None

    def test_export_creates_dialog(self, mock_facade, qapp, qtbot):
        """Экспорт создаёт ExportDialog."""
        view = ScheduleView(mock_facade)
        qtbot.addWidget(view)
        view.current_week_id = 1  # Нужно для экспорта

        # Mock ExportDialog to avoid actual dialog creation
        with patch("ui.export_dialog.ExportDialog") as MockDialog:
            mock_dialog = Mock()
            mock_dialog.exec = Mock(return_value=0)
            MockDialog.return_value = mock_dialog

            view._on_export("pdf")

        mock_facade.get_weeks_tree.assert_called()
        assert MockDialog.call_args.kwargs["formats"] == ("pdf",)

    def test_month_context_menu_exports_s89_for_whole_month(self, mock_facade, qapp):
        """Правый клик по месяцу: S-89 сразу на все недели месяца."""
        from PySide6.QtWidgets import QTreeWidgetItem

        view = ScheduleView(mock_facade)
        month = QTreeWidgetItem(["📆 Ноябрь"])
        for wid in (11, 12, 13):
            child = QTreeWidgetItem(["неделя"])
            child.setData(0, Qt.ItemDataRole.UserRole, wid)
            month.addChild(child)

        with (
            patch("ui.schedule_view.QMenu") as MockMenu,
            patch.object(view, "_export_s89_for_weeks") as export,
        ):
            menu = MockMenu.return_value
            view._show_month_context_menu(month, view.tree.rect().center())
            title = menu.addAction.call_args.args[0]
            menu.addAction.return_value.triggered.connect.call_args.args[0]()

        assert "S-89" in title and "ноябрь" in title
        export.assert_called_once_with([11, 12, 13])


# ============================================================
# ScheduleView Special Event Tests
# ============================================================


class TestScheduleViewSpecialEvent:
    """Тесты особых событий."""

    def test_show_special_event_placeholder_memorial(self, mock_facade, qapp):
        """Показ заглушки для Вечери."""
        view = ScheduleView(mock_facade)
        view._show_special_event_placeholder("memorial")

        # Проверяем, что форма содержит заглушку
        found_container = False
        for i in range(view.form_layout.count()):
            item = view.form_layout.itemAt(i)
            if item.widget() and isinstance(item.widget(), QFrame):
                found_container = True
                break

        assert found_container

    def test_set_special_event_calls_facade(self, mock_facade, qapp, qtbot):
        """Установка особого события вызывает facade."""
        view = ScheduleView(mock_facade)
        qtbot.addWidget(view)
        view.current_week_id = 1

        # Mock QMessageBox.information
        with patch("ui.schedule_view.QMessageBox.information"):
            view._set_special_event(1, "memorial")

        mock_facade.set_special_event.assert_called_with(1, "memorial")


# ============================================================
# ScheduleView Helper Method Tests
# ============================================================


class TestScheduleViewHelpers:
    """Тесты вспомогательных методов."""

    def test_strip_leading_number_removes_duplicate(self, mock_facade, qapp):
        """_strip_leading_number убирает дублирующий номер."""
        view = ScheduleView(mock_facade)

        result = view._strip_leading_number("4. Начинайте разговор", "4")

        assert result == "Начинайте разговор"

    def test_strip_leading_number_keeps_if_no_duplicate(self, mock_facade, qapp):
        """_strip_leading_number сохраняет текст без дубля."""
        view = ScheduleView(mock_facade)

        result = view._strip_leading_number("Начинайте разговор", "4")

        assert result == "Начинайте разговор"

    def test_strip_leading_number_with_parenthesis(self, mock_facade, qapp):
        """_strip_leading_number не убирает номер перед скобкой."""
        view = ScheduleView(mock_facade)

        result = view._strip_leading_number("4) Вопрос", "4")

        assert result == "4) Вопрос"

    def test_find_assignment_by_number(self, mock_facade, qapp):
        """_find_assignment находит задание по номеру."""
        view = ScheduleView(mock_facade)
        assignments = [
            {"assignment_number": "1", "id": 1},
            {"assignment_number": "2", "id": 2},
        ]

        result = view._find_assignment(assignments, "1")

        assert result is not None
        assert result["id"] == 1

    def test_find_assignment_with_dot(self, mock_facade, qapp):
        """_find_assignment находит задание с точкой."""
        view = ScheduleView(mock_facade)
        assignments = [
            {"assignment_number": "1.", "id": 1},
        ]

        result = view._find_assignment(assignments, "1")

        assert result is not None

    def test_assignment_table_preserves_assignment_mapping(self, mock_facade, qapp):
        """Таблица сохраняет соответствие строк и назначений."""
        view = ScheduleView(mock_facade)
        view._load_week_form(1)

        assert view._assignment_rows[1] == 0
        assert view._assignment_rows[2] == 1
        assert view.assignment_table.item(0, 2).text() == "Председатель"
        assert view.assignment_table.item(0, 3).text() == "19:00"
        assert view.assignment_table.item(1, 3).text() == "19:01"  # молитва — через 1 мин
        first_duration = view.assignment_table.cellWidget(0, 4)
        second_duration = view.assignment_table.cellWidget(1, 4)
        assert isinstance(first_duration, QSpinBox)
        assert first_duration.value() == 5
        assert second_duration.value() == 3

    def test_reorderable_table_moves_rows(self, qapp):
        assert ReorderableTableWidget._move_rows([1, 2, 3], [0], 2) == [2, 1, 3]
        assert ReorderableTableWidget._move_rows([1, 2, 3], [2], 0) == [3, 1, 2]

    def test_conflicting_assignment_highlights_row(self, mock_facade, qapp):
        mock_facade.get_week_conflicts.return_value = {1}
        view = ScheduleView(mock_facade)
        view._load_week_editor(1)

        assert view._conflicted_assignment_ids == {1}
        assert view.assignment_table.item(0, 0).background().color().name() == get_palette(Theme.LIGHT).conflict_background
        assert view.assignment_table.item(1, 0).background().color().name() != get_palette(Theme.LIGHT).conflict_background

    def test_duration_editor_saves_manual_change(self, mock_facade, qapp):
        view = ScheduleView(mock_facade)
        view._load_week_form(1)
        editor = view.assignment_table.cellWidget(0, 4)

        editor.setValue(12)
        editor.editingFinished.emit()

        mock_facade.update_assignment_duration.assert_called_once_with(1, 12)

    def test_create_cell_returns_assignment_cell(self, mock_facade, qapp):
        """_create_cell возвращает AssignmentCell."""
        view = ScheduleView(mock_facade)
        view.current_conflicts = set()

        cell = view._create_cell(1, "Иванов Иван", 1)

        assert isinstance(cell, AssignmentCell)
        assert cell.text() == "Иванов Иван"


# ============================================================
# ScheduleView Integration Tests
# ============================================================


class TestScheduleViewIntegration:
    """Интеграционные тесты."""

    def test_view_with_real_facade(self, facade, qapp, qtbot):
        """View с реальным facade."""
        view = ScheduleView(facade)
        qtbot.addWidget(view)

        assert view is not None

    def test_full_workflow(self, mock_facade, qapp, qtbot):
        """Полный рабочий цикл."""
        view = ScheduleView(mock_facade)
        qtbot.addWidget(view)

        # 1. Дерево загружено
        assert view.tree.topLevelItemCount() > 0

        # 2. Выбираем неделю
        year_item = view.tree.topLevelItem(0)
        month_item = year_item.child(0)
        week_item = month_item.child(0)
        view._on_tree_item_clicked(week_item, 0)

        # 3. Неделя загружена
        assert view.current_week_id is not None

        # 4. Очищаем неделю
        with patch(
            "ui.schedule_view.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes
        ):
            view._on_clear_week()

        mock_facade.clear_week_assignments.assert_called()

    def test_on_assignments_changed_reloads_current_week(self, mock_facade, qapp, qtbot):
        """_on_assignments_changed обновляет текущую неделю при получении события."""
        from core.events_base import Event as EventData

        view = ScheduleView(mock_facade)
        qtbot.addWidget(view)
        view.current_week_id = 1

        with patch.object(view, "_load_week_editor") as mock_load:
            # Создаем событие с тем же week_id
            event = EventData(name="ASSIGNMENT_CHANGED", data={"week_id": 1})
            view._on_assignments_changed(event)
            mock_load.assert_called_with(1)

    def test_on_assignments_changed_does_not_reload_different_week(self, mock_facade, qapp, qtbot):
        """_on_assignments_changed не обновляет другую неделю."""
        from core.events_base import Event as EventData

        view = ScheduleView(mock_facade)
        qtbot.addWidget(view)
        view.current_week_id = 1

        with patch.object(view, "_load_week_editor") as mock_load:
            # Создаем событие с другим week_id
            event = EventData(name="ASSIGNMENT_CHANGED", data={"week_id": 2})
            view._on_assignments_changed(event)
            mock_load.assert_not_called()


def test_week_navigation_buttons(mock_facade, qapp):
    """‹ › листают недели по порядку дерева, через границу месяца; «Сегодня» возвращает."""
    mock_facade.get_setting.return_value = None
    view = ScheduleView(mock_facade)
    view._load_tree()
    start = view.current_week_id

    view._step_week(1)
    assert view.current_week_id == 2
    view.btn_next_week.click()
    assert view.current_week_id == 3  # следующий месяц
    view._step_week(1)
    assert view.current_week_id == 3  # дальше недель нет — остаёмся
    view.btn_prev_week.click()
    assert view.current_week_id == 2

    view.btn_today.click()
    assert view.current_week_id == view._today_week_item.data(0, Qt.ItemDataRole.UserRole)
    assert start in (1, 2, 3)


def test_today_leaves_month_mode(mock_facade, qapp):
    """«Сегодня» на доске месяца — обратно в вид недели, на текущую неделю."""
    mock_facade.get_setting.return_value = None
    mock_facade.get_month_board.return_value = None  # доска пустая — проверяем только переключение
    view = ScheduleView(mock_facade)
    view._load_tree()
    view._step_week(1)
    view.btn_month.setChecked(True)
    assert view._month_mode()

    view.btn_today.click()
    assert not view._month_mode()
    assert view.right_stack.currentWidget() is view.right_panel
    assert view.current_week_id == view._today_week_item.data(0, Qt.ItemDataRole.UserRole)


def test_filled_cell_click_opens_menu_with_clear(qapp):
    """Нажатие на назначенного участника — меню; «Очистить» вызывает on_clear."""
    from unittest.mock import patch

    from PySide6.QtWidgets import QMenu

    chosen, cleared = [], []
    cell = AssignmentCell(
        assignment_id=5,
        participant_name="Иванов Иван",
        on_click=lambda aid, role: chosen.append(aid),
        on_send_email=lambda: None,
        on_clear=lambda: cleared.append(True),
    )
    with patch.object(QMenu, "popup") as popup:
        cell.click()
    popup.assert_called_once()
    assert chosen == []  # выбор не открылся сразу

    menu = cell.findChildren(QMenu)[-1]
    labels = [a.text() for a in menu.actions() if a.text()]
    assert labels == ["👤 Выбрать / заменить…", "✉️ Написать / отправить email...", "🗑️ Очистить"]
    menu.actions()[-1].trigger()
    assert cleared == [True]

    empty = AssignmentCell(
        assignment_id=6,
        participant_name=None,
        on_click=lambda aid, role: chosen.append(aid),
        on_clear=lambda: None,
    )
    empty.click()
    assert chosen == [6]  # пустая ячейка — сразу выбор


def test_not_notified_ids(mock_facade, qapp):
    """«Не уведомлено»: назначенные и напарники без успешного письма, без повторов."""
    view = ScheduleView(mock_facade)
    view.current_notif_statuses = {1: {"status": "success"}, 2: {"status": "error"}}
    assignments = [
        {"status": "assigned", "participant_id": 1, "assistant_id": 2},
        {"status": "assigned", "participant_id": 3, "assistant_id": None},
        {"status": "assigned", "participant_id": 3, "assistant_id": 4},
        {"status": "unassigned", "participant_id": 5, "assistant_id": None},
    ]
    assert view._not_notified_ids(assignments) == [2, 3, 4]


def test_notification_dialog_preselects_only_given(qapp):
    from unittest.mock import Mock

    from ui.notification_dialog import NotificationDialog

    facade = Mock()
    facade.get_setting.return_value = ""
    facade.get_week_data.return_value = {}
    facade.get_last_notification.return_value = None
    facade.get_notification_preview.return_value = [
        {"id": 1, "name": "А", "email": "a@x"},
        {"id": 2, "name": "Б", "email": "b@x"},
        {"id": 3, "name": "В", "email": None},
    ]
    dialog = NotificationDialog(facade, [10], only_participant_ids=[2, 3])
    checked = {pid: cb.isChecked() for pid, cb in dialog.participant_checks.items()}
    assert checked == {1: False, 2: True, 3: False}  # у 3 нет email


def test_narrow_toolbar_moves_pdf_txt_to_more_menu(schedule_view, qapp):
    """Узкое окно (планшет): «Авто» коротко, PDF/TXT — в меню «Ещё», а не обрезанные кнопки."""
    view = schedule_view
    view.show()
    view.toolbar_widget.setMaximumWidth(700)  # как на планшете: окно уже кнопок
    qapp.processEvents()
    view._fit_toolbar()
    assert view.btn_auto.text() == view.AUTO_TEXT_SHORT
    assert view.btn_export_pdf.isHidden() and view.action_export_pdf.isVisible()
    view.toolbar_widget.setMaximumWidth(16777215)
    view.resize(4000, 600)
    qapp.processEvents()
    view._fit_toolbar()
    assert view.btn_auto.text() == view.AUTO_TEXT_FULL
    assert not view.btn_export_pdf.isHidden() and not view.action_export_pdf.isVisible()


def test_month_auto_assign_takes_snapshot_and_undo_restores(schedule_view, tmp_path):
    """Перед «Авто-распределить месяц» — снимок базы; ↶ в месяце возвращает к нему."""
    from PySide6.QtWidgets import QMessageBox

    view = schedule_view
    view.facade.schedule.db.db_path = str(tmp_path / "test.db")
    view.facade.get_month_board.return_value = None
    view.btn_month.setChecked(True)
    view.month_board.weeks_with_gaps = lambda: [7]
    view.month_board.board = {"columns": [{"week_id": 7, "title": "8—14 февраля"}]}
    view.month_board.refresh = lambda: None
    assert not view.btn_undo.isEnabled()
    with (
        patch("ui.schedule_view.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes),
        patch("ui.schedule_auto.take_snapshot", return_value="snap.db") as take,
        patch("ui.schedule_auto.TaskWorker") as worker,
    ):
        view._on_auto_assign()
    take.assert_called_once_with(str(tmp_path / "test.db"), "month-auto")
    assert worker.call_args.args[:2] == (view.facade.auto_assign_weeks, [7])
    # пока распределение идёт: ни отката, ни повторного запуска
    assert not view.btn_undo.isEnabled() and not view.btn_auto.isEnabled()
    with patch("ui.schedule_auto.restore_snapshot") as restore:
        view._on_undo()
    restore.assert_not_called()
    with patch("ui.schedule_auto.take_snapshot") as take_again:
        view._on_auto_assign()
    take_again.assert_not_called()
    with patch("ui.schedule_auto.ToastNotification"):
        view._on_auto_assign_month_finished({"success": True, "weeks": 1, "count": 3})
    assert view.btn_undo.isEnabled() and view.btn_auto.isEnabled()
    with (
        patch("ui.schedule_view.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes),
        patch("ui.schedule_auto.restore_snapshot") as restore,
        patch("ui.schedule_auto.ToastNotification"),
    ):
        view._on_undo()
    restore.assert_called_once_with(view.facade.schedule.db, "snap.db")
    from core.events import Event

    view.facade.events.emit.assert_any_call(Event.ASSIGNMENT_CHANGED)  # неделя и доска перечитаются
    assert not view.btn_undo.isEnabled()


def test_print_asks_weeks_then_printer_and_prints(schedule_view):
    """«🖨 Печать»: выбор недель как для PDF, системный диалог принтера, печать."""
    from PySide6.QtWidgets import QDialog

    view = schedule_view
    assert view.btn_print.text() == "🖨️ Печать"
    view.facade.print_schedule.return_value = True
    with (
        patch("ui.export_dialog.ExportDialog.exec", return_value=True),
        patch("ui.export_dialog.ExportDialog.get_selected_week_ids", return_value=[7, 8]),
        patch("PySide6.QtPrintSupport.QPrintDialog.exec", return_value=QDialog.DialogCode.Accepted),
        patch("ui.schedule_export.ToastNotification") as toast,
    ):
        view._on_print()
    week_ids, printer = view.facade.print_schedule.call_args.args
    assert week_ids == [7, 8] and printer is not None
    toast.show_toast.assert_called_once()

    view.facade.print_schedule.reset_mock()
    with (
        patch("ui.export_dialog.ExportDialog.exec", return_value=True),
        patch("ui.export_dialog.ExportDialog.get_selected_week_ids", return_value=[7]),
        patch("PySide6.QtPrintSupport.QPrintDialog.exec", return_value=QDialog.DialogCode.Rejected),
    ):
        view._on_print()
    view.facade.print_schedule.assert_not_called()  # отмена в диалоге принтера


def test_month_undo_takes_board_edits_first_then_snapshot(schedule_view):
    """↶ в месяце: сначала последняя правка на доске, потом откат к снимку «Авто»."""
    from PySide6.QtWidgets import QMessageBox

    view = schedule_view
    view.facade.get_month_board.return_value = None
    view.btn_month.setChecked(True)
    view._month_snapshot = ("snap.db", "12:00")
    board = view.month_board
    board._undo = [[{"id": 1, "participant_id": None, "assistant_id": None}]]
    board.history_changed.emit()
    assert view.btn_undo.isEnabled() and "доске" in view.btn_undo.toolTip()
    assert view.btn_redo.isVisible() or not view.isVisible()

    with patch("ui.schedule_auto.restore_snapshot") as restore:
        view._on_undo()
    view.facade.restore_people.assert_called_once()
    restore.assert_not_called()
    assert board.can_redo() and view.btn_redo.isEnabled()

    view._on_redo()
    assert view.facade.restore_people.call_count == 2

    board._undo.clear()
    board.history_changed.emit()
    with (
        patch("ui.schedule_view.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes),
        patch("ui.schedule_auto.restore_snapshot") as restore,
        patch("ui.schedule_auto.ToastNotification"),
    ):
        view._on_undo()
    restore.assert_called_once()
    assert not board.can_undo() and not board.can_redo()


def test_response_marks_and_header_counts(schedule_view, qapp):
    """Ответ на письмо: ✅/❌ в ячейке, «Не подтвердили» и «Не смогут» в шапке."""
    from ui.schedule_view import AssignmentCell

    cell = AssignmentCell(
        1,
        "Тарасюк Тимур",
        None,
        notif_status="success",
        notif_info={"status": "success", "response": "confirmed"},
        on_set_response=lambda v: None,
    )
    assert cell.text().endswith("✅") and "Подтвердил" in cell.toolTip()

    view = schedule_view
    view.current_notif_statuses = {
        1: {"status": "success", "response": None},
        2: {"status": "success", "response": "declined"},
        3: {"status": "success", "response": "confirmed"},
    }
    assignments = [
        {"status": "assigned", "participant_id": 1, "participant_name": "Первый"},
        {
            "status": "assigned",
            "participant_id": 2,
            "participant_name": "Второй",
            "assistant_id": 3,
            "assistant_name": "Третий",
        },
        {"status": "assigned", "participant_id": 4, "participant_name": "Не уведомлён"},
    ]
    assert view._response_counts(assignments) == (["Первый"], ["Второй"])


def test_notification_dialog_does_not_close_while_sending(qapp):
    """Крестик/Esc во время рассылки не уничтожает поток отправки вместе с окном."""
    from unittest.mock import Mock

    from ui.notification_dialog import NotificationDialog

    facade = Mock()
    facade.get_setting.return_value = ""
    facade.get_week_data.return_value = {}
    facade.get_last_notification.return_value = None
    facade.get_notification_preview.return_value = []
    dialog = NotificationDialog(facade, [10])
    dialog.show()
    dialog._worker = Mock()
    dialog._worker.isRunning.return_value = True
    dialog._sending = True
    with patch("ui.notification_dialog.QMessageBox.information") as info:
        dialog.reject()
    info.assert_called_once()
    assert dialog.isVisible()
    dialog._sending = False  # результат получен, поток дорабатывает
    dialog.reject()
    dialog._worker.wait.assert_called_once()
    assert not dialog.isVisible()


def test_narrow_toolbar_fits_when_tab_shown_later(schedule_view, qapp):
    """Размер задан, пока вкладка скрыта (планшет открывается на «Сегодня»):
    при показе кнопки всё равно ужимаются, а не обрезаются."""
    from PySide6.QtWidgets import QTabWidget, QWidget

    view = schedule_view
    tabs = QTabWidget()
    tabs.addTab(QWidget(), "Сегодня")
    tabs.addTab(view, "Расписание")
    tabs.resize(700, 600)
    tabs.show()
    qapp.processEvents()
    tabs.setCurrentWidget(view)
    qapp.processEvents()
    assert view.btn_auto.text() == view.AUTO_TEXT_SHORT
    assert view.btn_export_pdf.isHidden()
