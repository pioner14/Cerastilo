"""Точка входа Android: то же главное окно, что у десктопа (main.py).

android/build_apk.sh собирает в android/build_src/ код приложения (core/, ui/,
modules/, assets/, migrations/), десктопный main.py под именем app_main.py
и этот файл как main.py — APK собирается оттуда.

База: python-for-android при обновлении приложения заново распаковывает папку
с кодом, поэтому scheduler.db живёт в постоянной папке данных (ANDROID_PRIVATE).
При первом запуске туда копируется база, вложенная в APK.
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("ANDROID_PRIVATE") or os.path.join(HERE, "data")


def _prepare_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    db = os.path.join(DATA_DIR, "scheduler.db")
    bundled = os.path.join(HERE, "scheduler.db")
    if not os.path.exists(db) and os.path.exists(bundled):
        shutil.copy2(bundled, db)
    # Настройка db_path в самой базе — относительное «scheduler.db», поэтому
    # рабочая папка процесса должна быть папкой данных.
    os.chdir(DATA_DIR)
    os.environ["DB_PATH"] = db


def _enable_touch_scrolling(app) -> None:
    """Прокрутка пальцем во всех списках, таблицах и областях прокрутки.

    Виджеты Qt по умолчанию листаются только колесом мыши и ползунком.
    """
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QAbstractScrollArea, QScroller

    class _ScrollerGrabber(QObject):
        def eventFilter(self, obj, event):
            if event.type() == QEvent.Type.Polish and isinstance(obj, QAbstractScrollArea):
                # Касание приходит в виджеты как мышь (Qt синтезирует её из
                # тача), поэтому жест — «левой кнопкой», а не TouchGesture.
                QScroller.grabGesture(
                    obj.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture
                )
            return False

    app._scroller_grabber = _ScrollerGrabber(app)
    app.installEventFilter(app._scroller_grabber)


def main() -> None:
    # Android увеличивает интерфейс по плотности экрана: на планшете 1920×1200
    # окну достаётся ~1280 точек по ширине, и панель кнопок не влезает.
    os.environ.setdefault("QT_SCALE_FACTOR", "0.85")
    _prepare_data_dir()
    sys.path.insert(0, HERE)

    from ui.crash_handler import install_crash_handler

    install_crash_handler(os.path.join(DATA_DIR, "crash.log"))

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    _enable_touch_scrolling(app)

    from ui.translations import install_qt_translator

    install_qt_translator(app)

    from core.container import Container
    from core.styles import ThemeManager, apply_theme

    container = Container()
    apply_theme(app, ThemeManager(container.facade).load_saved_theme())

    with container.db_manager.get_session() as session:
        container.facade.run_module_migrations(session)

    from app_main import MainWindow

    window = MainWindow(facade=container.facade, container=container)
    window.showMaximized()

    from ui.android_back import install_back_handler

    install_back_handler(app, window)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
