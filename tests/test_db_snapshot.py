"""Снимок базы перед авто-распределением месяца и откат к нему."""

import sqlite3
from types import SimpleNamespace

from core import db_snapshot


def _value(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT v FROM t").fetchone()[0]
    finally:
        conn.close()


def _set(path, v):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS t (v TEXT)")
    conn.execute("DELETE FROM t")
    conn.execute("INSERT INTO t VALUES (?)", (v,))
    conn.commit()
    conn.close()


def test_restore_returns_database_to_snapshot(tmp_path):
    db_path = str(tmp_path / "test.db")
    _set(db_path, "до распределения")
    snap = db_snapshot.take_snapshot(db_path, "month-auto")
    _set(db_path, "после распределения")
    closed = []
    db = SimpleNamespace(db_path=db_path, close=lambda: closed.append(True))
    db_snapshot.restore_snapshot(db, snap)
    assert _value(db_path) == "до распределения"
    assert closed == [True]  # соединения SQLAlchemy закрыты перед откатом


def test_only_last_snapshots_are_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(db_snapshot, "KEEP_SNAPSHOTS", 2)
    db_path = str(tmp_path / "test.db")
    _set(db_path, "x")
    paths = [db_snapshot.take_snapshot(db_path, "month-auto") for _ in range(4)]
    assert db_snapshot.list_snapshots(db_path) == paths[-2:]
