"""Папка данных (crash.log рядом с базой) и устойчивость журнала падений."""

import os
import sys

from core.config import get_data_dir
import ui.crash_handler as ch


def test_data_dir_from_db_path_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "sub" / "x.db"))
    assert get_data_dir() == str(tmp_path / "sub")


def test_data_dir_default_is_absolute_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv("DB_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    d = get_data_dir()
    assert os.path.isabs(d)
    assert os.path.realpath(d) == os.path.realpath(tmp_path)


def test_crash_handler_survives_unwritable_log(tmp_path, monkeypatch):
    old_hook = sys.excepthook
    monkeypatch.setattr(ch, "_fault_file", None)
    try:
        ch.install_crash_handler(str(tmp_path))  # каталог вместо файла: OSError
    finally:
        sys.excepthook = old_hook
