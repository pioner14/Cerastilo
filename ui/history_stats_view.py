"""Вкладка «История и статистика»: две страницы под одной вкладкой.

История заданий человека и тепловая карта нагрузки — про одно и то же
(кто когда выступал), поэтому по просьбе владельца (24.11) они вместе.
"""

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from core.i18n import _
from ui.history_view import HistoryView
from ui.statistics_view import StatisticsView


class HistoryStatsView(QWidget):
    def __init__(self, facade, parent=None):
        super().__init__(parent)
        self.history_view = HistoryView(facade=facade)
        self.statistics_view = StatisticsView(facade=facade)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.pages = QTabWidget()
        self.pages.setObjectName("historyStatsPages")
        self.pages.setDocumentMode(True)
        self.pages.addTab(self.history_view, _("🕒 История"))
        self.pages.addTab(self.statistics_view, _("📊 Статистика"))
        self.pages.currentChanged.connect(lambda _i: self.load_data())
        layout.addWidget(self.pages)

    def load_data(self) -> None:
        """Обновить открытую страницу (вызывается при переходе на вкладку)."""
        page = self.pages.currentWidget()
        if page is self.history_view:
            page.load_participants()
        else:
            page.load_data()

    def help_key(self) -> str:
        """Глава справки по открытой странице."""
        return "history" if self.pages.currentWidget() is self.history_view else "statistics"
