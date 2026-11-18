import logging
import traceback
from typing import Optional, Dict, Any
from core.events import EventBus, Event
from core.i18n import _

logger = logging.getLogger(__name__)

# Модули DOCX/S-89 и импорта EPUB: в APK их нет, пока он собран без WITH_DOCX=1
# (android/build_apk.sh) — вместо «No module named 'docx'» объясняем по-русски
_OPTIONAL_MODULES = {
    "docx": _("экспорт DOCX и S-89"),
    "lxml": _("экспорт DOCX и S-89, импорт тетради EPUB"),
    "bs4": _("импорт тетради EPUB"),
}


def _friendly_message(exception: Exception) -> str:
    if isinstance(exception, ModuleNotFoundError):
        root = (exception.name or "").split(".")[0]
        if root in _OPTIONAL_MODULES:
            return _(
                "В этой версии приложения нет модуля «{root}» ({v}). Сделайте это на компьютере — или соберите APK с WITH_DOCX=1.",
                root=root,
                v=_OPTIONAL_MODULES[root],
            )
    return str(exception)


class ErrorService:
    """
    Centralized service for error handling and reporting.
    Can emit events for UI to show alerts.
    """

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus

    def handle_exception(
        self, exception: Exception, context: str = "", extra: Optional[Dict[str, Any]] = None
    ):
        """Logs the exception and notifies the user via EventBus."""
        err_msg = _friendly_message(exception)
        tb = traceback.format_exc()

        logger.error(f"Exception in {context}: {err_msg}\n{tb}", extra=extra)

        # Notify UI
        self.event_bus.emit(Event.ERROR_OCCURRED, message=err_msg, context=context, traceback=tb)

        return {"success": False, "error": err_msg, "context": context}

    def report_error(self, message: str, context: str = ""):
        """Reports a non-exception error."""
        logger.error(f"Error in {context}: {message}")
        self.event_bus.emit(Event.ERROR_OCCURRED, message=message, context=context)
        return {"success": False, "error": message}
