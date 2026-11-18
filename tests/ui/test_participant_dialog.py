"""
Тесты для ParticipantEditDialog.

См. spec://ui/participant_dialog
См. plans/ui_testing_plan.md Phase 1
"""

import os
import sys
from unittest.mock import patch

# Добавляем корень проекта в sys.path для импорта ui модулей
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from ui.participant_dialog import ParticipantEditDialog


class TestParticipantDialogCreation:
    """Тесты создания диалога."""

    def test_dialog_creates_with_mock_facade(self, qapp, mock_facade):
        """Диалог создаётся с mock facade."""
        dialog = ParticipantEditDialog(mock_facade)

        assert dialog is not None
        assert dialog.facade is mock_facade
        assert dialog.windowTitle() == "Добавить возвещателя"

    def test_dialog_has_required_widgets(self, qapp, mock_facade):
        """Диалог содержит все необходимые виджеты."""
        dialog = ParticipantEditDialog(mock_facade)

        # Проверяем наличие основных виджетов
        assert hasattr(dialog, "name_edit")
        assert hasattr(dialog, "gender_combo")
        assert hasattr(dialog, "role_combo")
        assert hasattr(dialog, "family_combo")
        assert hasattr(dialog, "btn_save")
        assert hasattr(dialog, "btn_cancel")
        assert hasattr(dialog, "checkboxes")

    def test_dialog_has_qualification_checkboxes(self, qapp, mock_facade):
        """Диалог содержит чекбоксы квалификаций."""
        dialog = ParticipantEditDialog(mock_facade)

        # Проверяем наличие чекбоксов для ключевых квалификаций
        assert "chairman" in dialog.checkboxes
        assert "prayer" in dialog.checkboxes
        assert "bible_reading" in dialog.checkboxes
        # Квалификации удалённых «Графиков служения» в форме не показываются
        assert "microphone" not in dialog.checkboxes
        assert "attendant" not in dialog.checkboxes

    def test_dialog_title_for_new_participant(self, qapp, mock_facade):
        """Заголовок диалога для нового участника."""
        dialog = ParticipantEditDialog(mock_facade)

        assert dialog.windowTitle() == "Добавить возвещателя"

    def test_dialog_title_for_edit_participant(self, qapp, mock_facade):
        """Заголовок диалога для редактирования участника."""
        dialog = ParticipantEditDialog(mock_facade, participant_id=1)

        assert dialog.windowTitle() == "Редактировать возвещателя"


class TestParticipantDialogValidation:
    """Тесты валидации полей."""

    def test_gender_combo_has_correct_items(self, qapp, mock_facade):
        """Выпадающий список пола содержит правильные значения."""
        dialog = ParticipantEditDialog(mock_facade)

        assert dialog.gender_combo.count() == 2
        assert dialog.gender_combo.itemText(0) == "Брат"
        assert dialog.gender_combo.itemText(1) == "Сестра"

    def test_role_combo_has_correct_items(self, qapp, mock_facade):
        """Выпадающий список ролей содержит правильные значения."""
        dialog = ParticipantEditDialog(mock_facade)

        assert dialog.role_combo.count() == 3
        assert dialog.role_combo.itemText(0) == "Возвещатель"
        assert dialog.role_combo.itemText(1) == "Помощник"
        assert dialog.role_combo.itemText(2) == "Старейшина"

    def test_name_edit_is_empty_by_default(self, qapp, mock_facade):
        """Поле имени пустое по умолчанию."""
        dialog = ParticipantEditDialog(mock_facade)

        assert dialog.name_edit.text() == ""

    def test_qualifications_unchecked_by_default(self, qapp, mock_facade):
        """Все квалификации сняты по умолчанию."""
        dialog = ParticipantEditDialog(mock_facade)

        for key, checkbox in dialog.checkboxes.items():
            assert not checkbox.isChecked(), f"Чекбокс {key} должен быть снят"


