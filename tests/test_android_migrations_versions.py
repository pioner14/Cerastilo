"""Мобильный менеджер миграций не трогает базу, обновлённую Alembic на десктопе."""

import sqlite3

from core.android_migrations import apply_android_migrations


def test_newer_alembic_version_is_left_untouched(tmp_path):
    db = tmp_path / "scheduler.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
    con.execute("INSERT INTO alembic_version VALUES ('018_future_revision')")
    con.execute("CREATE TABLE weeks (id INTEGER PRIMARY KEY, week_title TEXT)")
    con.execute("INSERT INTO weeks VALUES (1, 'Неделя')")
    con.commit()
    con.close()

    apply_android_migrations(str(db))  # раньше: «с нуля» → падало на 011

    con = sqlite3.connect(db)
    assert (
        con.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        == "018_future_revision"
    )
    assert con.execute("SELECT week_title FROM weeks").fetchall() == [("Неделя",)]
    con.close()


def _columns(con, table):
    return {row[1] for row in con.execute(f"PRAGMA table_info({table})")}


def test_fresh_android_db_matches_models(tmp_path):
    """Чистая установка APK: после миграций в базе есть все таблицы и колонки модели."""
    from core.models import Base

    db = tmp_path / "fresh.db"
    apply_android_migrations(str(db))

    con = sqlite3.connect(db)
    assert (
        con.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        == "020_assignment_slip_given"
    )
    for table in Base.metadata.sorted_tables:
        missing = {c.name for c in table.columns} - _columns(con, table.name)
        assert not missing, f"{table.name}: нет колонок {missing}"
    con.close()


def test_android_011_keeps_discussion_marker(tmp_path):
    """011 пересоздаёт assignments — значение discussion_marker не теряется."""
    from core.android_migrations import MIGRATIONS, _safe_alter_table_add_column

    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    upto_010 = MIGRATIONS[
        : [m["revision"] for m in MIGRATIONS].index("010_add_discussion_marker") + 1
    ]
    for m in upto_010:
        for sql in m["sql"]:
            if "ADD COLUMN" in sql:
                _safe_alter_table_add_column(con, sql)
            else:
                con.execute(sql)
    con.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
    con.execute("INSERT INTO alembic_version VALUES ('010_add_discussion_marker')")
    con.execute("INSERT INTO weeks (id, week_title) VALUES (1, 'Неделя')")
    con.execute(
        "INSERT INTO assignments (id, week_id, assignment_text, discussion_marker) "
        "VALUES (1, 1, 'Обсуждение', 'Q')"
    )
    con.commit()
    con.close()

    apply_android_migrations(str(db))

    con = sqlite3.connect(db)
    assert con.execute("SELECT discussion_marker FROM assignments").fetchall() == [("Q",)]
    con.close()
