"""Тесты встроенной справки (core/help_docs.py, ui/help_dialog.py)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.help_docs import (
    DEFAULT_LANGUAGE,
    TAB_SECTIONS,
    document_path,
    help_root,
    section_matches,
    strip_manual_contents,
    tr,
)
from ui.help_dialog import HelpDialog


# --- 1. strip_manual_contents ------------------------------------------------


def test_strip_manual_contents_removes_section():
    md = (
        "# Руководство\n"
        "\n"
        "## Содержание\n"
        "1. Первая\n"
        "2. Вторая\n"
        "\n"
        "## 1. Первая\n"
        "Текст первой.\n"
        "### Подраздел\n"
        "## 2. Вторая\n"
        "Текст второй.\n"
    )
    result = strip_manual_contents(md)
    assert "## Содержание" not in result
    assert "1. Первая\n" not in result.split("## 1. Первая")[0]
    assert "## 1. Первая" in result
    assert "### Подраздел" in result
    assert "## 2. Вторая" in result
    assert result.startswith("# Руководство")


def test_strip_manual_contents_no_section():
    md = "# Т\n\n## 1. Один\nтекст\n"
    assert strip_manual_contents(md) == md


def test_strip_manual_contents_keeps_h3_inside():
    md = "## Содержание\n### Вложенный\n## 2. Далее\n"
    result = strip_manual_contents(md)
    assert "Содержание" not in result
    assert "Вложенный" not in result
    assert "## 2. Далее" in result


# --- 2. document_path --------------------------------------------------------


def test_document_path_fallback_to_ru(tmp_path: Path):
    ru = tmp_path / "ru"
    ru.mkdir()
    (ru / "guide.md").write_text("# Ру", encoding="utf-8")
    path = document_path("guide", "en", root=tmp_path)
    assert path == ru / "guide.md"


def test_document_path_prefers_language(tmp_path: Path):
    for lang, text in (("ru", "# Ру"), ("en", "# En")):
        d = tmp_path / lang
        d.mkdir()
        (d / "guide.md").write_text(text, encoding="utf-8")
    assert document_path("guide", "en", root=tmp_path) == tmp_path / "en" / "guide.md"
    assert document_path("guide", "de", root=tmp_path) == tmp_path / "ru" / "guide.md"


# --- 3. tr -------------------------------------------------------------------


def test_tr_fallback_unknown_language():
    assert tr("title", "xx") == tr("title", DEFAULT_LANGUAGE)
    assert tr("title", "xx") == "Справка"


def test_tr_substitution():
    text = tr("not_found", "ru", text="abc")
    assert "abc" in text
    assert "{text}" not in text
    en = tr("not_found", "en", text="abc")
    assert "abc" in en


# --- 4. TAB_SECTIONS в реальном руководстве -----------------------------------


def _guide_titles() -> list[str]:
    path = help_root() / DEFAULT_LANGUAGE / "guide.md"
    titles = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.lstrip("#").strip()
        if line.startswith("#") and stripped:
            titles.append(stripped)
    return titles


@pytest.mark.parametrize("tab,number", sorted(TAB_SECTIONS.items()))
def test_tab_section_exists_in_guide(tab: str, number: str):
    titles = _guide_titles()
    assert any(
        section_matches(t, number) for t in titles
    ), f"в guide.md нет главы {number} для вкладки {tab}"


def test_section_matches():
    assert section_matches("6. Составление", "6")
    assert not section_matches("6.1. Что-то", "6")  # нужен пробел после номера
    assert section_matches("8.1. История", "8.1")
    assert not section_matches("8.2. Статистика", "8.1")


# --- 5. HelpDialog -----------------------------------------------------------


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def dialog(qapp):
    d = HelpDialog(None, "ru")
    yield d
    d.close()
    d.deleteLater()


def test_headings_not_empty(dialog: HelpDialog):
    headings = dialog.headings()
    assert headings
    assert all(title for _, title in headings)


def test_open_section(dialog: HelpDialog):
    assert dialog.open_section("6") is True
    assert dialog.open_section("99") is False


def test_find_next_found_and_not_found(dialog: HelpDialog):
    assert dialog.browser.toPlainText()
    dialog.search_edit.setText("S-89")
    assert dialog.find_next() is True
    assert dialog.browser.textCursor().selectedText() == "S-89"
    assert dialog.status_label.isHidden()
    dialog.search_edit.setText("абракадабра-уникум-xyz")
    assert dialog.find_next() is False
    assert not dialog.status_label.isHidden()
    assert "абракадабра-уникум-xyz" in dialog.status_label.text()


def test_load_quick_start(dialog: HelpDialog):
    assert dialog.load_document("quick_start")
    titles = [t for _, t in dialog.headings()]
    steps = [t for t in titles if t.startswith("Шаг ")]
    assert steps, f"нет заголовков 'Шаг N.' в {titles}"
    assert any(t.startswith("Шаг 1.") for t in steps)


def test_images_not_wider_than_viewport(dialog: HelpDialog):
    dialog.resize(900, 700)
    dialog.show()
    QApplication.processEvents()
    dialog._fit_images()
    QApplication.processEvents()
    max_width = dialog.browser.viewport().width() - 40
    doc = dialog.browser.document()
    block = doc.begin()
    checked = 0
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            fragment = it.fragment()
            fmt = fragment.charFormat()
            if fragment.isValid() and fmt.isImageFormat():
                image_fmt = fmt.toImageFormat()
                assert image_fmt.width() <= max(200, max_width) + 1
                checked += 1
            it += 1
        block = block.next()
    assert checked > 0  # скриншоты в руководстве есть


def test_section_stays_on_top_after_resize(dialog: HelpDialog):
    """На Android окно разворачивается после open_section — глава должна остаться вверху."""
    dialog.resize(1100, 760)
    dialog.show()
    QApplication.processEvents()
    assert dialog.open_section("6")
    dialog.resize(600, 500)  # текст переносится заново, позиции блоков меняются
    QApplication.processEvents()
    dialog._fit_images()  # то же, что делает таймер после изменения размера
    doc = dialog.browser.document()
    block = next(
        doc.findBlock(pos) for _lvl, title, pos in dialog._headings if title.startswith("6. ")
    )
    top = int(doc.documentLayout().blockBoundingRect(block).top())
    bar = dialog.browser.verticalScrollBar()
    assert bar.value() == min(top, bar.maximum())


def test_found_text_near_top(dialog: HelpDialog):
    """Найденное слово — у верхнего края текста (внизу на планшете клавиатура)."""
    dialog.resize(1100, 760)
    dialog.show()
    QApplication.processEvents()
    dialog.search_edit.setText("S-89")
    assert dialog.find_next()
    top = dialog.browser.cursorRect(dialog.browser.textCursor()).top()
    assert 0 <= top <= dialog.browser.viewport().height() // 3
