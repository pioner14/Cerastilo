import logging
from datetime import date, datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.facade import ApplicationFacade
from core.styles import palette, register_theme_listener, unregister_theme_listener
from ui.participant_dialog import ParticipantEditDialog
from core.i18n import _

logger = logging.getLogger(__name__)

COL_NAME, COL_GENDER, COL_ROLE, COL_LAST, COL_TOTAL = range(5)
HEADERS = [_("ФИО"), _("Пол"), _("Роль"), _("Последнее"), _("Всего")]

# Сколько дней без заданий считается «давно» — такие даты подсвечиваются
STALE_AFTER_DAYS = 60

ROLE_NAMES = {
    "PUB": _("Возвещатель"),
    "RP": _("Возвещатель"),
    "MS": _("Помощник"),
    "E": _("Старейшина"),
    "publisher": _("Возвещатель"),
    "elder": _("Старейшина"),
    "ministerial_servant": _("Помощник"),
    None: _("Возвещатель"),
    "": _("Возвещатель"),
}

SORT_ROLE = Qt.ItemDataRole.UserRole + 1


class SortableItem(QTableWidgetItem):
    """Ячейка, которая сортируется по ключу в SORT_ROLE, а не по тексту.

    Иначе «14» оказывается раньше «2», а «02.11» раньше «21.04».
    """

    def __lt__(self, other):
        mine, theirs = self.data(SORT_ROLE), other.data(SORT_ROLE)
        if mine is not None and theirs is not None:
            return mine < theirs
        return super().__lt__(other)


def _set_bold(item):
    # QFont("") подменяет семейство шрифта — берём шрифт ячейки и меняем только жирность
    font = item.font()
    font.setBold(True)
    item.setFont(font)


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _unavailable_until(p_data, today):
    """Дата окончания недоступности, если человек недоступен сегодня, иначе None."""
    start = _as_date(p_data.get("unavailable_from"))
    end = _as_date(p_data.get("unavailable_to"))
    if end and (start is None or start <= today) and today <= end:
        return end
    return None


def _parse_date(text):
    try:
        return datetime.strptime(text, "%d.%m.%Y").date()
    except (TypeError, ValueError):
        return None


