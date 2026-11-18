"""
Тесты для ExportDialog.

См. spec://ui/dialogs#ExportDialog
См. plans/ui_testing_plan.md Phase 2
"""

import os
import sys

# Добавляем корень проекта в sys.path для импорта ui модулей
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest
from PySide6.QtWidgets import QPushButton, QRadioButton, QCheckBox, QMessageBox, QLabel
from PySide6.QtCore import Qt

from ui.export_dialog import ExportDialog


# === Fixture с тестовыми данными ===


@pytest.fixture
def sample_weeks_data():
    """Пример данных недель для диалога."""
    return [
        {
            "month": "Март 2026",
            "weeks": [
                {"id": 1, "title": "3-9 марта", "bible_reading": "Матфея 5-7"},
                {"id": 2, "title": "10-16 марта", "bible_reading": "Матфея 8-10"},
                {"id": 3, "title": "17-23 марта", "bible_reading": None},
            ],
        },
        {
            "month": "Апрель 2026",
            "weeks": [
                {"id": 4, "title": "31 марта - 6 апреля", "bible_reading": "Матфея 11-13"},
                {"id": 5, "title": "7-13 апреля", "bible_reading": "Матфея 14-16"},
            ],
        },
    ]


class TestExportDialogInit:
    """Тесты инициализации диалога."""

    def test_dialog_creates_with_weeks_data(self, qapp, sample_weeks_data):
        """Диалог создаётся с данными недель."""
        dialog = ExportDialog(sample_weeks_data)

        assert dialog is not None
        assert len(dialog.checkboxes) == 5  # 5 недель в данных

    def test_dialog_has_correct_title(self, qapp, sample_weeks_data):
        """Диалог имеет правильный заголовок."""
        dialog = ExportDialog(sample_weeks_data)

        assert dialog.windowTitle() == "Выбор недель для экспорта"

    def test_dialog_has_minimum_size(self, qapp, sample_weeks_data):
        """Диалог имеет минимальный размер."""
        dialog = ExportDialog(sample_weeks_data)

        assert dialog.minimumWidth() == 420
        assert dialog.minimumHeight() == 540

    def test_dialog_has_export_button(self, qapp, sample_weeks_data):
        """Диалог имеет кнопку экспорта."""
        dialog = ExportDialog(sample_weeks_data)

        export_btn = dialog.findChild(QPushButton, "")
        # Ищем кнопку по тексту
        export_buttons = [
            btn for btn in dialog.findChildren(QPushButton) if btn.text() == "📄 Word (DOCX)"
        ]
        assert len(export_buttons) == 1

    def test_dialog_has_cancel_button(self, qapp, sample_weeks_data):
        """Диалог имеет кнопку отмены."""
        dialog = ExportDialog(sample_weeks_data)

        cancel_buttons = [btn for btn in dialog.findChildren(QPushButton) if btn.text() == "Отмена"]
        assert len(cancel_buttons) == 1


class TestExportDialogCheckboxes:
    """Тесты чекбоксов недель."""

    def test_checkboxes_created_for_all_weeks(self, qapp, sample_weeks_data):
        """Чекбоксы созданы для всех недель."""
        dialog = ExportDialog(sample_weeks_data)

        assert len(dialog.checkboxes) == 5

    def test_checkbox_displays_week_title(self, qapp, sample_weeks_data):
        """Чекбокс отображает заголовок недели."""
        dialog = ExportDialog(sample_weeks_data)

        first_checkbox = dialog.checkboxes[0]
        assert "3-9 марта" in first_checkbox.text()

    def test_checkbox_displays_bible_reading(self, qapp, sample_weeks_data):
        """Чекбокс отображает чтение Библии в скобках."""
        dialog = ExportDialog(sample_weeks_data)

        first_checkbox = dialog.checkboxes[0]
        assert "(Матфея 5-7)" in first_checkbox.text()

    def test_checkbox_without_bible_reading(self, qapp, sample_weeks_data):
        """Чекбокс без чтения Библии не показывает скобки."""
        dialog = ExportDialog(sample_weeks_data)

        # Третья неделя без bible_reading
        third_checkbox = dialog.checkboxes[2]
        assert "()" not in third_checkbox.text()

    def test_checkbox_has_week_id_property(self, qapp, sample_weeks_data):
        """Чекбокс имеет свойство week_id."""
        dialog = ExportDialog(sample_weeks_data)

        first_checkbox = dialog.checkboxes[0]
        assert first_checkbox.property("week_id") == 1

    def test_checkboxes_unchecked_by_default(self, qapp, sample_weeks_data):
        """Чекбоксы не отмечены по умолчанию."""
        dialog = ExportDialog(sample_weeks_data)

        for cb in dialog.checkboxes:
            assert not cb.isChecked()


