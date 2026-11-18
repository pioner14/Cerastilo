import sqlite3
import zipfile
from pathlib import Path

from core.backup_logic import restore_backup, validate_database_file

REQUIRED_TABLES = ("participants", "weeks", "assignments")


def make_db(path, tables):
    conn = sqlite3.connect(path)
    try:
        for table in tables:
            conn.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)')
        conn.commit()
    finally:
        conn.close()


def _zip_entry(zip_path, entry_name, data):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(entry_name, data)


def _zip_file(zip_path, entry_name, file_path):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(file_path, entry_name)


def test_restore_good_database_and_keep_old(tmp_path, monkeypatch):
    db_path = tmp_path / "scheduler.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    make_db(db_path, REQUIRED_TABLES)
    old_bytes = db_path.read_bytes()

    source_db = tmp_path / "source.db"
    make_db(source_db, REQUIRED_TABLES)
    conn = sqlite3.connect(source_db)
    try:
        conn.execute("INSERT INTO participants (id) VALUES (1)")
        conn.commit()
    finally:
        conn.close()

    assert validate_database_file(source_db) is None

    zip_path = tmp_path / "backup.zip"
    _zip_file(zip_path, "scheduler.db", source_db)

    result = restore_backup(zip_path)

    assert result["success"] is True
    assert db_path.read_bytes() == source_db.read_bytes()

    old_path = Path(f"{db_path}.old")
    assert old_path.exists()
    assert old_path.read_bytes() == old_bytes
    assert not Path(f"{db_path}.restore-tmp").exists()


def test_restore_zip_with_non_sqlite_does_not_change_db(tmp_path, monkeypatch):
    db_path = tmp_path / "scheduler.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    make_db(db_path, REQUIRED_TABLES)
    before = db_path.read_bytes()

    zip_path = tmp_path / "backup.zip"
    _zip_entry(zip_path, "scheduler.db", b"this is not a sqlite database")

    result = restore_backup(zip_path)

    assert result["success"] is False
    assert result["error"]
    assert db_path.read_bytes() == before
    assert not Path(f"{db_path}.restore-tmp").exists()
    assert not Path(f"{db_path}.old").exists()


def test_restore_sqlite_without_assignments_does_not_change_db(tmp_path, monkeypatch):
    db_path = tmp_path / "scheduler.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    make_db(db_path, REQUIRED_TABLES)
    before = db_path.read_bytes()

    source_db = tmp_path / "missing_assignments.db"
    make_db(source_db, ("participants", "weeks"))
    assert validate_database_file(source_db) is not None

    zip_path = tmp_path / "backup.zip"
    _zip_file(zip_path, "scheduler.db", source_db)

    result = restore_backup(zip_path)

    assert result["success"] is False
    assert "assignments" in result["error"]
    assert db_path.read_bytes() == before
    assert not Path(f"{db_path}.restore-tmp").exists()
    assert not Path(f"{db_path}.old").exists()


def test_restore_non_zip_file_does_not_change_db(tmp_path, monkeypatch):
    db_path = tmp_path / "scheduler.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    make_db(db_path, REQUIRED_TABLES)
    before = db_path.read_bytes()

    bad_zip = tmp_path / "not_a_zip.zip"
    bad_zip.write_bytes(b"not a zip file")

    result = restore_backup(bad_zip)

    assert result["success"] is False
    assert result["error"]
    assert db_path.read_bytes() == before
    assert not Path(f"{db_path}.restore-tmp").exists()
    assert not Path(f"{db_path}.old").exists()


def test_restore_corrupted_sqlite_does_not_change_db(tmp_path, monkeypatch):
    db_path = tmp_path / "scheduler.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    make_db(db_path, REQUIRED_TABLES)
    before = db_path.read_bytes()

    good_db = tmp_path / "good.db"
    make_db(good_db, REQUIRED_TABLES)
    corrupted_bytes = bytearray(good_db.read_bytes())
    assert len(corrupted_bytes) > 100
    corrupted_bytes[100:] = b"\xff" * (len(corrupted_bytes) - 100)

    corrupted_db = tmp_path / "corrupted.db"
    corrupted_db.write_bytes(corrupted_bytes)
    assert validate_database_file(corrupted_db) is not None

    zip_path = tmp_path / "backup.zip"
    _zip_entry(zip_path, "scheduler.db", corrupted_bytes)

    result = restore_backup(zip_path)

    assert result["success"] is False
    assert result["error"]
    assert db_path.read_bytes() == before
    assert not Path(f"{db_path}.restore-tmp").exists()
    assert not Path(f"{db_path}.old").exists()
