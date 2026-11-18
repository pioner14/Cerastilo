import logging
import os
import sqlite3
from datetime import datetime

logger = logging.getLogger(__name__)

# Имя таблицы для хранения версии схемы
SCHEMA_VERSION_TABLE = "schema_version"
CURRENT_SCHEMA_VERSION = 1  # Версия 1: миграция start_date на DATE


def _parse_legacy_date(date_str: str) -> str | None:
    """Парсит дату из формата DD.MM.YYYY в ISO формат для DateTime.

    Args:
        date_str: Строка с датой в формате DD.MM.YYYY или уже в ISO

    Returns:
        Строка в ISO формате (YYYY-MM-DD HH:MM:SS) или None
    """
    if not date_str:
        return None

    # Если уже в ISO формате (YYYY-MM-DD), добавляем время
    if len(date_str) >= 10 and date_str[4] == "-":
        return f"{date_str[:10]} 00:00:00"

    # Пробуем DD.MM.YYYY
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

    return None


def _get_schema_version(conn: sqlite3.Connection) -> int:
    """Возвращает текущую версию схемы БД."""
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT version FROM {SCHEMA_VERSION_TABLE} LIMIT 1")
        row = cursor.fetchone()
        return row[0] if row else 0
    except sqlite3.OperationalError:
        # Таблица не существует
        return 0


def _set_schema_version(conn: sqlite3.Connection, version: int):
    """Устанавливает версию схемы БД."""
    cursor = conn.cursor()
    cursor.execute(
        f"CREATE TABLE IF NOT EXISTS {SCHEMA_VERSION_TABLE} (version INTEGER PRIMARY KEY)"
    )
    cursor.execute(f"DELETE FROM {SCHEMA_VERSION_TABLE}")
    cursor.execute(f"INSERT INTO {SCHEMA_VERSION_TABLE} (version) VALUES (?)", (version,))
    conn.commit()


def migrate_weeks_start_date_to_date(db_path: str) -> bool:
    """Миграция: конвертация start_date из String в DATE.

    SQLite не поддерживает ALTER COLUMN, поэтому используем подход:
    1. Создать новый столбец start_date_new типа DATE
    2. Скопировать данные с конвертацией
    3. Удалить старый столбец
    4. Переименовать новый столбец

    Args:
        db_path: Путь к файлу БД

    Returns:
        True если миграция выполнена успешно или не требуется
    """
    # :memory: — база в оперативной памяти, миграция не требуется
    if db_path == ":memory:":
        logger.info("БД в памяти (:memory:), миграция не требуется")
        return True

    if not os.path.exists(db_path):
        logger.info(f"БД не найдена: {db_path}, миграция не требуется")
        return True

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Проверяем версию схемы
        current_version = _get_schema_version(conn)
        if current_version >= CURRENT_SCHEMA_VERSION:
            logger.info(f"Схема БД уже версии {current_version}, миграция не требуется")
            return True

        logger.info(
            f"Начало миграции start_date: версия {current_version} -> {CURRENT_SCHEMA_VERSION}"
        )

        # Проверяем тип столбца start_date
        cursor.execute("PRAGMA table_info(weeks)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}

        if columns.get("start_date") == "DATE":
            logger.info("Столбец start_date уже имеет тип DATE")
            _set_schema_version(conn, CURRENT_SCHEMA_VERSION)
            return True

        # Проверяем наличие временного столбца (при незавершённой миграции)
        if "start_date_new" in columns:
            logger.info(
                "Обнаружен временный столбец start_date_new от прерванной миграции, продолжаем"
            )
        else:
            # Шаг 1: Добавляем временный столбец
            cursor.execute("ALTER TABLE weeks ADD COLUMN start_date_new DATE")

        # Шаг 2: Копируем данные с конвертацией
        # Данные уже хранятся в формате YYYY-MM-DD, просто копируем
        cursor.execute(
            """
            UPDATE weeks
            SET start_date_new = DATE(start_date)
            WHERE start_date IS NOT NULL AND start_date != ''
        """
        )

        # Шаг 3: SQLite не поддерживает DROP COLUMN напрямую до версии 3.35.0
        # Используем пересоздание таблицы
        cursor.execute(
            """
            CREATE TABLE weeks_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_title TEXT NOT NULL,
                start_date DATE,
                bible_reading TEXT,
                month TEXT,
                year INTEGER,
                workbook_source TEXT,
                special_event TEXT,
                announcement TEXT,
                songs TEXT,
                created_at DATETIME
            )
        """
        )

        cursor.execute(
            """
            INSERT INTO weeks_new (id, week_title, start_date, bible_reading, month, year,
                                   workbook_source, special_event, announcement, songs, created_at)
            SELECT id, week_title, start_date_new, bible_reading, month, year,
                   workbook_source, special_event, announcement, songs, created_at
            FROM weeks
        """
        )

        # Создаём бэкап оригинальной таблицы перед удалением (для восстановления при сбое)
        cursor.execute("CREATE TABLE IF NOT EXISTS weeks_backup AS SELECT * FROM weeks")

        # Удаляем старую таблицу и переименовываем новую
        cursor.execute("DROP TABLE weeks")
        cursor.execute("ALTER TABLE weeks_new RENAME TO weeks")

        # Обновляем версию схемы
        _set_schema_version(conn, CURRENT_SCHEMA_VERSION)

        # Удаляем бэкап после успешной миграции
        cursor.execute("DROP TABLE IF EXISTS weeks_backup")

        logger.info("Миграция start_date успешно завершена")
        return True

    except Exception as e:
        logger.error(f"Ошибка миграции start_date: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def migrate_participants(source_db, target_db):
    """Переносит участников из старой БД в новую."""
    if not os.path.exists(source_db):
        logger.warning(f"Исходная БД не найдена: {source_db}")
        return

    conn_src = sqlite3.connect(source_db)
    conn_dst = sqlite3.connect(target_db)

    cur_src = conn_src.cursor()
    cur_dst = conn_dst.cursor()

    try:
        cur_src.execute(
            "SELECT name, gender, service_type, is_active, last_assignment_date FROM participants"
        )
        rows = cur_src.fetchall()

        for row in rows:
            name = row[0]
            # Проверяем, нет ли уже такого имени в новой базе
            cur_dst.execute("SELECT id FROM participants WHERE name = ?", (name,))
            if not cur_dst.fetchone():
                # Преобразуем дату в ISO формат для DateTime колонки
                date_val = _parse_legacy_date(row[4]) if row[4] else None
                cur_dst.execute(
                    """
                    INSERT INTO participants (name, gender, service_type, is_active, last_assignment_date)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (row[0], row[1], row[2], row[3], date_val),
                )

        conn_dst.commit()
        logger.info(f"Успешно перенесено {len(rows)} возвещателей.")
    except Exception as e:
        logger.error(f"Ошибка миграции: {e}")
    finally:
        conn_src.close()
        conn_dst.close()