class TestExportDialogDefaultWeek:
    """Тесты выбора недели по умолчанию."""

    def test_default_week_checked(self, qapp, sample_weeks_data):
        """Неделя по умолчанию отмечена."""
        dialog = ExportDialog(sample_weeks_data, default_week_id=3)

        # Третья неделя должна быть отмечена
        assert dialog.checkboxes[2].isChecked()

    def test_other_weeks_unchecked(self, qapp, sample_weeks_data):
        """Другие недели не отмечены."""
        dialog = ExportDialog(sample_weeks_data, default_week_id=3)

        # Только третья неделя отмечена
        for i, cb in enumerate(dialog.checkboxes):
            if i != 2:
                assert not cb.isChecked()

    def test_default_week_with_string_id(self, qapp, sample_weeks_data):
        """Неделя по умолчанию работает со строковым ID."""
        dialog = ExportDialog(sample_weeks_data, default_week_id="3")

        assert dialog.checkboxes[2].isChecked()


class TestExportDialogMonthLabels:
    """Тесты меток месяцев."""

    def test_month_labels_displayed(self, qapp, sample_weeks_data):
        """Метки месяцев отображаются."""
        dialog = ExportDialog(sample_weeks_data)

        # Ищем QLabel с текстом месяца
        labels = [
            lbl
            for lbl in dialog.findChildren(QLabel)
            if "Март 2026" in lbl.text() or "Апрель 2026" in lbl.text()
        ]
        assert len(labels) >= 2


class TestExportDialogSelectButtons:
    """Тесты кнопок выбора."""

    def test_select_all_button_exists(self, qapp, sample_weeks_data):
        """Кнопка «Выбрать все» существует."""
        dialog = ExportDialog(sample_weeks_data)

        select_all_btn = [
            btn for btn in dialog.findChildren(QPushButton) if btn.text() == "Выбрать все"
        ]
        assert len(select_all_btn) == 1

    def test_select_none_button_exists(self, qapp, sample_weeks_data):
        """Кнопка «Снять все» существует."""
        dialog = ExportDialog(sample_weeks_data)

        select_none_btn = [
            btn for btn in dialog.findChildren(QPushButton) if btn.text() == "Снять все"
        ]
        assert len(select_none_btn) == 1

    def test_select_all_checks_all_boxes(self, qapp, sample_weeks_data, qtbot):
        """Кнопка «Выбрать все» отмечает все чекбоксы."""
        dialog = ExportDialog(sample_weeks_data)
        qtbot.addWidget(dialog)

        select_all_btn = [
            btn for btn in dialog.findChildren(QPushButton) if btn.text() == "Выбрать все"
        ][0]
        select_all_btn.click()

        for cb in dialog.checkboxes:
            assert cb.isChecked()

    def test_select_none_unchecks_all_boxes(self, qapp, sample_weeks_data, qtbot):
        """Кнопка «Снять все» снимает все чекбоксы."""
        dialog = ExportDialog(sample_weeks_data, default_week_id=1)
        qtbot.addWidget(dialog)

        # Сначала выбираем все
        select_all_btn = [
            btn for btn in dialog.findChildren(QPushButton) if btn.text() == "Выбрать все"
        ][0]
        select_all_btn.click()

        # Затем снимаем все
        select_none_btn = [
            btn for btn in dialog.findChildren(QPushButton) if btn.text() == "Снять все"
        ][0]
        select_none_btn.click()

        for cb in dialog.checkboxes:
            assert not cb.isChecked()


class TestExportDialogGetExportMode:
    """Тест режима экспорта — всегда compact_modern."""

    def test_get_export_mode_always_compact_modern(self, qapp, sample_weeks_data):
        """get_export_mode всегда возвращает compact_modern (единственный формат)."""
        dialog = ExportDialog(sample_weeks_data)

        assert dialog.get_export_mode() == "compact_modern"

    def test_no_format_radio_buttons(self, qapp, sample_weeks_data):
        """В диалоге нет радиокнопок выбора формата."""
        from PySide6.QtWidgets import QRadioButton, QGroupBox

        dialog = ExportDialog(sample_weeks_data)

        radio_buttons = dialog.findChildren(QRadioButton)
        assert len(radio_buttons) == 0, "Радиокнопки выбора формата удалены"

        format_groups = [
            grp for grp in dialog.findChildren(QGroupBox) if grp.title() == "Формат экспорта"
        ]
        assert len(format_groups) == 0, "Группа выбора формата удалена"


