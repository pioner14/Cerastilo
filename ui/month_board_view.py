"""
Доска месяца (режим «Месяц» во вкладке «Расписание»): недели колонками,
пункты программы строками, у имени — давность и цветная точка.

Щелчок по клетке показывает справа кандидатов на этот пункт; двойной щелчок
по кандидату или перетаскивание его на клетку — назначить. Двойной щелчок по
клетке — обычное окно выбора участника, правый щелчок — участник, напарник,
очистить. Щелчок по заголовку недели открывает её в обычном режиме.
Данные — facade.get_month_board().
"""

from html import escape
from typing import List, Optional

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.month_board import month_problems
from core.styles import palette, section_colors
from ui.candidates import (
    RECENT_WEEKS,
    RESTED_WEEKS,
    _hint_icon,
    by_rest,
    confirm_assignment,
    list_candidates,
)
from core.i18n import _

# Формат перетаскивания кандидата на клетку доски: id участника
PARTICIPANT_MIME = "application/x-nhjs-participant"


# Тема задаёт QTableWidget::item { padding: 6px } (core/styles.py) — виджет
# клетки на 2×6 px ниже строки, плюс линия сетки
CELL_PADDING = 2 * 6 + 1

ROW_SECTION_COLORS = {
    "chairman": "fixed",
    "prayer_open": "fixed",
    "prayer_close": "fixed",
    "fixed": "fixed",
    "treasures": "treasures",
    "ministry": "ministry",
    "living": "living",
    "cbs": "cbs",
}


# Статус уведомления у имени: значок и подсказка (core/month_board._notice)
NOTICE_MARKS = {"waiting": "⏳", "confirmed": "✅", "declined": "❌", "error": "⚠️✉️"}
NOTICE_TEXTS = {
    None: _("не уведомлён"),
    "error": _("письмо не ушло"),
    "waiting": _("уведомлён, ждём ответа"),
    "confirmed": _("подтвердил"),
    "declined": _("ответил: не сможет"),
}


def _header_text(column: dict) -> str:
    """Заголовок недели: дата и сводка уведомлений одной строкой."""
    text = column["title"] + (_("\nВизит РС") if column["circuit_overseer"] else "")
    notice = column.get("notice") or {}
    parts = []
    if notice.get("declined"):
        parts.append(f"❌ {notice['declined']}")
    if notice.get("waiting"):
        parts.append(f"⏳ {notice['waiting']}")
    # «не уведомлены» не показываем: о заданиях сообщают листками на встрече
    total = column.get("slips_total", 0)
    if total:
        parts.append(f"🧾 {column.get('slips_given', 0)}/{total}")
    return text + ("\n" + "  ".join(parts) if parts else "")


def recency_kind(person: dict) -> Optional[str]:
    """«rested» — давно (8+ нед.) или ещё не выступал, «recent» — меньше 4 нед.
    Старейшинам точку не ставим: они заняты почти каждую неделю, это норма."""
    if person.get("elder") or not person.get("id"):
        return None
    weeks = person.get("weeks_since")
    if weeks is None or weeks >= RESTED_WEEKS:
        return "rested"
    if weeks < RECENT_WEEKS:
        return "recent"
    return None


def _weeks_text(person: dict) -> str:
    weeks = person.get("weeks_since")
    if not person.get("id"):
        return ""
    return _("нов.") if weeks is None else _("{weeks} н.", weeks=weeks)


class _CandidateList(QListWidget):
    """Список кандидатов; при перетаскивании отдаёт id участника."""

    def mimeData(self, items):
        mime = QMimeData()
        if items and items[0].data(Qt.ItemDataRole.UserRole):
            mime.setData(PARTICIPANT_MIME, str(items[0].data(Qt.ItemDataRole.UserRole)).encode())
        return mime


