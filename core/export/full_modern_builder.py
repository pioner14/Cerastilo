# core/export/full_modern_builder.py
"""
Билдер для полного современного формата (Full Modern / Swiss Style).

Формат: Полная страница, минималистичный дизайн, высокая контрастность.
Шрифт Calibri, большие отступы, секции с серым фоном.

См. spec://export/docx#full-modern-builder
"""

from datetime import datetime, timedelta

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_ROW_HEIGHT_RULE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from core.export.base_builder import BaseTableBuilder
from core.export.filename import month_names
from core.i18n import _, language
from core.week_layout import counsel_minutes


class FullModernTableBuilder(BaseTableBuilder):
    """
    Полный современный формат (Swiss Style).

    Особенности:
    - Полная страница на неделю
    - Шапка с тёмным фоном и белым текстом
    - Секции с светло-серым фоном
    - Большие шрифты и отступы
    - Футер с годом и названием

    См. spec://export/docx#full-modern-builder
    """

    # Цвета
    COLOR_HEADER_BG = "2E4053"  # Dark Slate Blue
    COLOR_SECTION_BG = "F2F2F2"  # Light Gray
    COLOR_TEXT_WHITE = "FFFFFF"
    COLOR_TEXT_GRAY = "555555"
    COLOR_BORDER = "E0E0E0"

    # Шрифты
    FONT_MAIN = "Calibri"
    SZ_DATE = Pt(22)
    SZ_HEADER_TEXT = Pt(10)
    SZ_TIME = Pt(11.5)
    SZ_ITEM = Pt(12.5)
    SZ_SECTION = Pt(11.5)
    SZ_PARTICIPANT = Pt(12.5)

    def build(self, doc: Document, week_data: dict) -> None:
        """
        Построить таблицу для недели в полном современном формате.

        Args:
            doc: Документ python-docx
            week_data: Данные недели
        """
        # Если неделя отмечена как конгресс / Вечеря — вставить заглушку
        if self._try_build_special_event(doc, week_data):
            return

        week = week_data["week"]
        asses = week_data["assignments"]
        settings = week_data["settings"]

        # === ЗАГОЛОВОК ===
        self._build_header(doc, week, settings)

        # === ОСНОВНАЯ ТАБЛИЦА ===
        table = self._create_main_table(doc)

        # Расчет времени
        start_time_str = settings.get("meeting_time", "19:00").replace(".", ":")
        t = self._parse_time(start_time_str)

        # Парсим песни
        songs = self._parse_songs(week.songs)

        # === СТРОКИ ===
        chairman = self._get_assignment_by_position(asses, "chairman")
        prayer_open = self._get_assignment_by_position(asses, "prayer_open")
        c_name = chairman["participant"] if chairman else "—"
        po_name = prayer_open["participant"] if prayer_open else "—"
        song1 = songs[0] if len(songs) > 0 else ""

        # Председатель
        self._add_row(table, self._fmt_time(t), _("Председатель"), c_name)
        t += timedelta(minutes=1)

        # Песня 1 и молитва
        self._add_row(table, self._fmt_time(t), _("Песня {n} и молитва", n=song1), po_name)
        if language() == "en":
            opening_time = t + timedelta(minutes=4)
            self._add_row(
                table, self._fmt_time(opening_time), _("Вступительные слова (1 мин.)"), ""
            )
        t += timedelta(minutes=5)  # песня и молитва + вступительные слова (1 мин)

        # Сокровища
        self._add_section_row(table, _("СОКРОВИЩА ИЗ СЛОВА БОГА"))
        for item in self._get_section_assignments(asses, "treasures"):
            self._add_row(table, self._fmt_time(t), item["text"], item["participant"])
            t += timedelta(minutes=item["duration"] + counsel_minutes(item))

        # Служение
        self._add_section_row(table, _("ОТТАЧИВАЕМ НАВЫКИ СЛУЖЕНИЯ"))
        for item in self._get_section_assignments(asses, "ministry"):
            part = item["participant"] or ""
            if item["assistant"]:
                part += f" / {item['assistant']}"
            self._add_row(table, self._fmt_time(t), item["text"], part)
            t += timedelta(minutes=item["duration"] + counsel_minutes(item))

        # Песня 2
        song2 = songs[1] if len(songs) > 1 else ""
        self._add_row(table, self._fmt_time(t), _("Песня {n}", n=song2), "")
        t += timedelta(minutes=5)

        # Христианская жизнь
        self._add_section_row(table, _("ХРИСТИАНСКАЯ ЖИЗНЬ"))
        living = sorted(
            [a for a in asses if a["section"] in ("living", "cbs") and a["type"] != "cbs_reader"],
            key=lambda x: str(x["position"]),
        )
        cbs_reader = self._get_assignment_by_type(asses, "cbs_reader")

        is_co = getattr(week, "special_event", None) == "circuit_overseer"

        for item in living:
            is_cbs = item["type"] == "cbs"
            if is_co and is_cbs:
                self._add_row(
                    table,
                    self._fmt_time(t),
                    _("Служебная речь РС (30 мин.)"),
                    _("Районный старейшина"),
                )
                t += timedelta(minutes=30)
                continue

            part = item["participant"] or ""
            if is_cbs and cbs_reader:
                reader_name = cbs_reader["participant"]
                if reader_name:
                    part = _(
                        "Ведущий: {conductor}\nЧтец: {reader}", conductor=part, reader=reader_name
                    )
            self._add_row(table, self._fmt_time(t), item["text"], part)
            t += timedelta(minutes=item["duration"] + counsel_minutes(item))

        # Заключение
        self._add_row(table, self._fmt_time(t), _("Заключительные слова"), c_name)
        t += timedelta(minutes=3)

        # Песня 3
        song3 = songs[2] if len(songs) > 2 else ""
        prayer_close = self._get_assignment_by_position(asses, "prayer_close")
        pc_name = prayer_close["participant"] if prayer_close else "—"
        self._add_row(
            table, self._fmt_time(t), _("Песня {n} и заключительная молитва", n=song3), pc_name
        )

        # Модули
        self._add_modules(table, week, settings)

        # Футер
        self._add_footer(doc, week)

    def _build_header(self, doc: Document, week, settings: dict) -> None:
        """Создать заголовок недели."""
        header_table = doc.add_table(rows=1, cols=3)
        header_table.autofit = True

        # Фон для всех ячеек
        for cell in header_table.rows[0].cells:
            self._set_cell_shading(cell, self.COLOR_HEADER_BG)

        # Дата
        from datetime import date as date_type

        date_obj = week.start_date
        try:
            if isinstance(date_obj, date_type) and date_obj:
                d = date_obj
            elif date_obj:
                d = datetime.strptime(date_obj, "%Y-%m-%d")
            else:
                d = None
            if d:
                months_ru = [
                    "",
                    "января",
                    "февраля",
                    "марта",
                    "апреля",
                    "мая",
                    "июня",
                    "июля",
                    "августа",
                    "сентября",
                    "октября",
                    "ноября",
                    "декабря",
                ]
                if language() == "en":
                    date_text = f"{month_names()[d.month]} {d.day}, {d.year}"
                else:
                    date_text = f"{d.day} {months_ru[d.month]} {d.year}"
            else:
                date_text = ""
        except (ValueError, TypeError):
            date_text = str(date_obj) if date_obj else ""

        reading = (week.bible_reading or "").upper()
        cong_name = settings.get("cong_name", "").strip()

        # Колонка 0: Дата
        cell0 = header_table.cell(0, 0)
        p = cell0.paragraphs[0]
        r = p.add_run(date_text)
        r.font.name = self.FONT_MAIN
        r.font.size = self.SZ_DATE
        r.bold = True
        r.font.color.rgb = RGBColor.from_string(self.COLOR_TEXT_WHITE)
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(6)

        # Колонка 1: Чтение Библии
        cell1 = header_table.cell(0, 1)
        p = cell1.paragraphs[0]
        r = p.add_run(_("ЧТЕНИЕ БИБЛИИ:\n{reading}", reading=reading))
        r.font.name = self.FONT_MAIN
        r.font.size = self.SZ_HEADER_TEXT
        r.bold = True
        r.font.color.rgb = RGBColor.from_string(self.COLOR_TEXT_WHITE)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(6)

        # Колонка 2: Название собрания
        cell2 = header_table.cell(0, 2)
        p = cell2.paragraphs[0]
        r = p.add_run(cong_name)
        r.font.name = self.FONT_MAIN
        r.font.size = self.SZ_HEADER_TEXT
        r.font.color.rgb = RGBColor.from_string(self.COLOR_TEXT_WHITE)
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(6)

        # Отступ после заголовка
        spacing_p = doc.add_paragraph()
        spacing_p.paragraph_format.space_after = Pt(12)

    def _create_main_table(self, doc: Document) -> "Table":
        """Создать основную таблицу."""
        table = doc.add_table(rows=0, cols=3)
        table.autofit = True

        # Ширина колонок
        table.columns[0].width = Cm(1.5)
        table.columns[1].width = Cm(8.5)
        table.columns[2].width = Cm(8.5)

        # Границы
        self._set_table_borders(table)

        return table

    def _set_cell_shading(self, cell, color_hex: str) -> None:
        """Установить цвет фона ячейки."""
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), color_hex)
        tcPr.append(shd)

    def _set_table_borders(self, table) -> None:
        """Установить границы таблицы."""
        tbl = table._tbl
        tblPr = tbl.tblPr
        tblBorders = OxmlElement("w:tblBorders")

        # Убираем все границы кроме горизонтальных
        for border_name in ("top", "left", "bottom", "right", "insideV"):
            b = OxmlElement(f"w:{border_name}")
            b.set(qn("w:val"), "nil")
            tblBorders.append(b)

        # Горизонтальные границы
        insideH = OxmlElement("w:insideH")
        insideH.set(qn("w:val"), "single")
        insideH.set(qn("w:sz"), "4")
        insideH.set(qn("w:space"), "0")
        insideH.set(qn("w:color"), self.COLOR_BORDER)
        tblBorders.append(insideH)

        # Нижняя граница
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), "4")
        bottom.set(qn("w:color"), self.COLOR_BORDER)
        tblBorders.append(bottom)

        tblPr.append(tblBorders)

    def _add_row(
        self, table, time_val: str, item_text: str, part_text: str, is_section: bool = False
    ) -> None:
        """Добавить строку в таблицу."""
        row = table.add_row()

        # Высота строки
        if not is_section:
            row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
            row.height = Cm(1.1)

        # Фон секции
        if is_section:
            for c in row.cells:
                self._set_cell_shading(c, self.COLOR_SECTION_BG)

        # Вертикальное выравнивание
        for c in row.cells:
            c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

        # Отступы
        sp_before = Pt(12) if is_section else Pt(2)
        sp_after = Pt(3)

        # Колонка 0: Время
        p0 = row.cells[0].paragraphs[0]
        if time_val:
            r0 = p0.add_run(time_val)
            r0.font.name = self.FONT_MAIN
            r0.font.size = self.SZ_TIME
            r0.font.color.rgb = RGBColor.from_string(self.COLOR_TEXT_GRAY)
        p0.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p0.paragraph_format.space_before = sp_before
        p0.paragraph_format.space_after = sp_after
        p0.paragraph_format.line_spacing = 1.0

        # Колонка 1: Тема
        p1 = row.cells[1].paragraphs[0]
        r1 = p1.add_run(item_text)
        r1.font.name = self.FONT_MAIN
        r1.font.size = self.SZ_SECTION if is_section else self.SZ_ITEM
        if is_section:
            r1.bold = True
        p1.paragraph_format.space_before = sp_before
        p1.paragraph_format.space_after = sp_after
        p1.paragraph_format.line_spacing = 1.0

        # Колонка 2: Участник
        p2 = row.cells[2].paragraphs[0]
        if part_text:
            r2 = p2.add_run(part_text)
            r2.font.name = self.FONT_MAIN
            r2.font.size = self.SZ_PARTICIPANT
            r2.bold = True
        p2.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p2.paragraph_format.space_before = sp_before
        p2.paragraph_format.space_after = sp_after
        p2.paragraph_format.line_spacing = 1.0

    def _add_section_row(self, table, text: str) -> None:
        """Добавить заголовок секции."""
        self._add_row(table, "", text, "", is_section=True)

    def _add_modules(self, table, week, settings: dict) -> None:
        """Добавить контент модулей."""
        from modules.announcement import AnnouncementModule
        from modules.registry import ModuleRegistry

        registry = ModuleRegistry()
        registry.register(AnnouncementModule())

        for module in registry.get_all():
            if settings.get(f"module_{module.id}", "true") == "true":
                content = module.get_export_content(week, None)
                if content:
                    row = table.add_row()
                    row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
                    row.height = Cm(1.1)
                    row.cells[0].merge(row.cells[2])
                    p = row.cells[0].paragraphs[0]
                    r = p.add_run(content)
                    r.font.name = self.FONT_MAIN
                    r.font.size = self.SZ_ITEM
                    r.italic = True
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    for c in row.cells:
                        c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

    def _add_footer(self, doc: Document, week) -> None:
        """Добавить футер документа."""
        section = doc.sections[0]
        footer = section.footer
        footer.is_linked_to_previous = False

        if not footer.paragraphs:
            fp = footer.paragraphs[0]
        else:
            fp = footer.paragraphs[0]
            fp.clear()

        # Верхняя граница футера
        pPr = fp._p.get_or_add_pPr()
        pbdr = OxmlElement("w:pBdr")
        top = OxmlElement("w:top")
        top.set(qn("w:val"), "single")
        top.set(qn("w:sz"), "6")
        top.set(qn("w:space"), "1")
        top.set(qn("w:color"), "AAAAAA")
        pbdr.append(top)
        pPr.append(pbdr)

        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER

        # Год
        from datetime import date as date_type

        year_str = str(datetime.now().year)
        if week.start_date:
            try:
                if isinstance(week.start_date, date_type):
                    year_str = str(week.start_date.year)
                else:
                    year_str = str(datetime.strptime(week.start_date, "%Y-%m-%d").year)
            except (ValueError, TypeError):
                pass

        fr = fp.add_run(f"\n{year_str} | " + _("Недельное расписание"))
        fr.font.name = self.FONT_MAIN
        fr.font.size = Pt(9)
        fr.font.color.rgb = RGBColor.from_string("888888")
