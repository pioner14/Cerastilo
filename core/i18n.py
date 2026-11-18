"""Язык интерфейса: русский (исходный) или английский.

В коде пишем русский текст и оборачиваем его: ``_("Сохранить")``. Английский
перевод ищется в словаре ``core.i18n_en.EN`` по самому русскому тексту; нет
перевода — показывается русский.

Подстановки — только после перевода: ``_("Недель: {n}").format(n=n)`` или
``_("Недель: {n}", n=n)``. Обёрнутая f-строка не найдётся в словаре.

Числа с существительным — ``plural(n, "неделя", "недели", "недель")``:
в словаре ключ — три русские формы через «|», значение — («week», «weeks»).

Язык хранится на устройстве (файл ``ui_language`` рядом с базой), а не в
таблице settings: база синхронизируется ПК ↔ планшет, а язык у каждого свой.
Язык читается один раз при импорте модуля — поэтому строки на уровне модулей
ui/ тоже переводятся; смена языка применяется после перезапуска.
Без Qt — чтобы проверять тестами без окна.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_LANGUAGE = "ru"
# код → подпись в списке выбора (каждая на своём языке)
LANGUAGES = {"ru": "Русский", "en": "English"}

_FILE_NAME = "ui_language"


def _settings_dir() -> str:
    """Папка базы: на Android — личная папка приложения, на ПК — папка программы."""
    db_path = os.environ.get("DB_PATH")
    if db_path and os.path.dirname(db_path):
        return os.path.dirname(os.path.abspath(db_path))
    from core.config import get_app_path

    return get_app_path()


def language_file() -> str:
    return os.path.join(_settings_dir(), _FILE_NAME)


def load_saved_language() -> str:
    """Язык из переменной NHJS_LANG или из файла; иначе русский."""
    lang = os.environ.get("NHJS_LANG", "").strip()
    if not lang:
        try:
            with open(language_file(), encoding="utf-8") as f:
                lang = f.read().strip()
        except OSError:
            lang = ""
    return lang if lang in LANGUAGES else DEFAULT_LANGUAGE


def save_language(lang: str) -> None:
    """Запомнить язык на этом устройстве (включится после перезапуска)."""
    if lang not in LANGUAGES:
        raise ValueError(f"Неизвестный язык: {lang}")
    with open(language_file(), "w", encoding="utf-8") as f:
        f.write(lang)


_current = DEFAULT_LANGUAGE
_catalog: dict = {}


def set_language(lang: str) -> None:
    """Включить язык для строк, переведённых после вызова."""
    global _current, _catalog
    _current = lang if lang in LANGUAGES else DEFAULT_LANGUAGE
    if _current == "en":
        from core.i18n_en import EN

        _catalog = EN
    else:
        _catalog = {}


def language() -> str:
    return _current


def _(text: str, /, **kwargs) -> str:
    """Перевод строки интерфейса; с kwargs — ещё и подстановка {имя}."""
    result = _catalog.get(text, text) if _catalog else text
    if kwargs:
        try:
            return result.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            logger.warning("Перевод с неверными подстановками: %r", result)
            return text.format(**kwargs)
    return result


def tr(text: str, /, **kwargs) -> str:
    """То же, что ``_`` — для мест, где имя ``_`` занято (``for _, x in …``)."""
    return _(text, **kwargs)


def _ru_form(n: int, one: str, few: str, many: str) -> str:
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def plural(n: int, one: str, few: str, many: str) -> str:
    """Форма слова для числа n: русские три формы или английские две."""
    if _catalog:
        forms = _catalog.get(f"{one}|{few}|{many}")
        if forms:
            return forms[0] if abs(n) == 1 else forms[1]
    return _ru_form(n, one, few, many)


set_language(load_saved_language())