class TestExportDialogExport:
    """Тесты экспорта."""

    def test_export_with_no_selection_shows_warning(
        self, qapp, sample_weeks_data, qtbot, monkeypatch
    ):
        """Экспорт без выбора показывает предупреждение."""
        dialog = ExportDialog(sample_weeks_data)
        qtbot.addWidget(dialog)

        # Флаг для проверки вызова QMessageBox
        warning_called = []
        original_warning = QMessageBox.warning
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda *args: warning_called.append(True) or QMessageBox.StandardButton.Ok,
        )

        # Находим кнопку экспорта и нажимаем
        export_btn = [
            btn for btn in dialog.findChildren(QPushButton) if btn.text() == "📄 Word (DOCX)"
        ][0]
        export_btn.click()

        assert warning_called, "QMessageBox.warning должен быть вызван"

    def test_export_with_selection_accepts(self, qapp, sample_weeks_data, qtbot):
        """Экспорт с выбором закрывает диалог с accept."""
        dialog = ExportDialog(sample_weeks_data)
        qtbot.addWidget(dialog)

        # Выбираем первую неделю
        dialog.checkboxes[0].setChecked(True)

        # Находим кнопку экспорта и нажимаем
        export_btn = [
            btn for btn in dialog.findChildren(QPushButton) if btn.text() == "📄 Word (DOCX)"
        ][0]
        export_btn.click()

        from PySide6.QtWidgets import QDialog

        assert dialog.result() == QDialog.DialogCode.Accepted

    def test_export_collects_selected_weeks(self, qapp, sample_weeks_data, qtbot):
        """Экспорт собирает выбранные недели."""
        dialog = ExportDialog(sample_weeks_data)
        qtbot.addWidget(dialog)

        # Выбираем недели 1 и 3
        dialog.checkboxes[0].setChecked(True)
        dialog.checkboxes[2].setChecked(True)

        export_btn = [
            btn for btn in dialog.findChildren(QPushButton) if btn.text() == "📄 Word (DOCX)"
        ][0]
        export_btn.click()

        selected = dialog.get_selected_week_ids()
        assert 1 in selected
        assert 3 in selected
        assert len(selected) == 2


class TestExportDialogCancel:
    """Тесты отмены."""

    def test_cancel_rejects_dialog(self, qapp, sample_weeks_data, qtbot):
        """Кнопка «Отмена» закрывает диалог с reject."""
        dialog = ExportDialog(sample_weeks_data)
        qtbot.addWidget(dialog)

        cancel_btn = [btn for btn in dialog.findChildren(QPushButton) if btn.text() == "Отмена"][0]
        cancel_btn.click()

        from PySide6.QtWidgets import QDialog

        assert dialog.result() == QDialog.DialogCode.Rejected


class TestExportDialogEmpty:
    """Тесты пустых данных."""

    def test_dialog_with_empty_weeks(self, qapp):
        """Диалог с пустыми данными недель."""
        dialog = ExportDialog([])

        assert dialog is not None
        assert len(dialog.checkboxes) == 0

    def test_dialog_with_single_week(self, qapp):
        """Диалог с одной неделей."""
        single_week = [
            {
                "month": "Март 2026",
                "weeks": [{"id": 1, "title": "3-9 марта", "bible_reading": "Матфея 5-7"}],
            }
        ]

        dialog = ExportDialog(single_week)

        assert len(dialog.checkboxes) == 1
        assert dialog.checkboxes[0].property("week_id") == 1


class TestExportDialogButtons:
    """Набор кнопок внизу: все форматы, один формат или одна кнопка подтверждения."""

    @staticmethod
    def _action_texts(dialog):
        return [
            b.text()
            for b in dialog.findChildren(QPushButton)
            if b.text() not in ("Отмена", "Выбрать все", "Снять все")
        ]

    def test_default_shows_all_formats(self, qapp, sample_weeks_data):
        dialog = ExportDialog(sample_weeks_data)

        texts = self._action_texts(dialog)
        assert len(texts) == 3

    def test_single_format(self, qapp, sample_weeks_data):
        dialog = ExportDialog(sample_weeks_data, default_week_id=1, formats=("pdf",))

        texts = self._action_texts(dialog)
        assert texts == ["📕 PDF"]
        dialog.findChildren(QPushButton)[-1].click()
        assert dialog.get_selected_format() == "pdf"
        assert dialog.get_selected_week_ids() == [1]

    def test_confirm_text_replaces_format_buttons(self, qapp, sample_weeks_data):
        dialog = ExportDialog(sample_weeks_data, default_week_id=2, confirm_text="Далее →")

        assert self._action_texts(dialog) == ["Далее →"]
        dialog.findChildren(QPushButton)[-1].click()
        assert dialog.get_selected_week_ids() == [2]