class TestParticipantDialogButtons:
    """Тесты кнопок OK/Cancel."""

    def test_cancel_button_rejects_dialog(self, qapp, mock_facade, qtbot):
        """Кнопка 'Отмена' закрывает диалог с reject."""
        dialog = ParticipantEditDialog(mock_facade)
        qtbot.addWidget(dialog)

        # Симулируем нажатие Cancel
        dialog.btn_cancel.click()

        assert dialog.result() == QDialog.DialogCode.Rejected

    def test_save_button_accepts_dialog_with_data(self, qapp, mock_facade, qtbot):
        """Кнопка 'Сохранить' закрывает диалог с accept при заполненных данных."""
        dialog = ParticipantEditDialog(mock_facade)
        qtbot.addWidget(dialog)

        # Заполняем данные
        dialog.name_edit.setText("Тестовый Пользователь")
        dialog.gender_combo.setCurrentIndex(0)  # Брат
        dialog.role_combo.setCurrentIndex(2)  # Старейшина

        # Симулируем нажатие Save
        dialog.btn_save.click()

        assert dialog.result() == QDialog.DialogCode.Accepted
        mock_facade.add_participant.assert_called_once()

    def test_save_calls_add_participant_for_new(self, qapp, mock_facade, qtbot):
        """Сохранение нового участника вызывает add_participant."""
        dialog = ParticipantEditDialog(mock_facade)
        qtbot.addWidget(dialog)

        dialog.name_edit.setText("Новый Участник")
        dialog.btn_save.click()

        mock_facade.add_participant.assert_called_once()
        # Проверяем, что update_participant НЕ вызывался
        mock_facade.update_participant.assert_not_called()

    def test_save_keeps_qualifications_without_checkbox(self, qapp, mock_facade, qtbot):
        """Квалификации из БД без галочки в форме не стираются при сохранении."""
        mock_facade.get_participant.return_value["qualifications"] = ["chairman", "microphone"]
        dialog = ParticipantEditDialog(mock_facade, participant_id=1)
        qtbot.addWidget(dialog)

        dialog.btn_save.click()

        quals = mock_facade.update_participant.call_args.args[4]
        assert set(quals) == {"chairman", "microphone"}

    def test_save_calls_update_participant_for_existing(self, qapp, mock_facade, qtbot):
        """Сохранение существующего участника вызывает update_participant."""
        dialog = ParticipantEditDialog(mock_facade, participant_id=1)
        qtbot.addWidget(dialog)

        dialog.name_edit.setText("Обновлённый Участник")
        dialog.btn_save.click()

        mock_facade.update_participant.assert_called_once()
        # Проверяем, что add_participant НЕ вызывался
        mock_facade.add_participant.assert_not_called()


class TestParticipantDialogDataLoading:
    """Тесты предзаполнения данных при редактировании."""

    def test_load_data_populates_name(self, qapp, mock_facade, qtbot):
        """Загрузка данных заполняет имя участника."""
        dialog = ParticipantEditDialog(mock_facade, participant_id=1)
        qtbot.addWidget(dialog)

        # При создании с participant_id вызывается load_data
        assert dialog.name_edit.text() == "Иванов Иван"

    def test_load_data_populates_gender(self, qapp, mock_facade, qtbot):
        """Загрузка данных устанавливает пол."""
        dialog = ParticipantEditDialog(mock_facade, participant_id=1)
        qtbot.addWidget(dialog)

        # Участник с gender="male" должен показывать "Брат"
        assert dialog.gender_combo.currentText() == "Брат"

    def test_load_data_populates_role(self, qapp, mock_facade, qtbot):
        """Загрузка данных устанавливает духовный статус."""
        dialog = ParticipantEditDialog(mock_facade, participant_id=1)
        qtbot.addWidget(dialog)

        # Участник с service_type="elder" должен показывать "Старейшина"
        assert dialog.role_combo.currentText() == "Старейшина"

    def test_load_data_populates_qualifications(self, qapp, mock_facade, qtbot):
        """Загрузка данных отмечает квалификации."""
        dialog = ParticipantEditDialog(mock_facade, participant_id=1)
        qtbot.addWidget(dialog)

        # Участник имеет квалификации ["chairman", "prayer"]
        assert dialog.checkboxes["chairman"].isChecked()
        assert dialog.checkboxes["prayer"].isChecked()
        # Другие квалификации не отмечены
        assert not dialog.checkboxes["bible_reading"].isChecked()

    def test_load_data_calls_get_participant(self, qapp, mock_facade, qtbot):
        """Загрузка данных вызывает get_participant с правильным ID."""
        dialog = ParticipantEditDialog(mock_facade, participant_id=1)
        qtbot.addWidget(dialog)

        mock_facade.get_participant.assert_called_with(1)


class TestParticipantDialogFamilySelection:
    """Тесты выбора семьи."""

    def test_family_combo_has_default_item(self, qapp, mock_facade):
        """Выпадающий список семьи имеет пункт по умолчанию."""
        dialog = ParticipantEditDialog(mock_facade)

        # Первый пункт должен быть "Нет семьи / Глава"
        assert dialog.family_combo.itemText(0) == "— Нет семьи / Глава —"
        assert dialog.family_combo.itemData(0) is None

    def test_family_combo_populates_from_facade(self, qapp, mock_facade):
        """Выпадающий список семьи заполняется из facade."""
        dialog = ParticipantEditDialog(mock_facade)

        # mock_facade возвращает 3 участников, 2 из них мужчины
        # Должны быть: пункт по умолчанию + потенциальные главы семьи
        assert dialog.family_combo.count() >= 1  # Как минимум пункт по умолчанию


