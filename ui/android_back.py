"""Системная кнопка «Назад» на Android.

Порядок: открыто меню или выпадающий список — закрыть его; открыто окно
(справка, карточка участника, любой диалог) — закрыть как «Отмена»;
иначе — подсказка «Нажмите «Назад» ещё раз, чтобы выйти», и второе нажатие
в течение EXIT_INTERVAL_MS закрывает программу.

Клавиша приходит из Qt как Key_Back (оболочку APK, которая раньше перехватывала
её сама, правит android/p4a_hook.py). Событие принимаем и на нажатие, и на
отпускание: непринятое отпускание Qt отдаёт Android, и тот закрывает программу.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QDialog, QWidget
from core.i18n import _

EXIT_INTERVAL_MS = 2000
EXIT_HINT = _("Нажмите «Назад» ещё раз, чтобы выйти")


class BackKeyHandler(QObject):
    def __init__(self, main_window: QWidget | None = None, parent=None, clock=time.monotonic):
        super().__init__(parent)
        self.main_window = main_window
        self._clock = clock
        self._last_back: float | None = None
        self._last_stamp = None

    def eventFilter(self, obj, event):
        etype = event.type()
        if etype not in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            return False
        if event.key() != Qt.Key.Key_Back:
            return False
        # Фильтр стоит на приложении — одно нажатие проходит через несколько
        # объектов (окно Qt, виджет в фокусе) с одной и той же меткой времени;
        # действуем один раз
        if etype == QEvent.Type.KeyPress and not event.isAutoRepeat():
            stamp = event.timestamp()
            if not stamp or stamp != self._last_stamp:
                self._last_stamp = stamp
                self.handle_back()
        return True

    def handle_back(self) -> str:
        """Выполнить действие «Назад». Возвращает, что сделано (для тестов)."""
        popup = QApplication.activePopupWidget()
        if popup is not None:
            popup.close()
            return "popup"

        window = QApplication.activeModalWidget() or QApplication.activeWindow()
        if window is not None and window is not self.main_window and window.isWindow():
            if isinstance(window, QDialog):
                window.reject()
            else:
                window.close()
            return "window"

        now = self._clock()
        if self._last_back is not None and (now - self._last_back) * 1000 <= EXIT_INTERVAL_MS:
            self._last_back = None
            if self.main_window is not None:
                self.main_window.close()
            QApplication.quit()
            return "quit"
        self._last_back = now
        if self.main_window is not None:
            from ui.toast import ToastNotification

            ToastNotification.show_toast(
                self.main_window, EXIT_HINT, success=True, duration_ms=EXIT_INTERVAL_MS
            )
        return "hint"


def install_back_handler(app, main_window) -> BackKeyHandler:
    handler = BackKeyHandler(main_window, parent=app)
    app.installEventFilter(handler)
    app._back_key_handler = handler  # держим ссылку
    return handler
