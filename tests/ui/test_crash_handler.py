"""Журнал падений: необработанная ошибка пишется в файл."""

import faulthandler
import sys

import ui.crash_handler as ch


def test_unhandled_error_is_logged(tmp_path, monkeypatch):
    log = tmp_path / "crash.log"
    shown = []
    monkeypatch.setattr(ch, "_show_message", lambda exc, path: shown.append(str(exc)))
    old_hook = sys.excepthook
    try:
        ch.install_crash_handler(str(log))
        try:
            raise ValueError("сбой при щелчке по неделе")
        except ValueError:
            sys.excepthook(*sys.exc_info())
    finally:
        sys.excepthook = old_hook
        faulthandler.disable()
        ch._fault_file.close()

    text = log.read_text(encoding="utf-8")
    assert "необработанная ошибка" in text
    assert "ValueError: сбой при щелчке по неделе" in text
    assert shown == ["сбой при щелчке по неделе"]
