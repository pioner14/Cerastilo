"""«🏖 Отсутствия»: отпуска нескольких участников одним списком."""

from datetime import date
from unittest.mock import MagicMock

from PySide6.QtWidgets import QComboBox, QMessageBox

from ui.absences_dialog import AbsencesDialog


def _facade():
    facade = MagicMock()
    facade.get_all_participants.return_value = [
        {
            "id": 1,
            "name": "Иванов",
            "unavailable_from": date(2030, 3, 1),
            "unavailable_to": date(2030, 3, 10),
        },
        {"id": 2, "name": "Петров", "unavailable_from": None, "unavailable_to": None},
        {"id": 3, "name": "Сидоров", "unavailable_from": "2030-04-01", "unavailable_to": None},
    ]
    return facade


def test_existing_absences_are_listed(qapp):
    dialog = AbsencesDialog(_facade())
    assert dialog.rows() == [
        (1, date(2030, 3, 1), date(2030, 3, 10)),
        (3, date(2030, 4, 1), date(2030, 4, 1)),
    ]


def test_save_sets_new_and_clears_removed(qapp):
    facade = _facade()
    dialog = AbsencesDialog(facade)
    dialog._table.removeRow(1)  # Сидоров — отпуск снимается
    dialog._add_empty_row()
    combo = dialog._table.cellWidget(1, 0)
    assert isinstance(combo, QComboBox)
    combo.setCurrentIndex(combo.findData(2))  # Петров — новый отпуск
    dialog._on_save()
    calls = [c.args for c in facade.set_unavailable.call_args_list]
    assert (3, None, None) in calls
    assert any(c[0] == 2 for c in calls)
    assert dialog.changed_ids == [2]  # Иванов не менялся


def test_duplicate_participant_is_rejected(qapp, monkeypatch):
    facade = _facade()
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warned.append(a[2]))
    dialog = AbsencesDialog(facade)
    dialog._add_empty_row()
    combo = dialog._table.cellWidget(2, 0)
    combo.setCurrentIndex(combo.findData(1))
    dialog._on_save()
    assert warned and facade.set_unavailable.call_count == 0
