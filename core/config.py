import sys
import os


def get_bundle_dir():
    """
    Returns the path to the bundled files (inside PyInstaller temporary directory).
    When running as a script, this is the same as get_app_path().
    Use this for resources packed with the executable (e.g. assets, migrations).
    """
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    else:
        return get_app_path()


def get_app_path():
    """
    Returns the path to the application directory (where the executable lives).
    - If frozen (PyInstaller), returns the directory containing the executable.
    - If running as script, returns the project root directory.
    Use this for external data that should persist (e.g. databases, backups).
    """
    if getattr(sys, "frozen", False):
        # Running in PyInstaller bundle
        return os.path.dirname(sys.executable)
    else:
        # Running in normal Python environment.
        # This file is in core/, so project root is one level up.
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_db_path():
    """Returns the absolute path to the database file."""
    return os.path.join(get_app_path(), "scheduler.db")


def get_data_dir() -> str:
    """Папка с данными пользователя (рядом с базой): сюда пишем crash.log.

    DB_PATH из окружения, иначе путь к базе из настроек (по умолчанию
    относительный «scheduler.db» — берём от текущей папки).
    """
    db_path = os.environ.get("DB_PATH")
    if not db_path:
        from core.settings import Settings

        db_path = Settings().db_path
    return os.path.dirname(os.path.abspath(db_path))


# Global constant for easy import
DB_PATH = get_db_path()
