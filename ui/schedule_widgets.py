"""Виджеты вкладки «Расписание»: клетка назначения, диалоги выбора
участника, таблица с перетаскиванием. Вынесены из ui/schedule_view.py."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
)
from ui.candidates import _hint_icon, by_rest, list_candidates
from core.i18n import _


# Отметки ответа участника на уведомление: в ячейке и в подсказке
RESPONSE_MARKS = {"confirmed": "  ✅", "declined": "  ❌"}
RESPONSE_TEXTS = {"confirmed": _("✅ Подтвердил задание"), "declined": _("❌ Ответил: не сможет")}


class AssignmentCell(QPushButton):
    """Кликабельная ячейка для назначения участника."""

    def __init__(
        self,
        assignment_id,
        participant_name,
        on_click,
        role="participant",
        has_conflict=False,
        notif_status=None,
        notif_info=None,
        on_open_log=None,
        on_send_email=None,
        on_clear=None,
        on_set_response=None,
    ):
        display_text = participant_name or "—"
        if has_conflict:
            display_text = "⚠️ " + display_text

        # Добавляем иконку статуса уведомления
        if notif_status == "success":
            display_text += "  ✉️"
        elif notif_status == "error":
            display_text += "  ⚠️"
        # Ответ участника на письмо (core/notification_replies.py)
        response = (notif_info or {}).get("response")
        display_text += RESPONSE_MARKS.get(response, "")

        super().__init__(display_text)
        self.assignment_id = assignment_id
        self.role = role
        self.on_click_callback = on_click
        self.on_open_log = on_open_log
        self.on_send_email = on_send_email
        self.on_clear = on_clear
        self.on_set_response = on_set_response
        self.response = response
        self.participant_name = participant_name
        self.notif_info = notif_info

        self.setMinimumWidth(130)
        self.setMinimumHeight(26)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # Tooltip с информацией об уведомлении
        if notif_status == "success" and notif_info:
            sent_at = notif_info.get("sent_at")
            subject = notif_info.get("subject") or ""
            date_str = ""
            if sent_at:
                try:
                    if hasattr(sent_at, "strftime"):
                        date_str = sent_at.strftime("%d.%m.%Y %H:%M")
                    else:
                        from datetime import datetime as _dt

                        date_str = _dt.fromisoformat(str(sent_at)).strftime("%d.%m.%Y %H:%M")
                except Exception:
                    date_str = str(sent_at)
            tip = _("✉️ Уведомление отправлено {date_str}", date_str=date_str)
            if subject:
                tip += _("\nТема: {subject}", subject=subject)
            tip += _("\n\n(Правый клик или нажатие — меню: заменить, письмо, очистить)")
            self.setToolTip(tip)
        elif notif_status == "error" and notif_info:
            err = notif_info.get("error") or _("Неизвестная ошибка")
            sent_at = notif_info.get("sent_at")
            subject = notif_info.get("subject") or ""
            date_str = ""
            if sent_at:
                try:
                    if hasattr(sent_at, "strftime"):
                        date_str = sent_at.strftime("%d.%m.%Y %H:%M")
                    else:
                        from datetime import datetime as _dt

                        date_str = _dt.fromisoformat(str(sent_at)).strftime("%d.%m.%Y %H:%M")
                except Exception:
                    date_str = str(sent_at)
            tip = _("⚠️ Ошибка отправки {date_str}\n{err}", date_str=date_str, err=err)
            if subject:
                tip += _("\nТема: {subject}", subject=subject)
            tip += _("\n\n(Правый клик или нажатие — меню: заменить, письмо, очистить)")
            self.setToolTip(tip)
        elif participant_name and participant_name != "—":
            self.setToolTip(
                _(
                    "{participant_name}\n\n(Правый клик или нажатие — меню: заменить, письмо, очистить)",
                    participant_name=participant_name,
                )
            )
        if response in RESPONSE_TEXTS:
            self.setToolTip(f"{RESPONSE_TEXTS[response]}\n{self.toolTip()}")

        # Theme-aware styling via objectName (styles in QSS files)
        # Статус уведомления заливает ячейку (как на доске месяца): отказ — красным
        has_name = bool(participant_name)
        if has_conflict or (has_name and response == "declined"):
            self.setObjectName("assignmentCellConflict")
        elif has_name and response == "confirmed":
            self.setObjectName("assignmentCellConfirmed")
        elif has_name and notif_status == "success":
            self.setObjectName("assignmentCellWaiting")
        elif has_name:
            self.setObjectName("assignmentCellFilled")
        else:
            self.setObjectName("assignmentCellEmpty")

        self.clicked.connect(self._on_click)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _has_menu(self) -> bool:
        return bool(
            self.participant_name and (self.on_send_email or self.on_open_log or self.on_clear)
        )

    def _on_click(self):
        # Назначенный участник: меню (заменить / письмо / очистить) — так оно
        # доступно и на планшете, где нет правого клика. Пусто — сразу выбор.
        if self._has_menu():
            self._show_context_menu(self.rect().bottomLeft())
        else:
            self._choose()

    def _choose(self):
        if self.on_click_callback and self.assignment_id:
            self.on_click_callback(self.assignment_id, self.role)

    def _show_context_menu(self, pos):
        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        actions = {}
        if self.on_click_callback and self.assignment_id:
            choose_action = QAction(_("👤 Выбрать / заменить…"), self)
            actions[choose_action] = self._choose
            menu.addAction(choose_action)

        if self.on_send_email:
            email_action = QAction(_("✉️ Написать / отправить email..."), self)
            actions[email_action] = self.on_send_email
            menu.addAction(email_action)

        if self.on_set_response:
            menu.addSeparator()
            for value, title in (
                ("confirmed", _("✅ Подтвердил")),
                ("declined", _("❌ Не сможет")),
            ):
                action = QAction(title, self)
                action.setCheckable(True)
                action.setChecked(self.response == value)
                actions[action] = lambda v=value: self.on_set_response(
                    None if self.response == v else v
                )
                menu.addAction(action)

        if self.on_open_log:
            log_action = QAction(_("📋 Открыть журнал уведомлений"), self)
            actions[log_action] = self.on_open_log
            menu.addAction(log_action)

        if self.on_clear and self.participant_name:
            menu.addSeparator()
            clear_action = QAction(_("🗑️ Очистить"), self)
            actions[clear_action] = self.on_clear
            menu.addAction(clear_action)

        if actions:
            menu.triggered.connect(lambda action: actions[action]() if action in actions else None)
            menu.popup(self.mapToGlobal(pos))


class ParticipantSelectDialog(QDialog):
    """Диалог выбора участника с фильтрацией по полу и квалификации."""

    def __init__(
        self, parent, facade, assignment_id=None, role="participant", title=_("Выбор участника")
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(300)
        self.facade = facade
        self.assignment_id = assignment_id
        self.role = role

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(_("Участник:")))

        assignment = facade.get_assignment(assignment_id) if assignment_id else None

        # Поиск по имени: при 60 участниках прокручивать список долго
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("🔍 Поиск по имени…"))
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)

        self.combo = QComboBox()
        # Фильтры (пол, квалификация, напарник) и подсказки — ui/candidates.py;
        # порядок как на доске месяца: кто дольше не выступал (новые) — сверху
        self._candidates = by_rest(list_candidates(facade, assignment_id, role))
        self._fill_combo("")
        layout.addWidget(self.combo)
        self.search.textChanged.connect(self._on_search)

        # Сразу выбираем того, кто уже назначен: иначе OK без выбора стирает назначение
        if assignment_id and assignment:
            current_id = assignment.get("assistant_id" if role == "assistant" else "participant_id")
            index = self.combo.findData(current_id) if current_id else -1
            if index >= 0:
                self.combo.setCurrentIndex(index)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _fill_combo(self, text: str) -> None:
        needle = text.strip().casefold()
        self.combo.clear()
        self.combo.addItem(_("— Не назначен —"), None)
        for c in self._candidates:
            if needle and needle not in c["name"].casefold():
                continue
            self.combo.addItem(_hint_icon(c["kind"]), f"{c['name']}  —  {c['hint']}", c["id"])
            self.combo.setItemData(
                self.combo.count() - 1, c["tooltip"], Qt.ItemDataRole.ToolTipRole
            )

    def _on_search(self, text: str) -> None:
        """Отфильтровать список; если кто-то нашёлся — сразу выбрать первого,
        чтобы хватило набрать фамилию и нажать Enter."""
        current = self.combo.currentData()
        self._fill_combo(text)
        index = self.combo.findData(current) if current is not None else -1
        if index >= 0:
            self.combo.setCurrentIndex(index)
        elif text.strip() and self.combo.count() > 1:
            self.combo.setCurrentIndex(1)

    def get_selected_id(self):
        return self.combo.currentData()


class ManualAssignmentDialog(QDialog):
    SECTION_OPTIONS = (
        (_("Служение"), "ministry"),
        (_("Сокровища"), "treasures"),
        (_("Жизнь"), "living"),
        (_("Библия"), "cbs"),
    )

    def __init__(self, facade, week_id, parent=None, assignment=None):
        super().__init__(parent)
        self.facade = facade
        self.week_id = week_id
        self.assignment = assignment
        self.setWindowTitle(
            _("Изменить пункт расписания") if assignment else _("Добавить пункт в расписание")
        )
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.text_edit = QLineEdit()
        self.text_edit.setObjectName("manualAssignmentText")
        self.text_edit.setPlaceholderText(_("Например: Внеочередное выступление"))
        form.addRow(_("Название:"), self.text_edit)

        self.section_combo = QComboBox()
        self.section_combo.setObjectName("manualAssignmentSection")
        for title, value in self.SECTION_OPTIONS:
            self.section_combo.addItem(title, value)
        form.addRow(_("Раздел:"), self.section_combo)

        self.duration_spin = QSpinBox()
        self.duration_spin.setObjectName("manualAssignmentDuration")
        self.duration_spin.setRange(1, 180)
        self.duration_spin.setValue(5)
        self.duration_spin.setSuffix(_(" мин"))
        form.addRow(_("Длительность:"), self.duration_spin)

        self.participant_combo = QComboBox()
        self.participant_combo.setObjectName("manualAssignmentParticipant")
        self.participant_combo.addItem(_("Без назначения"), None)
        for participant in self.facade.get_all_participants(active_only=True):
            self.participant_combo.addItem(participant["name"], participant["id"])
        form.addRow(_("Участник:"), self.participant_combo)

        if assignment:
            self.text_edit.setText(assignment.get("assignment_text") or "")
            section_index = self.section_combo.findData(assignment.get("section"))
            if section_index >= 0:
                self.section_combo.setCurrentIndex(section_index)
            self.duration_spin.setValue(max(int(assignment.get("duration") or 1), 1))
            participant_index = self.participant_combo.findData(assignment.get("participant_id"))
            if participant_index >= 0:
                self.participant_combo.setCurrentIndex(participant_index)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(
            _("Сохранить") if assignment else _("Добавить")
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self):
        if not self.text_edit.text().strip():
            QMessageBox.warning(self, _("Текст пункта"), _("Введите название пункта."))
            return
        self.accept()

    def get_values(self):
        return {
            "text": self.text_edit.text().strip(),
            "section": self.section_combo.currentData(),
            "duration": self.duration_spin.value(),
            "participant_id": self.participant_combo.currentData(),
        }


class ReorderableTableWidget(QTableWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reorder_callback = None
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    @staticmethod
    def _move_rows(row_ids, selected_rows, target_row):
        if max(selected_rows) < target_row:
            target_row -= len(selected_rows)
        moving_ids = [row_ids[row] for row in selected_rows]
        remaining_ids = [
            assignment_id for row, assignment_id in enumerate(row_ids) if row not in selected_rows
        ]
        remaining_ids[target_row:target_row] = moving_ids
        return remaining_ids

    def dropEvent(self, event):
        row_ids = getattr(self, "_row_assignment_ids", [])
        selected_rows = sorted({index.row() for index in self.selectionModel().selectedRows()})
        if not row_ids or not selected_rows:
            event.ignore()
            return

        target_row = self.indexAt(event.position()).row()
        if target_row < 0:
            target_row = self.rowCount()
        if target_row in selected_rows:
            event.ignore()
            return

        remaining_ids = self._move_rows(row_ids, selected_rows, target_row)
        if self.reorder_callback:
            self.reorder_callback(remaining_ids)
        event.accept()
