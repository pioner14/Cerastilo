# core/export/qt_pdf.py
"""
PDF компактного расписания средствами Qt — для Android, где нет python-docx
и LibreOffice. Строки берутся из compact_layout (те же, что в DOCX/PDF на ПК),
оформление повторяет compact_v2_builder: две недели на лист A4.
"""
import html

from core.export.compact_layout import (
    CONTENT_WIDTH_CM,
    SECTION_LIVING,
    SECTION_MINISTRY,
    SECTION_TREASURES,
    TIME_COL_CM,
    build_week_layout,
    name_column_cm,
)

WEEKS_PER_PAGE = 2
MARGIN_MM = 12.5  # как COMPACT_MODERN_MARGIN в DOCX

COLOR_HEADER_BG = "#2E6EA6"
COLOR_GRAY = "#555555"
COLOR_LINE = "#D0D3D4"
SECTION_BG = {
    SECTION_TREASURES: "#D4E9F7",
    SECTION_MINISTRY: "#F5D5A0",
    SECTION_LIVING: "#F2B8B5",
}
SPECIAL_BG = {
    "memorial": "#7B1FA2",
    "circuit_assembly": "#1565C0",
    "regional_convention": "#2E7D32",
}

# Шрифты на Android (Roboto) шире Calibri — колонку имён берём шире.
QT_NAME_WIDEN = 1.1


def column_percents(layouts: list) -> tuple:
    """Ширины колонок листа в процентах, как в DOCX (compact_v2_builder.fit_columns)."""
    name = min(name_column_cm(layouts) * QT_NAME_WIDEN, CONTENT_WIDTH_CM - TIME_COL_CM - 4)
    w_time = round(TIME_COL_CM / CONTENT_WIDTH_CM * 100)
    w_name = round(name / CONTENT_WIDTH_CM * 100)
    return w_time, 100 - w_time - w_name, w_name


_CELL = f"border-bottom: 1px solid {COLOR_LINE}; padding: 2px 3px;"


def _esc(text: str) -> str:
    return html.escape(text or "").replace("\n", "<br/>")


def week_html(layout: dict, cols: tuple = None) -> str:
    """HTML одной недели (заголовок + таблица)."""
    special = layout["special"]
    if special:
        bg = SPECIAL_BG.get(special["event"], "#455A64")
        return (
            '<table width="100%" cellspacing="0" cellpadding="6" style="border-collapse: collapse;">'
            f'<tr><td align="center" style="background-color: {bg}; color: white; '
            f'font-size: 14pt; font-weight: bold;">{_esc(special["date"])}  —  {_esc(special["title"])}</td></tr>'
            f'<tr><td align="center" style="font-size: 12pt; font-style: italic;">{_esc(special["message"])}</td></tr>'
            "</table>"
        )

    header = layout["header"]
    parts = [
        '<table width="100%" cellspacing="0" cellpadding="3" style="border-collapse: collapse;">'
        "<tr>"
        f'<td width="34%" bgcolor="{COLOR_HEADER_BG}" style="color: white; font-size: 11pt; '
        f'font-weight: bold;">{_esc(header["title"])}</td>'
        f'<td width="33%" bgcolor="{COLOR_HEADER_BG}" align="center" style="color: white; '
        f'font-size: 10pt;">{_esc(header["reading"])}</td>'
        f'<td width="33%" bgcolor="{COLOR_HEADER_BG}" align="right" style="color: white; '
        f'font-size: 10pt;">{_esc(header["cong_name"])}</td>'
        "</tr></table>",
        '<table width="100%" cellspacing="0" cellpadding="0" style="border-collapse: collapse;">',
    ]
    w_time, w_text, w_name = cols or column_percents([layout])
    for row in layout["rows"]:
        if row["kind"] == "section":
            bg = SECTION_BG.get(row["section"], "#EEEEEE")
            parts.append(
                f'<tr style="background-color: {bg};">'
                f'<td width="{w_time}%" style="{_CELL}"></td>'
                f'<td colspan="2" style="{_CELL} font-size: 10.5pt; font-weight: bold;">{_esc(row["text"])}</td>'
                "</tr>"
            )
        elif row["kind"] == "module":
            parts.append(
                f'<tr><td colspan="3" align="center" style="{_CELL} font-style: italic;">'
                f'{_esc(row["text"])}</td></tr>'
            )
        else:
            parts.append(
                '<tr valign="middle">'
                f'<td width="{w_time}%" style="{_CELL} font-size: 9pt; color: {COLOR_GRAY};">{_esc(row["time"])}</td>'
                f'<td width="{w_text}%" style="{_CELL} font-size: 11pt;">{_esc(row["text"])}</td>'
                f'<td width="{w_name}%" style="{_CELL} font-size: 12pt; font-weight: bold;">{_esc(row["person"])}</td>'
                "</tr>"
            )
    parts.append("</table>")
    return "".join(parts)


def page_html(layouts: list) -> str:
    cols = column_percents(layouts)
    body = '<p style="font-size: 4pt;">&nbsp;</p>'.join(week_html(lay, cols) for lay in layouts)
    return (
        "<html><body style=\"font-family: 'Calibri', 'Carlito', 'Roboto', sans-serif; "
        f'font-size: 10pt; color: black;">{body}</body></html>'
    )


def render_compact_pdf(weeks_data: list, output_path: str) -> bool:
    """Нарисовать PDF: по WEEKS_PER_PAGE недели на страницу A4."""
    from PySide6.QtCore import QMarginsF
    from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter

    writer = QPdfWriter(output_path)
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(
        QMarginsF(MARGIN_MM, MARGIN_MM, MARGIN_MM, MARGIN_MM), QPageLayout.Unit.Millimeter
    )
    # 96 dpi — та же единица, в которой QTextDocument раскладывает HTML
    writer.setResolution(96)
    return paint_compact(writer, weeks_data)


def setup_printer(printer) -> None:
    """Лист и поля принтера — как у PDF (пользователь может поменять в диалоге)."""
    from PySide6.QtCore import QMarginsF
    from PySide6.QtGui import QPageLayout, QPageSize

    printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    printer.setPageMargins(
        QMarginsF(MARGIN_MM, MARGIN_MM, MARGIN_MM, MARGIN_MM), QPageLayout.Unit.Millimeter
    )


def paint_compact(device, weeks_data: list) -> bool:
    """Нарисовать расписание на страничное устройство: QPdfWriter или QPrinter.

    HTML раскладывается в единицах 96 dpi; у принтера разрешение выше,
    поэтому рисунок масштабируется под настоящее разрешение устройства.
    """
    from PySide6.QtCore import QRectF, QSizeF
    from PySide6.QtGui import QPainter, QTextDocument

    painter = QPainter(device)
    if not painter.isActive():
        return False
    try:
        scale = device.logicalDpiX() / 96.0 if device.logicalDpiX() > 0 else 1.0
        page = QSizeF(device.width() / scale, device.height() / scale)
        painter.scale(scale, scale)
        first_page = True
        layouts = [build_week_layout(w) for w in weeks_data]
        for start in range(0, len(layouts), WEEKS_PER_PAGE):
            doc = QTextDocument()
            doc.setDocumentMargin(0)
            doc.setHtml(page_html(layouts[start : start + WEEKS_PER_PAGE]))
            doc.setPageSize(page)
            for i in range(doc.pageCount()):
                if not first_page:
                    device.newPage()
                first_page = False
                painter.save()
                painter.translate(0, -i * page.height())
                doc.drawContents(painter, QRectF(0, i * page.height(), page.width(), page.height()))
                painter.restore()
    finally:
        painter.end()
    return True
