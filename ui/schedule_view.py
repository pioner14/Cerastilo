from copy import deepcopy
from datetime import datetime

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTableWidgetItem,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.events import Event
from core.week_layout import (
    apply_circuit_overseer_week,
    assignment_label,
    order_week_assignments,
    parse_meeting_start,
    start_minutes,
)
from core.facade import ApplicationFacade
from core.styles import event_colors, palette, register_theme_listener, section_colors
from ui.candidates import (  # noqa: F401 — candidate_hint и _same_family импортируют тесты
    _same_family,
    candidate_hint,
    confirm_assignment,
)
from ui.month_board_view import MonthBoardView
from core.i18n import _, tr

SECTION_ORDER = (
    # Colours come from the theme palette; the literals stay out of the code
    # so the dark theme keeps contrast.
    ("fixed", _("Общие"), "fixed"),
    ("treasures", _("Сокровища"), "treasures"),
    ("ministry", _("Служение"), "ministry"),
    ("living", _("Жизнь"), "living"),
    ("cbs", _("Библия"), "cbs"),
)


from ui.schedule_widgets import (  # noqa: E402,F401 — импортируют тесты и другие модули
    AssignmentCell,
    ManualAssignmentDialog,
    ParticipantSelectDialog,
    ReorderableTableWidget,
)


from ui.schedule_auto import ScheduleAutoMixin
from ui.schedule_export import ScheduleExportMixin
from ui.schedule_notify import ScheduleNotifyMixin
from ui.schedule_table_edit import ScheduleTableEditMixin


