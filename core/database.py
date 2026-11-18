import logging
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.config import DB_PATH
from core.models import AssignmentConfig, Base, Group, Setting, Week
from core.secret_store import SECRET_KEYS, SecretStore

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def apply_migrations(db_path: str) -> None:
    """Apply migrations to the database.

    On Android: uses a pure-Python/sqlite3 migration manager to avoid
    the SIGSEGV crash in alembic.command.upgrade() caused by C-extension
    issues in the Android environment.

    On Desktop: uses standard Alembic for full compatibility.

    See: spec://database/migrations#integration
    """
    import os

    is_android = "ANDROID_ARGUMENT" in os.environ

    if is_android:
        # Используем кастомный менеджер на Android (без C-расширений Alembic)
        logger.info(f"Android detected: using pure-Python migration manager for {db_path}")
        from core.android_migrations import apply_android_migrations

        apply_android_migrations(db_path)
        logger.info("Android migrations applied successfully")
    else:
        # На десктопе используем стандартный Alembic
        import traceback
        from alembic.config import Config
        from alembic import command
        from core.config import get_bundle_dir

        try:
            bundle_path = get_bundle_dir()
            alembic_path = os.path.join(bundle_path, "alembic.ini")
            logger.info(
                f"Applying Alembic migrations with config: {alembic_path}, database: {db_path}"
            )
            alembic_cfg = Config(alembic_path)
            alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
            alembic_cfg.set_main_option("script_location", os.path.join(bundle_path, "migrations"))

            # Применяем все миграции
            command.upgrade(alembic_cfg, "head")
            logger.info("Alembic migrations applied successfully")
        except Exception as e:
            logger.error(f"Error applying Alembic migrations: {e}")
            logger.error(traceback.format_exc())
            raise


# Колонки, которые должны быть в базе независимо от цепочки миграций: на
# Android цепочка Alembic не прогоняется (core/android_migrations.py считает
# базу с десктопа актуальной), а синхронизация может получить базу со старой
# версии приложения. Модель эти колонки уже использует.
REQUIRED_COLUMNS = (
    ("assignments", "updated_at", "DATETIME"),
    ("participants", "updated_at", "DATETIME"),
    ("assignments", "slip_given_at", "DATETIME"),
)


def ensure_required_columns(engine) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        for table, column, sql_type in REQUIRED_COLUMNS:
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            if existing and column not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"))
                logger.info(f"Добавлена колонка {table}.{column}")


