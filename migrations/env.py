"""
Alembic env.py для NHJS_N.

Настройка окружения для миграций SQLite.
See: spec://database/migrations#env
"""
import logging
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Импорт моделей для автогенерации миграций
from core.models import (
    Base, Participant, Week, Assignment, AssignmentConfig, Setting,
    Group, CleaningSchedule, AttendantSchedule, MicrophoneSchedule,
    SoundSchedule, ZoomAttendantSchedule, StageSchedule
)
from core.config import DB_PATH

# Alembic Config
config = context.config

# Переопределяем URL для использования нашего пути к БД, только если это не тестовая БД
current_url = config.get_main_option("sqlalchemy.url")
if not current_url or current_url == "sqlite:///scheduler.db":
    config.set_main_option("sqlalchemy.url", f"sqlite:///{DB_PATH}")

# Логирование
#
# fileConfig() применяет секцию [logger_root] из alembic.ini (level = WARN,
# handlers = console) к root-логгеру. Если приложение уже настроило
# логирование, это молча глушит весь его INFO-вывод. disable_existing_loggers
# =False тут не спасает — он защищает объекты логгеров, но не уровень и не
# хендлеры root, поэтому их сохраняем и возвращаем.
if config.config_file_name is not None:
    root_logger = logging.getLogger()
    saved_handlers = root_logger.handlers[:]
    saved_level = root_logger.level
    try:
        # disable_existing_loggers=False обязателен: при True fileConfig()
        # гасит уже созданные логгеры приложения (например, core.database),
        # и весь дальнейший вывод приложения пропадает.
        fileConfig(config.config_file_name, disable_existing_loggers=False)
    except Exception:
        pass
    finally:
        # Восстанавливаем root только если логирование уже было настроено
        # приложением. При автономном `alembic upgrade` хендлеров нет, и
        # конфиг из alembic.ini остаётся в силе.
        if saved_handlers:
            root_logger.setLevel(saved_level)
            root_logger.handlers[:] = saved_handlers

# Метаданные для автогенерации
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Запуск миграций в offline-режиме (без подключения к БД).

    See: spec://database/migrations#offline_mode
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # Важно для SQLite
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Запуск миграций в online-режиме (с подключением к БД).

    See: spec://database/migrations#online_mode
    """
    import logging
    logger = logging.getLogger("alembic.env")
    logger.info("Online migrations: Creating engine...")
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    logger.info("Online migrations: Engine created. Connecting...")
    try:
        with connectable.connect() as connection:
            logger.info("Online migrations: Connected successfully. Configuring context...")
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,  # Важно для SQLite
            )
            logger.info("Online migrations: Context configured. Beginning transaction...")
            with context.begin_transaction():
                logger.info("Online migrations: Transaction started. Running migrations...")
                context.run_migrations()
                logger.info("Online migrations: Migrations completed successfully.")
    except Exception as e:
        logger.error(f"Error in run_migrations_online: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