class ParticipantsView(QWidget):
    def __init__(self, facade: ApplicationFacade):
        super().__init__()
        self.facade = facade
        self.layout = QVBoxLayout(self)

        # Заголовок, поиск и действия
        self.toolbar_widget = QWidget()
        self.toolbar_widget.setObjectName("participantsToolbar")
        header_layout = QHBoxLayout(self.toolbar_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        self.title = QLabel(_("Возвещатели"))
        self.title.setObjectName("participantsTitle")
        header_layout.addWidget(self.title)
        header_layout.addSpacing(16)

        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("participantsSearch")
        self.search_edit.setPlaceholderText(_("🔍 Поиск по имени…"))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMaximumWidth(320)
        self.search_edit.textChanged.connect(self._apply_search)
        header_layout.addWidget(self.search_edit)

        header_layout.addStretch()

        self.btn_edit = QPushButton(_("✏️ Изменить"))
        self.btn_edit.setToolTip(_("Изменить выбранного (двойной клик или Enter)"))
        self.btn_edit.clicked.connect(self._edit_selected)
        header_layout.addWidget(self.btn_edit)

        self.btn_delete = QPushButton(_("🗑️ Удалить"))
        self.btn_delete.setObjectName("btnDelete")
        self.btn_delete.setToolTip(_("Удалить выбранного (Delete)"))
        self.btn_delete.clicked.connect(self._delete_selected)
        header_layout.addWidget(self.btn_delete)

        self.btn_absences = QPushButton(_("🏖️ Отсутствия"))
        self.btn_absences.setToolTip(_("Отпуска сразу нескольких участников одним списком"))
        self.btn_absences.clicked.connect(self.open_absences_dialog)
        header_layout.addWidget(self.btn_absences)

        self.btn_add = QPushButton(_("➕ Добавить"))
        self.btn_add.setObjectName("btnAdd")
        self.btn_add.clicked.connect(self.open_add_dialog)
        header_layout.addWidget(self.btn_add)

        self.layout.addWidget(self.toolbar_widget)

        # Таблица
        self.table = QTableWidget()
        self.table.setObjectName("participantsTable")
        self.table.setColumnCount(len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setMinimumSectionSize(70)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.cellDoubleClicked.connect(lambda *_: self._edit_selected())
        self.table.itemSelectionChanged.connect(self._update_action_buttons)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.layout.addWidget(self.table)

        for key in ("Return", "Enter"):
            QShortcut(QKeySequence(key), self.table, activated=self._edit_selected)
        QShortcut(QKeySequence("Delete"), self.table, activated=self._delete_selected)

        register_theme_listener(self._on_theme_changed)
        self.destroyed.connect(lambda *_, cb=self._on_theme_changed: unregister_theme_listener(cb))

        self.load_participants()

    # --- Загрузка ---

    def load_participants(self, scroll_to_id=None):
        participants = self.facade.get_all_participants()
        self.table.setSortingEnabled(False)  # Отключаем на время загрузки
        self.table.setRowCount(0)

        colors = palette()
        today = date.today()

        for row_idx, p_data in enumerate(participants):
            self.table.insertRow(row_idx)
            p_id = p_data["id"]

            name_item = QTableWidgetItem(str(p_data["name"]))
            name_item.setData(Qt.ItemDataRole.UserRole, p_id)
            self.table.setItem(row_idx, COL_NAME, name_item)

            gender_item = QTableWidgetItem(_("М") if p_data["gender"] == "male" else _("Ж"))
            gender_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row_idx, COL_GENDER, gender_item)

            role = ROLE_NAMES.get(p_data["service_type"], str(p_data["service_type"]))
            role_item = QTableWidgetItem(role)
            # по коду статуса, а не по надписи: надписи переводятся
            service = p_data["service_type"]
            if service in ("E", "elder"):
                role_item.setForeground(QColor(colors.text_heading))
                _set_bold(role_item)
            elif service in ("MS", "ministerial_servant"):
                role_item.setForeground(QColor(colors.text_heading))
            self.table.setItem(row_idx, COL_ROLE, role_item)

            last_text = p_data["last_assignment_date_real"] or "—"
            last_date = _parse_date(last_text)
            last_item = SortableItem(last_text)
            last_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            # без даты — в начало при сортировке по возрастанию
            last_item.setData(SORT_ROLE, last_date.toordinal() if last_date else 0)
            self.table.setItem(row_idx, COL_LAST, last_item)

            total = p_data["total_assignments"] or 0
            total_item = SortableItem(str(total))
            total_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            total_item.setData(SORT_ROLE, int(total))
            self.table.setItem(row_idx, COL_TOTAL, total_item)

            row_items = (name_item, gender_item, role_item, last_item, total_item)
            has_roles = bool(p_data.get("qualifications"))
            unavailable_to = _unavailable_until(p_data, today)

            if not has_roles:
                # Ничего не может быть назначено — приглушаем всю строку
                for item in row_items:
                    item.setForeground(QColor(colors.text_secondary))
                name_item.setToolTip(_("Нет ролей — в распределение не попадает"))
            elif unavailable_to:
                font = name_item.font()
                font.setItalic(True)
                name_item.setFont(font)
                name_item.setToolTip(
                    _("Недоступен до {unavailable_to:%d.%m.%Y}", unavailable_to=unavailable_to)
                )
            elif last_date is None or (today - last_date).days > STALE_AFTER_DAYS:
                # Есть роли, но давно (или ни разу) не было заданий
                last_item.setForeground(QColor(colors.text_warning))
                _set_bold(last_item)
                last_item.setToolTip(
                    _("Есть роли, но ещё не было заданий")
                    if last_date is None
                    else _(
                        "Есть роли, но давно не было заданий: {days} дн. назад",
                        days=(today - last_date).days,
                    )
                )

        self.table.setSortingEnabled(True)
        self.table.sortItems(COL_NAME, Qt.SortOrder.AscendingOrder)
        self.title.setText(_("Возвещатели · {n_participants}", n_participants=len(participants)))

        self._apply_search(self.search_edit.text())

        # Фокус на нужную строку (после сортировки!)
        if scroll_to_id:
            row = self._row_of(scroll_to_id)
            if row is not None:
                self.table.selectRow(row)
                self.table.scrollToItem(self.table.item(row, COL_NAME))

        self._update_action_buttons()

    def _on_theme_changed(self, _theme):
        """Цвета ролей и дат берутся из палитры — перерисовать таблицу."""
        self.load_participants(self.selected_participant_id())

    # --- Выбор и поиск ---

    def _row_of(self, p_id):
        for r in range(self.table.rowCount()):
            item = self.table.item(r, COL_NAME)
            if item and str(item.data(Qt.ItemDataRole.UserRole)) == str(p_id):
                return r
        return None

    def selected_participant_id(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.table.item(rows[0].row(), COL_NAME).data(Qt.ItemDataRole.UserRole)

    def _selected_name(self):
        rows = self.table.selectionModel().selectedRows()
        return self.table.item(rows[0].row(), COL_NAME).text() if rows else ""

    def _apply_search(self, text):
        needle = text.strip().lower()
        for r in range(self.table.rowCount()):
            name = self.table.item(r, COL_NAME).text().lower()
            self.table.setRowHidden(r, bool(needle) and needle not in name)

    def _update_action_buttons(self):
        has_selection = self.selected_participant_id() is not None
        self.btn_edit.setEnabled(has_selection)
        self.btn_delete.setEnabled(has_selection)

    def _show_context_menu(self, position):
        item = self.table.itemAt(position)
        if item is None:
            return
        self.table.selectRow(item.row())
        menu = QMenu(self)
        menu.addAction(_("✏️ Изменить"), self._edit_selected)
        menu.addSeparator()
        menu.addAction(_("🗑️ Удалить"), self._delete_selected)
        menu.exec(self.table.viewport().mapToGlobal(position))

    def _edit_selected(self):
        p_id = self.selected_participant_id()
        if p_id is not None:
            self.open_edit_dialog(p_id)

    def _delete_selected(self):
        p_id = self.selected_participant_id()
        if p_id is not None:
            self.confirm_delete(p_id, self._selected_name())

    # --- Действия ---

    def confirm_delete(self, p_id, p_name):
        reply = QMessageBox.question(
            self,
            _("Подтверждение"),
            _(
                "Вы уверены, что хотите удалить возвещателя {p_name}?\n\nИстория его назначений будет сохранена.",
                p_name=p_name,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            if self.facade.delete_participant(p_id):
                self.load_participants()

    def open_add_dialog(self):
        dialog = ParticipantEditDialog(self.facade, self)
        if dialog.exec():
            # Dialog handles saving via facade
            self.load_participants()

    def open_edit_dialog(self, p_id):
        dialog = ParticipantEditDialog(self.facade, self, participant_id=p_id)
        if dialog.exec():
            # Dialog handles saving via facade
            self.load_participants(scroll_to_id=p_id)
            self.offer_away_replacements(p_id)

    def open_absences_dialog(self) -> None:
        from ui.absences_dialog import AbsencesDialog

        dialog = AbsencesDialog(self.facade, self)
        if dialog.exec():
            self.load_participants()
            if dialog.changed_ids:
                self.offer_away_replacements(dialog.changed_ids)

    def offer_away_replacements(self, p_ids) -> None:
        """Отпуск одним окном: если у участника (или нескольких — список id)
        есть задания на неделях, когда его не будет, — показать их и
        предложить снять и подобрать замену."""
        p_ids = list(p_ids) if isinstance(p_ids, (list, tuple, set)) else [p_ids]
        items = []
        try:
            for p_id in p_ids:
                for item in self.facade.get_away_assignments(p_id):
                    items.append({**item, "who": self._name_of(p_id)})
        except Exception:
            logger.exception("Не удалось найти задания на время отсутствия")
            return
        if not items:
            return
        items.sort(key=lambda i: i["start_date"])
        several = len(p_ids) > 1
        lines = "\n".join(
            f"• {i['start_date'].strftime('%d.%m')} — {i['text']}"
            + (f" — {i['who']}" if several else "")
            + (_(" (напарник)") if i["role"] == "assistant" else "")
            for i in items
        )
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(_("Задания на время отсутствия"))
        box.setText(
            _("Задания на неделях, когда участников не будет:\n\n{lines}", lines=lines)
            if several
            else _(
                "Задания на неделях, когда участника не будет ({name}):\n\n{lines}",
                name=items[0]["who"],
                lines=lines,
            )
        )
        replace = box.addButton(_("Снять и подобрать замену"), QMessageBox.ButtonRole.AcceptRole)
        release = box.addButton(_("Только снять"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(_("Оставить как есть"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(replace)
        box.exec()
        clicked = box.clickedButton()
        if clicked not in (replace, release):
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = self.facade.replace_away_assignments(
                [{k: v for k, v in i.items() if k != "who"} for i in items], auto=clicked is replace
            )
        finally:
            QApplication.restoreOverrideCursor()
        if clicked is replace:
            done = "\n".join(
                f"• {r['start_date'].strftime('%d.%m')} — {r['text']}: "
                + (r["name"] or _("замены не нашлось, пункт пустой"))
                for r in result["replacements"]
            )
            QMessageBox.information(self, _("Замены"), _("Новые назначения:\n\n{done}", done=done))

    def _name_of(self, p_id) -> str:
        try:
            return (self.facade.get_participant(p_id) or {}).get("name") or ""
        except Exception:
            return ""
