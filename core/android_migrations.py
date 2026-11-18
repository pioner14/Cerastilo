"""
Кастомный менеджер миграций для Android/SQLite.

Обходит проблему SIGSEGV в alembic.command.upgrade() на Android,
выполняя SQL-миграции напрямую через stdlib sqlite3.

Совместим с форматом alembic_version: хранит версию текущей схемы
в той же таблице alembic_version, что и Alembic, поэтому обе системы
могут работать совместно на десктопе (через Alembic) и на Android
(через этот менеджер).

See: spec://database/migrations#android
"""

import sqlite3
import logging
import os

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# Описание всех миграций в виде чистого SQL.
# Ключ — revision ID (совпадает с Alembic revision).
# "sql" — список SQL-операторов, которые выполняются по порядку.
# "down_revision" — предшествующая ревизия (None для первой).
# -----------------------------------------------------------------------
MIGRATIONS = [
    {
        "revision": "001_initial",
        "down_revision": None,
        "description": "Initial schema - create all tables",
        "sql": [
            """
            CREATE TABLE IF NOT EXISTS participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR NOT NULL,
                gender VARCHAR,
                service_type VARCHAR,
                family_group_id INTEGER,
                is_active BOOLEAN DEFAULT 1,
                last_assignment_date DATETIME,
                created_at DATETIME,
                CONSTRAINT ck_participants_gender CHECK (gender IN ('male', 'female'))
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS participant_qualifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                participant_id INTEGER NOT NULL,
                qualification_name VARCHAR NOT NULL,
                FOREIGN KEY(participant_id) REFERENCES participants(id),
                UNIQUE(participant_id, qualification_name)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS weeks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_title VARCHAR NOT NULL,
                start_date DATE,
                bible_reading VARCHAR,
                month VARCHAR,
                year INTEGER,
                workbook_source VARCHAR,
                special_event VARCHAR,
                announcement VARCHAR,
                songs VARCHAR,
                created_at DATETIME
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_id INTEGER NOT NULL,
                assignment_text VARCHAR NOT NULL,
                assignment_type VARCHAR,
                assignment_number VARCHAR,
                section VARCHAR,
                section_position INTEGER,
                duration INTEGER,
                participant_id INTEGER,
                assistant_id INTEGER,
                status VARCHAR,
                FOREIGN KEY(week_id) REFERENCES weeks(id),
                FOREIGN KEY(participant_id) REFERENCES participants(id),
                FOREIGN KEY(assistant_id) REFERENCES participants(id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS assignment_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                section VARCHAR NOT NULL,
                position VARCHAR NOT NULL,
                assignment_name VARCHAR,
                required_qualification VARCHAR,
                is_brothers_only BOOLEAN DEFAULT 0,
                needs_assistant BOOLEAN DEFAULT 0,
                UNIQUE(section, position)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS settings (
                key VARCHAR PRIMARY KEY,
                value VARCHAR
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NOT NULL,
                "order" INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT 1
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS cleaning_schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start DATE NOT NULL,
                group_id INTEGER NOT NULL,
                FOREIGN KEY(group_id) REFERENCES groups(id),
                UNIQUE(week_start)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS attendant_schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start DATE NOT NULL,
                meeting_type VARCHAR(20) NOT NULL,
                participant_id INTEGER,
                position INTEGER DEFAULT 1,
                FOREIGN KEY(participant_id) REFERENCES participants(id),
                UNIQUE(week_start, meeting_type, position)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS microphone_schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start DATE NOT NULL,
                meeting_type VARCHAR(20) NOT NULL,
                participant_id INTEGER,
                position INTEGER DEFAULT 1,
                FOREIGN KEY(participant_id) REFERENCES participants(id),
                UNIQUE(week_start, meeting_type, position)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS sound_schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start DATE NOT NULL,
                meeting_type VARCHAR(20) NOT NULL,
                participant_id INTEGER,
                position INTEGER DEFAULT 1,
                FOREIGN KEY(participant_id) REFERENCES participants(id),
                UNIQUE(week_start, meeting_type, position)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS zoom_attendant_schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start DATE NOT NULL,
                meeting_type VARCHAR(20) NOT NULL,
                participant_id INTEGER,
                FOREIGN KEY(participant_id) REFERENCES participants(id),
                UNIQUE(week_start, meeting_type)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS stage_schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start DATE NOT NULL,
                meeting_type VARCHAR(20) NOT NULL,
                participant_id INTEGER,
                position INTEGER DEFAULT 1,
                FOREIGN KEY(participant_id) REFERENCES participants(id),
                UNIQUE(week_start, meeting_type, position)
            )
            """,
        ],
    },
    {
        "revision": "002_add_personal_gap",
        "down_revision": "001_initial",
        "description": "Add personal_gap to participants",
        "sql": [
            "ALTER TABLE participants ADD COLUMN personal_gap INTEGER",
        ],
    },
    {
        "revision": "003_add_is_minor",
        "down_revision": "002_add_personal_gap",
        "description": "Add is_minor to participants",
        "sql": [
            "ALTER TABLE participants ADD COLUMN is_minor BOOLEAN NOT NULL DEFAULT 0",
        ],
    },
    {
        "revision": "004_add_unavailability",
        "down_revision": "003_add_is_minor",
        "description": "Add unavailability dates to participants",
        "sql": [
            "ALTER TABLE participants ADD COLUMN unavailable_from DATE",
            "ALTER TABLE participants ADD COLUMN unavailable_to DATE",
        ],
    },
    {
        "revision": "005_add_excluded_weeks_table",
        "down_revision": "004_add_unavailability",
        "description": "Add participant_excluded_weeks table",
        "sql": [
            """
            CREATE TABLE IF NOT EXISTS participant_excluded_weeks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                participant_id INTEGER NOT NULL,
                week_start DATE NOT NULL,
                FOREIGN KEY(participant_id) REFERENCES participants(id) ON DELETE CASCADE,
                UNIQUE(participant_id, week_start)
            )
            """,
        ],
    },
    {
        "revision": "006_add_elder_position_gap",
        "down_revision": "005_add_excluded_weeks_table",
        "description": "Add elder_position_gap to assignment_config for elder rotation enforcement",
        "sql": [
            "ALTER TABLE assignment_config ADD COLUMN elder_position_gap INTEGER",
            "UPDATE assignment_config SET elder_position_gap = 4 WHERE (section = 'cbs' AND position = 'conductor') OR (section = 'fixed' AND position = 'chairman')",
        ],
    },
    {
        "revision": "007_add_is_exclusive",
        "down_revision": "006_add_elder_position_gap",
        "description": "Add is_exclusive to assignment_config (prayer/bible_reading are non-exclusive)",
        "sql": [
            "ALTER TABLE assignment_config ADD COLUMN is_exclusive INTEGER NOT NULL DEFAULT 1",
            "UPDATE assignment_config SET is_exclusive = 0 "
            "WHERE (section = 'fixed' AND position IN ('prayer_open', 'prayer_close')) "
            "   OR (section = 'treasures' AND position = '3')",
        ],
    },
    {
        "revision": "008_participant_position_configs",
        "down_revision": "007_add_is_exclusive",
        "description": "Add participant_position_configs table for per-participant position gap overrides",
        "sql": [
            """
            CREATE TABLE IF NOT EXISTS participant_position_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                participant_id INTEGER NOT NULL,
                section VARCHAR NOT NULL,
                position VARCHAR NOT NULL,
                position_gap INTEGER NOT NULL,
                FOREIGN KEY(participant_id) REFERENCES participants(id) ON DELETE CASCADE,
                UNIQUE(participant_id, section, position)
            )
            """,
            # Участник с id=8 (руководитель встречи в базе владельца):
            # разрешено быть председателем раз в 2 недели вместо 4.
            # На чистой базе участника 8 нет — без проверки INSERT падал
            # на FOREIGN KEY и APK с нуля не запускался.
            "INSERT OR IGNORE INTO participant_position_configs "
            "(participant_id, section, position, position_gap) "
            "SELECT 8, 'fixed', 'chairman', 2 "
            "WHERE EXISTS (SELECT 1 FROM participants WHERE id = 8)",
        ],
    },
    {
        "revision": "009_add_last_main_date",
        "down_revision": "008_participant_position_configs",
        "description": "Add last_main_date to participants",
        "sql": [
            "ALTER TABLE participants ADD COLUMN last_main_date DATETIME",
            "UPDATE participants SET last_main_date = last_assignment_date "
            "WHERE last_assignment_date IS NOT NULL",
        ],
    },
    {
        "revision": "010_add_discussion_marker",
        "down_revision": "009_add_last_main_date",
        "description": "Add discussion_marker to assignments",
        "sql": [
            "ALTER TABLE assignments ADD COLUMN discussion_marker VARCHAR",
        ],
    },
    {
        "revision": "011_section_position_string",
        "down_revision": "010_add_discussion_marker",
        "description": "Change section_position column type from INTEGER to String/TEXT",
        "sql": [
            """
            CREATE TABLE IF NOT EXISTS assignments_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_id INTEGER NOT NULL,
                assignment_text VARCHAR NOT NULL,
                assignment_type VARCHAR,
                assignment_number VARCHAR,
                section VARCHAR,
                section_position VARCHAR,
                duration INTEGER,
                participant_id INTEGER,
                assistant_id INTEGER,
                status VARCHAR,
                discussion_marker VARCHAR,
                FOREIGN KEY(week_id) REFERENCES weeks(id),
                FOREIGN KEY(participant_id) REFERENCES participants(id),
                FOREIGN KEY(assistant_id) REFERENCES participants(id)
            )
            """,
            """
            INSERT INTO assignments_new
                (id, week_id, assignment_text, assignment_type, assignment_number,
                 section, section_position, duration, participant_id, assistant_id, status,
                 discussion_marker)
            SELECT
                id, week_id, assignment_text, assignment_type, assignment_number,
                section, CAST(section_position AS TEXT), duration,
                participant_id, assistant_id, status, discussion_marker
            FROM assignments
            """,
            "DROP TABLE assignments",
            "ALTER TABLE assignments_new RENAME TO assignments",
        ],
    },
    {
        "revision": "012_add_email_phone",
        "down_revision": "011_section_position_string",
        "description": "Add email and phone to participants",
        "sql": [
            "ALTER TABLE participants ADD COLUMN email VARCHAR",
            "ALTER TABLE participants ADD COLUMN phone VARCHAR",
        ],
    },
    {
        "revision": "013_add_notification_history",
        "down_revision": "012_add_email_phone",
        "description": "Add notification_history table",
        "sql": [
            """
            CREATE TABLE IF NOT EXISTS notification_history (
                id INTEGER NOT NULL PRIMARY KEY,
                participant_id INTEGER NOT NULL,
                week_id INTEGER NOT NULL,
                sent_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
                status VARCHAR(20) NOT NULL,
                error_message TEXT,
                subject VARCHAR(200)
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_notification_history_participant_id "
            "ON notification_history (participant_id)",
            "CREATE INDEX IF NOT EXISTS ix_notification_history_week_id "
            "ON notification_history (week_id)",
        ],
    },
    {
        "revision": "014_assignment_sort_order",
        "down_revision": "013_add_notification_history",
        "description": "Add sort_order to assignments",
        "sql": [
            "ALTER TABLE assignments ADD COLUMN sort_order INTEGER",
        ],
    },
    {
        # 015 создавала assignment_templates, 016 её удалила — на Android
        # таблица не нужна, ревизии оставлены для совпадения с Alembic.
        "revision": "015_assignment_templates",
        "down_revision": "014_assignment_sort_order",
        "description": "Assignment templates (dropped in 016)",
        "sql": [],
    },
    {
        "revision": "016_drop_assignment_templates",
        "down_revision": "015_assignment_templates",
        "description": "Drop assignment_templates",
        "sql": [
            "DROP TABLE IF EXISTS assignment_templates",
        ],
    },
    {
        "revision": "017_assignment_updated_at",
        "down_revision": "016_drop_assignment_templates",
        "description": "Add updated_at to assignments",
        "sql": [
            "ALTER TABLE assignments ADD COLUMN updated_at DATETIME",
        ],
    },
    {
        "revision": "018_notification_responses",
        "down_revision": "017_assignment_updated_at",
        "description": "Notification responses (confirmed / declined)",
        "sql": [
            """CREATE TABLE IF NOT EXISTS notification_responses (
                id INTEGER PRIMARY KEY,
                participant_id INTEGER NOT NULL,
                week_id INTEGER NOT NULL,
                response VARCHAR(20) NOT NULL,
                source VARCHAR(20) NOT NULL,
                responded_at DATETIME NOT NULL,
                CONSTRAINT uq_notification_response UNIQUE (participant_id, week_id)
            )""",
            "CREATE INDEX IF NOT EXISTS ix_notification_responses_participant_id ON notification_responses (participant_id)",
            "CREATE INDEX IF NOT EXISTS ix_notification_responses_week_id ON notification_responses (week_id)",
        ],
    },
    {
        "revision": "019_participant_updated_at",
        "down_revision": "018_notification_responses",
        "description": "Add updated_at to participants",
        "sql": [
            "ALTER TABLE participants ADD COLUMN updated_at DATETIME",
        ],
    },
    {
        "revision": "020_assignment_slip_given",
        "down_revision": "019_participant_updated_at",
        "description": "Add slip_given_at to assignments",
        "sql": [
            "ALTER TABLE assignments ADD COLUMN slip_given_at DATETIME",
        ],
    },
]

# Цепочка повторяет Alembic (migrations/versions). Новую миграцию на десктопе
# нужно добавить и сюда, иначе база, созданная на планшете, отстанет от модели.
HEAD_REVISION = MIGRATIONS[-1]["revision"]


def _get_current_version(conn: sqlite3.Connection) -> str | None:
    """Получить текущую версию схемы из таблицы alembic_version."""
    try:
        cursor = conn.execute("SELECT version_num FROM alembic_version LIMIT 1")
        row = cursor.fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        # Таблица не существует — БД ещё не инициализирована
        return None


def _ensure_version_table(conn: sqlite3.Connection) -> None:
    """Создать таблицу alembic_version, если её нет."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alembic_version (
            version_num VARCHAR(32) NOT NULL,
            CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
        )
    """
    )
    conn.commit()


def _set_version(conn: sqlite3.Connection, version: str) -> None:
    """Обновить версию в таблице alembic_version."""
    conn.execute("DELETE FROM alembic_version")
    conn.execute("INSERT INTO alembic_version (version_num) VALUES (?)", (version,))
    conn.commit()


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Проверить, существует ли колонка в таблице (для идемпотентности ALTER TABLE)."""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    return column in columns


def _safe_alter_table_add_column(conn: sqlite3.Connection, sql: str) -> None:
    """
    Безопасно выполнить ALTER TABLE ... ADD COLUMN.
    Если колонка уже существует — игнорировать ошибку (идемпотентность).
    """
    try:
        conn.execute(sql)
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            logger.debug(f"Column already exists (skipping): {e}")
        else:
            raise


def apply_android_migrations(db_path: str) -> None:
    """
    Применить все ожидающие миграции к БД по указанному пути.

    Это замена alembic.command.upgrade() для Android, использующая
    только stdlib sqlite3 без каких-либо C-расширений.

    Args:
        db_path: Абсолютный путь к файлу SQLite.
    """
    logger.info(f"[AndroidMigrations] Starting migrations for: {db_path}")

    # Убедимся, что директория существует
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
        logger.info(f"[AndroidMigrations] Created directory: {db_dir}")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        _ensure_version_table(conn)
        current_version = _get_current_version(conn)
        logger.info(f"[AndroidMigrations] Current DB version: {current_version}")

        if current_version == HEAD_REVISION:
            logger.info("[AndroidMigrations] Database is up to date, no migrations needed.")
            return

        # Найти стартовую точку (первая ненапримененная миграция)
        if current_version is None:
            start_index = 0
        else:
            # Найти индекс текущей версии и начать со следующей
            revision_list = [m["revision"] for m in MIGRATIONS]
            if current_version not in revision_list:
                # Версию, которой нет в этом списке, поставил Alembic на десктопе
                # (012+ сюда не переносились) — схема новее, чем знает этот список.
                # Раньше здесь все миграции применялись «с нуля» поверх данных:
                # 011 пересоздаёт таблицы и падала на FOREIGN KEY, а могла бы
                # и испортить базу. Такую базу считаем актуальной и не трогаем.
                logger.warning(
                    f"[AndroidMigrations] DB version '{current_version}' is not in the "
                    f"Android migration list (set by desktop Alembic) — assuming up to date."
                )
                return
            else:
                start_index = revision_list.index(current_version) + 1

        # Применить ожидающие миграции
        migrations_to_apply = MIGRATIONS[start_index:]
        if not migrations_to_apply:
            logger.info("[AndroidMigrations] No pending migrations found.")
            return

        logger.info(f"[AndroidMigrations] Applying {len(migrations_to_apply)} migration(s)...")

        for migration in migrations_to_apply:
            rev = migration["revision"]
            desc = migration["description"]
            logger.info(f"[AndroidMigrations] Applying {rev}: {desc}")

            try:
                for sql_stmt in migration["sql"]:
                    sql_stripped = sql_stmt.strip()
                    if not sql_stripped:
                        continue

                    # Специальная обработка ALTER TABLE для идемпотентности
                    if (
                        "ALTER TABLE" in sql_stripped.upper()
                        and "ADD COLUMN" in sql_stripped.upper()
                    ):
                        _safe_alter_table_add_column(conn, sql_stripped)
                    else:
                        conn.execute(sql_stripped)

                # Обновить версию после успешной миграции
                _set_version(conn, rev)
                conn.commit()
                logger.info(f"[AndroidMigrations] {rev} applied successfully.")

            except Exception as e:
                conn.rollback()
                logger.error(f"[AndroidMigrations] Failed to apply {rev}: {e}")
                import traceback

                logger.error(traceback.format_exc())
                raise RuntimeError(f"Migration {rev} failed: {e}") from e

        logger.info(f"[AndroidMigrations] All migrations applied. DB version: {HEAD_REVISION}")

    finally:
        conn.close()
