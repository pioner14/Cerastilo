import os
import shutil
import zipfile
from datetime import datetime

from core.config import DB_PATH


def current_db_path():
    """Путь к рабочей базе. На Android её кладут в папку данных и передают
    через DB_PATH (android/main.py); config.DB_PATH там указывает на папку кода."""
    return os.environ.get("DB_PATH") or DB_PATH


def create_backup(dest_path, db_path=None):
    """Создает ZIP-архив с базой данных."""
    if db_path is None:
        db_path = current_db_path()
    try:
        if not os.path.exists(db_path):
            return {"success": False, "error": "База данных не найдена"}

        # Создаем временную копию БД (чтобы не копировать заблокированный файл)
        temp_db = db_path + ".tmp"
        shutil.copy2(db_path, temp_db)

        with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(temp_db, "scheduler.db")

        os.remove(temp_db)
        return {"success": True, "path": dest_path}
    except Exception as e:
        return {"success": False, "error": str(e)}


def restore_backup(zip_path, db_path=None):
    """Восстанавливает базу данных из ZIP-архива."""
    if db_path is None:
        db_path = current_db_path()
    try:
        if not os.path.exists(zip_path):
            return {"success": False, "error": "Файл архива не найден"}

        with zipfile.ZipFile(zip_path, "r") as zipf:
            # Проверяем, есть ли там БД
            if "scheduler.db" not in zipf.namelist():
                return {"success": False, "error": "В архиве нет файла scheduler.db"}
            data = zipf.read("scheduler.db")
    except zipfile.BadZipFile:
        return {"success": False, "error": "Файл не является ZIP-архивом"}
    except Exception as e:
        return {"success": False, "error": str(e)}

    # Сначала пишем во временный файл рядом с базой и проверяем его:
    # битый или чужой архив не должен заменить рабочую базу.
    temp_path = db_path + ".restore-tmp"
    try:
        with open(temp_path, "wb") as f:
            f.write(data)
        problem = validate_database_file(temp_path)
        if problem:
            os.remove(temp_path)
            return {"success": False, "error": problem}

        # Делаем бэкап текущей перед заменой (на всякий случай)
        if os.path.exists(db_path):
            shutil.copy2(db_path, db_path + ".old")
        os.replace(temp_path, db_path)
        return {"success": True}
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return {"success": False, "error": str(e)}


REQUIRED_TABLES = ("participants", "weeks", "assignments")


def validate_database_file(path):
    """Проверяет, что файл — целая база SQLite с таблицами программы.

    Возвращает текст ошибки или None, если база годится.
    """
    import sqlite3

    with open(path, "rb") as f:
        if f.read(16) != b"SQLite format 3\x00":
            return "В архиве не база данных SQLite"
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            check = conn.execute("PRAGMA quick_check").fetchone()
            if not check or check[0] != "ok":
                return "База данных в архиве повреждена"
            tables = {
                row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        return f"База данных в архиве повреждена: {e}"
    missing = [t for t in REQUIRED_TABLES if t not in tables]
    if missing:
        return "Это не база NHJS: нет таблиц " + ", ".join(missing)
    return None


def list_backups(backup_dir):
    """Возвращает список доступных бэкапов."""
    try:
        if not os.path.exists(backup_dir):
            return []

        backups = []
        for f in os.listdir(backup_dir):
            if f.endswith(".zip") or f.endswith(".db"):
                path = os.path.join(backup_dir, f)
                stat = os.stat(path)
                backups.append(
                    {
                        "filename": f,
                        "path": path,
                        "size": stat.st_size,
                        "created": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    }
                )

        # Sort by creation date, newest first
        backups.sort(key=lambda x: x["created"], reverse=True)
        return backups
    except Exception:
        return []


def get_backup_filename():
    """Генерирует имя файла для бэкапа."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"backup_{timestamp}.zip"


def cleanup_old_backups(backup_dir, max_backups=10):
    """Удаляет старые бэкапы, оставляя только max_backups последних."""
    try:
        backups = list_backups(backup_dir)
        if len(backups) <= max_backups:
            return {"success": True, "removed": 0}

        to_remove = backups[max_backups:]
        removed = 0
        for backup in to_remove:
            try:
                os.remove(backup["path"])
                removed += 1
            except OSError:
                pass

        return {"success": True, "removed": removed}
    except Exception as e:
        return {"success": False, "error": str(e)}
