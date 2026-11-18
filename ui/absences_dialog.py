"""«Отсутствия»: отпуска сразу нескольких участников одним списком.

Черновик — DeepSeek, проверен и поправлен. После сохранения участники с
новыми датами — в changed_ids (ui/participants_view.py предложит замены)."""

from datetime import date, datetime

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
)

from core.i18n import _


def _as_date(value):
    """date, datetime или строка ГГГГ-ММ-ДД → date (None — как есть)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


class AbsencesDialog(QDialog):
    def __init__(self, facade, parent=None):
        super().__init__(parent)

        self._facade = facade
        self._participants = list(facade.get_all_participants() or [])

        self._original = {}
        for p in self._participants:
            f = _as_date(p.get("unavailable_from"))
            t = _as_date(p.get("unavailable_to"))
            if f is None and t is None:
                continue
            if f is None:
                f = t
            if t is None:
                t = f
            self._original[p["id"]] = (f, t)

        self.changed_ids = []

        self.setWindowTitle(_("Отсутствия"))
        self.resize(640, 420)

        self._build_ui()
        self._populate()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        layout = QVBoxLayout(self)

        hint = QLabel(_("Кого не будет и когда. Строку можно удалить — отпуск снимется."))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._table = QTableWidget(0, 4, self)
        self._table.setHorizontalHeaderLabels(
            [
                _("Участник"),
                _("С"),
                _("По"),
                "",
            ]
        )
        self._table.verticalHeader().setVisible(False)

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(self._table, 1)

        add_row = QHBoxLayout()
        self._add_btn = QPushButton(_("➕ Добавить"))
        self._add_btn.clicked.connect(self._add_empty_row)
        add_row.addWidget(self._add_btn)
        add_row.addStretch(1)
        layout.addLayout(add_row)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self._save_btn = QPushButton(_("Сохранить"))
        self._save_btn.clicked.connect(self._on_save)
        self._cancel_btn = QPushButton(_("Отмена"))
        self._cancel_btn.clicked.connect(self.reject)
        bottom.addWidget(self._save_btn)
        bottom.addWidget(self._cancel_btn)
        layout.addLayout(bottom)

    # -------------------------------------------------------------- helpers

    def _make_combo(self, pid):
        combo = QComboBox()
        for p in self._participants:
            combo.addItem(p.get("name", ""), p["id"])
        idx = combo.findData(pid)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        return combo

    def _make_date_edit(self, d):
        edit = QDateEdit()
        edit.setCalendarPopup(True)
        edit.setDisplayFormat("dd.MM.yyyy")
        edit.setDate(QDate(d.year, d.month, d.day))
        return edit

    def _append_row(self, pid, d_from, d_to):
        row = self._table.rowCount()
        self._table.insertRow(row)

        self._table.setCellWidget(row, 0, self._make_combo(pid))
        self._table.setCellWidget(row, 1, self._make_date_edit(d_from))
        self._table.setCellWidget(row, 2, self._make_date_edit(d_to))

        del_btn = QPushButton("🗑️")
        del_btn.setToolTip(_("Удалить"))
        del_btn.clicked.connect(lambda _checked=False, b=del_btn: self._delete_row_by_widget(b))
        self._table.setCellWidget(row, 3, del_btn)
        # Высота строки по виджетам: по умолчанию строка ниже выпадающего
        # списка и полей дат, и имена обрезались сверху и снизу
        widgets = [self._table.cellWidget(row, col) for col in range(4)]
        self._table.setRowHeight(row, max(w.sizeHint().height() for w in widgets) + 6)

    def _delete_row_by_widget(self, widget):
        for row in range(self._table.rowCount()):
            if self._table.cellWidget(row, 3) is widget:
                self._table.removeRow(row)
                return

    def _populate(self):
        for pid, (d_from, d_to) in self._original.items():
            self._append_row(pid, d_from, d_to)

    def _add_empty_row(self):
        if not self._participants:
            return
        today = date.today()
        self._append_row(self._participants[0]["id"], today, today)

    # ----------------------------------------------------------- public API

    def rows(self):
        result = []
        for row in range(self._table.rowCount()):
            combo = self._table.cellWidget(row, 0)
            edit_from = self._table.cellWidget(row, 1)
            edit_to = self._table.cellWidget(row, 2)
            if (
                not isinstance(combo, QComboBox)
                or not isinstance(edit_from, QDateEdit)
                or not isinstance(edit_to, QDateEdit)
            ):
                continue
            pid = combo.currentData()
            qf = edit_from.date()
            qt = edit_to.date()
            result.append(
                (
                    pid,
                    date(qf.year(), qf.month(), qf.day()),
                    date(qt.year(), qt.month(), qt.day()),
                )
            )
        return result

    # --------------------------------------------------------------- save

    def _on_save(self):
        rows = self.rows()

        for _pid, d_from, d_to in rows:
            if d_from > d_to:
                QMessageBox.warning(
                    self,
                    _("Проверка"),
                    _("Дата начала не может быть позже даты окончания."),
                )
                return

        seen = set()
        for pid, _d_from, _d_to in rows:
            if pid in seen:
                QMessageBox.warning(
                    self,
                    _("Проверка"),
                    _("Участник не должен повторяться."),
                )
                return
            seen.add(pid)

        for pid in self._original:
            if pid not in seen:
                self._facade.set_unavailable(pid, None, None)

        self.changed_ids = []
        for pid, d_from, d_to in rows:
            self._facade.set_unavailable(pid, d_from, d_to)
            if self._original.get(pid) != (d_from, d_to):
                self.changed_ids.append(pid)

        self.accept()
