# core/export/compact_v2_builder.py
"""
Билдер для компактного современного формата (Compact Modern v2).

Формат: 3 колонки жёсткой ширины, имена по левому краю, мягкие цвета.
Заголовок недели в отдельной таблице.

См. spec://export/docx#compact-v2-builder
"""

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from core.export.base_builder import BaseTableBuilder
from core.export.compact_layout import (
    CONTENT_WIDTH_CM,
    SECTION_LIVING,
    SECTION_MINISTRY,
    SECTION_TREASURES,
    TIME_COL_CM,
    build_week_layout,
    name_column_cm,
)


class CompactV2TableBuilder(BaseTableBuilder):
    """
    Компактный современный формат (v2).

    Особенности:
    - 3 колонки: Время | Тема | Участник (имена слева, без пустой середины)
    - Мягкие пастельные цвета
    - Заголовок недели в отдельной таблице
    - Минимальные отступы для компактности

    См. spec://export/docx#compact-v2-builder
    """

    # Цвета для современного дизайна
    COLOR_HEADER_BG = "2E6EA6"  # Steel Blue
    COLOR_WHITE = "FFFFFF"
    COLOR_TREASURES = "D4E9F7"  # Light blue
    COLOR_MINISTRY = "F5D5A0"  # Light amber
    COLOR_LIVING = "F2B8B5"  # Light rose
    COLOR_GRAY = "555555"

    # Шрифты
    FONT_MAIN = "Calibri"
    SZ_MAIN = Pt(11)
    SZ_NAME = Pt(12)
    SZ_HEADER = Pt(10.5)

    def fit_columns(self, weeks_data: list) -> None:
        """Ширины колонок для листа: колонка имён — по самому длинному имени
        недель этого листа (обе недели листа выровнены одинаково)."""
        layouts = [build_week_layout(w) for w in weeks_data]
        name_cm = name_column_cm(layouts)
        self.COL_WIDTHS = (
            Cm(TIME_COL_CM),
            Cm(CONTENT_WIDTH_CM - TIME_COL_CM - name_cm),
            Cm(name_cm),
        )

    def build(self, doc: Document, week_data: dict) -> None:
        """
        Построить таблицу для недели в компактном современном формате.

        Args:
            doc: Документ python-docx
            week_data: Данные недели
        """
        # Если неделя отмечена как конгресс / Вечеря — вставить заглушку
        if self._try_build_special_event(doc, week_data):
            return

        # Строки расписания — общие с PDF на Android (core/export/compact_layout.py)
        layout = build_week_layout(week_data)
        header = layout["header"]

        # === ЗАГОЛОВОК НЕДЕЛИ (отдельная таблица) ===
        self._build_header_table(doc, header)

        # === ОСНОВНАЯ ТАБЛИЦА ===
        table = self._create_main_table(doc)
        line_sp = 0.95 if layout["dense"] else 1.0
        section_colors = {
            SECTION_TREASURES: self.COLOR_TREASURES,
            SECTION_MINISTRY: self.COLOR_MINISTRY,
            SECTION_LIVING: self.COLOR_LIVING,
        }
        for row in layout["rows"]:
            if row["kind"] == "section":
                self._add_section_row(
                    table, row["text"], section_colors[row["section"]], line_sp=line_sp
                )
            elif row["kind"] == "module":
                self._add_module_row(table, row["text"], line_sp)
            else:
                self._add_row(table, row["time"], row["text"], row["person"], line_sp=line_sp)

    def _build_header_table(self, doc: Document, header: dict) -> None:
        """Создать заголовок недели: дата | чтение Библии | собрание."""
        h_table = doc.add_table(rows=1, cols=3)
        self._fix_widths(h_table, self.HEADER_WIDTHS)
        for c, w in zip(h_table.rows[0].cells, self.HEADER_WIDTHS):
            c.width = w
        h_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        h_table.rows[0].height_rule = WD_ROW_HEIGHT_RULE.EXACTLY
        h_table.rows[0].height = Cm(0.65)

        for c in h_table.rows[0].cells:
            self._set_cell_bg_oxml(c, self.COLOR_HEADER_BG)
            c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            c.paragraphs[0].paragraph_format.space_before = Pt(0)
            c.paragraphs[0].paragraph_format.space_after = Pt(0)

        # Дата (левая ячейка)
        p = h_table.rows[0].cells[0].paragraphs[0]
        r = p.add_run(header["title"])
        r.font.name = self.FONT_MAIN
        r.font.size = Pt(11)
        r.bold = True
        r.font.color.rgb = RGBColor.from_string(self.COLOR_WHITE)
        p.paragraph_format.left_indent = Pt(4)

        # Чтение Библии (центр)
        p = h_table.rows[0].cells[1].paragraphs[0]
        r = p.add_run(header["reading"])
        r.font.name = self.FONT_MAIN
        r.font.size = Pt(10)
        r.font.color.rgb = RGBColor.from_string(self.COLOR_WHITE)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER

        # Название собрания (правая ячейка)
        p = h_table.rows[0].cells[2].paragraphs[0]
        r = p.add_run(header["cong_name"])
        r.font.name = self.FONT_MAIN
        r.font.size = Pt(10)
        r.font.color.rgb = RGBColor.from_string(self.COLOR_WHITE)
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p.paragraph_format.right_indent = Pt(4)

    # Ширины колонок: время | пункт | имя; сумма — A4 без полей (21 − 2 × 1,25 см).
    # Экспорт подгоняет их под каждый лист через fit_columns().
    COL_WIDTHS = (Cm(1.2), Cm(9.3), Cm(8.0))
    HEADER_WIDTHS = (Cm(6.2), Cm(6.1), Cm(6.2))

    @staticmethod
    def _fix_widths(table, widths) -> None:
        """Жёсткие ширины колонок: без tblLayout=fixed и w:gridCol Word и
        LibreOffice подбирают ширины сами и делят таблицу почти поровну."""
        table.autofit = False
        layout = OxmlElement("w:tblLayout")
        layout.set(qn("w:type"), "fixed")
        table._tbl.tblPr.append(layout)
        for grid_col, w in zip(table._tbl.tblGrid.findall(qn("w:gridCol")), widths):
            grid_col.set(qn("w:w"), str(w.twips))

    def _create_main_table(self, doc: Document) -> "Table":
        """Создать основную таблицу с настройками."""
        table = doc.add_table(rows=0, cols=len(self.COL_WIDTHS))
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        self._fix_widths(table, self.COL_WIDTHS)

        # Настройка границ
        tbl = table._tbl
        tblPr = tbl.tblPr
        tblBorders = OxmlElement("w:tblBorders")

        for b in ("top", "left", "bottom", "right", "insideV"):
            x = OxmlElement(f"w:{b}")
            x.set(qn("w:val"), "nil")
            tblBorders.append(x)

        insideH = OxmlElement("w:insideH")
        insideH.set(qn("w:val"), "single")
        insideH.set(qn("w:sz"), "4")
        insideH.set(qn("w:color"), "D0D3D4")
        tblBorders.append(insideH)
        tblPr.append(tblBorders)

        # Отступы в ячейках: сверху/снизу 1 pt, по бокам 0,1 см
        cellMar = OxmlElement("w:tblCellMar")
        for side, w in (("top", 20), ("bottom", 20), ("left", 57), ("right", 57)):
            el = OxmlElement(f"w:{side}")
            el.set(qn("w:w"), str(w))
            el.set(qn("w:type"), "dxa")
            cellMar.append(el)
        tblPr.append(cellMar)

        return table

    def _new_row(self, table):
        """Строка таблицы с ширинами ячеек и выравниванием по центру."""
        row = table.add_row()
        for c, w in zip(row.cells, self.COL_WIDTHS):
            c.width = w
            c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        return row

    def _write(
        self,
        cell,
        text: str,
        size,
        bold: bool = False,
        color: str = None,
        align=None,
        line_sp: float = 1.0,
    ) -> None:
        """Текст в ячейку; переводы строк — разрывы внутри абзаца."""
        p = cell.paragraphs[0]
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = line_sp
        if align is not None:
            p.alignment = align
        lines = (text or "").split("\n")
        for i, line in enumerate(lines):
            if not line and len(lines) == 1:
                break
            r = p.add_run(line)
            r.font.name = self.FONT_MAIN
            r.font.size = size
            r.bold = bold
            if color:
                r.font.color.rgb = RGBColor.from_string(color)
            if i < len(lines) - 1:
                r.add_break()

    @staticmethod
    def _merge_across(row, first: int, last: int):
        """Объединить ячейки строки, оставив один абзац."""
        merged = row.cells[first].merge(row.cells[last])
        for extra in merged.paragraphs[1:]:
            extra._p.getparent().remove(extra._p)
        return merged

    def _add_row(
        self,
        table,
        time: str,
        text: str,
        name: str = "",
        line_sp: float = 1.0,
    ) -> None:
        """Строка пункта: время | название | имя (по левому краю колонки)."""
        row = self._new_row(table)
        row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        row.height = Pt(15)

        self._write(row.cells[0], time, Pt(9), color=self.COLOR_GRAY, line_sp=line_sp)
        self._write(row.cells[1], text, self.SZ_MAIN, line_sp=line_sp)
        self._write(row.cells[2], name, self.SZ_NAME, bold=True, line_sp=line_sp)

    def _add_section_row(self, table, text: str, bg_color: str, line_sp: float = 1.0) -> None:
        """Добавить заголовок секции (цветная полоса во всю ширину)."""
        row = self._new_row(table)
        for c in row.cells:
            self._set_cell_bg_oxml(c, bg_color)
        self._write(row.cells[0], "", Pt(9), line_sp=line_sp)
        merged = self._merge_across(row, 1, len(self.COL_WIDTHS) - 1)
        self._write(merged, text, self.SZ_HEADER, bold=True, line_sp=line_sp)

    def _add_module_row(self, table, content: str, line_sp: float) -> None:
        """Строка с текстом модуля (объявление недели) на всю ширину."""
        r = self._new_row(table)
        cell = self._merge_across(r, 0, len(self.COL_WIDTHS) - 1)
        p = cell.paragraphs[0]
        run = p.add_run(content)
        run.font.name = self.FONT_MAIN
        run.font.size = self.SZ_MAIN
        run.italic = True
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = line_sp
