"""Следит за сменой светлой/тёмной темы в системе (xdg-desktop-portal).

Когда KDE или GNOME переключают цветовую схему (например, автоматически
вечером), портал шлёт сигнал SettingChanged. Если в настройках приложения
выбрано «Как в системе», тема применяется сразу, без перезапуска.
"""

import logging
from typing import Callable

from PySide6.QtCore import SLOT, QObject, Slot
from PySide6.QtDBus import QDBusConnection, QDBusMessage

logger = logging.getLogger(__name__)

PORTAL_SERVICE = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
PORTAL_INTERFACE = "org.freedesktop.portal.Settings"


class SystemThemeWatcher(QObject):
    """Вызывает on_change() при смене org.freedesktop.appearance/color-scheme."""

    def __init__(self, on_change: Callable[[], None], parent=None):
        super().__init__(parent)
        self._on_change = on_change
        bus = QDBusConnection.sessionBus()
        # PySide6: получатель — объект и сигнатура слота строкой
        self.connected = bus.isConnected() and bus.connect(
            PORTAL_SERVICE,
            PORTAL_PATH,
            PORTAL_INTERFACE,
            "SettingChanged",
            self,
            SLOT("_on_setting_changed(QDBusMessage)"),
        )
        if not self.connected:
            logger.info("System theme watcher: portal signal unavailable, live switching off")

    @Slot(QDBusMessage)
    def _on_setting_changed(self, message) -> None:
        args = message.arguments()
        if len(args) >= 2 and args[0] == "org.freedesktop.appearance" and args[1] == "color-scheme":
            try:
                self._on_change()
            except Exception as e:  # тема не должна ронять приложение
                logger.error(f"System theme watcher: failed to apply theme: {e}")
