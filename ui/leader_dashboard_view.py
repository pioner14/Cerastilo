"""
Вкладка «Сегодня» — пульт руководителя встречи (того, кто составляет
расписание): список дел с кнопкой перехода к каждому и карточка ближайшей
встречи. На планшете карточка — это и есть вид «на встречу».
Данные — facade.get_leader_dashboard(), логика — core/leader_dashboard.py.
"""

from html import escape
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.styles import palette
from ui.month_board_view import NOTICE_MARKS, NOTICE_TEXTS
from core.i18n import _

TODO_ICONS = {
    "declined": "❌",
    "empty": "📭",
    "not_notified": "✉️",
    "waiting": "⏳",
    "no_program": "📚",
    "unassigned": "🪄",
}
# Подпись кнопки дела
TODO_ACTIONS = {
    "declined": _("Найти замену"),
    "empty": _("Заполнить"),
    "not_notified": _("Уведомить"),
    "waiting": _("Напомнить"),
    "no_program": _("Импорт тетради"),
    "unassigned": _("Открыть месяц"),
}


class LeaderDashboardView(QWidget):
    """Сигналы: open_week(week_id), open_month(week_id) — перейти в «Расписание»,
    open_workbooks() — во вкладку «Тетради»."""

    open_week = Signal(int)
    open_month = Signal(int)
    open_workbooks = Signal()
    open_tab = Signal(str)  # «Первые шаги»: settings, participants, workbooks, schedule

    def __init__(self, facade, parent=None):
        super().__init__(parent)
        self.facade = facade
        self.data: Optional[Dict] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        self.layout_ = QVBoxLayout(content)
        self.layout_.setContentsMargins(16, 12, 16, 12)
        self.layout_.setSpacing(10)

        # «Первые шаги» — только пока база не заполнена
        self.steps_title = QLabel(_("Первые шаги"))
        self.steps_title.setObjectName("headerLabel")
        self.layout_.addWidget(self.steps_title)
        self.steps_box = QVBoxLayout()
        self.steps_box.setSpacing(4)
        self.layout_.addLayout(self.steps_box)

        top = QHBoxLayout()
        title = QLabel(_("Что сделать"))
        title.setObjectName("headerLabel")
        top.addWidget(title)
        top.addStretch(1)
        refresh = QPushButton(_("🔄 Обновить"))
        refresh.clicked.connect(self.load_data)
        top.addWidget(refresh)
        self.layout_.addLayout(top)

        self.todo_box = QVBoxLayout()
        self.todo_box.setSpacing(6)
        self.layout_.addLayout(self.todo_box)

        self.meeting_title = QLabel()
        self.meeting_title.setObjectName("headerLabel")
        self.layout_.addWidget(self.meeting_title)
        self.meeting_grid = QGridLayout()
        self.meeting_grid.setHorizontalSpacing(16)
        self.meeting_grid.setVerticalSpacing(4)
        self.layout_.addLayout(self.meeting_grid)
        self.layout_.addStretch(1)

    # --- данные ---

    def load_data(self) -> None:
        try:
            data = self.facade.get_leader_dashboard()
        except Exception as exc:  # пульт не должен мешать запуску программы
            self.data = None
            self._clear(self.todo_box)
            self.todo_box.addWidget(QLabel(_("Не удалось собрать список дел: {exc}", exc=exc)))
            self._render_meeting(None)
            return
        self.data = data
        self._render_first_steps(data.get("first_steps") or [])
        self._render_todos(data["todos"])
        self._render_meeting(data["meeting"])

    @staticmethod
    def _clear(box) -> None:
        while box.count():
            child = box.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _render_first_steps(self, steps: List[Dict]) -> None:
        self._clear(self.steps_box)
        self.steps_title.setVisible(bool(steps))
        pal = palette()
        for step in steps:
            line = QHBoxLayout()
            mark = f'<span style="color:{pal.text_success}">✓</span>' if step["done"] else "○"
            color = pal.text_secondary if step["done"] else pal.text_primary
            label = QLabel(f'{mark} <span style="color:{color}">{escape(step["text"])}</span>')
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setWordWrap(True)
            line.addWidget(label, 1)
            if not step["done"]:
                button = QPushButton(_("Перейти"))
                button.clicked.connect(lambda _=False, t=step["target"]: self.open_tab.emit(t))
                line.addWidget(button)
            holder = QWidget()
            holder.setLayout(line)
            self.steps_box.addWidget(holder)

    def _render_todos(self, todos: List[Dict]) -> None:
        self._clear(self.todo_box)
        pal = palette()
        if not todos:
            done = QLabel(
                _(
                    '<span style="color:{text_success}">✓</span> Всё готово',
                    text_success=pal.text_success,
                )
            )
            done.setTextFormat(Qt.TextFormat.RichText)
            self.todo_box.addWidget(done)
            return
        for todo in todos:
            row = QFrame()
            row.setObjectName("leaderTodo")
            row.setStyleSheet(
                f"QFrame#leaderTodo {{ border: 1px solid {pal.border}; border-radius: 6px;"
                f" background: {pal.surface}; }}"
            )
            line = QHBoxLayout(row)
            line.setContentsMargins(10, 6, 10, 6)
            color = pal.text_error if todo["kind"] in ("declined", "empty") else pal.text_primary
            label = QLabel(
                f'{TODO_ICONS.get(todo["kind"], "•")} '
                f'<span style="color:{color}">{escape(todo["text"])}</span>'
            )
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setWordWrap(True)
            line.addWidget(label, 1)
            button = QPushButton(TODO_ACTIONS.get(todo["kind"], _("Перейти")))
            button.clicked.connect(lambda _=False, t=todo: self.run_todo(t))
            line.addWidget(button)
            self.todo_box.addWidget(row)

    def _render_meeting(self, meeting: Optional[Dict]) -> None:
        self._clear(self.meeting_grid)
        self.meeting_title.setVisible(meeting is not None)
        if meeting is None:
            return
        pal = palette()
        column = meeting["column"]
        self.meeting_title.setText(
            _("Ближайшая встреча · {v}", v=column["title"])
            + (_(" · визит РС") if column.get("circuit_overseer") else "")
        )
        for i, item in enumerate(meeting["items"]):
            what = QLabel(escape(item["label"]))
            what.setStyleSheet(f"color: {pal.text_secondary};")
            self.meeting_grid.addWidget(what, i, 0, Qt.AlignmentFlag.AlignTop)
            names = []
            tips = []
            for person in item["cell"]["people"]:
                mark = NOTICE_MARKS.get(person.get("notice"), "") if person.get("id") else ""
                names.append(escape(person["name"]) + (f" {mark}" if mark else ""))
                if person.get("id"):
                    tips.append(f"{person['name']}: {NOTICE_TEXTS.get(person.get('notice'), '')}")
            text = (
                " + ".join(names)
                if names
                else _('<span style="color:{text_error}">— пусто</span>', text_error=pal.text_error)
            )
            who = QLabel(text)
            who.setTextFormat(Qt.TextFormat.RichText)
            who.setWordWrap(True)
            who.setToolTip("\n".join(tips))
            font = who.font()
            font.setPointSizeF(font.pointSizeF() * 1.15)
            who.setFont(font)
            self.meeting_grid.addWidget(who, i, 1)
        self.meeting_grid.setColumnStretch(1, 1)

    # --- действия ---

    def run_todo(self, todo: Dict) -> None:
        kind = todo["kind"]
        week_ids = todo.get("week_ids") or []
        if kind in ("not_notified", "waiting"):
            from ui.notification_dialog import NotificationDialog

            NotificationDialog(
                self.facade,
                week_ids,
                parent=self,
                only_participant_ids=todo.get("participant_ids") or None,
            ).exec()
            self.load_data()
        elif kind == "no_program":
            self.open_workbooks.emit()
        elif week_ids:
            # отказ и пустые пункты правятся на доске месяца первой такой недели
            self.open_month.emit(week_ids[0])
