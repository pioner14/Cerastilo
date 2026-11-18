from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QSplitter,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QLabel,
    QHeaderView,
    QLineEdit,
    QFrame,
)
from PySide6.QtCore import Qt
from core.facade import ApplicationFacade
from core.i18n import _


class HistoryView(QWidget):
    def __init__(self, facade: ApplicationFacade):
        super().__init__()
        self.facade = facade
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 10, 10, 10)

        # Заголовок
        header = QLabel(_("🕒 История назначений"))
        header.setObjectName("headerLabel")
        self.layout.addWidget(header)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        # === ЛЕВАЯ ПАНЕЛЬ: СПИСОК УЧАСТНИКОВ ===
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 5, 0)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(_("🔍 Поиск участника..."))
        self.search_input.textChanged.connect(self._filter_list)
        left_layout.addWidget(self.search_input)

        self.list_widget = QListWidget()
        self.list_widget.currentRowChanged.connect(self._on_participant_selected)
        left_layout.addWidget(self.list_widget)

        self.splitter.addWidget(left_panel)

        # === ПРАВАЯ ПАНЕЛЬ: ИСТОРИЯ ===
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(5, 0, 0, 0)

        # Инфо-блок выбранного участника
        self.info_frame = QFrame()
        self.info_frame.setObjectName("infoFrame")
        self.info_layout = QVBoxLayout(self.info_frame)
        self.info_layout.setContentsMargins(15, 10, 15, 10)

        self.name_label = QLabel(_("Выберите участника слева"))
        self.name_label.setObjectName("infoNameLabel")
        self.info_layout.addWidget(self.name_label)

        self.stats_label = QLabel("")
        self.stats_label.setObjectName("statsLabel")
        self.info_layout.addWidget(self.stats_label)

        right_layout.addWidget(self.info_frame, 0)

        # Таблица истории
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            [_("Дата"), _("Неделя"), _("Задание"), _("Роль / Напарник")]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)

        right_layout.addWidget(self.table, 1)

        self.splitter.addWidget(right_panel)
        self.splitter.setSizes([250, 750])

        self.layout.addWidget(self.splitter, 1)

        self._load_participants()

    def load_participants(self):
        """Перечитать участников и историю (главное окно вызывает при переходе
        на вкладку): выбранный участник и фильтр поиска сохраняются."""
        current = self.list_widget.currentItem()
        self._load_participants(current.data(Qt.ItemDataRole.UserRole) if current else None)
        self._filter_list(self.search_input.text())

    def _load_participants(self, select_id=None):
        """Загружает список участников в левую панель."""
        self.list_widget.clear()
        participants = self.facade.get_participants_list()
        row = 0
        for i, p in enumerate(participants):
            item = QListWidgetItem(p["name"])
            item.setData(Qt.ItemDataRole.UserRole, p["id"])
            self.list_widget.addItem(item)
            if p["id"] == select_id:
                row = i

        # Прежний участник или первый по умолчанию (если список не пуст)
        if self.list_widget.count() > 0:
            if self.list_widget.currentRow() == row:
                self._on_participant_selected(row)  # сигнал не придёт, а история могла измениться
            else:
                self.list_widget.setCurrentRow(row)

    def _filter_list(self, text):
        """Простая фильтрация списка по имени."""
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item.setHidden(text.lower() not in item.text().lower())

    def _on_participant_selected(self, index):
        if index < 0:
            return

        item = self.list_widget.item(index)
        p_id = item.data(Qt.ItemDataRole.UserRole)
        p_name = item.text()

        self.name_label.setText(p_name)
        self._load_history(p_id)

    def _load_history(self, p_id):
        """Загружает историю для конкретного участника."""
        history = self.facade.get_participant_history(p_id)
        self.table.setRowCount(0)

        total_count = len(history)
        raw_last = history[0]["date"] if history else None
        last_date = (
            raw_last.strftime("%d.%m.%Y")
            if hasattr(raw_last, "strftime")
            else (str(raw_last) if raw_last else _("никогда"))
        )

        self.stats_label.setText(
            _(
                "Всего назначений: {total_count}  |  Последнее: {last_date}",
                total_count=total_count,
                last_date=last_date,
            )
        )

        for i, entry in enumerate(history):
            self.table.insertRow(i)

            # Дата (центр) — ensure string format
            date_val = entry["date"]
            date_str = (
                date_val.strftime("%d.%m.%Y") if hasattr(date_val, "strftime") else str(date_val)
            )
            date_item = QTableWidgetItem(date_str)
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(i, 0, date_item)

            # Неделя
            self.table.setItem(i, 1, QTableWidgetItem(entry["week_title"]))

            # Задание
            self.table.setItem(i, 2, QTableWidgetItem(entry["assignment_text"]))

            # Роль
            self.table.setItem(i, 3, QTableWidgetItem(entry["role"]))