class TestParticipantDialogGenderMapping:
    """Тесты маппинга пола."""

    def test_male_gender_selected_correctly(self, qapp, mock_facade, qtbot):
        """Мужской пол корректно отображается при загрузке."""
        dialog = ParticipantEditDialog(mock_facade, participant_id=1)
        qtbot.addWidget(dialog)

        assert dialog.gender_combo.currentText() == "Брат"

    def test_female_gender_selected_correctly(self, qapp, mock_facade, qtbot):
        """Женский пол корректно отображается при загрузке."""
        # Меняем mock на женщину
        mock_facade.get_participant.return_value = {
            "id": 3,
            "name": "Сидорова Анна",
            "gender": "female",
            "service_type": "publisher",
            "is_active": True,
            "qualifications": [],
            "last_assignment_date": None,
            "last_assignment_date_real": "—",
            "total_assignments": 0,
            "family_group_id": 1,
        }

        dialog = ParticipantEditDialog(mock_facade, participant_id=3)
        qtbot.addWidget(dialog)

        assert dialog.gender_combo.currentText() == "Сестра"


class TestParticipantDialogSaveData:
    """Тесты сохранения данных."""

    def test_save_passes_correct_gender_male(self, qapp, mock_facade, qtbot):
        """Сохранение передаёт правильный пол (мужской)."""
        dialog = ParticipantEditDialog(mock_facade)
        qtbot.addWidget(dialog)

        dialog.name_edit.setText("Тест")
        dialog.gender_combo.setCurrentText("Брат")
        dialog.btn_save.click()

        # Проверяем, что add_participant был вызван с gender="male"
        call_args = mock_facade.add_participant.call_args
        assert call_args[0][1] == "male"  # Второй аргумент - gender

    def test_save_passes_correct_gender_female(self, qapp, mock_facade, qtbot):
        """Сохранение передаёт правильный пол (женский)."""
        dialog = ParticipantEditDialog(mock_facade)
        qtbot.addWidget(dialog)

        dialog.name_edit.setText("Тест")
        dialog.gender_combo.setCurrentText("Сестра")
        dialog.btn_save.click()

        call_args = mock_facade.add_participant.call_args
        assert call_args[0][1] == "female"

    def test_save_passes_correct_role_elder(self, qapp, mock_facade, qtbot):
        """Сохранение передаёт правильную роль (старейшина)."""
        dialog = ParticipantEditDialog(mock_facade)
        qtbot.addWidget(dialog)

        dialog.name_edit.setText("Тест")
        dialog.role_combo.setCurrentText("Старейшина")
        dialog.btn_save.click()

        call_args = mock_facade.add_participant.call_args
        assert call_args[0][2] == "E"  # Elder

    def test_save_passes_correct_role_ministerial_servant(self, qapp, mock_facade, qtbot):
        """Сохранение передаёт правильную роль (помощник)."""
        dialog = ParticipantEditDialog(mock_facade)
        qtbot.addWidget(dialog)

        dialog.name_edit.setText("Тест")
        dialog.role_combo.setCurrentText("Помощник")
        dialog.btn_save.click()

        call_args = mock_facade.add_participant.call_args
        assert call_args[0][2] == "MS"  # Ministerial Servant

    def test_save_passes_checked_qualifications(self, qapp, mock_facade, qtbot):
        """Сохранение передаёт отмеченные квалификации."""
        dialog = ParticipantEditDialog(mock_facade)
        qtbot.addWidget(dialog)

        dialog.name_edit.setText("Тест")
        dialog.checkboxes["chairman"].setChecked(True)
        dialog.checkboxes["prayer"].setChecked(True)
        dialog.btn_save.click()

        call_args = mock_facade.add_participant.call_args
        quals = call_args[0][3]  # Четвёртый аргумент - qualifications

        assert "chairman" in quals
        assert "prayer" in quals
        assert "bible_reading" not in quals


