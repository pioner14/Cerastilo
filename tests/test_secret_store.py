"""Пароль SMTP хранится не в таблице settings, а в файле секретов рядом с базой."""

import os
import sqlite3
import stat

from core.database import DatabaseManager


def _settings_rows(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return dict(conn.execute("SELECT key, value FROM settings").fetchall())
    finally:
        conn.close()


def test_password_is_saved_outside_db(tmp_path):
    db_path = str(tmp_path / "scheduler.db")
    db = DatabaseManager(db_path)

    db.save_setting("smtp_password", "секрет")

    assert db.get_setting("smtp_password") == "секрет"
    assert "smtp_password" not in _settings_rows(db_path)
    secret_file = tmp_path / ".scheduler.db.secrets.json"
    assert secret_file.exists()
    assert stat.S_IMODE(os.stat(secret_file).st_mode) == 0o600
    db.close()


def test_old_password_in_db_is_moved_to_file(tmp_path):
    db_path = str(tmp_path / "scheduler.db")
    db = DatabaseManager(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO settings (key, value) VALUES ('smtp_password', 'старый')")
    conn.commit()
    conn.close()

    assert db.get_setting("smtp_password") == "старый"
    assert "smtp_password" not in _settings_rows(db_path)
    assert db.get_setting("smtp_password") == "старый"
    db.close()


def test_in_memory_db_keeps_password_in_memory():
    db = DatabaseManager(":memory:")

    db.save_setting("smtp_password", "x")

    assert db.get_setting("smtp_password") == "x"
    assert db.get_setting("smtp_user", "нет") == "нет"
