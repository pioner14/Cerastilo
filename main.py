import os
import sys

if sys.platform == "win32" and getattr(sys, "frozen", False) and "DB_PATH" not in os.environ:
    data_dir = os.path.join(os.environ["LOCALAPPDATA"], "Cerastilo")
    os.makedirs(data_dir, exist_ok=True)
    os.environ["DB_PATH"] = os.path.join(data_dir, "scheduler.db")

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core import update_check
from core.container import Container
from core.events import Event
from core.styles import Theme, ThemeManager, apply_theme
from core.version import APP_VERSION
from core.workers import TaskWorker
from ui.assignment_config_view import AssignmentConfigView
from ui.history_view import HistoryView
from ui.leader_dashboard_view import LeaderDashboardView
from ui.participants_view import ParticipantsView
from ui.schedule_view import ScheduleView
from ui.settings_view import SettingsView
from ui.statistics_view import StatisticsView
from core.i18n import _, tr


class MainWindow(QMainWindow):
    def __init__(self, facade, container=None):
        super().__init__()
        self.facade = facade
        self._update_worker = None

        self.setWindowTitle(_("Cerastilo - Планировщик Встреч"))
        self.resize(1280, 800)
        self.setMinimumSize(1000, 700)
        if sys.platform != "darwin":  # Maximize on non-macOS usually works better for this app type
            self.showMaximized()

        # Главный виджет и слой
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # Создаем вкладки
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.layout.addWidget(self.tabs)

        # Добавляем страницы
        # Внедряем зависимости через Фасад
        self.schedule_view = ScheduleView(facade=self.facade)

        # Остальные view пока используют старый подход (db глобально или внутри),
        # будем рефакторить их постепенно.
        self.participants_view = ParticipantsView(facade=self.facade)
        self.history_view = HistoryView(facade=self.facade)
        self.statistics_view = StatisticsView(facade=self.facade)
        self.config_view = AssignmentConfigView(facade=self.facade)
        self.settings_view = SettingsView(facade=self.facade)
        # Импорт EPUB — раздел «Настроек», отдельной вкладки больше нет
        self.workbook_view = self.settings_view.workbook_view

        # Пульт руководителя встречи (того, кто составляет расписание) — первым
        self.dashboard_view = LeaderDashboardView(facade=self.facade)
        self.tabs.addTab(self.dashboard_view, _("🏠 Сегодня"))
        self.tabs.addTab(self.schedule_view, _("📅 Расписание"))
        self.tabs.addTab(self.participants_view, _("👥 Возвещатели"))
        self.tabs.addTab(self.history_view, _("🕒 История"))
        self.tabs.addTab(self.statistics_view, _("📊 Статистика"))
        # self.tabs.addTab(self.config_view, "🛠️ Квалификации") # Скрыл по просьбе, т.к. используется редко

        self.tabs.addTab(self.settings_view, _("⚙️ Настройки"))

        self._setup_help()

        # При переключении на вкладку истории - обновляем список
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Статусбар
        self.statusBar().showMessage(_("Готово"))

        # Сигналы
        self.workbook_view.import_finished.connect(self.schedule_view._load_tree)
        self.dashboard_view.open_week.connect(lambda wid: self._open_schedule(wid, month=False))
        self.dashboard_view.open_month.connect(lambda wid: self._open_schedule(wid, month=True))
        self.dashboard_view.open_workbooks.connect(self._open_workbooks)
        self.dashboard_view.open_tab.connect(
            lambda name: (
                self._open_workbooks()
                if name == "workbooks"
                else self.tabs.setCurrentWidget(
                    {
                        "settings": self.settings_view,
                        "participants": self.participants_view,
                        "schedule": self.schedule_view,
                    }.get(name, self.dashboard_view)
                )
            )
        )
        self.dashboard_view.load_data()

        # Centralized Error Handling
        self.facade.events.subscribe(Event.ERROR_OCCURRED, self._on_error)

    def schedule_update_check(self) -> None:
        if "PYTEST_CURRENT_TEST" not in os.environ:
            QTimer.singleShot(3000, self, self._check_updates)

    def _check_updates(self) -> None:
        if not self.isVisible() or not update_check.should_auto_check():
            return
        self._update_worker = TaskWorker(update_check.fetch_latest)
        self._update_worker.finished.connect(self._show_update_notice)
        self._update_worker.start()

    def _show_update_notice(self, result: dict) -> None:
        if "version" not in result:
            return
        update_check.mark_checked()
        version = result["version"]
        if not self.isVisible() or not update_check.is_newer(version, APP_VERSION):
            return
        notice = QMessageBox(self)
        notice.setWindowTitle(_("⬆️ Обновления"))
        notice.setIcon(QMessageBox.Icon.Information)
        notice.setText(
            _(
                "Доступна новая версия Cerastilo {v}. Сейчас установлена {current}.",
                v=version,
                current=APP_VERSION,
            )
        )
        download = notice.addButton(_("Скачать"), QMessageBox.ButtonRole.ActionRole)
        later = notice.addButton(_("Позже"), QMessageBox.ButtonRole.RejectRole)
        notice.setDefaultButton(later)
        notice.setEscapeButton(later)
        notice.buttonClicked.connect(
            lambda button: button == download and QDesktopServices.openUrl(QUrl(result["url"]))
        )
        notice.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        notice.setModal(False)
        notice.show()

    def wait_for_update_checks(self) -> None:
        if self._update_worker is not None:
            self._update_worker.wait()
        self.settings_view.wait_for_update_check()

    def _open_workbooks(self) -> None:
        """«Настройки» → раздел «📚 Рабочие тетради» (импорт EPUB)."""
        self.tabs.setCurrentWidget(self.settings_view)
        self.settings_view.show_workbooks()

    def _setup_help(self) -> None:
        """Кнопка «❓ Справка» справа от вкладок и F1: руководство на главе текущей вкладки."""
        from core.help_docs import tr
        from core.i18n import language

        self.help_language = language()
        self._help_sections = {
            self.dashboard_view: "dashboard",
            self.schedule_view: "schedule",
            self.participants_view: "participants",
            self.history_view: "history",
            self.statistics_view: "statistics",
            self.settings_view: "settings",
        }
        self.help_button = QToolButton()
        self.help_button.setText(tr("button", self.help_language))
        self.help_button.setToolTip(tr("button_tip", self.help_language))
        self.help_button.setAutoRaise(True)
        self.help_button.clicked.connect(self.show_help)
        self.tabs.setCornerWidget(self.help_button)
        QShortcut(QKeySequence(QKeySequence.StandardKey.HelpContents), self).activated.connect(
            self.show_help
        )

    def show_help(self) -> None:
        from core.help_docs import TAB_SECTIONS
        from ui.help_dialog import show_help

        key = self._help_sections.get(self.tabs.currentWidget())
        show_help(self, TAB_SECTIONS.get(key) if key else None, self.help_language)

    def _on_error(self, message, context="", **kwargs):
        from PySide6.QtWidgets import QMessageBox

        if hasattr(message, "data"):
            event = message
            data = event.data
            message = ""
            context = ""
            if isinstance(data, dict):
                kwargs_data = data.get("kwargs", {})
                message = kwargs_data.get("message") or data.get("message", "")
                context = kwargs_data.get("context") or data.get("context", "")
            else:
                message = str(data)

        QMessageBox.critical(
            self, _("Ошибка: {context}", context=context) if context else _("Ошибка"), str(message)
        )

    def _open_schedule(self, week_id: int, month: bool) -> None:
        self.tabs.setCurrentWidget(self.schedule_view)
        self.schedule_view.show_week(week_id, month=month)

    def _on_tab_changed(self, index):
        """Обновляет данные во вкладке при переключении."""
        widget = self.tabs.widget(index)
        if hasattr(widget, "load_participants"):
            widget.load_participants()
        elif hasattr(widget, "load_data"):
            widget.load_data()


