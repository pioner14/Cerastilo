"""Журнал падений: необработанные ошибки и аварийные завершения → crash.log.

Без этого ошибка в обработчике щелчка (PySide6 при стандартном sys.excepthook
сразу завершает процесс) пропадала бесследно, если программа запущена ярлыком,
а не из терминала.
"""

import faulthandler
import logging
import os
import sys
import traceback
from datetime import datetime
from core.i18n import _

_fault_file = None  # держим открытым: faulthandler пишет в него при падении


def install_crash_handler(log_path: str) -> None:
    """Писать ошибки в log_path и сообщать о них, не закрывая программу."""
    global _fault_file
    # Аварийные завершения (segfault, abort) — трассировка всех потоков.
    # Если файл не открыть (папка только для чтения), программа всё равно стартует.
    try:
        os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
        _fault_file = open(log_path, "a", encoding="utf-8")
        faulthandler.enable(file=_fault_file, all_threads=True)
    except OSError as e:
        logging.getLogger(__name__).warning("crash.log unavailable (%s): %s", log_path, e)

    def handle(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                line = f"\n=== {stamp} — необработанная ошибка ===\n{text}"  # i18n: не переводить
                f.write(line)
        except OSError:
            pass
        # sys.stderr, а не __stderr__: на Android python-for-android
        # перенаправляет в logcat только sys.stderr
        (sys.stderr or sys.__stderr__).write(text)
        _show_message(exc, log_path)

    # С собственным excepthook PySide6 не завершает процесс, а вызывает его
    sys.excepthook = handle


def _show_message(exc, log_path: str) -> None:
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        if QApplication.instance() is None:
            return
        QMessageBox.warning(
            None,
            _("Ошибка"),
            _(
                "Произошла ошибка: {exc}\n\nПодробности записаны в {log_path}",
                exc=exc,
                log_path=log_path,
            ),
        )
    except Exception:
        pass  # сообщение о сбое не должно вызывать новый сбой
