"""Русский перевод стандартных кнопок и диалогов Qt (Yes/No → Да/Нет, Cancel…).

Без QTranslator QMessageBox и QDialogButtonBox подписаны по-английски — и на
ПК, и в APK. Файл qtbase_ru.qm идёт вместе с PySide6.
"""

import logging
import os

from PySide6.QtCore import QLibraryInfo, QTranslator

logger = logging.getLogger(__name__)


def _translation_dirs():
    yield QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    import PySide6  # в APK путь из QLibraryInfo может не совпасть с пакетом

    yield os.path.join(os.path.dirname(PySide6.__file__), "Qt", "translations")


def install_qt_translator(app, language: str | None = None) -> bool:
    """Подключить qtbase_<language>.qm (по умолчанию — язык интерфейса).

    True — перевод загружен или не нужен (английский у Qt встроенный).
    """
    if language is None:
        from core.i18n import language as ui_language

        language = ui_language()
    if language == "en":
        return True
    translator = QTranslator(app)
    for folder in _translation_dirs():
        if folder and translator.load(f"qtbase_{language}", folder):
            app.installTranslator(translator)
            app._qt_translator = translator  # держим ссылку, иначе перевод пропадёт
            return True
    logger.warning("Перевод Qt qtbase_%s не найден — кнопки диалогов будут по-английски", language)
    return False
