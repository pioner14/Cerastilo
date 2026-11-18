"""Встроенная справка: где лежат тексты, подписи окна, привязка вкладок к главам.

Тексты справки — Markdown в ``docs/help/<язык>/`` (``guide.md`` — руководство,
``quick_start.md`` — «Быстрый старт», картинки в ``screenshots/`` рядом).
Если перевода на нужный язык нет, показывается русский текст.
Без Qt — чтобы проверять тестами без окна.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

DEFAULT_LANGUAGE = "ru"

# Документы справки: ключ → имя файла в docs/help/<язык>/
DOCUMENTS = {
    "guide": "guide.md",
    "quick_start": "quick_start.md",
}

# Вкладка главного окна → номер главы руководства (заголовок «## 6. …»).
TAB_SECTIONS = {
    "dashboard": "3",
    "schedule": "6",
    "participants": "5",
    "history": "8.1",
    "statistics": "8.2",
    "workbooks": "4",
    "settings": "11",
}

# Подписи окна справки. Для нового языка достаточно добавить словарь.
STRINGS = {
    "ru": {
        "button": "❓ Справка",
        "button_tip": "Руководство пользователя (F1)",
        "title": "Справка",
        "guide": "Руководство",
        "quick_start": "Быстрый старт",
        "search": "Поиск по тексту…",
        "find_next": "Найти",
        "not_found": "Не найдено: «{text}»",
        "contents": "Оглавление",
        "toggle_contents": "Оглавление",
        "close": "Закрыть",
        "missing": "Файл справки не найден: {path}",
    },
    "en": {
        "button": "❓ Help",
        "button_tip": "User guide (F1)",
        "title": "Help",
        "guide": "User guide",
        "quick_start": "Quick start",
        "search": "Search the text…",
        "find_next": "Find",
        "not_found": "Not found: “{text}”",
        "contents": "Contents",
        "toggle_contents": "Contents",
        "close": "Close",
        "missing": "Help file not found: {path}",
    },
}


def tr(key: str, language: str = DEFAULT_LANGUAGE, **kwargs) -> str:
    """Подпись окна справки на нужном языке (нет перевода — по-русски)."""
    text = STRINGS.get(language, {}).get(key) or STRINGS[DEFAULT_LANGUAGE][key]
    return text.format(**kwargs) if kwargs else text


def help_root() -> Path:
    """Папка docs/help — рядом с кодом и на ПК, и в APK (build_apk.sh её копирует)."""
    return Path(__file__).resolve().parent.parent / "docs" / "help"


def document_path(doc: str, language: str = DEFAULT_LANGUAGE, root: Path | None = None) -> Path:
    """Путь к тексту справки на языке ``language``, иначе — к русскому."""
    root = root or help_root()
    filename = DOCUMENTS[doc]
    path = root / language / filename
    if path.is_file():
        return path
    return root / DEFAULT_LANGUAGE / filename


_CONTENTS_TITLES = {"содержание", "contents", "table of contents"}


def strip_manual_contents(markdown: str) -> str:
    """Убрать раздел «## Содержание»: в окне справки оглавление стоит сбоку и кликается."""
    lines = markdown.splitlines(keepends=True)
    out = []
    skipping = False
    for line in lines:
        match = re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
        if match:
            level, title = len(match.group(1)), match.group(2).strip().lower()
            if skipping and level <= 2:
                skipping = False
            elif not skipping and level == 2 and title in _CONTENTS_TITLES:
                skipping = True
                continue
        if not skipping:
            out.append(line)
    return "".join(out)


def section_matches(title: str, number: str) -> bool:
    """Заголовок «6. Составление…» или «8.1. История…» относится к главе ``number``."""
    return title.strip().startswith(f"{number}. ")


def read_document(doc: str, language: str = DEFAULT_LANGUAGE) -> tuple[str, Path]:
    """Текст справки (без «Содержания») и путь к файлу. Нет файла — FileNotFoundError."""
    path = document_path(doc, language)
    text = path.read_text(encoding="utf-8")
    if doc == "guide":
        text = strip_manual_contents(text)
    return text, path


def help_available() -> bool:
    return os.path.isfile(document_path("guide"))
