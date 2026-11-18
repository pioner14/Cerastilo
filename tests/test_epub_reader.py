"""Чтение EPUB через zipfile (без EbookLib): порядок и состав документов."""

import zipfile

from core.epub_parser import iter_epub_documents

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

OPF = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
<manifest>
<item id="toc" properties="nav" href="toc.xhtml" media-type="application/xhtml+xml"/>
<item id="css" href="css/a.css" media-type="text/css"/>
<item id="b" href="part%20b.xhtml" media-type="application/xhtml+xml"/>
<item id="a" href="a.xhtml" media-type="application/xhtml+xml"/>
</manifest>
<spine><itemref idref="a"/><itemref idref="b"/></spine>
</package>"""


def _make_epub(path):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", OPF)
        zf.writestr("OEBPS/toc.xhtml", "<html><body>toc</body></html>")
        zf.writestr("OEBPS/css/a.css", "p{}")
        zf.writestr("OEBPS/part b.xhtml", "<html><body>B</body></html>")
        zf.writestr("OEBPS/a.xhtml", "<html><body>A</body></html>")


def test_documents_in_manifest_order_without_non_xhtml(tmp_path):
    path = tmp_path / "t.epub"
    _make_epub(path)
    docs = list(iter_epub_documents(str(path)))
    # порядок — по manifest (не по spine), css не входит, href декодируется
    assert [n for n, _ in docs] == ["toc.xhtml", "part b.xhtml", "a.xhtml"]
    assert docs[1][1] == b"<html><body>B</body></html>"


def test_parser_skips_nav_document(tmp_path):
    from core.epub_parser import WorkbookParser

    path = tmp_path / "t.epub"
    _make_epub(path)
    assert WorkbookParser(str(path)).parse() == []


def test_parser_reads_utf16_document(tmp_path, monkeypatch):
    """Документ в UTF-16 (с BOM) читается как текст, а не как мусор."""
    from core.epub_parser import WorkbookParser

    path = tmp_path / "t.epub"
    html = '<?xml version="1.0" encoding="UTF-16"?><html><body><h1>Неделя 1</h1></body></html>'
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", OPF)
        zf.writestr("OEBPS/a.xhtml", html.encode("utf-16"))
        zf.writestr("OEBPS/part b.xhtml", "<html><body>B</body></html>")
        zf.writestr("OEBPS/toc.xhtml", "<html><body>toc</body></html>")

    seen = []
    monkeypatch.setattr(
        WorkbookParser, "_try_parse_week", lambda self, soup: seen.append(soup.get_text())
    )
    WorkbookParser(str(path)).parse()
    assert "Неделя 1" in seen