class ScheduleView(
    ScheduleExportMixin, ScheduleAutoMixin, ScheduleNotifyMixin, ScheduleTableEditMixin, QWidget
):
    """Представление расписания с деревом недель и таблицей назначений."""

    # Константа названий месяцев на русском (избегаем зависимости от locale в NixOS)
    MONTHS_RU = {
        1: _("Январь"),
        2: _("Февраль"),
        3: _("Март"),
        4: _("Апрель"),
        5: _("Май"),
        6: _("Июнь"),
        7: _("Июль"),
        8: _("Август"),
        9: _("Сентябрь"),
        10: _("Октябрь"),
        11: _("Ноябрь"),
        12: _("Декабрь"),
    }

    def __init__(self, facade: ApplicationFacade):
        super().__init__()
        self.facade = facade
        # self.db_manager is removed to enforce separation
        # Subscribe to data changes
        self.facade.events.subscribe(Event.ASSIGNMENT_CHANGED, self._on_assignments_changed)
        self.facade.events.subscribe(Event.SCHEDULE_IMPORTED, self._load_tree)

        self.active_workers = []  # Keep references to prevent GC
        self._undo_stack = []
        # снимок базы перед «Авто-распределить месяц»: (путь, время) — для ↶ в месяце
        self._month_snapshot = None
        # идёт «Авто-распределить месяц»: ↶, «Авто» и доска заблокированы
        self._month_busy = False
        self._redo_stack = []

        # Colours set from Python (tree items, table cells, inline styles) are
        # not covered by the QSS theme, so they follow the palette explicitly.
        register_theme_listener(self._on_theme_changed)

        # --- Layout Initialization ---
        import logging

        logging.getLogger(__name__)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        # === ЛЕВАЯ ПАНЕЛЬ ===
        self.left_panel = left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(5, 5, 5, 5)
        left_layout.setSpacing(4)
        left_panel.setMinimumWidth(220)

        left_header = QLabel(_("📅 Расписание"))
        left_header.setObjectName("scheduleHeaderLabel")
        left_layout.addWidget(left_header)

        self.tree = QTreeWidget()
        self.tree.setObjectName("scheduleTree")
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.itemClicked.connect(self._on_tree_item_clicked)
        left_layout.addWidget(self.tree)

        # Кнопка "Добавить будущий год" остается внизу слева, так как это редкое действие
        self.btn_add_year = QPushButton(_("➕ Будущий год"))
        self.btn_add_year.setObjectName("btnAddYear")
        self.btn_add_year.setToolTip(_("Создать пустые шаблоны на следующий год"))
        self.btn_add_year.clicked.connect(self._on_add_future_year)
        left_layout.addWidget(self.btn_add_year)

        self.splitter.addWidget(left_panel)

        # === ПРАВАЯ ПАНЕЛЬ ===
        self.right_container = QWidget()
        self.right_layout = QVBoxLayout(self.right_container)
        self.right_layout.setContentsMargins(0, 0, 0, 0)
        self.right_layout.setSpacing(0)

        # --- TOOLBAR (Панель инструментов) ---
        # Слева — правка недели, справа — вывод (экспорт, уведомления).
        # Редкие действия (Word, S-89, журнал) спрятаны в выпадающие меню.
        self.toolbar_widget = QWidget()
        self.toolbar_widget.setObjectName("scheduleToolbar")
        self.toolbar_layout = toolbar_layout = QHBoxLayout(self.toolbar_widget)
        toolbar_layout.setContentsMargins(8, 8, 8, 4)
        toolbar_layout.setSpacing(6)

        # Значки — картинки из стиля Qt, а не символы ☰ ↶ ↷: на Android
        # в шрифтах приложения этих символов нет, вместо них были квадраты.
        style = self.style()
        self.btn_toggle_sidebar = QPushButton()
        self.btn_toggle_sidebar.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_FileDialogListView)
        )
        self.btn_toggle_sidebar.setObjectName("btnToggleSidebar")
        self.btn_toggle_sidebar.setProperty("iconButton", True)
        self.btn_toggle_sidebar.setCheckable(True)
        self.btn_toggle_sidebar.setChecked(True)
        self.btn_toggle_sidebar.setToolTip(_("Показать или скрыть список недель"))
        self.btn_toggle_sidebar.clicked.connect(self._toggle_sidebar)
        toolbar_layout.addWidget(self.btn_toggle_sidebar)

        # Режим «Месяц»: доска всех недель месяца (ui/month_board_view.py)
        self.btn_month = QPushButton(_("Месяц"))
        self.btn_month.setObjectName("btnMonthBoard")
        self.btn_month.setCheckable(True)
        self.btn_month.setToolTip(_("Показать весь месяц: недели колонками, пункты строками"))
        self.btn_month.toggled.connect(self._set_month_mode)
        toolbar_layout.addWidget(self.btn_month)

        # Переход по неделям без дерева: ‹ предыдущая, «Сегодня», следующая ›
        self.btn_prev_week = QPushButton("‹")
        self.btn_prev_week.setObjectName("btnPrevWeek")
        self.btn_prev_week.setProperty("iconButton", True)
        self.btn_prev_week.setToolTip(_("Предыдущая неделя (Alt+←)"))
        self.btn_prev_week.clicked.connect(lambda: self._step_week(-1))
        toolbar_layout.addWidget(self.btn_prev_week)

        self.btn_today = QPushButton(_("Сегодня"))
        self.btn_today.setObjectName("btnToday")
        self.btn_today.setToolTip(_("Перейти к текущей неделе (из «Месяца» — в вид недели)"))
        self.btn_today.clicked.connect(self._go_to_today)
        toolbar_layout.addWidget(self.btn_today)

        self.btn_next_week = QPushButton("›")
        self.btn_next_week.setObjectName("btnNextWeek")
        self.btn_next_week.setProperty("iconButton", True)
        self.btn_next_week.setToolTip(_("Следующая неделя (Alt+→)"))
        self.btn_next_week.clicked.connect(lambda: self._step_week(1))
        toolbar_layout.addWidget(self.btn_next_week)

        self.shortcut_prev_week = QShortcut(QKeySequence("Alt+Left"), self)
        self.shortcut_prev_week.activated.connect(lambda: self._step_week(-1))
        self.shortcut_next_week = QShortcut(QKeySequence("Alt+Right"), self)
        self.shortcut_next_week.activated.connect(lambda: self._step_week(1))

        self._refresh_meeting_start_minutes()

        self.btn_auto = QPushButton(_("🪄 Авто-распределение"))
        self.btn_auto.setObjectName("btnAuto")
        self.btn_auto.setToolTip(_("Автоматически назначить участников на пустые пункты"))
        self.btn_auto.clicked.connect(self._on_auto_assign)
        toolbar_layout.addWidget(self.btn_auto)

        self.btn_add_item = QPushButton(_("➕ Пункт"))
        self.btn_add_item.setObjectName("btnAddItem")
        self.btn_add_item.setToolTip(_("Добавить внеочередной пункт в расписание"))
        self.btn_add_item.clicked.connect(self._on_add_item)
        toolbar_layout.addWidget(self.btn_add_item)

        self.btn_undo = QPushButton()
        self.btn_undo.setIcon(
            QIcon.fromTheme("edit-undo", style.standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
        )
        self.btn_undo.setObjectName("btnUndo")
        self.btn_undo.setProperty("iconButton", True)
        self.btn_undo.setToolTip(_("Отменить последнее изменение расписания (Ctrl+Z)"))
        self.btn_undo.setEnabled(False)
        self.btn_undo.clicked.connect(self._on_undo)
        toolbar_layout.addWidget(self.btn_undo)

        self.btn_redo = QPushButton()
        self.btn_redo.setIcon(
            QIcon.fromTheme("edit-redo", style.standardIcon(QStyle.StandardPixmap.SP_ArrowForward))
        )
        self.btn_redo.setObjectName("btnRedo")
        self.btn_redo.setProperty("iconButton", True)
        self.btn_redo.setToolTip(_("Повторить отменённое изменение (Ctrl+Shift+Z)"))
        self.btn_redo.setEnabled(False)
        self.btn_redo.clicked.connect(self._on_redo)
        toolbar_layout.addWidget(self.btn_redo)

        self.shortcut_undo = QShortcut(QKeySequence("Ctrl+Z"), self)
        self.shortcut_undo.activated.connect(self._on_undo)
        self.shortcut_redo = QShortcut(QKeySequence("Ctrl+Shift+Z"), self)
        self.shortcut_redo.activated.connect(self._on_redo)
        self.shortcut_redo_alt = QShortcut(QKeySequence("Ctrl+Y"), self)
        self.shortcut_redo_alt.activated.connect(self._on_redo)

        self.btn_clear = QPushButton("🗑️")
        self.btn_clear.setObjectName("btnClear")
        self.btn_clear.setProperty("iconButton", True)
        self.btn_clear.setToolTip(_("Очистить: удалить все назначения на этой неделе"))
        self.btn_clear.clicked.connect(self._on_clear_week)
        toolbar_layout.addWidget(self.btn_clear)

        toolbar_layout.addStretch(1)

        # Печать сразу на принтер — о заданиях сообщают бумажными листками
        self.btn_print = QPushButton(_("🖨️ Печать"))
        self.btn_print.setObjectName("btnPrint")
        self.btn_print.setToolTip(_("Напечатать расписание на принтере (Ctrl+P)"))
        self.btn_print.clicked.connect(self._on_print)
        toolbar_layout.addWidget(self.btn_print)
        self.shortcut_print = QShortcut(QKeySequence(QKeySequence.StandardKey.Print), self)
        self.shortcut_print.activated.connect(self._on_print)

        # Экспорт: PDF и TXT — в один клик, остальное — в «Ещё»
        self.btn_export_pdf = QPushButton("📕 PDF")
        self.btn_export_pdf.setObjectName("btnExportPdf")
        self.btn_export_pdf.setToolTip(_("Экспорт расписания в PDF"))
        self.btn_export_pdf.clicked.connect(lambda: self._on_export("pdf"))
        toolbar_layout.addWidget(self.btn_export_pdf)

        self.btn_export_txt = QPushButton("📝 TXT")
        self.btn_export_txt.setObjectName("btnExportTxt")
        self.btn_export_txt.setToolTip(_("Экспорт расписания в текстовый файл"))
        self.btn_export_txt.clicked.connect(lambda: self._on_export("txt"))
        toolbar_layout.addWidget(self.btn_export_txt)

        self.btn_more = QPushButton(_("⋯ Ещё"))
        self.btn_more.setObjectName("btnMore")
        self.btn_more.setToolTip(_("Другие форматы экспорта"))
        more_menu = QMenu(self.btn_more)
        # В узком окне (планшет) печать, PDF и TXT уходят сюда — см. _fit_toolbar()
        self.action_print = more_menu.addAction(_("🖨️ Печать…"))
        self.action_print.triggered.connect(self._on_print)
        self.action_export_pdf = more_menu.addAction("📕 PDF…")
        self.action_export_pdf.triggered.connect(lambda: self._on_export("pdf"))
        self.action_export_txt = more_menu.addAction("📝 TXT…")
        self.action_export_txt.triggered.connect(lambda: self._on_export("txt"))
        self.action_export_docx = more_menu.addAction("📄 Word (DOCX)…")
        self.action_export_docx.triggered.connect(lambda: self._on_export("docx"))
        self.action_export_s89 = more_menu.addAction(_("🎟️ Советы S-89…"))
        self.action_export_s89.setToolTip(_("Быстрее: правый клик по месяцу в списке недель"))
        self.action_export_s89.triggered.connect(self._on_export_s89)
        self.btn_more.setMenu(more_menu)
        toolbar_layout.addWidget(self.btn_more)

        toolbar_layout.addSpacing(10)

        # Уведомления: основное действие + журнал в выпадающем меню
        self.btn_notify = QToolButton()
        self.btn_notify.setObjectName("btnNotify")
        self.btn_notify.setText(_("📨 Уведомить"))
        self.btn_notify.setToolTip(_("Отправить email-уведомления участникам об их заданиях"))
        self.btn_notify.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.btn_notify.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.btn_notify.clicked.connect(self._on_notify)
        notify_menu = QMenu(self.btn_notify)
        self.action_notif_log = notify_menu.addAction(_("📋 Журнал уведомлений"))
        self.action_notif_log.triggered.connect(lambda: self._open_notification_log())
        self.action_check_replies = notify_menu.addAction(_("📥 Проверить ответы"))
        self.action_check_replies.setToolTip(
            _("Прочитать во «Входящих» ответы «Подтверждаю» / «Не смогу»")
        )
        self.action_check_replies.triggered.connect(self._check_replies)
        self.btn_notify.setMenu(notify_menu)
        toolbar_layout.addWidget(self.btn_notify)

        self.right_layout.addWidget(self.toolbar_widget)
        self.toolbar_widget.installEventFilter(self)
        self._fit_toolbar()

        # 1. Страница редактирования (Всегда активна)
        self.right_panel = QScrollArea()
        self.right_panel.setObjectName("scheduleScroll")
        self.right_panel.setWidgetResizable(True)
        self.right_panel.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.form_widget = QWidget()
        self.form_layout = QVBoxLayout(self.form_widget)
        self.form_layout.setContentsMargins(8, 8, 8, 8)
        self.form_layout.setSpacing(6)
        self.form_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.right_panel.setWidget(self.form_widget)

        # 2. Доска месяца — вторая страница вместо формы недели
        self.month_board = MonthBoardView(self.facade)
        self.month_board.week_activated.connect(self._open_week_from_board)
        self.month_board.history_changed.connect(
            lambda: self._month_mode() and self._update_month_undo()
        )
        self.right_stack = QStackedWidget()
        self.right_stack.addWidget(self.right_panel)
        self.right_stack.addWidget(self.month_board)
        self.right_layout.addWidget(self.right_stack)

        self._show_empty_state()

        self.splitter.addWidget(self.right_container)
        self.splitter.setChildrenCollapsible(True)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([240, 1040])

        layout.addWidget(self.splitter)

        self._load_tree()

    def _refresh_meeting_start_minutes(self):
        self.meeting_start_minutes = parse_meeting_start(
            self.facade.get_setting("meeting_time", "19:00")
        )

    def _toggle_sidebar(self):
        show_sidebar = self.btn_toggle_sidebar.isChecked()
        self.left_panel.setVisible(show_sidebar)
        if show_sidebar:
            self.splitter.setSizes([240, 1040])
        else:
            self.splitter.setSizes([0, 1280])

    def _on_assignments_changed(self, event=None):
        """Handler for ASSIGNMENT_CHANGED event.

        SimpleEventBus.emit вызывает handler(event), где event — объект Event.
        Извлекаем week_id из event.data для обновления текущей недели.
        """
        from core.events_base import Event as EventData

        week_id = None
        if isinstance(event, EventData):
            data = event.data
            if isinstance(data, dict):
                # Данные могут быть в kwargs (старый API) или напрямую
                kwargs = data.get("kwargs")
                kwargs_dict = kwargs if isinstance(kwargs, dict) else {}
                week_id = kwargs_dict.get("week_id") or data.get("week_id")

        if self.current_week_id and (week_id is None or week_id == self.current_week_id):
            self._load_week_editor(self.current_week_id)
        if self._month_mode() and (week_id is None or week_id in self.month_board.week_ids):
            self.month_board.refresh()

    def _show_empty_state(self):
        self._clear_form()
        label = QLabel(_("👈 Выберите неделю из списка слева"))
        label.setObjectName("emptyStateLabel")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.form_layout.addWidget(label)

    def _on_theme_changed(self, theme) -> None:
        """Re-render what Qt cannot restyle from the stylesheet alone."""
        self._load_tree()
        if getattr(self, "current_week_id", None):
            self._load_week_editor(self.current_week_id)
        if self._month_mode():
            self._show_month_board()

    def _clear_form(self):
        while self.form_layout.count():
            child = self.form_layout.takeAt(0)
            if child.widget():
                # прячем сразу: deleteLater срабатывает позже, и до этого
                # старый виджет мог просвечивать поверх нового заголовка
                child.widget().hide()
                child.widget().deleteLater()

    def _load_tree(self, event=None):
        self.tree.clear()
        tree_data = self.facade.get_weeks_tree()

        last_week_id = self.facade.get_setting("last_selected_week")
        item_to_select = None

        today = datetime.now().date()
        current_week_item = None
        closest_past_week_item = None
        first_week_item = None
        self._week_items = []  # все недели по порядку — для ‹ ›

        colors_palette = palette()

        # tree_data is {year: {month: [weeks]}}
        for year, months_dict in tree_data.items():
            year_item = QTreeWidgetItem([f"📅 {year}"])
            year_item.setFont(0, QFont("", 12, QFont.Weight.Bold))
            year_item.setForeground(0, QColor(colors_palette.text_heading))

            for month_name, weeks_list in months_dict.items():
                month_item = QTreeWidgetItem([f"📆 {_(month_name)}"])
                month_item.setFont(0, QFont("", 11, QFont.Weight.Bold))
                month_item.setForeground(0, QColor(colors_palette.text_secondary))

                for week in weeks_list:
                    week_item = QTreeWidgetItem([f"  {week['title']}"])
                    week_id = week["id"]
                    week_item.setData(0, Qt.ItemDataRole.UserRole, week_id)
                    month_item.addChild(week_item)
                    self._week_items.append(week_item)

                    if first_week_item is None:
                        first_week_item = week_item

                    if last_week_id and str(week_id) == str(last_week_id):
                        item_to_select = week_item

                    # Проверка даты недели для автоматического фокуса на текущую неделю
                    w_start_str = week.get("start_date")
                    if w_start_str:
                        try:
                            w_start = datetime.strptime(w_start_str, "%Y-%m-%d").date()
                            # Если дата понедельника этой недели <= сегодня и до +6 дней (текущая неделя)
                            if w_start <= today and (today - w_start).days < 7:
                                current_week_item = week_item
                            elif w_start <= today:
                                closest_past_week_item = week_item
                        except ValueError:
                            pass

                year_item.addChild(month_item)

            self.tree.addTopLevelItem(year_item)

            # Разворачиваем текущий год по умолчанию
            current_year = datetime.now().year
            year_item.setExpanded(str(year) == str(current_year))

        # Приоритет выбора:
        # 1. Ранее сохраненная неделя пользователя
        # 2. Текущая неделя (сегодняшняя)
        # 3. Ближайшая прошедшая неделя
        # 4. Первая доступная неделя
        self._today_week_item = current_week_item or closest_past_week_item or first_week_item
        target_item = (
            item_to_select or current_week_item or closest_past_week_item or first_week_item
        )

        if target_item:
            # Разворачиваем родительские элементы (месяц, год) для выбранной недели
            parent = target_item.parent()
            while parent:
                parent.setExpanded(True)
                parent = parent.parent()

            self.tree.setCurrentItem(target_item)
            self.current_week_id = target_item.data(0, Qt.ItemDataRole.UserRole)
            self._load_week_editor(self.current_week_id)
            self.tree.scrollToItem(target_item)

    def _select_week_item(self, item) -> None:
        """Выделить неделю в дереве (раскрыв месяц и год) и открыть её."""
        parent = item.parent()
        while parent:
            parent.setExpanded(True)
            parent = parent.parent()
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)
        self._on_tree_item_clicked(item, 0)

    def _step_week(self, delta: int) -> None:
        if self._month_mode():
            self._step_month(delta)
            return
        items = getattr(self, "_week_items", [])
        ids = [it.data(0, Qt.ItemDataRole.UserRole) for it in items]
        if self.current_week_id not in ids:
            return
        index = ids.index(self.current_week_id) + delta
        if 0 <= index < len(items):
            self._select_week_item(items[index])

    def _go_to_today(self) -> None:
        """«Сегодня» — текущая неделя в обычном виде, и из режима «Месяц» тоже."""
        item = getattr(self, "_today_week_item", None)
        if item is None:
            return
        if self._month_mode():
            self.btn_month.setChecked(False)
        self._select_week_item(item)

    def _on_tree_item_clicked(self, item, column):
        week_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not week_id and self._month_mode() and item.childCount():
            # щелчок по месяцу в режиме «Месяц» — открыть этот месяц
            first = item.child(0)
            if first.data(0, Qt.ItemDataRole.UserRole):
                self._select_week_item(first)
            return
        if week_id:
            self.current_week_id = week_id
            self.facade.save_setting("last_selected_week", str(week_id))
            self._load_week_editor(week_id)
            if self._month_mode():
                self._show_month_board()

    # --- Режим «Месяц» ---

    def _month_mode(self) -> bool:
        return hasattr(self, "btn_month") and self.btn_month.isChecked()

    def _current_week_item(self):
        for item in getattr(self, "_week_items", []):
            if item.data(0, Qt.ItemDataRole.UserRole) == self.current_week_id:
                return item
        return None

    AUTO_TEXT_FULL = _("🪄 Авто-распределение")
    AUTO_TEXT_SHORT = _("🪄 Авто")

    def eventFilter(self, obj, event):
        # Show — тоже: на планшете окно открывается на «Сегодня», размер
        # вкладке задаётся, пока она скрыта, и Resize потом не приходит
        if obj is getattr(self, "toolbar_widget", None) and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Show,
        ):
            self._fit_toolbar()
        return super().eventFilter(obj, event)

    def _fit_toolbar(self) -> None:
        """Если кнопки не влезают (планшет, узкое окно) — короткая подпись
        «Авто», а PDF и TXT прячутся в меню «Ещё»; иначе Qt сжимает кнопки
        и обрезает надписи («Іеся», «егодн»)."""
        self.btn_auto.setText(self.AUTO_TEXT_FULL)
        self.btn_export_pdf.setVisible(True)
        self.btn_export_txt.setVisible(True)
        self.btn_print.setVisible(self._can_print())
        # пока окно не показано, ширина условная (640) — не сжимаем
        compact = (
            self.toolbar_widget.isVisible()
            and self.toolbar_layout.sizeHint().width() > self.toolbar_widget.width()
        )
        if compact:
            self.btn_auto.setText(self.AUTO_TEXT_SHORT)
        self.btn_export_pdf.setVisible(not compact)
        self.btn_export_txt.setVisible(not compact)
        self.btn_print.setVisible(self._can_print() and not compact)
        self.action_print.setVisible(self._can_print() and compact)
        self.action_export_pdf.setVisible(compact)
        self.action_export_txt.setVisible(compact)

    def _set_month_mode(self, on: bool) -> None:
        self.right_stack.setCurrentWidget(self.month_board if on else self.right_panel)
        # Эти кнопки работают с одной неделей — в режиме месяца их прячем;
        # «Авто-распределение» в месяце заполняет только пустые недели
        for button in (self.btn_add_item, self.btn_clear):
            button.setVisible(not on)
        # ↶ ↷ в месяце — правки на доске, затем откат распределения месяца к снимку
        if on:
            self._update_month_undo()
        else:
            self.btn_undo.setToolTip(_("Отменить последнее изменение расписания (Ctrl+Z)"))
            self._update_history_buttons()
        self.btn_auto.setToolTip(
            _("Заполнить пустые пункты месяца (назначенные не меняются)")
            if on
            else _("Автоматически назначить участников на пустые пункты")
        )
        self.btn_prev_week.setToolTip(
            _("Предыдущий месяц (Alt+←)") if on else _("Предыдущая неделя (Alt+←)")
        )
        self.btn_next_week.setToolTip(
            _("Следующий месяц (Alt+→)") if on else _("Следующая неделя (Alt+→)")
        )
        self._fit_toolbar()
        if on:
            self._show_month_board()

    def _show_month_board(self) -> None:
        item = self._current_week_item()
        month_item = item.parent() if item else None
        if month_item is None:
            self.month_board.show_weeks([])
            return
        week_ids = [
            month_item.child(i).data(0, Qt.ItemDataRole.UserRole)
            for i in range(month_item.childCount())
        ]
        year_item = month_item.parent()
        month = month_item.text(0).replace("📆", "").strip()
        year = year_item.text(0).replace("📅", "").strip() if year_item else ""
        self.month_board.show_weeks([w for w in week_ids if w], f"{month} {year}".strip())

    def _step_month(self, delta: int) -> None:
        months = []
        for item in getattr(self, "_week_items", []):
            parent = item.parent()
            if parent is not None and parent not in months:
                months.append(parent)
        current = self._current_week_item()
        if current is None or current.parent() not in months:
            return
        index = months.index(current.parent()) + delta
        if 0 <= index < len(months):
            self._select_week_item(months[index].child(0))

    def show_week(self, week_id: int, month: bool = False) -> None:
        """Открыть неделю (с пульта «Сегодня»): в обычном виде или на доске её месяца."""
        self.current_week_id = week_id
        item = self._current_week_item()
        if item is not None:
            self._select_week_item(item)
        if self.btn_month.isChecked() != month:
            self.btn_month.setChecked(month)

    def _open_week_from_board(self, week_id: int) -> None:
        self.current_week_id = week_id
        self.btn_month.setChecked(False)
        item = self._current_week_item()
        if item is not None:
            self._select_week_item(item)

    def _clean_worker(self):
        """Clean up finished worker from active list."""
        worker = self.sender()
        if worker and worker in self.active_workers:
            worker.wait()  # Ждем фактического завершения потока
            self.active_workers.remove(worker)
            import logging

            logger = logging.getLogger(__name__)
            logger.debug(f"Worker cleaned up. Remaining: {len(self.active_workers)}")

    def _find_assignment(self, assignments, num_key):
        """Ищет задание по номеру в списке заданий."""
        # assignments теперь list, не dict
        for a in assignments:
            assignment_num = str(a.get("assignment_number", ""))
            # Прямое совпадение
            if assignment_num == num_key:
                return a
            # С точкой (например "1.")
            if assignment_num == f"{num_key}.":
                return a
            # Начинается с num_key
            if assignment_num.startswith(num_key):
                return a
        return None

    def _load_week_editor(self, week_id):
        self._refresh_meeting_start_minutes()
        # Check special event
        special_event = self.facade.get_week_special_event(week_id)

        self.current_week_id = week_id

        # circuit_overseer (Посещение РС) проводится как обычная встреча с измененной программой,
        # поэтому для неё открывается полноценная форма недели, а не полноэкранная заглушка.
        if special_event and special_event != "circuit_overseer":
            self._show_special_event_placeholder(special_event)
            return

        self._load_week_form(week_id)

    @staticmethod
    def _count_assigned(assignments):
        return sum(
            1
            for assignment in assignments
            if assignment.get("participant_id")
            or assignment.get("assistant_id")
            or assignment.get("status") == "assigned"
        )

    def _build_week_header(self, week, assignments, is_co_week):
        """Одна строка: дата · чтение Библии … бейдж РС, заполненность, конфликты."""
        row = QWidget()
        row.setObjectName("weekHeader")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 2, 4, 6)
        layout.setSpacing(10)

        title = QLabel(week.get("week_title", _("Неделя")))
        title.setObjectName("headerLabel")
        layout.addWidget(title)

        if week.get("bible_reading"):
            bible = QLabel(f"·  📚 {week['bible_reading']}")
            bible.setObjectName("bibleReadingLabel")
            layout.addWidget(bible)

        layout.addStretch(1)

        if is_co_week:
            badge = QLabel(_("👔 Визит РС"))
            badge.setObjectName("weekBadge")
            badge.setToolTip(
                _(
                    "Посещение районного старейшины (РС): "
                    "Изучение Библии в собрании заменено служебной речью"
                )
            )
            layout.addWidget(badge)

        assigned, total = self._count_assigned(assignments), len(assignments)
        self.week_stats_label = QLabel(
            _("Назначено {assigned} из {total}", assigned=assigned, total=total)
        )
        self.week_stats_label.setObjectName("weekStats")
        self.week_stats_label.setProperty("complete", assigned >= total)
        layout.addWidget(self.week_stats_label)

        not_notified = self._not_notified_ids(assignments)
        if not_notified:
            # Главный способ сообщить о задании — бумажный листок на встрече,
            # письма — по случаю. Поэтому без предупреждающего счётчика:
            # только тихая кнопка, число — в подсказке.
            self.btn_notify_rest = QPushButton(_("✉️ Уведомить оставшихся"))
            self.btn_notify_rest.setObjectName("btnNotifyRest")
            self.btn_notify_rest.setFlat(True)
            self.btn_notify_rest.setToolTip(
                _("Письмо тем, кому на этой неделе ещё не писали: {n}", n=len(not_notified))
            )
            self.btn_notify_rest.clicked.connect(
                lambda: self._notify_participants(list(not_notified))
            )
            layout.addWidget(self.btn_notify_rest)

        waiting, declined = self._response_counts(assignments)
        if declined:
            declined_label = QLabel(_("❌ Не смогут: {n_declined}", n_declined=len(declined)))
            declined_label.setObjectName("weekConflicts")
            declined_label.setToolTip(
                _("Ответили на письмо, что не смогут:\n") + "\n".join(declined)
            )
            layout.addWidget(declined_label)
        if waiting:
            waiting_label = QLabel(_("⏳ Не подтвердили: {n_waiting}", n_waiting=len(waiting)))
            waiting_label.setObjectName("weekNotNotified")
            waiting_label.setToolTip(
                _("Письмо ушло, ответа ещё нет:\n")
                + "\n".join(waiting)
                + _("\n\nОтветы из почты: «Уведомить» ▾ → «Проверить ответы»")
            )
            layout.addWidget(waiting_label)

        conflicts = len(self.current_conflicts)
        if conflicts:
            conflicts_label = QLabel(_("⚠️ Конфликты: {conflicts}", conflicts=conflicts))
            conflicts_label.setObjectName("weekConflicts")
            conflicts_label.setToolTip(_("Участник назначен больше одного раза за неделю"))
            layout.addWidget(conflicts_label)

        return row

    @staticmethod
    def _event_name(event_type):
        return {
            "memorial": _("Вечеря Господня"),
            "circuit_assembly": _("Районный конгресс"),
            "regional_convention": _("Региональный конгресс"),
            "circuit_overseer": _("Посещение районного старейшины (РС)"),
        }.get(event_type, _("Особое событие"))

    def _show_special_event_placeholder(self, event_type):
        self._clear_form()

        colors = {
            **event_colors(),
        }
        titles = {
            "memorial": _("🍷 Вечеря Господня"),
            "circuit_assembly": _("🏟️ Районный Конгресс"),
            "regional_convention": _("🌍 Региональный Конгресс"),
        }
        messages = {
            "memorial": _("На этой неделе обычная встреча не проводится."),
            "circuit_assembly": _("Встреча отменена в связи с конгрессом."),
            "regional_convention": _("Встреча отменена в связи с конгрессом."),
        }

        container = QFrame()
        container.setStyleSheet(
            f"background-color: {colors.get(event_type, palette().text_secondary)}; border-radius: 10px;"
        )
        layout = QVBoxLayout(container)

        title = QLabel(titles.get(event_type, _("Особое событие")))
        # В тёмной теме цвета событий светлые, поэтому текст берём контрастный из палитры
        on_event = palette().on_accent
        title.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {on_event};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        msg = QLabel(messages.get(event_type, ""))
        msg.setStyleSheet(f"font-size: 14px; color: {on_event};")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(msg)
        layout.addStretch()

        self.form_layout.addWidget(container)

    def _load_week_form(self, week_id):
        from core.assignment_classifier import AssignmentClassifier

        data = self.facade.get_week_data(week_id)
        if not data:
            return

        self.current_week_data = data
        self.current_conflicts = self.facade.get_week_conflicts(week_id)
        try:
            self.current_notif_statuses = self.facade.get_week_notification_statuses(week_id)
        except Exception:
            self.current_notif_statuses = {}
        self._clear_form()

        week = data["week"]
        assignments = data["assignments"]

        # Неделя районного старейшины: вместо Изучения Библии — Служебная речь РС
        assignments, is_co_week = apply_circuit_overseer_week(week, assignments)

        self.form_layout.addWidget(self._build_week_header(week, assignments, is_co_week))

        # Порядок пунктов — общий с просмотром недели и PDF (core/week_layout.py)
        classifier = AssignmentClassifier()
        section_palette = section_colors()
        section_meta = {key: (title, color) for key, title, color in SECTION_ORDER}
        other = (_("Прочее"), section_palette.get("other", ""))
        ordered_assignments = [
            (*section_meta.get(section_key, other), assignment)
            for section_key, assignment in order_week_assignments(assignments, classifier)
        ]

        self._populate_assignment_table(ordered_assignments, classifier)

        # --- Modules Injection ---
        if hasattr(self.facade, "registry"):
            for module in self.facade.registry.get_enabled(self.facade):
                try:
                    widget = module.get_week_widget(week_id, self.facade)
                    if widget:
                        self.form_layout.addWidget(widget)
                except Exception as e:
                    import logging

                    logging.getLogger(__name__).error(
                        f"Error loading module widget {module.id}: {e}"
                    )

    def _capture_schedule_state(self):
        if not self.current_week_id:
            return None
        data = self.facade.get_week_data(self.current_week_id)
        if not data:
            return None
        return deepcopy(data.get("assignments", []))

    def _record_undo_state(self):
        state = self._capture_schedule_state()
        if state is None:
            return
        self._undo_stack.append(state)
        self._undo_stack = self._undo_stack[-30:]
        self._redo_stack.clear()
        self._update_history_buttons()

    def _update_history_buttons(self):
        self.btn_undo.setEnabled(bool(self._undo_stack))
        self.btn_redo.setEnabled(bool(self._redo_stack))

    def _restore_schedule_state(self, state):
        if self.facade.replace_week_assignments(self.current_week_id, state):
            self._load_week_editor(self.current_week_id)
        self._update_history_buttons()

    def _on_undo(self):
        if self._month_mode():
            self._undo_month()
            return
        if not self._undo_stack:
            return
        current = self._capture_schedule_state()
        state = self._undo_stack.pop()
        if current is not None:
            self._redo_stack.append(current)
        self._restore_schedule_state(state)

    def _on_redo(self):
        if self._month_mode():
            if not self._month_busy:
                self.month_board.redo()
            return
        if not self._redo_stack:
            return
        current = self._capture_schedule_state()
        state = self._redo_stack.pop()
        if current is not None:
            self._undo_stack.append(current)
        self._restore_schedule_state(state)

    def _populate_assignment_table(self, rows, classifier):
        row_assignments = [assignment for _, _, assignment in rows]
        start_minutes_by_assignment = {
            assignment.get("id", id(assignment)): start
            for assignment, start in zip(
                row_assignments, start_minutes(row_assignments, self.meeting_start_minutes)
            )
        }

        table = ReorderableTableWidget(len(rows), 7)
        table.setObjectName("assignmentTable")
        table.setHorizontalHeaderLabels(
            [
                tr("Раздел"),
                "№",
                tr("Назначение"),
                tr("Начало"),
                tr("Время"),
                tr("Участник"),
                tr("Напарник"),
            ]
        )
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self._on_table_context_menu)
        self.shortcut_enter = QShortcut(QKeySequence("Return"), table)
        self.shortcut_enter.activated.connect(self._on_table_enter)
        self.shortcut_enter_alt = QShortcut(QKeySequence("Enter"), table)
        self.shortcut_enter_alt.activated.connect(self._on_table_enter)
        self.shortcut_delete = QShortcut(QKeySequence("Del"), table)
        self.shortcut_delete.activated.connect(self._on_table_delete)
        self.shortcut_edit = QShortcut(QKeySequence("F2"), table)
        self.shortcut_edit.activated.connect(self._on_table_edit)
        table.setAlternatingRowColors(True)
        table.setWordWrap(True)
        table.setMinimumHeight(360)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        # «Назначение», «Участник» и «Напарник» делят свободную ширину поровну:
        # при фиксированных 220 px на узком экране (планшет) «Назначение» сжималось до «…»
        table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)

        colors_palette = palette()
        section_palette = section_colors()

        self._assignment_rows = {}
        self._table_assignments = {}
        self._conflicted_assignment_ids = set()
        row_assignment_ids = []
        conflict_color = QColor(colors_palette.conflict_background)

        for row_number, (section, color, assignment) in enumerate(rows):
            assignment_id = assignment.get("id")
            assignment_key = assignment.get("id", id(assignment))
            raw_number = str(assignment.get("assignment_number") or "")
            # служебные ключи вроде «chairman» или «prayer_open» номером не являются
            number = raw_number if raw_number.isdigit() else ""
            label = assignment_label(assignment.get("assignment_text") or tr("Назначение"))
            text = classifier.strip_leading_number(label, raw_number)

            section_item = QTableWidgetItem(section)
            section_item.setForeground(QColor(section_palette.get(color, color)))
            section_item.setFont(QFont("", 10, QFont.Weight.Bold))
            number_item = QTableWidgetItem(number)
            number_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            text_item = QTableWidgetItem(text)
            text_item.setToolTip(label)
            # Чтец ИБС читает вместе с ведущим — своего времени у него нет
            is_reader = assignment.get("assignment_type") == "cbs_reader"
            start_item = QTableWidgetItem(
                ""
                if is_reader
                else self._format_minutes(
                    start_minutes_by_assignment.get(assignment_key, self.meeting_start_minutes)
                )
            )
            start_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            duration = assignment.get("duration")
            duration_value = int(duration) if duration not in (None, "") else 0
            duration_spin = QSpinBox()
            duration_spin.setObjectName(f"duration_{assignment_id}")
            duration_spin.setRange(0, 180)
            duration_spin.setSuffix(tr(" мин"))
            duration_spin.setSpecialValueText("—")
            duration_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
            duration_spin.setKeyboardTracking(False)
            duration_spin.setValue(duration_value)
            if assignment_id is not None:
                duration_spin.editingFinished.connect(
                    lambda spin=duration_spin, aid=assignment_id: self._on_duration_edited(
                        aid, spin
                    )
                )
            else:
                duration_spin.setEnabled(False)

            for column, item in enumerate((section_item, number_item, text_item)):
                if assignment_id is not None:
                    item.setData(Qt.ItemDataRole.UserRole, assignment_id)
                table.setItem(row_number, column, item)
            table.setItem(row_number, 3, start_item)
            # Председатель и молитвы не длятся отдельно — поле «—» им ни к чему
            if not is_reader and (number or duration_value):
                table.setCellWidget(row_number, 4, duration_spin)
            else:
                duration_spin.deleteLater()
                table.setItem(row_number, 4, QTableWidgetItem(""))

            participant_cell = self._create_cell(
                assignment_id,
                assignment.get("participant_name"),
                assignment.get("participant_id"),
            )
            table.setCellWidget(row_number, 5, participant_cell)

            if classifier.needs_assistant(assignment):
                assistant_cell = self._create_cell(
                    assignment_id,
                    assignment.get("assistant_name"),
                    assignment.get("assistant_id"),
                    "assistant",
                )
                table.setCellWidget(row_number, 6, assistant_cell)
            else:
                assistant_item = QTableWidgetItem("—")
                assistant_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row_number, 6, assistant_item)

            participant_id = assignment.get("participant_id")
            assistant_id = assignment.get("assistant_id")
            conflicts = getattr(self, "current_conflicts", set())
            if participant_id in conflicts or assistant_id in conflicts:
                if assignment_id is not None:
                    self._conflicted_assignment_ids.add(assignment_id)
                for column in range(4):
                    item = table.item(row_number, column)
                    if item:
                        item.setBackground(conflict_color)
                duration_spin.setStyleSheet(
                    f"background-color: {colors_palette.conflict_background};"
                )
                text_item.setToolTip(tr("Конфликт: участник уже назначен в эту неделю"))

            if assignment_id is not None:
                self._assignment_rows[assignment_id] = row_number
                self._table_assignments[assignment_id] = assignment
                row_assignment_ids.append(assignment_id)
            # Кнопке участника — высота строки текста с запасом на «ножки» букв
            # плюс отступы ячейки (::item padding 6px) и рамка
            cell_text = participant_cell.fontMetrics().height()
            table.setRowHeight(row_number, max(38, cell_text + 22))

        table._row_assignment_ids = row_assignment_ids
        table.reorder_callback = self._on_assignment_rows_reordered
        table.setDragEnabled(bool(row_assignment_ids))
        self.assignment_table = table
        self.form_layout.addWidget(table)

    @staticmethod
    def _format_minutes(total_minutes: int) -> str:
        total_minutes %= 24 * 60
        return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"

    @staticmethod
    def _strip_leading_number(text: str, num: str) -> str:
        """Убирает дублирующий номер из текста задания.

        Если assignment_text='4. Начинайте разговор' и num='4',
        возвращает 'Начинайте разговор' (без дубля '4. 4. ...')
        """
        prefix = f"{num}."
        if text.startswith(prefix):
            stripped = text[len(prefix) :].strip()
            if stripped and not stripped.startswith(")"):
                return stripped
        return text

    def _create_cell(
        self, assignment_id, participant_name, participant_id=None, role="participant"
    ):
        has_conflict = False
        if participant_id and participant_id in getattr(self, "current_conflicts", set()):
            has_conflict = True

        notif_info = None
        notif_status = None
        if participant_id and hasattr(self, "current_notif_statuses"):
            notif_info = self.current_notif_statuses.get(participant_id)
            if notif_info:
                notif_status = notif_info.get("status")

        on_open_log = (
            (lambda pid=participant_id: self._open_notification_log(pid))
            if participant_id
            else None
        )
        on_send_email = (
            (
                lambda pid=participant_id, pname=participant_name: self._open_participant_email(
                    pid, pname
                )
            )
            if participant_id
            else None
        )

        return AssignmentCell(
            assignment_id,
            participant_name,
            self._on_cell_click,
            role,
            has_conflict,
            notif_status=notif_status,
            notif_info=notif_info,
            on_open_log=on_open_log,
            on_send_email=on_send_email,
            on_clear=(
                (lambda aid=assignment_id, r=role: self._clear_cell(aid, r))
                if participant_id
                else None
            ),
            on_set_response=(
                (
                    lambda value, pid=participant_id: self.facade.set_notification_response(
                        pid, self.current_week_id, value
                    )
                )
                if participant_id and self.current_week_id
                else None
            ),
        )

    def _clear_cell(self, assignment_id, role):
        self._record_undo_state()
        self.facade.assign_participant(assignment_id, None, role)
        self._load_week_editor(self.current_week_id)

    def _on_cell_click(self, assignment_id, role):
        dialog = ParticipantSelectDialog(
            self, self.facade, assignment_id=assignment_id, role=role, title=_("Выбор участника")
        )
        if dialog.exec():
            selected_id = dialog.get_selected_id()
            if not confirm_assignment(self, self.facade, assignment_id, selected_id):
                return
            self._record_undo_state()
            self.facade.assign_participant(assignment_id, selected_id, role)
            self._load_week_editor(self.current_week_id)  # Обновляем UI после назначения

        # Errors handled by error_service

    def statusBar(self):
        # Helper to try to reach main window status bar
        parent = self.window()
        if parent is not None and parent is not self and hasattr(parent, "statusBar"):
            return parent.statusBar()
        return None

    def _show_context_menu(self, position):
        item = self.tree.itemAt(position)
        if not item:
            return

        week_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not week_id:
            self._show_month_context_menu(item, position)
            return

        from PySide6.QtGui import QAction

        menu = QMenu()

        # Determine current event
        current_event = self.facade.get_week_special_event(week_id)

        action_normal = QAction(_("Обычная неделя"), self)
        action_memorial = QAction(_("🍷 Вечеря Господня"), self)
        action_circuit = QAction(_("🏟️ Районный конгресс"), self)
        action_regional = QAction(_("🌍 Региональный конгресс"), self)
        action_co = QAction(_("👔 Посещение районного старейшины (РС)"), self)

        action_normal.setCheckable(True)
        action_memorial.setCheckable(True)
        action_circuit.setCheckable(True)
        action_regional.setCheckable(True)
        action_co.setCheckable(True)

        if current_event == "memorial":
            action_memorial.setChecked(True)
        elif current_event == "circuit_assembly":
            action_circuit.setChecked(True)
        elif current_event == "regional_convention":
            action_regional.setChecked(True)
        elif current_event == "circuit_overseer":
            action_co.setChecked(True)
        else:
            action_normal.setChecked(True)

        action_normal.triggered.connect(lambda: self._set_special_event(week_id, None))
        action_memorial.triggered.connect(lambda: self._set_special_event(week_id, "memorial"))
        action_circuit.triggered.connect(
            lambda: self._set_special_event(week_id, "circuit_assembly")
        )
        action_regional.triggered.connect(
            lambda: self._set_special_event(week_id, "regional_convention")
        )
        action_co.triggered.connect(lambda: self._set_special_event(week_id, "circuit_overseer"))

        menu.addAction(action_normal)
        menu.addSeparator()
        menu.addAction(action_memorial)
        menu.addAction(action_circuit)
        menu.addAction(action_regional)
        menu.addAction(action_co)

        menu.exec(self.tree.viewport().mapToGlobal(position))

    def _show_month_context_menu(self, item, position):
        """Меню месяца в дереве: S-89 сразу на все недели месяца."""
        week_ids = [
            item.child(i).data(0, Qt.ItemDataRole.UserRole) for i in range(item.childCount())
        ]
        week_ids = [wid for wid in week_ids if wid]
        if not week_ids:
            return  # Год или пустой месяц

        month_name = item.text(0).replace("📆", "").strip()
        menu = QMenu(self)
        action_s89 = menu.addAction(_("🎟️ Советы S-89 за {v}…", v=month_name.lower()))
        action_s89.triggered.connect(lambda: self._export_s89_for_weeks(week_ids))
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def _set_special_event(self, week_id, event_type):
        success = self.facade.set_special_event(week_id, event_type)
        if success:
            sb = self.statusBar()
            if sb:
                sb.showMessage(_("Тип недели обновлен"), 3000)
            # If this is the currently selected week, reload right panel
            if self.current_week_id == week_id:
                self._load_week_editor(week_id)
        else:
            QMessageBox.warning(self, _("Ошибка"), _("Не удалось сохранить тип недели"))

    def closeEvent(self, event):
        """Graceful shutdown для всех активных воркеров."""
        for worker in self.active_workers:
            if worker.isRunning():
                worker.quit()
                worker.wait(1000)  # Ждём макс 1 сек
        self.active_workers.clear()
        super().closeEvent(event)
