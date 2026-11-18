"""Переключатель языка интерфейса (core/i18n.py) и полнота английского перевода."""

import ast
import re
from pathlib import Path

import pytest

from core import i18n
from core.i18n_en import EN

ROOT = Path(__file__).resolve().parent.parent
CYR = re.compile("[А-Яа-яЁё]")
PLACEHOLDER = re.compile(r"(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_]*)?(![rsa])?(:[^{}]*)?\}(?!\})")

# Файлы, где весь видимый текст интерфейса обёрнут в _()/tr()
FULLY_WRAPPED = (
    [ROOT / "main.py", *sorted((ROOT / "ui").glob("*.py"))]
    + [
        ROOT / "core" / name
        for name in (
            "month_board.py",
            "statistics.py",
            "sync_service.py",
            "error_service.py",
            "leader_dashboard.py",
        )
    ]
    + [ROOT / "modules" / "announcement.py"]
)
# Где _() встречается точечно — проверяем только наличие перевода
PARTLY_WRAPPED = [ROOT / "core" / "base_facade.py"]

WRAPPERS = {"_", "tr"}
ALLOWED_CALLS = WRAPPERS | {"plural", "_plural", "print"}
LOGGERS = {"logger", "logging", "log"}


def _parents(tree):
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _call_name(call: ast.Call) -> str:
    func = call.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


def unwrapped_cyrillic(path: Path):
    """Кириллические литералы вне _()/tr()/plural(), логов и докстрингов."""
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source)
    parents = _parents(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if not CYR.search(node.value) or isinstance(parents.get(node), ast.JoinedStr):
                continue
        elif isinstance(node, ast.JoinedStr):
            if not any(isinstance(v, ast.Constant) and CYR.search(v.value) for v in node.values):
                continue
        else:
            continue
        if isinstance(parents.get(node), ast.Expr):  # докстринг
            continue
        if "i18n: не переводить" in lines[node.lineno - 1] or "Language" in str(
            getattr(node, "value", "")
        ):
            continue
        allowed = False
        up = parents.get(node)
        while up is not None and not isinstance(up, ast.stmt):
            if isinstance(up, ast.Call):
                base = getattr(getattr(up.func, "value", None), "id", "")
                if _call_name(up) in ALLOWED_CALLS or base in LOGGERS:
                    allowed = True
                    break
            up = parents.get(up)
        if not allowed:
            found.append(
                f"{path.relative_to(ROOT)}:{node.lineno}: {ast.get_source_segment(source, node)[:60]}"
            )
    return found


def translation_keys(path: Path):
    """Строки из _("…")/tr("…") и формы из plural(n, "…", "…", "…")."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        args = node.args
        if node.func.id in WRAPPERS and args and isinstance(args[0], ast.Constant):
            if isinstance(args[0].value, str) and CYR.search(args[0].value):
                yield node.lineno, args[0].value
        elif node.func.id in ("plural", "_plural") and len(args) == 4:
            if all(isinstance(a, ast.Constant) for a in args[1:]):
                yield node.lineno, "|".join(a.value for a in args[1:])


def _placeholders(text: str):
    return sorted(m.group(1) or "" for m in PLACEHOLDER.finditer(text))


@pytest.mark.parametrize("path", FULLY_WRAPPED, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_unwrapped_russian_text(path):
    assert unwrapped_cyrillic(path) == []


@pytest.mark.parametrize(
    "path", FULLY_WRAPPED + PARTLY_WRAPPED, ids=lambda p: str(p.relative_to(ROOT))
)
def test_every_string_has_english_translation(path):
    missing = [f"{line}: {key!r}" for line, key in translation_keys(path) if key not in EN]
    assert missing == []


def test_translations_keep_placeholders():
    wrong = []
    for key, value in EN.items():
        if "|" in key and isinstance(value, tuple):
            continue
        assert isinstance(value, str), key
        if _placeholders(key) != _placeholders(value):
            wrong.append(key)
    assert wrong == []


def test_plural_entries_are_pairs():
    for key, value in EN.items():
        if isinstance(value, tuple):
            assert key.count("|") == 2 and len(value) == 2, key


def test_fallback_and_switch():
    try:
        i18n.set_language("en")
        assert i18n._("Сохранить в EN нет такой строки") == "Сохранить в EN нет такой строки"
        assert i18n._("Ошибка") == EN["Ошибка"]
        assert i18n._("{n} без перевода", n=3) == "3 без перевода"
        i18n.set_language("ru")
        assert i18n._("Ошибка") == "Ошибка"
    finally:
        i18n.set_language("ru")


def test_plural_forms():
    assert [i18n.plural(n, "неделя", "недели", "недель") for n in (1, 2, 5, 11, 21, 104)] == [
        "неделя",
        "недели",
        "недель",
        "недель",
        "неделя",
        "недели",
    ]
    try:
        i18n.set_language("en")
        key = next(k for k, v in EN.items() if isinstance(v, tuple))
        one, few, many = key.split("|")
        assert i18n.plural(1, one, few, many) == EN[key][0]
        assert i18n.plural(5, one, few, many) == EN[key][1]
    finally:
        i18n.set_language("ru")


def test_language_saved_per_device(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.delenv("NHJS_LANG", raising=False)
    assert i18n.load_saved_language() == "ru"
    i18n.save_language("en")
    assert (tmp_path / "ui_language").read_text(encoding="utf-8") == "en"
    assert i18n.load_saved_language() == "en"
    (tmp_path / "ui_language").write_text("xx", encoding="utf-8")
    assert i18n.load_saved_language() == "ru"
    with pytest.raises(ValueError, match="Неизвестный язык"):
        i18n.save_language("de")


def test_bad_translation_placeholder_falls_back(monkeypatch):
    monkeypatch.setattr(i18n, "_catalog", {"Недель: {n}": "Weeks: {count}"})
    assert i18n._("Недель: {n}", n=4) == "Недель: 4"