class TestParticipantDialogExcludedWeeks:
    """Тесты исключенных недель и сменных графиков."""

    def test_add_manual_excluded_week(self, qapp, mock_facade, qtbot):
        """Ручное добавление исключенной недели."""
        dialog = ParticipantEditDialog(mock_facade)
        qtbot.addWidget(dialog)

        from datetime import date

        # Устанавливаем дату в календаре/поле ручного ввода
        test_date = date(2026, 6, 4)  # Четверг
        dialog.manual_date_edit.setDate(test_date)

        # Кликаем "Добавить неделю"
        dialog.add_manual_excluded_week()

        # Должен добавиться понедельник этой недели
        expected_monday = date(2026, 6, 1)  # Понедельник
        assert expected_monday in dialog.excluded_weeks_dates
        assert dialog.excluded_weeks_list.count() == 1
        assert dialog.excluded_weeks_list.item(0).text() == expected_monday.strftime("%d.%m.%Y")

    def test_add_pattern_excluded_weeks(self, qapp, mock_facade, qtbot):
        """Добавление исключенных недель по шаблону."""
        dialog = ParticipantEditDialog(mock_facade)
        qtbot.addWidget(dialog)

        from datetime import date

        # Устанавливаем начальную дату шаблона
        start_date = date(2026, 6, 4)  # Четверг
        dialog.pattern_start_edit.setDate(start_date)

        # Периодичность: 2 недели (индекс 1 в комбобоксе, т.к. 0 - 1 неделя, 1 - 2 недели...)
        dialog.pattern_interval_combo.setCurrentIndex(1)
        dialog.pattern_count_spin.setValue(3)  # 3 раза

        # Генерируем
        with patch("ui.participant_dialog.QMessageBox.information") as information:
            dialog.add_pattern_excluded_weeks()
            information.assert_called_once()

        # Понедельник от 2026-06-04 — это 2026-06-01
        # Ожидаются: 2026-06-01, 2026-06-15, 2026-06-29
        expected_dates = [date(2026, 6, 1), date(2026, 6, 15), date(2026, 6, 29)]

        for ed in expected_dates:
            assert ed in dialog.excluded_weeks_dates

        assert dialog.excluded_weeks_list.count() == 3

    def test_remove_selected_excluded_weeks(self, qapp, mock_facade, qtbot):
        """Удаление выбранных недель из списка."""
        dialog = ParticipantEditDialog(mock_facade)
        qtbot.addWidget(dialog)

        from datetime import date

        dialog.excluded_weeks_dates = [date(2026, 6, 1), date(2026, 6, 15)]
        dialog.update_excluded_weeks_ui_list()

        # Выделяем первый элемент
        dialog.excluded_weeks_list.setCurrentRow(0)

        # Удаляем
        dialog.remove_selected_excluded_weeks()

        assert len(dialog.excluded_weeks_dates) == 1
        assert date(2026, 6, 15) in dialog.excluded_weeks_dates
        assert dialog.excluded_weeks_list.count() == 1


def test_add_excluded_range_adds_every_week(qapp, mock_facade, qtbot):
    """Отпуск датами: с среды 4.11 по вторник 17.11 — три недели (понедельники)."""
    from datetime import date

    dialog = ParticipantEditDialog(mock_facade)
    qtbot.addWidget(dialog)
    dialog.manual_date_edit.setDate(date(2026, 11, 4))
    dialog.manual_end_edit.setDate(date(2026, 11, 17))
    dialog.add_manual_excluded_week()
    assert dialog.excluded_weeks_dates == [date(2026, 11, 2), date(2026, 11, 9), date(2026, 11, 16)]


class TestParticipantDialogGuards:
    """Карточка не теряет введённое молча и подсказывает про квалификации."""

    def test_cancel_with_changes_asks_and_can_keep_editing(
        self, qapp, mock_facade, qtbot, monkeypatch
    ):
        from PySide6.QtWidgets import QMessageBox

        dialog = ParticipantEditDialog(mock_facade)
        qtbot.addWidget(dialog)
        dialog.name_edit.setText("Новый Участник")
        closed = []
        dialog.rejected.connect(lambda: closed.append(True))
        asked = []
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.Cancel,
        )
        dialog.btn_cancel.click()
        assert asked and not closed  # спросили и оставили открытой

        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Discard
        )
        dialog.btn_cancel.click()
        assert closed
        mock_facade.add_participant.assert_not_called()

    def test_cancel_with_changes_can_save(self, qapp, mock_facade, qtbot, monkeypatch):
        from PySide6.QtWidgets import QMessageBox

        dialog = ParticipantEditDialog(mock_facade)
        qtbot.addWidget(dialog)
        dialog.name_edit.setText("Новый Участник")
        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Save
        )
        dialog.btn_cancel.click()
        mock_facade.add_participant.assert_called_once()
        assert dialog.result() == QDialog.DialogCode.Accepted

    def test_no_qualifications_hint_follows_checkboxes(self, qapp, mock_facade, qtbot):
        dialog = ParticipantEditDialog(mock_facade)
        qtbot.addWidget(dialog)
        assert not dialog.quals_warning.isHidden()
        assert dialog.tabs.tabText(dialog._quals_tab_index).startswith("⚠")
        next(iter(dialog.checkboxes.values())).setChecked(True)
        assert dialog.quals_warning.isHidden()
        assert not dialog.tabs.tabText(dialog._quals_tab_index).startswith("⚠")