class _BoardTable(QTableWidget):
    """Таблица доски, принимает кандидата: participant_dropped(row, col, id)."""

    participant_dropped = Signal(int, int, int)

    def __init__(self, can_drop, parent=None):
        super().__init__(parent)
        self._can_drop = can_drop  # (row, col) -> bool
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

    def _target(self, event):
        if not event.mimeData().hasFormat(PARTICIPANT_MIME):
            return None
        index = self.indexAt(event.position().toPoint())
        if index.isValid() and self._can_drop(index.row(), index.column()):
            return index.row(), index.column()
        return None

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(PARTICIPANT_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._target(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        target = self._target(event)
        if not target:
            event.ignore()
            return
        pid = int(bytes(event.mimeData().data(PARTICIPANT_MIME)).decode())
        event.acceptProposedAction()
        self.participant_dropped.emit(target[0], target[1], pid)


class MonthCheckDialog(QDialog):
    """Проблемы месяца списком; двойной щелчок или Enter — к клетке."""

    def __init__(self, board_view: "MonthBoardView"):
        super().__init__(board_view)
        self.board_view = board_view
        self.setWindowTitle(_("Проверка месяца"))
        self.resize(560, 420)
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.itemActivated.connect(self._go)
        self.list.currentRowChanged.connect(lambda _row: self._go(self.list.currentItem()))
        layout.addWidget(self.list)
        buttons = QHBoxLayout()
        refresh = QPushButton(_("Обновить"))
        refresh.clicked.connect(self.reload)
        close = QPushButton(_("Закрыть"))
        close.clicked.connect(self.close)
        buttons.addStretch(1)
        buttons.addWidget(refresh)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def reload(self) -> None:
        problems = self.board_view.problems()
        self.list.clear()
        for problem in problems:
            item = QListWidgetItem(problem["text"])
            item.setData(Qt.ItemDataRole.UserRole, (problem["row"], problem["col"]))
            self.list.addItem(item)
        self.summary.setText(
            _("Всё в порядке: пустых пунктов и накладок нет.")
            if not problems
            else _("Найдено: {n}. Выберите строку — клетка выделится на доске.", n=len(problems))
        )

    def _go(self, item) -> None:
        if item is not None:
            self.board_view.go_to_cell(*item.data(Qt.ItemDataRole.UserRole))


class MonthBoardView(QWidget):
    """Сетка месяца. Сигнал week_activated(week_id) — открыть неделю."""

    week_activated = Signal(int)
    history_changed = Signal()  # изменились стеки отмены/повтора доски

    HISTORY_LIMIT = 30

    def __init__(self, facade, parent=None):
        super().__init__(parent)
        self.facade = facade
        self.week_ids: List[int] = []
        self.title = ""
        self.board = None
        self.selected = None  # (row, col) выбранной клетки — для панели кандидатов
        self._check_dialog = None  # окно «Проверить месяц»
        self._swap_from = None  # (row, col, role): кого меняем местами — ждём вторую клетку
        # Отмена правок на доске (Ctrl+Z): каждая запись — люди пунктов до правки,
        # [{"id", "participant_id", "assistant_id"}]
        self._undo: List[list] = []
        self._redo: List[list] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.summary_widget = QWidget()
        self.summary_widget.setObjectName("monthSummary")
        summary_rows = QVBoxLayout(self.summary_widget)
        summary_rows.setContentsMargins(0, 0, 0, 0)
        summary_rows.setSpacing(2)
        # сводка в две строки, иначе на ширине 1600 обрезается справа
        self.summary_layout = QHBoxLayout()
        self.summary_layout.setSpacing(12)
        self.notes_layout = QHBoxLayout()
        self.notes_layout.setSpacing(12)
        summary_rows.addLayout(self.summary_layout)
        summary_rows.addLayout(self.notes_layout)
        layout.addWidget(self.summary_widget)

        self.table = _BoardTable(lambda row, col: self._assignment_id_at(row, col) is not None)
        self.table.setObjectName("monthBoardTable")
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setWordWrap(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.table.currentCellChanged.connect(lambda row, col, *_: self._select_cell(row, col))
        self.table.participant_dropped.connect(self._on_participant_dropped)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        self.table.cellClicked.connect(self._on_cell_clicked)
        QShortcut(
            QKeySequence("Escape"),
            self.table,
            activated=self.cancel_swap,
            context=Qt.ShortcutContext.WidgetShortcut,
        )
        # Клавиатура: стрелки — по клеткам (сама таблица), Enter — выбрать
        # участника, Delete — очистить клетку
        for key in ("Return", "Enter"):
            QShortcut(
                QKeySequence(key),
                self.table,
                activated=self._on_key_enter,
                context=Qt.ShortcutContext.WidgetShortcut,
            )
        QShortcut(
            QKeySequence("Delete"),
            self.table,
            activated=self._on_key_delete,
            context=Qt.ShortcutContext.WidgetShortcut,
        )

        # Панель кандидатов справа от сетки
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(4)
        # кнопка, а не только пункт меню: на планшете нет правого клика
        self.btn_check = QPushButton(_("🔍 Проверить месяц"))
        self.btn_check.setToolTip(
            _(
                "Список всего, что стоит поправить перед печатью: пустые пункты, "
                "отпуск, дважды за неделю, две недели подряд, не подходит по квалификации"
            )
        )
        self.btn_check.clicked.connect(self.check_month)
        panel_layout.addWidget(self.btn_check)
        self.btn_swap = QPushButton(_("⇄ Поменять местами"))
        self.btn_swap.setToolTip(
            _(
                "Выберите клетку, нажмите и выберите вторую клетку — "
                "участники поменяются местами (Esc — отмена)"
            )
        )
        self.btn_swap.clicked.connect(self._on_swap_button)
        panel_layout.addWidget(self.btn_swap)
        self.swap_hint = QLabel()
        self.swap_hint.setWordWrap(True)
        self.swap_hint.setObjectName("monthSwapHint")
        self.swap_hint.hide()
        panel_layout.addWidget(self.swap_hint)
        self.btn_notify_week = QPushButton(_("✉️ Уведомить эту неделю"))
        self.btn_notify_week.setFlat(True)  # письма — по случаю, о заданиях сообщают листками
        self.btn_notify_week.setToolTip(
            _("Письма тем, кому на неделе выбранной клетки ещё не писали")
        )
        self.btn_notify_week.clicked.connect(
            lambda: self.notify_week(self.selected[1]) if self.selected else None
        )
        panel_layout.addWidget(self.btn_notify_week)
        self.candidates_title = QLabel()
        self.candidates_title.setObjectName("headerLabel")
        self.candidates_title.setWordWrap(True)
        panel_layout.addWidget(self.candidates_title)
        self.candidate_search = QLineEdit()
        self.candidate_search.setObjectName("monthCandidateSearch")
        self.candidate_search.setPlaceholderText(_("🔍 Поиск по имени…"))
        self.candidate_search.setClearButtonEnabled(True)
        self.candidate_search.textChanged.connect(self._filter_candidates)
        panel_layout.addWidget(self.candidate_search)
        self.candidates = _CandidateList()
        self.candidates.setObjectName("monthCandidates")
        self.candidates.setDragEnabled(True)
        self.candidates.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.candidates.setWordWrap(True)
        # подсказки переносятся по ширине панели, а не уезжают вбок
        self.candidates.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.candidates.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.candidates.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.candidates.itemDoubleClicked.connect(self._on_candidate_double_clicked)
        panel_layout.addWidget(self.candidates, 1)
        hint = QLabel(
            _("Двойной щелчок — назначить в выбранную клетку.\nМожно перетащить на любую клетку.")
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {palette().text_secondary};")
        panel_layout.addWidget(hint)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.table)
        splitter.addWidget(panel)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)
        self._show_candidates()

    # --- данные ---

    def show_weeks(self, week_ids: List[int], title: str = "") -> None:
        if list(week_ids) != self.week_ids:
            self.clear_history()  # отмена — только для видимого месяца
        self.week_ids = list(week_ids)
        self.title = title
        self.cancel_swap()  # другой месяц — обмен не переносится
        self.refresh()

    def refresh(self) -> None:
        self.board = self.facade.get_month_board(self.week_ids) if self.week_ids else None
        selected = self.selected
        self.table.blockSignals(True)  # смена текущей клетки при перерисовке — не выбор
        try:
            self._render()
        finally:
            self.table.blockSignals(False)
        # после назначения остаёмся на той же клетке, кандидаты пересчитаны
        if selected and self._assignment_id_at(*selected) is not None:
            self.table.setCurrentCell(*selected)
            self._select_cell(*selected)
        else:
            self._select_cell(-1, -1)

    # --- отрисовка ---

    def _render(self) -> None:
        # clear() не снимает объединения ячеек (особая неделя) и виджеты клеток
        self.table.clearSpans()
        self.table.setRowCount(0)
        self.table.clear()
        self._render_summary()
        board = self.board
        if not board or not board["columns"]:
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            return

        columns, rows = board["columns"], board["rows"]
        self.table.setColumnCount(len(columns))
        self.table.setRowCount(max(len(rows), 1))

        for col, column in enumerate(columns):
            header = QTableWidgetItem(_header_text(column))
            header.setToolTip(_("Открыть неделю\n❌ не смогут · ⏳ ждём ответа"))
            self.table.setHorizontalHeaderItem(col, header)

        colors = section_colors()
        for row, info in enumerate(rows):
            item = QTableWidgetItem(info["label"])
            color = colors.get(ROW_SECTION_COLORS.get(info["section"], "other"))
            if color:
                item.setForeground(QColor(color))
            self.table.setVerticalHeaderItem(row, item)

        for col, column in enumerate(columns):
            if column["special"]:
                self._render_special_column(col, column["special"], len(rows))
                continue
            for row, info in enumerate(rows):
                cell = board["cells"][row][col]
                widget = self._cell_widget(cell, info["section"])
                # подсказка — у элемента таблицы: виджет клетки прозрачен для мыши,
                # чтобы щелчки и перетаскивание доходили до таблицы
                item = QTableWidgetItem()
                item.setToolTip(widget.toolTip())
                widget.setToolTip("")
                widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                self.table.setItem(row, col, item)
                self.table.setCellWidget(row, col, widget)
        self._fit_rows()

    def _fit_rows(self) -> None:
        """Высота строки — по самой высокой клетке: ResizeToContents видит
        только QTableWidgetItem, а клетки здесь — виджеты (напарник обрезался)."""
        for row in range(self.table.rowCount()):
            heights = [
                widget.sizeHint().height() + CELL_PADDING
                for col in range(self.table.columnCount())
                if self.table.rowSpan(row, col) == 1
                and (widget := self.table.cellWidget(row, col)) is not None
            ]
            self.table.setRowHeight(
                row, max(heights + [self.table.verticalHeader().sectionSizeHint(row)])
            )

    def _render_special_column(self, col: int, name: str, row_count: int) -> None:
        label = QLabel(_("{v}<br><br>встречи нет", v=escape(name)))
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        pal = palette()
        label.setStyleSheet(f"background: {pal.surface_subtle}; color: {pal.text_secondary};")
        if row_count > 1:
            self.table.setSpan(0, col, row_count, 1)
        self.table.setCellWidget(0, col, label)

    def _cell_widget(self, cell: Optional[dict], section: str) -> QLabel:
        pal = palette()
        label = QLabel()
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setContentsMargins(6, 3, 6, 3)
        if cell is None:  # такого пункта на этой неделе нет
            label.setStyleSheet(f"color: {pal.text_secondary};")
            return label

        flags = set(cell["flags"])
        lines = []
        if section == "ministry" and cell["text"]:
            lines.append(
                f'<span style="color:{pal.text_secondary}; font-size:small">{escape(cell["text"])}</span>'
            )
        for person in cell["people"]:
            kind = recency_kind(person)
            dot = {"rested": pal.text_success, "recent": pal.text_warning}.get(kind)
            mark = f'<span style="color:{dot}">●</span> ' if dot else ""
            weeks_color = pal.text_warning if kind == "recent" else pal.text_secondary
            notice = NOTICE_MARKS.get(person.get("notice"), "") if person.get("id") else ""
            lines.append(
                f'{mark}{escape(person["short"])} '
                f'<span style="color:{weeks_color}; font-size:small">{_weeks_text(person)}</span>'
                + (f' <span style="font-size:small">{notice}</span>' if notice else "")
            )
        if cell.get("slip") and lines:
            lines[-len(cell["people"])] += ' <span style="font-size:small">🧾</span>'
        if "empty" in flags:
            lines.append(
                _('<span style="color:{text_error}">— пусто</span>', text_error=pal.text_error)
            )
        if "consecutive" in flags:
            lines.append(
                _(
                    '<span style="color:{text_warning}; font-size:small">2× подряд</span>',
                    text_warning=pal.text_warning,
                )
            )
        if "double" in flags:
            lines.append(
                _(
                    '<span style="color:{text_error}; font-size:small">⚠️ дважды за неделю</span>',
                    text_error=pal.text_error,
                )
            )
        if "elder_student" in flags:
            lines.append(
                _(
                    '<span style="color:{text_warning}; font-size:small">⚠️ старейшина на учебном</span>',
                    text_warning=pal.text_warning,
                )
            )
        if "declined" in flags:
            lines.append(
                _(
                    '<span style="color:{text_error}; font-size:small">❌ не сможет — нужна замена</span>',
                    text_error=pal.text_error,
                )
            )
        if "away" in flags:
            lines.append(
                _(
                    '<span style="color:{text_error}; font-size:small">🏖️ в отпуске — нужна замена</span>',
                    text_error=pal.text_error,
                )
            )
        label.setText("<br>".join(lines))

        # заливка — по статусу уведомления, рамка — по предупреждению
        notice = cell.get("notice")
        warning = "consecutive" in flags or "elder_student" in flags
        if flags & {"double", "empty", "declined", "away"}:
            label.setStyleSheet(
                f"background: {pal.conflict_background}; border: 2px solid {pal.text_error};"
            )
        elif notice in ("waiting", "confirmed") or warning:
            background, border = {
                "waiting": (pal.notice_waiting_background, pal.notice_waiting_border),
                "confirmed": (pal.notice_confirmed_background, pal.notice_confirmed_border),
            }.get(notice, (pal.warning_background, pal.warning_border))
            if warning:
                border = pal.warning_border
            label.setStyleSheet(f"background: {background}; border: 2px solid {border};")

        tips = [cell["text"]] if cell["text"] else []
        for person in cell["people"]:
            weeks = person.get("weeks_since")
            when = (
                _("раньше не выступал")
                if weeks is None
                else _("прошлое задание {weeks} нед. назад", weeks=weeks)
            )
            role = _(" (напарник)") if person["role"] == "assistant" else ""
            notice = NOTICE_TEXTS.get(person.get("notice"), "")
            if "away" in person.get("flags", ()):
                notice += _(", в отпуске на этой неделе — нужна замена")
            tips.append(
                f"{person['name']}{role}: {when}, {notice}" if person.get("id") else person["name"]
            )
        if cell.get("slip"):
            tips.append(_("🧾 Листок выдан"))
        label.setToolTip("\n".join(tips))
        return label

    def _render_summary(self) -> None:
        for box in (self.summary_layout, self.notes_layout):
            while box.count():
                child = box.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
        if self.title:
            title = QLabel(escape(self.title))
            title.setObjectName("headerLabel")
            self.summary_layout.addWidget(title)
        board = self.board
        if not board:
            return
        pal = palette()
        s = board["summary"]
        chips = [
            (
                _("Назначено {v} из {v2}", v=s["assigned"], v2=s["total"]),
                pal.text_success if s["assigned"] >= s["total"] else pal.text_warning,
            ),
            (_("Пустых: {v}", v=s["empty"]), pal.text_error if s["empty"] else pal.text_success),
            (
                _("Дважды за неделю: {v}", v=s["double"]),
                pal.text_error if s["double"] else pal.text_success,
            ),
            (
                _("Подряд две недели: {v}", v=s["consecutive"]),
                pal.text_warning if s["consecutive"] else pal.text_success,
            ),
        ]
        away = sum("away" in cell["flags"] for row in board["cells"] for cell in row if cell)
        if away:
            chips.append((_("В отпуске, нужна замена: {away}", away=away), pal.text_error))
        n = board.get("notice_summary") or {}
        if n.get("declined"):
            chips.append((_("Не смогут: {v}", v=n["declined"]), pal.text_error))
        # «Не уведомлено» — не предупреждение (о заданиях сообщают листками),
        # рассылка остаётся в меню клетки: «✉️ Уведомить месяц».
        if n.get("waiting"):
            chips.append((_("Ждут ответа: {v}", v=n["waiting"]), pal.text_secondary))
        if s.get("elder_student"):  # допустимо, но стоит видеть — только когда есть
            chips.append((_("Старейшины на учебных: {v}", v=s["elder_student"]), pal.text_warning))
        notes = []
        for column in board["columns"]:
            if column["special"]:
                start = column["start_date"]
                notes.append(
                    (
                        _(
                            "{v} — {v2}, не распределяется",
                            v=start.strftime("%d.%m") if start else "",
                            v2=column["special"],
                        ),
                        pal.text_secondary,
                    )
                )
        for box, items in ((self.summary_layout, chips), (self.notes_layout, notes)):
            for text, color in items:
                chip = QLabel(f'<span style="color:{color}">●</span> {escape(text)}')
                chip.setTextFormat(Qt.TextFormat.RichText)
                chip.setObjectName("monthSummaryChip")
                box.addWidget(chip)
        self.summary_layout.addStretch(1)
        legend = QLabel(
            _(
                '<span style="color:{text_success}">●</span> давно не выступал или новый &nbsp; <span style="color:{text_warning}">●</span> меньше 4 нед. назад &nbsp; <span style="background:{notice_waiting_background}">&nbsp;⏳ ждём ответа&nbsp;</span> &nbsp; <span style="background:{notice_confirmed_background}">&nbsp;✅ подтвердил&nbsp;</span> &nbsp; <span style="background:{conflict_background}">&nbsp;❌ не сможет / 🏖️ в отпуске&nbsp;</span>',
                text_success=pal.text_success,
                text_warning=pal.text_warning,
                notice_waiting_background=pal.notice_waiting_background,
                notice_confirmed_background=pal.notice_confirmed_background,
                conflict_background=pal.conflict_background,
            )
        )
        legend.setTextFormat(Qt.TextFormat.RichText)
        legend.setToolTip(
            _(
                "У старейшин точки нет: они выступают почти каждую неделю.\n"
                "«Подряд» отмечается тоже только у тех, кто не старейшина."
            )
        )
        self.notes_layout.addStretch(1)
        self.notes_layout.addWidget(legend)

    # --- действия ---

    def empty_week_ids(self) -> List[int]:
        """Недели месяца, где не назначен никто (ни участник, ни напарник);
        особые недели и недели хотя бы с одним назначением не входят."""
        board = self.board
        if not board:
            return []
        result = []
        for col, column in enumerate(board["columns"]):
            if column["special"] or not column["week_id"]:
                continue
            cells = [row[col] for row in board["cells"] if row[col] is not None]
            if cells and not any(cell["people"] for cell in cells):
                result.append(column["week_id"])
        return result

    def weeks_with_gaps(self) -> List[int]:
        """Недели месяца, где есть хотя бы один пустой пункт (особые — нет).
        Для «Авто» в месяце: заполняются только пустые клетки."""
        board = self.board
        if not board:
            return []
        result = []
        for col, column in enumerate(board["columns"]):
            if column["special"] or not column["week_id"]:
                continue
            if any(row[col] is not None and "empty" in row[col]["flags"] for row in board["cells"]):
                result.append(column["week_id"])
        return result

    def unsuitable_people(self) -> List[tuple]:
        """(assignment_id, participant_id): назначенные, кто не проходит фильтр
        кандидатов этого пункта (пол, квалификация, статус служения)."""
        result = []
        board = self.board or {}
        for row in board.get("cells", []):
            for cell in row:
                if not cell or not cell.get("assignment_id"):
                    continue
                for person in cell["people"]:
                    if not person.get("id"):
                        continue
                    role = "assistant" if person["role"] == "assistant" else "participant"
                    allowed = {
                        c["id"] for c in list_candidates(self.facade, cell["assignment_id"], role)
                    }
                    if person["id"] not in allowed:
                        result.append((cell["assignment_id"], person["id"]))
        return result

    def check_month(self) -> None:
        """«🔍 Проверить месяц»: окно со списком проблем; выбор строки —
        переход к клетке на доске. Окно не модальное: правьте и «Обновить»."""
        if self._check_dialog is None:
            self._check_dialog = MonthCheckDialog(self)
        self._check_dialog.reload()
        self._check_dialog.show()
        self._check_dialog.raise_()
        self._check_dialog.activateWindow()

    def problems(self) -> List[dict]:
        if not self.board:
            return []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            return month_problems(self.board, self.unsuitable_people())
        finally:
            QApplication.restoreOverrideCursor()

    def go_to_cell(self, row: int, col: int) -> None:
        self.table.setCurrentCell(row, col)
        item = self.table.item(row, col)
        if item is not None:
            self.table.scrollToItem(item)
        else:
            self.table.scrollTo(self.table.model().index(row, col))

    def _week_id_at(self, col: int) -> Optional[int]:
        if self.board and 0 <= col < len(self.board["columns"]):
            return self.board["columns"][col]["week_id"]
        return None

    def _on_header_clicked(self, col: int) -> None:
        week_id = self._week_id_at(col)
        if week_id:
            self.week_activated.emit(week_id)

    def _cell_at(self, row: int, col: int) -> Optional[dict]:
        board = self.board
        if not board or not (0 <= row < len(board["rows"]) and 0 <= col < len(board["columns"])):
            return None
        if board["columns"][col]["special"]:
            return None
        return board["cells"][row][col]

    def _assignment_id_at(self, row: int, col: int) -> Optional[int]:
        cell = self._cell_at(row, col)
        return cell.get("assignment_id") if cell else None

    def _select_cell(self, row: int, col: int) -> None:
        self.selected = (row, col) if self._assignment_id_at(row, col) is not None else None
        self._show_candidates()

    def _show_candidates(self) -> None:
        self.candidates.clear()
        self.btn_notify_week.setEnabled(bool(self.selected))
        self.btn_notify_week.setText(_("✉️ Уведомить эту неделю"))
        if not self.selected:
            self.candidates_title.setText(_("Кандидаты"))
            self.candidates.addItem(QListWidgetItem(_("Выберите клетку на доске")))
            self.candidates.item(0).setFlags(Qt.ItemFlag.NoItemFlags)
            return
        row, col = self.selected
        column = self.board["columns"][col]
        start = column["start_date"]
        if start:
            self.btn_notify_week.setText(_("✉️ Уведомить неделю {v}", v=start.strftime("%d.%m")))
        self.candidates_title.setText(
            f"{self.board['rows'][row]['label']} · {start.strftime('%d.%m') if start else column['title']}"
        )
        for c in by_rest(
            list_candidates(self.facade, self._assignment_id_at(row, col), "participant")
        ):
            item = QListWidgetItem(_hint_icon(c["kind"]), f"{c['name']}\n{c['hint']}")
            item.setData(Qt.ItemDataRole.UserRole, c["id"])
            item.setToolTip(c["tooltip"])
            item.setData(Qt.ItemDataRole.UserRole + 1, c["name"])
            if c["busy"]:
                item.setForeground(QColor(palette().text_secondary))
            self.candidates.addItem(item)
        self._filter_candidates(self.candidate_search.text())

    def _filter_candidates(self, text: str) -> None:
        """Оставить в списке кандидатов тех, в чьём имени есть набранный текст.
        Строка поиска не сбрасывается при выборе другой клетки: удобно искать
        одного человека по нескольким пунктам."""
        needle = text.strip().casefold()
        for i in range(self.candidates.count()):
            item = self.candidates.item(i)
            name = item.data(Qt.ItemDataRole.UserRole + 1)
            if name is None:  # «Выберите клетку на доске»
                continue
            item.setHidden(bool(needle) and needle not in name.casefold())

    # --- Листки -----------------------------------------------------------

    def week_slip_ids(self, col: int) -> List[int]:
        """Пункты недели с людьми, у которых листок ещё не отмечен выданным."""
        board = self.board or {}
        ids = []
        for row in board.get("cells", []):
            cell = row[col] if col < len(row) else None
            if cell and cell.get("assignment_id") and cell["people"] and not cell.get("slip"):
                ids.append(cell["assignment_id"])
        return ids

    def set_slip(self, assignment_ids: List[int], given: bool) -> None:
        """Отметить «🧾 листок выдан» (или снять). Смена участника снимает
        отметку сама — новому человеку нужен новый листок."""
        if assignment_ids and self.facade.set_slip_given(assignment_ids, given):
            self.refresh()

    # --- Отмена и повтор правок доски -------------------------------------

    def _people_of(self, assignment_ids) -> list:
        state = []
        for aid in dict.fromkeys(assignment_ids):
            a = self.facade.get_assignment(aid) or {}
            state.append(
                {
                    "id": aid,
                    "participant_id": a.get("participant_id"),
                    "assistant_id": a.get("assistant_id"),
                }
            )
        return state

    def _remember(self, assignment_ids) -> None:
        """Запомнить людей пунктов перед правкой — для Ctrl+Z."""
        self._undo.append(self._people_of(assignment_ids))
        del self._undo[: -self.HISTORY_LIMIT]
        self._redo.clear()
        self.history_changed.emit()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def clear_history(self) -> None:
        """База изменилась целиком (откат к снимку, «Авто» месяца) или другой месяц."""
        if self._undo or self._redo:
            self._undo.clear()
            self._redo.clear()
            self.history_changed.emit()

    def _step(self, source: list, target: list) -> None:
        if not source:
            return
        state = source.pop()
        current = self._people_of([e["id"] for e in state])
        if self.facade.restore_people(state):
            target.append(current)
        else:
            source.append(state)
            QMessageBox.warning(self, _("Ошибка"), _("Не удалось вернуть изменение."))
        self.history_changed.emit()
        self.refresh()

    def undo(self) -> None:
        self._step(self._undo, self._redo)

    def redo(self) -> None:
        self._step(self._redo, self._undo)

    def assign(
        self,
        row: int,
        col: int,
        participant_id: Optional[int],
        role: str = "participant",
        remember: bool = True,
    ) -> None:
        """Назначить участника (None — очистить) в клетку и перерисовать доску."""
        assignment_id = self._assignment_id_at(row, col)
        if assignment_id is None or not confirm_assignment(
            self, self.facade, assignment_id, participant_id
        ):
            return
        if remember:
            self._remember([assignment_id])
        self.facade.assign_participant(assignment_id, participant_id, role)
        self.selected = (row, col)
        self.refresh()

    def _on_candidate_double_clicked(self, item: QListWidgetItem) -> None:
        pid = item.data(Qt.ItemDataRole.UserRole)
        if pid and self.selected:
            self.assign(*self.selected, pid)

    def _on_participant_dropped(self, row: int, col: int, pid: int) -> None:
        # Кандидаты считались для выбранной клетки, а бросить можно на любую:
        # пригодность для этого пункта (пол, квалификация) проверяем заново
        assignment_id = self._assignment_id_at(row, col)
        if assignment_id is None:
            return
        if (row, col) != self.selected:
            allowed = {c["id"] for c in list_candidates(self.facade, assignment_id, "participant")}
            if pid not in allowed:
                name = (self.facade.get_participant(pid) or {}).get("name", "")
                QMessageBox.information(
                    self,
                    _("Не подходит"),
                    _(
                        "{name} не подходит для пункта «{v}» (пол или квалификация). Выберите эту клетку — справа будут её кандидаты.",
                        name=name,
                        v=self.board["rows"][row]["label"],
                    ),
                )
                return
        self.assign(row, col, pid)

    def _choose(self, row: int, col: int, role: str) -> None:
        """Обычное окно выбора участника/напарника, как в таблице недели."""
        from ui.schedule_widgets import ParticipantSelectDialog

        assignment_id = self._assignment_id_at(row, col)
        if assignment_id is None:
            return
        title = _("Выбор напарника") if role == "assistant" else _("Выбор участника")
        dialog = ParticipantSelectDialog(
            self, self.facade, assignment_id=assignment_id, role=role, title=title
        )
        if dialog.exec():
            self.assign(row, col, dialog.get_selected_id(), role)

    def _replace(self, row: int, col: int, role: str) -> None:
        """Замена отказавшегося: выбор нового и сразу письмо ему."""
        before = self._assignment_id_at(row, col)
        old = {p["id"] for p in (self._cell_at(row, col) or {}).get("people", [])}
        self._choose(row, col, role)
        cell = self._cell_at(row, col)
        if before is None or not cell:
            return
        new = [p for p in cell["people"] if p.get("id") and p["id"] not in old]
        if not new:
            return
        answer = QMessageBox.question(
            self,
            _("Уведомить замену"),
            _("Отправить уведомление: {v}?", v=new[0]["name"]),
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._notify([self._week_id_at(col)], [new[0]["id"]])

    def notify_not_notified(self) -> None:
        """«Уведомить» в сводке: всем, кому на этих неделях письмо не ушло."""
        board = self.board
        if not board:
            return
        ids = []
        for row in board["cells"]:
            for cell in row:
                for p in (cell or {}).get("people", []):
                    if p.get("id") and p.get("notice") in (None, "error") and p["id"] not in ids:
                        ids.append(p["id"])
        if ids:
            self._notify([c["week_id"] for c in board["columns"] if not c["special"]], ids)

    def week_not_notified_ids(self, col: int) -> List[int]:
        """Кому на неделе столбца col письмо ещё не ушло (или не дошло)."""
        board = self.board
        if not board or not (0 <= col < len(board["columns"])) or board["columns"][col]["special"]:
            return []
        ids = []
        for row in board["cells"]:
            for p in (row[col] or {}).get("people", []):
                if p.get("id") and p.get("notice") in (None, "error") and p["id"] not in ids:
                    ids.append(p["id"])
        return ids

    def week_waiting_ids(self, col: int) -> List[int]:
        """Кому на неделе столбца col письмо ушло, а ответа ещё нет (⏳)."""
        board = self.board
        if not board or not (0 <= col < len(board["columns"])) or board["columns"][col]["special"]:
            return []
        ids = []
        for row in board["cells"]:
            for p in (row[col] or {}).get("people", []):
                if p.get("id") and p.get("notice") == "waiting" and p["id"] not in ids:
                    ids.append(p["id"])
        return ids

    def remind_waiting(self, col: int) -> None:
        """«⏳ Напомнить ждущим»: повторное письмо только тем, кто не ответил."""
        ids = self.week_waiting_ids(col)
        week_id = self._week_id_at(col)
        if ids and week_id:
            self._notify([week_id], ids)

    def _on_key_enter(self) -> None:
        row, col = self.table.currentRow(), self.table.currentColumn()
        if self._swap_from:
            if (row, col) != self._swap_from[:2]:
                self.swap_with(row, col)
            return
        if self._assignment_id_at(row, col) is not None:
            self._choose(row, col, "participant")

    def _on_key_delete(self) -> None:
        row, col = self.table.currentRow(), self.table.currentColumn()
        cell = self._cell_at(row, col)
        if not cell or not cell.get("assignment_id") or not cell["people"]:
            return
        names = ", ".join(p["short"] for p in cell["people"] if p.get("name"))
        reply = QMessageBox.question(
            self,
            _("Очистить"),
            _(
                "Снять {names} с пункта «{label}»?",
                names=names,
                label=self.board["rows"][row]["label"],
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        assignment = self.facade.get_assignment(cell["assignment_id"]) or {}
        self._clear(row, col, cell["assignment_id"], assignment)

    def notify_week(self, col: int) -> None:
        """«Уведомить эту неделю»: отмечены те, кому ещё не писали; если
        уведомлены все — окно со всеми участниками недели (повторное письмо)."""
        week_id = self._week_id_at(col)
        if not week_id or self.board["columns"][col]["special"]:
            return
        self._notify([week_id], self.week_not_notified_ids(col) or None)

    def _notify(
        self,
        week_ids: List[int],
        participant_ids: Optional[List[int]],
        subject: Optional[str] = None,
    ) -> None:
        from ui.notification_dialog import NotificationDialog

        extra = {"default_subject": subject} if subject else {}
        NotificationDialog(
            self.facade, week_ids, parent=self, only_participant_ids=participant_ids, **extra
        ).exec()
        self.refresh()

    def send_month_digest(self) -> None:
        """«📅 Задания на месяц»: каждому одно письмо со всеми его заданиями
        месяца (с календарём .ics). Отмечены все, уже уведомлённые тоже."""
        board = self.board or {}
        week_ids = [
            c["week_id"] for c in board.get("columns", []) if c["week_id"] and not c["special"]
        ]
        if not week_ids:
            return
        month = self.title[:1].lower() + self.title[1:] if self.title else ""
        subject = _("Ваши задания на {month}", month=month) if month else _("Ваши задания на месяц")
        self._notify(week_ids, None, subject)

    def _on_cell_double_clicked(self, row: int, col: int) -> None:
        self._choose(row, col, "participant")

    def _on_context_menu(self, pos) -> None:
        index = self.table.indexAt(pos)
        row, col = index.row(), index.column()
        assignment_id = self._assignment_id_at(row, col)
        if assignment_id is None:
            return
        from core.assignment_classifier import AssignmentClassifier

        menu = QMenu(self)
        menu.addAction(_("Выбрать участника…"), lambda: self._choose(row, col, "participant"))
        assignment = self.facade.get_assignment(assignment_id) or {}
        if AssignmentClassifier().needs_assistant(assignment):
            menu.addAction(_("Выбрать напарника…"), lambda: self._choose(row, col, "assistant"))
        cell = self._cell_at(row, col)
        for person in (cell or {}).get("people", []):
            reason = (
                ("❌", _("не сможет"))
                if person.get("notice") == "declined"
                else (("🏖️", _("в отпуске")) if "away" in person.get("flags", ()) else None)
            )
            if reason:
                role = "assistant" if person["role"] == "assistant" else "participant"
                menu.addAction(
                    _(
                        "{v} {v2} {v3} — найти замену…",
                        v=reason[0],
                        v2=person["short"],
                        v3=reason[1],
                    ),
                    lambda r=role: self._replace(row, col, r),
                )
        for person in (cell or {}).get("people", []):
            if person.get("id"):
                role = "assistant" if person["role"] == "assistant" else "participant"
                menu.addAction(
                    _("⇄ Поменять {v} местами…", v=person["short"]),
                    lambda r=role: self.start_swap(row, col, r),
                )
        if cell and cell["people"]:
            menu.addAction(_("Очистить"), lambda: self._clear(row, col, assignment_id, assignment))
            slip = menu.addAction(_("🧾 Листок выдан"))
            slip.setCheckable(True)
            slip.setChecked(bool(cell.get("slip")))
            slip.toggled.connect(lambda on: self.set_slip([assignment_id], on))
        menu.addSeparator()
        week_slips = self.week_slip_ids(col)
        if week_slips:
            menu.addAction(
                _("🧾 Листки недели выданы — отметить все ({n})", n=len(week_slips)),
                lambda: self.set_slip(week_slips, True),
            )
        menu.addAction(_("✉️ Уведомить эту неделю"), lambda: self.notify_week(col))
        if self.week_waiting_ids(col):
            menu.addAction(_("⏳ Напомнить ждущим ответа"), lambda: self.remind_waiting(col))
        menu.addAction(_("✉️ Уведомить месяц (кому ещё не писали)"), self.notify_not_notified)
        menu.addAction(_("📅 Задания на месяц — письмо каждому…"), self.send_month_digest)
        menu.addAction(_("Открыть неделю"), lambda: self._on_header_clicked(col))
        menu.popup(self.table.viewport().mapToGlobal(pos))

    # --- Обмен местами ------------------------------------------------------

    def _person_at(self, row: int, col: int, role: str) -> Optional[dict]:
        want = "assistant" if role == "assistant" else "main"
        for person in (self._cell_at(row, col) or {}).get("people", []):
            if person.get("id") and person["role"] == want:
                return person
        return None

    def _on_swap_button(self) -> None:
        if self._swap_from:
            self.cancel_swap()
        elif self.selected and self._person_at(*self.selected, "participant"):
            self.start_swap(*self.selected, "participant")
        else:
            QMessageBox.information(
                self, _("Поменять местами"), _("Сначала выберите клетку с назначенным участником.")
            )

    def start_swap(self, row: int, col: int, role: str) -> None:
        person = self._person_at(row, col, role)
        if not person:
            return
        self._swap_from = (row, col, role)
        self.btn_swap.setText(_("✕ Отменить обмен"))
        self.swap_hint.setText(
            _("⇄ {name}: выберите клетку, с которой поменять (Esc — отмена)", name=person["short"])
        )
        self.swap_hint.show()

    def cancel_swap(self) -> None:
        self._swap_from = None
        self.btn_swap.setText(_("⇄ Поменять местами"))
        self.swap_hint.hide()

    def _on_cell_clicked(self, row: int, col: int) -> None:
        if self._swap_from and (row, col) != self._swap_from[:2]:
            self.swap_with(row, col)

    def swap_with(self, row: int, col: int, role: Optional[str] = None) -> None:
        """Поменять участника из start_swap() с участником клетки (row, col).
        role — роль во второй клетке; по умолчанию та же, что в первой, а если
        там её нет — главный участник."""
        if not self._swap_from:
            return
        r1, c1, role1 = self._swap_from
        if role is None:
            role = role1 if self._person_at(row, col, role1) else "participant"
        first, second = self._person_at(r1, c1, role1), self._person_at(row, col, role)
        a1, a2 = self._assignment_id_at(r1, c1), self._assignment_id_at(row, col)
        if not first or not second or a1 is None or a2 is None or first["id"] == second["id"]:
            QMessageBox.information(
                self,
                _("Поменять местами"),
                _("Во второй клетке нет участника, с которым можно поменяться."),
            )
            return
        problems = []
        for person, assignment_id, new_role, label in (
            (first, a2, role, self.board["rows"][row]["label"]),
            (second, a1, role1, self.board["rows"][r1]["label"]),
        ):
            allowed = {c["id"] for c in list_candidates(self.facade, assignment_id, new_role)}
            if person["id"] not in allowed:
                problems.append(
                    _(
                        "{name} не подходит для «{label}» (пол, квалификация или статус)",
                        name=person["short"],
                        label=label,
                    )
                )
        question = _("Поменять местами {a} и {b}?", a=first["short"], b=second["short"])
        if problems:
            question += "\n\n" + "\n".join(problems) + "\n\n" + _("Всё равно поменять?")
        reply = QMessageBox.question(
            self,
            _("Поменять местами"),
            question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.cancel_swap()
        self._remember([a1, a2])
        if not self.facade.swap_people(a1, role1, a2, role):
            self._undo.pop()
            self.history_changed.emit()
            QMessageBox.warning(
                self,
                _("Поменять местами"),
                _("Не удалось поменять местами — расписание не изменилось."),
            )
        self.selected = (row, col)
        self.refresh()

    def _clear(self, row: int, col: int, assignment_id: int, assignment: dict) -> None:
        self._remember([assignment_id])  # и главного, и напарника — одним шагом отмены
        if assignment.get("assistant_id"):
            self.facade.assign_participant(assignment_id, None, "assistant")
        self.assign(row, col, None, remember=False)
