"""Схема базы после миграций совпадает с моделями — и на ПК (Alembic),
и на Android (core/android_migrations.py). Новая колонка в core/models.py без
миграции в обеих цепочках ломает этот тест, а не планшет у пользователя."""

import sqlite3

from core.models import Base


def _missing(db_path):
    con = sqlite3.connect(db_path)
    try:
        problems = []
        for table in Base.metadata.sorted_tables:
            cols = {row[1] for row in con.execute(f"PRAGMA table_info({table.name})")}
            if not cols:
                problems.append(f"нет таблицы {table.name}")
                continue
            missing = sorted({c.name for c in table.columns} - cols)
            if missing:
                problems.append(f"{table.name}: нет {', '.join(missing)}")
        return problems
    finally:
        con.close()


def test_android_migrations_cover_models(tmp_path):
    from core.android_migrations import apply_android_migrations

    path = str(tmp_path / "android.db")
    apply_android_migrations(path)
    assert _missing(path) == []


def test_alembic_migrations_cover_models(tmp_path):
    from core.database import DatabaseManager

    path = str(tmp_path / "desktop.db")
    DatabaseManager(path).close()
    assert _missing(path) == []