class DatabaseManager:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.secrets = SecretStore(db_path)
        self.engine = create_engine(f"sqlite:///{db_path}")
        self.SessionFactory = sessionmaker(bind=self.engine)
        self._init_db()

    def get_session(self) -> Session:
        return self.SessionFactory()

    def close(self):
        """Закрыть все соединения движка SQLAlchemy."""
        if hasattr(self, "engine") and self.engine:
            self.engine.dispose()

    def _init_db(self):
        """Инициализация БД через SQLAlchemy + Alembic migrations."""
        if self.db_path == ":memory:":
            Base.metadata.create_all(self.engine)
            logger.info("In-memory database initialized via metadata.create_all()")
        else:
            # Применяем миграции alembic
            apply_migrations(self.db_path)
            self._ensure_columns()

        # Для новых БД инициализируем данные по умолчанию
        with self.get_session() as session:
            self._ensure_default_settings(session)
            self._init_default_config(session)
            self._init_default_groups(session)
            session.commit()
        logger.info("База данных успешно инициализирована через ORM.")

    def _ensure_columns(self):
        ensure_required_columns(self.engine)

    def _ensure_default_settings(self, session: Session):
        defaults = {
            "min_assignment_gap": "2",
            "ms_assignment_gap": "2",  # Gap для служебных помощников (по умолч. = 2 нед.)
        }
        for k, v in defaults.items():
            if not session.get(Setting, k):
                session.add(Setting(key=k, value=v))

    def get_setting(self, key: str, default: Any = None) -> Any:
        if key in SECRET_KEYS:
            return self._get_secret(key, default)
        with self.get_session() as session:
            s = session.get(Setting, key)
            return s.value if s else default

    def _get_secret(self, key: str, default: Any = None) -> Any:
        """Секрет из файла рядом с базой; старое значение из таблицы переносится туда."""
        if not self.secrets.has(key):
            with self.get_session() as session:
                s = session.get(Setting, key)
                if s and s.value:
                    self.secrets.set(key, s.value)
                    session.delete(s)
                    session.commit()
                    logger.info(f"Настройка {key} перенесена из базы в файл секретов")
        return self.secrets.get(key, default)

    def save_setting(self, key: str, value: str):
        if key in SECRET_KEYS:
            self.secrets.set(key, value)
            with self.get_session() as session:
                s = session.get(Setting, key)
                if s:
                    session.delete(s)
                    session.commit()
            return
        with self.get_session() as session:
            s = session.get(Setting, key)
            if s:
                s.value = value
            else:
                session.add(Setting(key=key, value=value))
            session.commit()

    def _init_default_config(self, session: Session):
        """Инициализация конфигурации заданий по (section, position).

        Ключ — (section, position), а НЕ глобальный номер EPUB.
        Это позволяет корректно обрабатывать плавающую нумерацию:
        пункт 7 в EPUB может быть (ministry, 4) или (living, 1).
        """
        if session.query(AssignmentConfig).count() > 0:
            return

        defaults = [
            # === Фиксированные роли ===
            AssignmentConfig(
                section="fixed",
                position="chairman",
                assignment_name="Председатель",
                required_qualification="chairman",
                is_brothers_only=True,
                needs_assistant=False,
            ),
            AssignmentConfig(
                section="fixed",
                position="prayer_open",
                assignment_name="Молитва (открытие)",
                required_qualification="prayer",
                is_brothers_only=True,
                needs_assistant=False,
            ),
            AssignmentConfig(
                section="fixed",
                position="prayer_close",
                assignment_name="Молитва (закрытие)",
                required_qualification="prayer",
                is_brothers_only=True,
                needs_assistant=False,
            ),
            # === Сокровища из слова Бога (всегда 3 пункта) ===
            AssignmentConfig(
                section="treasures",
                position="1",
                assignment_name="Вступительная речь",
                required_qualification="treasures_talk",
                is_brothers_only=True,
                needs_assistant=False,
            ),
            AssignmentConfig(
                section="treasures",
                position="2",
                assignment_name="Духовные жемчужины",
                required_qualification="gems",
                is_brothers_only=True,
                needs_assistant=False,
            ),
            AssignmentConfig(
                section="treasures",
                position="3",
                assignment_name="Чтение Библии",
                required_qualification="bible_reading",
                is_brothers_only=True,
                needs_assistant=False,
            ),
            # === Оттачиваем навыки служения (2-4 пункта) ===
            AssignmentConfig(
                section="ministry",
                position="1",
                assignment_name="Учебное задание (1-е)",
                required_qualification="ministry_item",
                is_brothers_only=False,
                needs_assistant=True,
            ),
            AssignmentConfig(
                section="ministry",
                position="2",
                assignment_name="Учебное задание (2-е)",
                required_qualification="ministry_item",
                is_brothers_only=False,
                needs_assistant=True,
            ),
            AssignmentConfig(
                section="ministry",
                position="3",
                assignment_name="Учебное задание (3-е)",
                required_qualification="ministry_item",
                is_brothers_only=False,
                needs_assistant=True,
            ),
            AssignmentConfig(
                section="ministry",
                position="4",
                assignment_name="Речь (только братья)",
                required_qualification="ministry_speech",
                is_brothers_only=True,
                needs_assistant=False,
            ),
            # === Христианская жизнь (1-3 пункта) ===
            AssignmentConfig(
                section="living",
                position="1",
                assignment_name="Часть ХЖС (1-я)",
                required_qualification="living_part",
                is_brothers_only=True,
                needs_assistant=False,
            ),
            AssignmentConfig(
                section="living",
                position="2",
                assignment_name="Часть ХЖС (2-я)",
                required_qualification="living_part",
                is_brothers_only=True,
                needs_assistant=False,
            ),
            AssignmentConfig(
                section="living",
                position="3",
                assignment_name="Часть ХЖС (3-я)",
                required_qualification="living_part",
                is_brothers_only=True,
                needs_assistant=False,
            ),
            # === Изучение Библии в собрании ===
            AssignmentConfig(
                section="cbs",
                position="conductor",
                assignment_name="Ведущий ИБС",
                required_qualification="cbs_conductor",
                is_brothers_only=True,
                needs_assistant=False,
            ),
            AssignmentConfig(
                section="cbs",
                position="reader",
                assignment_name="Чтец ИБС",
                required_qualification="cbs_reader",
                is_brothers_only=True,
                needs_assistant=False,
            ),
        ]
        session.add_all(defaults)

    def _init_default_groups(self, session: Session):
        """Инициализация групп для уборки зала.

        Создаёт 6 групп по умолчанию, если таблица пуста.
        Группы используются для ротационного графика уборки.
        """
        if session.query(Group).count() > 0:
            return

        defaults = [
            Group(name="Группа 1", order=1, is_active=True),
            Group(name="Группа 2", order=2, is_active=True),
            Group(name="Группа 3", order=3, is_active=True),
            Group(name="Группа 4", order=4, is_active=True),
            Group(name="Группа 5", order=5, is_active=True),
            Group(name="Группа 6", order=6, is_active=True),
        ]
        session.add_all(defaults)

    def get_week_special_event(self, week_id: int):
        """Get the special event for a week (memorial, assembly, etc.)"""
        with self.get_session() as session:
            week = session.get(Week, week_id)
            return week.special_event if week else None

    def set_week_special_event(self, week_id: int, event_type: str) -> bool:
        """Установить специальное событие для недели"""
        with self.get_session() as session:
            try:
                week = session.get(Week, week_id)
                if week:
                    week.special_event = event_type if event_type else None
                    session.commit()
                    return True
                return False
            except Exception as e:
                session.rollback()
                logger.error(f"Error setting special event: {e}")
                return False


# NOTE: Singleton removed - use DI container (core.container.Container) instead
# Reference: spec://architecture/di#database
