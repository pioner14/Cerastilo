"""S-89 Export Module.

Implements: spec://export/s89#layout

Генерирует DOCX с 4 карточками S-89 (версия 11/23) на странице A4 в сетке 2x2.
"""

import logging
import os
from datetime import timedelta
from sqlalchemy import select, and_, or_

from core.assignment_rules import needs_slip
from core.export.filename import format_output_date, month_names
from core.i18n import _, language
from core.models import Assignment, Week, Participant
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_ROW_HEIGHT_RULE, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "scheduler.db")

logger = logging.getLogger(__name__)


class S89Exporter:
    """Экспортер карточек S-89 (11/23) в формате DOCX."""

    def __init__(self, session=None):
        self.session = session

    def export(self, session, week_ids, output_path):
        """Экспорт бланков S-89 в DOCX."""
        logger.info(f"Exporting S-89 for weeks {week_ids} to {output_path}")
        doc = Document()

        # === ПАРАМЕТРЫ СТРАНИЦЫ A4 ===
        section = doc.sections[0]
        section.page_width = Cm(21.0)
        section.page_height = Cm(29.7)
        section.top_margin = Cm(0.8)
        section.bottom_margin = Cm(0.8)
        section.left_margin = Cm(0.8)
        section.right_margin = Cm(0.8)

        data = self._fetch_student_data(session, week_ids)

        if not data:
            return {"success": False, "error": _("Нет назначений учеников для этих недель")}

        for page_idx, start_idx in enumerate(range(0, len(data), 4)):
            if page_idx > 0:
                doc.add_page_break()
            page_items = data[start_idx : start_idx + 4]
            self._add_page_with_slips(doc, page_items)
            self._kill_last_paragraph(doc)

        doc.save(output_path)
        logger.info(f"S-89 export finished: {output_path}")
        return {"success": True, "path": output_path, "count": len(data)}

    def _add_page_with_slips(self, doc, items):
        """Создаёт страницу с до 4 карточками в сетке 2x2."""
        page_table = doc.add_table(rows=2, cols=2)
        page_table.autofit = False

        # Уменьшаем размер ячеек с учётом отступов для разрезания
        # 3 мм отступа с каждой стороны = 6 мм между карточками
        cell_width = Cm(9.4)  # было 9.7
        cell_height = Cm(13.5)  # было 13.8

        for row in page_table.rows:
            row.height = cell_height
            row.height_rule = WD_ROW_HEIGHT_RULE.EXACTLY
            # Аппаратный запрет разрыва строки
            self._prevent_row_split(row)
            for cell in row.cells:
                cell.width = cell_width
                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
                self._set_cell_margins_zero(cell)

        # Добавляем отступы между карточками (3 мм)
        self._set_table_cell_spacing(page_table, spacing_cm=0.3)
        self._set_table_borders(page_table)

        positions = [(0, 0), (0, 1), (1, 0), (1, 1)]
        for idx, item in enumerate(items):
            if idx < 4:
                row, col = positions[idx]
                cell = page_table.rows[row].cells[col]
                self._add_slip_to_cell(cell, item)

    def _fetch_student_data(self, session, week_ids):
        """Получает ученические задания из БД."""
        query = (
            select(Assignment, Week.week_title, Week.start_date)
            .join(Week, Assignment.week_id == Week.id)
            .where(
                and_(
                    Assignment.week_id.in_(week_ids),
                    Assignment.participant_id != None,
                    or_(
                        and_(Assignment.section == "treasures", Assignment.section_position == "3"),
                        Assignment.section == "ministry",
                    ),
                )
            )
            .order_by(Week.id, Assignment.section, Assignment.section_position)
        )

        results = session.execute(query).all()

        data = []
        for a, title, start in results:
            if not needs_slip(a):
                continue
            student = session.get(Participant, a.participant_id)
            assistant = session.get(Participant, a.assistant_id) if a.assistant_id else None

            item = {
                "student_name": student.name if student else "—",
                "assistant_name": assistant.name if assistant else "—",
                "week_title": title,
                "start_date": start,
                "assignment_text": a.assignment_text,
                "assignment_number": str(a.assignment_number) if a.assignment_number else "",
                "classroom": "main",  # По умолчанию главный зал. Если в БД есть поле, замените логику.
            }
            data.append(item)

        return data

    def _slip_date(self, item):
        """Период недели для английского бланка."""
        if language() == "ru":
            return item["week_title"]
        start = item.get("start_date")
        if not start:
            return ""
        end = start + timedelta(days=6)
        if start.year != end.year:
            first = format_output_date(start)
        elif start.month != end.month:
            first = f"{month_names()[start.month]} {start.day}"
        else:
            return f"{month_names()[start.month]} {start.day}-{end.day}, {end.year}"
        return f"{first} - {format_output_date(end)}"

    def _add_slip_to_cell(self, cell, item):
        """Создает карточку S-89 (11/23) внутри ячейки таблицы."""
        # === 1. ЗАГОЛОВОК ===
        p_title = cell.paragraphs[0]
        p_title.clear()  # Очищаем перед добавлением
        p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        self._set_tight_spacing(p_title)

        run_title = p_title.add_run(_("ЗАДАНИЕ «НАША ХРИСТИАНСКАЯ\nЖИЗНЬ И СЛУЖЕНИЕ»"))
        run_title.bold = True
        run_title.font.size = Pt(10)
        run_title.font.name = "Arial"

        # Отступ после заголовка
        p_spacer = cell.add_paragraph()
        self._set_tight_spacing(p_spacer)
        p_spacer.runs.clear()
        p_spacer.add_run("").font.size = Pt(4)  # Маленький пустой отступ

        # === 2. ПОЛЯ ДЛЯ ЗАПОЛНЕНИЯ ===
        inner_table = cell.add_table(rows=4, cols=2)
        inner_table.autofit = False

        col_widths = [Cm(2.6), Cm(6.7)]
        row_height = Cm(0.9)  # Сделали чуть уже, так как внизу много текста

        data_rows = [
            (_("Имя:"), item["student_name"]),
            (_("Напарник:"), item["assistant_name"]),
            (_("Дата:"), self._slip_date(item)),
            (_("Задание №:"), item["assignment_number"]),
        ]

        for i, (label, value) in enumerate(data_rows):
            r = inner_table.rows[i]
            r.height = row_height
            r.height_rule = WD_ROW_HEIGHT_RULE.EXACTLY
            self._prevent_row_split(r)

            for j, c in enumerate(r.cells):
                c.width = col_widths[j]
                c.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.BOTTOM
                self._set_cell_margins_zero(c)

                # Метка (Имя, Дата и т.д.)
                p_label = r.cells[0].paragraphs[0]
                p_label.clear()  # Очищаем перед добавлением
                self._set_tight_spacing(p_label)
                run_label = p_label.add_run(label)
                run_label.bold = True
                run_label.font.size = Pt(10)
                run_label.font.name = "Arial"

                # Значение (Подчеркнутое линией снизу ячейки)
                p_val = r.cells[1].paragraphs[0]
                p_val.clear()  # Очищаем перед добавлением
                self._set_tight_spacing(p_val)
                run_val = p_val.add_run(value)
                run_val.font.name = "Arial"
                run_val.font.size = Pt(10)

                # Линия подчеркивания для значений
                self._set_cell_bottom_border(r.cells[1])

        # === 3. БЛОК ГАЛОЧЕК (ЗАЛЫ) ===
        p_halls = cell.add_paragraph()
        self._set_tight_spacing(p_halls)
        p_halls.paragraph_format.space_before = Pt(10)  # Отступ от полей

        run_halls_title = p_halls.add_run(_("Преподносится:\n"))
        run_halls_title.bold = True
        run_halls_title.font.size = Pt(10)
        run_halls_title.font.name = "Arial"

        # Определяем, где поставить галочку (☑ - 2611, ☐ - 2610)
        box_main = "☑" if item.get("classroom") == "main" else "☐"
        box_aux1 = "☑" if item.get("classroom") == "aux1" else "☐"
        box_aux2 = "☑" if item.get("classroom") == "aux2" else "☐"

        run_halls = p_halls.add_run(
            f" {box_main} {_('В главном зале')}\n"
            f" {box_aux1} {_('В дополнительном классе 1')}\n"
            f" {box_aux2} {_('В дополнительном классе 2')}"
        )
        run_halls.font.size = Pt(10)
        run_halls.font.name = "Arial"

        # === 4. ПРИМЕЧАНИЕ ===
        p_note = cell.add_paragraph()
        self._set_tight_spacing(p_note)
        p_note.paragraph_format.space_before = Pt(10)

        run_note_b = p_note.add_run(_("Примечание для учащегося. "))
        run_note_b.bold = True
        run_note_b.font.size = Pt(8)
        run_note_b.font.name = "Arial"

        run_note_t = p_note.add_run(
            _(
                "Материал для этого задания и номер урока указаны в рабочей тетради "
                "«Жизнь и служение». Воспользуйтесь руководством к своему заданию из "
                "«Указаний для встречи «Наша христианская жизнь и служение» (S-38)."
            )
        )
        run_note_t.font.size = Pt(8)
        run_note_t.font.name = "Arial"

        # === 5. ФУТЕР S-89 ===
        p_footer = cell.add_paragraph()
        self._set_tight_spacing(p_footer)
        p_footer.paragraph_format.space_before = Pt(8)

        run_s89 = p_footer.add_run(_("S-89-U 11/23"))
        run_s89.font.size = Pt(8)
        run_s89.font.name = "Arial"

    def _prevent_row_split(self, row):
        """Аппаратный хак XML для запрета разрыва строки на следующую страницу."""
        tr = row._tr
        trPr = tr.get_or_add_trPr()
        cantSplit = OxmlElement("w:cantSplit")
        cantSplit.set(qn("w:val"), "true")
        trPr.append(cantSplit)

    def _set_tight_spacing(self, p):
        """Убирает 'воздух' вокруг параграфа."""
        pf = p.paragraph_format
        pf.space_before = Pt(0)
        pf.space_after = Pt(0)
        pf.line_spacing = 1.0

    def _set_cell_margins_zero(self, cell):
        """Устанавливает все внутренние отступы ячейки в 0."""
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        tcMar = OxmlElement("w:tcMar")
        for side in ["top", "left", "bottom", "right"]:
            node = OxmlElement(f"w:{side}")
            node.set(qn("w:w"), "0")
            node.set(qn("w:type"), "dxa")
            tcMar.append(node)
        tcPr.append(tcMar)

    def _set_cell_bottom_border(self, cell):
        """Добавляет нижнюю пунктирную границу для ячейки (имитация заполнения)."""
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        tcBorders = OxmlElement("w:tcBorders")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "dashed")  # Сделали пунктиром, как в оригинале
        bottom.set(qn("w:sz"), "4")
        bottom.set(qn("w:color"), "000000")
        tcBorders.append(bottom)
        tcPr.append(tcBorders)

    def _set_table_borders(self, table):
        """Устанавливает линии разреза для всего листа."""
        tbl = table._tbl
        tblPr = tbl.tblPr if tbl.tblPr is not None else OxmlElement("w:tblPr")
        tblBorders = OxmlElement("w:tblBorders")

        for side in ["top", "left", "bottom", "right", "insideH", "insideV"]:
            border = OxmlElement(f"w:{side}")
            border.set(qn("w:val"), "dashed")
            border.set(qn("w:sz"), "4")
            border.set(qn("w:space"), "0")
            border.set(qn("w:color"), "AAAAAA")
            tblBorders.append(border)

        tblPr.append(tblBorders)
        if tbl.tblPr is None:
            tbl.insert(0, tblPr)

    def _set_table_cell_spacing(self, table, spacing_cm=0.3):
        """Добавляет отступы между ячейками таблицы для удобного разрезания.

        Args:
            table: Таблица DOCX
            spacing_cm: Отступ в сантиметрах (по умолчанию 3 мм)
        """
        tbl = table._tbl
        tblPr = tbl.tblPr if tbl.tblPr is not None else OxmlElement("w:tblPr")

        # Преобразуем см в twips (1 см = 567 twips)
        spacing_twips = int(spacing_cm * 567)

        # Добавляем отступы между ячейками
        tblCellSpacing = OxmlElement("w:tblCellSpacing")
        tblCellSpacing.set(qn("w:w"), str(spacing_twips))
        tblCellSpacing.set(qn("w:type"), "dxa")
        tblPr.append(tblCellSpacing)

        if tbl.tblPr is None:
            tbl.insert(0, tblPr)

    def _kill_last_paragraph(self, doc):
        """Схлопывает финальный параграф документа."""
        if doc.paragraphs:
            last_para = doc.paragraphs[-1]
            last_para.text = ""
            last_para.paragraph_format.space_before = Pt(0)
            last_para.paragraph_format.space_after = Pt(0)
            last_para.paragraph_format.line_spacing = Pt(1)
            if not last_para.runs:
                last_para.add_run("")
            for run in last_para.runs:
                run.font.size = Pt(1)