def _shutdown(app, window, container) -> None:
    """Аккуратное закрытие до того, как PySide начнёт разбирать QApplication.

    Иначе при выходе бывало «Segmentation fault» (crash.log, 09.11:
    PySide::destroyQCoreApplication → visitAllPyObjects): глобальная шина
    событий (QObject без родителя) держала методы уже удалённых виджетов,
    а окно и наблюдатель темы жили в глобальных переменных модуля.
    """
    from PySide6.QtCore import QCoreApplication, QEvent

    from core.events import reset_event_bus

    window.wait_for_update_checks()
    bus = getattr(container, "event_bus", None)
    handlers = getattr(bus, "_handlers", None)
    if isinstance(handlers, dict):
        handlers.clear()
    reset_event_bus()
    watcher = getattr(app, "_system_theme_watcher", None)
    if watcher is not None:
        app._system_theme_watcher = None
        watcher.deleteLater()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def main() -> int:
    import os

    from core.config import get_data_dir
    from ui.crash_handler import install_crash_handler

    install_crash_handler(os.path.join(get_data_dir(), "crash.log"))
    app = QApplication(sys.argv)
    # Значок в панели задач: на Wayland app_id = имя .desktop-файла (cerastilo.desktop),
    # иначе панель показывает значок Python
    app.setApplicationName("cerastilo")
    app.setDesktopFileName("cerastilo")
    from PySide6.QtGui import QIcon

    app.setWindowIcon(
        QIcon(os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.png"))
    )
    from ui.translations import install_qt_translator

    install_qt_translator(app)

    # Отключаем нативные диалоговые окна ОС во избежание зависаний/блокировок на Linux/NixOS
    import traceback

    app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)

    container = None
    try:
        # Initialize DI Container
        container = Container()

        # Apply theme (load from settings or detect system theme)
        theme_manager = ThemeManager(container.facade)
        saved_theme = theme_manager.load_saved_theme()
        # Без сохранения: в настройку пишет только явный выбор в «Настройках»,
        # иначе однажды определённая системная тема залипала навсегда.
        apply_theme(app, saved_theme)

        # «Как в системе»: следим за сменой темы в KDE/GNOME и применяем её сразу
        from core.styles import get_system_theme
        from ui.theme_watcher import SystemThemeWatcher

        def _follow_system_theme():
            if container.facade.get_setting("theme", "system") == "system":
                apply_theme(app, get_system_theme())

        app._system_theme_watcher = SystemThemeWatcher(_follow_system_theme, parent=app)

        # Run module migrations BEFORE creating UI which might query DB
        with container.db_manager.get_session() as session:
            container.facade.run_module_migrations(session)

        window = MainWindow(facade=container.facade, container=container)
        window.show()
        window.schedule_update_check()
        code = app.exec()
        _shutdown(app, window, container)
        return code
    except Exception as e:
        error_msg = _(
            "Критическая ошибка при запуске приложения:\n\n{v}\n\n{v2}",
            v=str(e),
            v2=traceback.format_exc(),
        )
        QMessageBox.critical(None, _("Ошибка запуска"), error_msg)
        return 1
    finally:
        if container is not None:
            container.db_manager.close()


if __name__ == "__main__":
    sys.exit(main())
