"""Check the shipped English help and its shared screenshots."""

import re
import unicodedata

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QApplication

from core.help_docs import TAB_SECTIONS, help_root, read_document, section_matches
from ui.help_dialog import HelpDialog


@pytest.mark.parametrize("key", ["guide", "quick_start"])
def test_english_help_document(key):
    _, path = read_document(key, "en")

    assert path == help_root() / "en" / f"{key}.md"
    markdown = path.read_text(encoding="utf-8")
    assert markdown.startswith("# Cerastilo")
    assert not any("CYRILLIC" in unicodedata.name(char, "") for char in markdown)

    for image in re.findall(r"!\[[^\]\n]*\]\(([^)]+)\)", markdown):
        assert (path.parent / image).is_file(), image


@pytest.mark.parametrize("number", TAB_SECTIONS.values())
def test_english_guide_has_tab_section(number):
    markdown, _ = read_document("guide", "en")
    headings = re.findall(r"^#{2,6} (.+)$", markdown, re.MULTILINE)
    assert any(section_matches(title, number) for title in headings)


def test_english_help_loads_shared_screenshots(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    dialog = HelpDialog(language="en")
    markdown, _ = read_document("guide", "en")
    images = re.findall(r"!\[[^\]\n]*\]\(([^)]+)\)", markdown)
    assert images

    document = dialog.browser.document()
    for image in images:
        resource = document.resource(QTextDocument.ResourceType.ImageResource, QUrl(image))
        assert resource is not None, image
        assert dialog._natural_size(image) is not None, image

    assert dialog.open_section("8.1")
    assert dialog.load_document("quick_start")
    assert dialog.browser.toPlainText().startswith("Cerastilo Quick Start")
    dialog.close()
    dialog.deleteLater()
    app.processEvents()
