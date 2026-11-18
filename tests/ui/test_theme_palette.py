"""
Запрет на возвращение захардкоженных цветов в UI.

Цвет, зашитый в код, не переключается вместе с темой: тёмная тема ломалась
из-за тёмно-бирюзовых заголовков (#006064) на чёрном и белого фона блока
объявления. Теперь такие места берут цвета из core.styles.palette().

Тест перечисляет файлы, где работа ещё не закончена, — список не должен
уменьшаться молча.
"""

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
UI_DIR = PROJECT_ROOT / "ui"
MODULES_DIR = PROJECT_ROOT / "modules"

# Цвета, которые читались только на светлом фоне
FORBIDDEN = {
    "#006064": "бирюзовый заголовок — не читается на тёмном фоне",
    "#004d40": "тёмно-бирюзовый заголовок — не читается на тёмном фоне",
    "#00838f": "яркая бирюза в коде, должна быть из палитры",
    "#1b5e20": "зелёная заливка поля участника",
    "#2e7d32": "зелёная заливка поля участника",
    "#e8f5e9": "светло-зелёная подложка",
    "#ffebee": "подсветка конфликта — засвечивает тёмную тему",
    "#7b1fa2": "фиолетовая кнопка",
    "#1565c0": "синяя кнопка вместо акцента темы",
}

# Файлы, где цвета ещё не переведены на палитру.
# Уменьшение списка — это изменение, его нужно делать вместе с правкой файла.
PENDING: set = set()

COLOR_PATTERN = re.compile(r"#[0-9a-fA-F]{6}")


def _ui_files():
    return sorted(list(UI_DIR.glob("*.py")) + list(MODULES_DIR.glob("*.py")))


@pytest.mark.parametrize("path", _ui_files(), ids=lambda p: p.name)
def test_no_light_only_colors_in_ui_code(path):
    """В UI-коде не должно быть цветов, работающих только на светлом фоне."""
    if path.name in PENDING:
        pytest.skip(f"{path.name}: перевод на палитру ещё не сделан")

    source = path.read_text(encoding="utf-8")
    found = {color: reason for color, reason in FORBIDDEN.items() if color in source.lower()}
    assert not found, f"{path.name}: цвета должны идти из core.styles.palette() — " + "; ".join(
        f"{c} ({r})" for c, r in found.items()
    )


def test_pending_list_has_no_unnecessary_entries():
    """Файл из PENDING не должен содержать запрещённых цветов."""
    stale = []
    for name in sorted(PENDING):
        matches = [p for p in _ui_files() if p.name == name]
        if not matches:
            stale.append(f"{name} (файла нет)")
            continue
        source = matches[0].read_text(encoding="utf-8").lower()
        if not any(color in source for color in FORBIDDEN):
            stale.append(f"{name} (цвета уже переведены — уберите из списка)")
    assert not stale, "Список PENDING устарел: " + ", ".join(stale)


def test_no_white_background_in_widget_code():
    """`background: white` в коде виджета ломает тёмную тему."""
    offenders = []
    for path in _ui_files():
        if path.name in PENDING:
            continue
        source = path.read_text(encoding="utf-8").lower()
        if "background: white" in source or "background-color: white" in source:
            offenders.append(path.name)
    assert not offenders, f"Белый фон зашит в коде: {offenders}"


def test_dark_theme_has_no_loud_palette():
    """Тёмная тема не должна вернуть кислотные цвета."""
    theme = (
        (PROJECT_ROOT / "assets" / "styles" / "dark_theme.qss").read_text(encoding="utf-8").lower()
    )
    loud = [c for c in ("#1b5e20", "#2e7d32", "#7b1fa2", "#9c27b0", "#ffebee") if c in theme]
    assert not loud, f"В тёмной теме вернулись кричащие цвета: {loud}"


def test_palette_exposes_semantic_colors():
    """Палитра обязана покрывать цвета, которыми пользуется UI."""
    from core.styles import Theme, get_palette

    for theme in (Theme.LIGHT, Theme.DARK):
        colors = get_palette(theme)
        for name in (
            "text_primary",
            "text_secondary",
            "text_heading",
            "accent",
            "on_accent",
            "conflict_background",
            "surface",
        ):
            value = getattr(colors, name)
            assert COLOR_PATTERN.fullmatch(value), f"{theme.value}.{name} = {value}"
