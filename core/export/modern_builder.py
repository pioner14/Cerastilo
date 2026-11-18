# core/export/modern_builder.py
"""
Билдер для современного формата с цветными полосами.

Формат: 3 колонки с цветной полосой слева для секций.
Шрифт Arial Narrow для компактности.

См. spec://export/docx#modern-builder
"""

from datetime import datetime, timedelta

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from core.export.base_builder import BaseTableBuilder
from core.export.filename import month_names
from core.i18n import _, language
from core.week_layout import counsel_minutes


class ModernTableBuilder(BaseTableBuilder):
    """
    Современный формат с цветными полосами.

    Особенности:
    - 3 колонки: [Полоса 0.4см] [Тема 12.5см] [Участник 5.7см]
    - Цветная полоса слева для визуального разделения секций
    - Шрифт Arial Narrow для компактности

    См. spec://export/docx#modern-builder
    """

    # Цвета
    COLOR_NAVY = "1A237E"
    COLOR_SLATE = "455A64"
    COLOR_DARK_GREY = "212121"

    # Цвета полос
    STRIP_HEADER = "1A237E"  # Navy
    STRIP_TREASURES = "006064"  # Teal
    STRIP_MINISTRY = "BF360C"  # Deep Burnt Orange
    STRIP_LIVING = "B71C1C"  # Deep Red

    # Шрифт
    FONT_CONDENSED = "Arial Narrow"

    def build(self, doc: Document, week_data: dict) -> None:
        """
        Построить таблицу для недели в современном формате.

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

        # Создаем таблицу
        table = self._create_table(doc)

        # Расчет времени
        start_time_str = settings.get("meeting_time", "19:00").replace(".", ":")
        t = self._parse_time(start_time_str)

        # Парсим песни
        songs = self._parse_songs(week.songs)

        # === ЗАГОЛОВОК НЕДЕЛИ ===
        date_str = self._format_date_russian(week.start_date or "")
        reading = week.bible_reading or ""
        self._add_header_row(table, f"{date_str}  |  {reading}")

        # === ПРЕДСЕДАТЕЛЬ ===
        chairman = self._get_assignment_by_position(asses, "chairman")
        prayer_open = self._get_assignment_by_position(asses, "prayer_open")
        c_name = chairman["participant"] if chairman else "—"
        po_name = prayer_open["participant"] if prayer_open else "—"

        time_str = self._fmt_time(t)
        self._add_row(table, self.STRIP_HEADER, time_str, _("Председатель"), c_name)
        t += timedelta(minutes=1)

        # === ПЕСНЯ 1 ===
        song1 = songs[0] if len(songs) > 0 else ""
        time_str = self._fmt_time(t)
        self._add_row(
            table,
            self.STRIP_HEADER,
            time_str,
            _("Песня {n} и молитва", n=song1),
            _("Молитва: {name}", name=po_name),
            song=True,
        )
        if language() == "en":
            opening_time = t + timedelta(minutes=4)
            self._add_row(
                table,
                self.STRIP_HEADER,
                self._fmt_time(opening_time),
                _("Вступительные слова (1 мин.)"),
            )
        t += timedelta(minutes=5)  # песня и молитва + вступительные слова (1 мин)

        # === СОКРОВИЩА ===
        self._add_section_header(table, _("СОКРОВИЩА ИЗ СЛОВА БОГА"), self.STRIP_TREASURES)

        for item in self._get_section_assignments(asses, "treasures"):
            time_str = self._fmt_time(t)
            self._add_row(table, self.STRIP_TREASURES, time_str, item["text"], item["participant"])
            t += timedelta(minutes=item["duration"] + counsel_minutes(item))

        # === СЛУЖЕНИЕ ===
        self._add_section_header(table, _("ОТТАЧИВАЕМ НАВЫКИ СЛУЖЕНИЯ"), self.STRIP_MINISTRY)

        for item in self._get_section_assignments(asses, "ministry"):
            time_str = self._fmt_time(t)
            part = item["participant"] or ""
            if item["assistant"]:
                part += f" / {item['assistant']}"
            self._add_row(table, self.STRIP_MINISTRY, time_str, item["text"], part)
            t += timedelta(minutes=item["duration"] + counsel_minutes(item))

        # === ПЕСНЯ 2 ===
        song2 = songs[1] if len(songs) > 1 else ""
        time_str = self._fmt_time(t)
        self._add_row(table, self.STRIP_LIVING, time_str, _("Песня {n}", n=song2), song=True)
        t += timedelta(minutes=5)

        # === ХРИСТИАНСКАЯ ЖИЗНЬ ===
        self._add_section_header(table, _("ХРИСТИАНСКАЯ ЖИЗНЬ"), self.STRIP_LIVING)

        living = sorted(
            [a for a in asses if a["section"] in ("living", "cbs") and a["type"] != "cbs_reader"],
            key=lambda x: str(x["position"]),
        )
        cbs_reader = self._get_assignment_by_type(asses, "cbs_reader")

        is_co = getattr(week, "special_event", None) == "circuit_overseer"

        for item in living:
            time_str = self._fmt_time(t)
            is_cbs = item["type"] == "cbs"

            if is_co and is_cbs:
                self._add_row(
                    table,
                    self.STRIP_LIVING,
                    time_str,
                    _("Служебная речь РС (30 мин.)"),
                    _("Районный старейшина"),
                )
                t += timedelta(minutes=30)
                continue

            part = item["participant"] or ""

            if is_cbs:
                reader_name = cbs_reader["participant"] if cbs_reader else ""
                if reader_name:
                    part = _("{conductor}\n(Чтец: {reader})", conductor=part, reader=reader_name)

            self._add_row(table, self.STRIP_LIVING, time_str, item["text"], part)
            t += timedelta(minutes=item["duration"] + counsel_minutes(item))

        # === ЗАКЛЮЧЕНИЕ ===
        time_str = self._fmt_time(t)
        self._add_row(table, self.STRIP_LIVING, time_str, _("Заключительные слова"))
        t += timedelta(minutes=3)

        # === ПЕСНЯ 3 ===
        song3 = songs[2] if len(songs) > 2 else ""
        prayer_close = self._get_assignment_by_position(asses, "prayer_close")
        pc_name = prayer_close["participant"] if prayer_close else "—"

        time_str = self._fmt_time(t)
        self._add_row(
            table,
            self.STRIP_LIVING,
            time_str,
            _("Песня {n} и молитва", n=song3),
            _("Молитва: {name}", name=pc_name),
            song=True,
        )

        # === МОДУЛИ ===
        self._add_modules(table, week, settings)

    def _create_table(self, doc: Document) -> "Table":
        """Создать таблицу с настройками."""
        table = doc.add_table(rows=0, cols=3)

        # Убираем границы
        tbl = table._tbl
        tblPr = tbl.tblPr
        tblBorders = OxmlElement("w:tblBorders")

        for border_name in ("top", "left", "bottom", "right", "insideH", "insideV"):
            border = OxmlElement(f"w:{border_name}")
            border.set(qn("w:val"), "nil")
            tblBorders.append(border)
        tblPr.append(tblBorders)

        # Ширина колонок
        table.autofit = False
        table.columns[0].width = Cm(0.4)
        table.columns[1].width = Cm(12.5)
        table.columns[2].width = Cm(5.7)

        return table

    def _format_date_russian(self, date_obj) -> str:
        """Форматировать дату в русском формате.

        Args:
            date_obj: date объект или строка в формате YYYY-MM-DD
        """
        from datetime import date

        try:
            if isinstance(date_obj, date):
                d = date_obj
            elif date_obj:
                d = datetime.strptime(date_obj, "%Y-%m-%d")
            else:
                return ""
            if language() == "en":
                return f"{month_names()[d.month][:3]} {d.day}"
            months_ru = [
                "",
                "янв",
                "фев",
                "мар",
                "апр",
                "мая",
                "июн",
                "июл",
                "авг",
                "сен",
                "окт",
                "ноя",
                "дек",
            ]
            return f"{d.day} {months_ru[d.month]}."
        except (ValueError, TypeError):
            return str(date_obj) if date_obj else ""

    def _set_cell_bg(self, cell, color_hex: str) -> None:
        """Установить цвет фона ячейки."""
        from docx.oxml import parse_xml
        from docx.oxml.ns import nsdecls

        shading_elm = parse_xml(r'<w:shd {} w:fill="{}" />'.format(nsdecls("w"), color_hex))
        cell._tc.get_or_add_tcPr().append(shading_elm)

    def _set_bottom_border(self, row) -> None:
        """Добавить нижнюю границу к строке."""
        for cell in row.cells:
            tcPr = cell._tc.get_or_add_tcPr()
            tcBorders = tcPr.find(qn("w:tcBorders"))
            if tcBorders is None:
                tcBorders = OxmlElement("w:tcBorders")
                tcPr.append(tcBorders)
            bottom = OxmlElement("w:bottom")
            bottom.set(qn("w:val"), "single")
            bottom.set(qn("w:sz"), "4")
            bottom.set(qn("w:space"), "0")
            bottom.set(qn("w:color"), "E0E0E0")
            tcBorders.append(bottom)

    def _add_header_row(self, table, text: str) -> None:
        """Добавить заголовок недели."""
        row = table.add_row()

        # Полоса
        self._set_cell_bg(row.cells[0], self.STRIP_HEADER)

        # Объединяем тему и участника
        row.cells[1].merge(row.cells[2])
        self._set_cell_bg(row.cells[1], self.STRIP_HEADER)

        p = row.cells[1].paragraphs[0]
        run = p.add_run(text)
        run.font.name = self.FONT_CONDENSED
        run.font.size = Pt(12)
        run.bold = True
        run.font.color.rgb = RGBColor.from_string("FFFFFF")
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    def _add_section_header(self, table, text: str, strip_color: str) -> None:
        """Добавить заголовок секции."""
        row = table.add_row()

        # Полоса
        self._set_cell_bg(row.cells[0], strip_color)

        # Объединяем тему и участника
        row.cells[1].merge(row.cells[2])

        p = row.cells[1].paragraphs[0]
        r = p.add_run(text)
        r.font.name = self.FONT_CONDENSED
        r.font.size = Pt(10)
        r.bold = True
        r.font.color.rgb = RGBColor.from_string(strip_color)
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(2)

        self._set_bottom_border(row)

    def _add_row(
        self,
        table,
        strip_color: str,
        time_text: str,
        subject_text: str,
        participant_text: str = None,
        *,
        song: bool = False,
    ) -> None:
        """Добавить строку в таблицу."""
        row = table.add_row()

        # Полоса
        self._set_cell_bg(row.cells[0], strip_color)

        # Тема
        p = row.cells[1].paragraphs[0]
        p.paragraph_format.line_spacing = 1.05
        p.paragraph_format.space_after = Pt(2)

        self._set_bottom_border(row)

        # Время
        if time_text:
            r_time = p.add_run(f"[{time_text}]  ")
            r_time.font.name = self.FONT_CONDENSED
            r_time.font.size = Pt(10.5)
            r_time.font.color.rgb = RGBColor.from_string(self.COLOR_SLATE)

        # Текст темы
        r_subj = p.add_run(subject_text)
        r_subj.font.name = self.FONT_CONDENSED
        r_subj.font.size = Pt(10.5)
        r_subj.font.color.rgb = RGBColor.from_string(self.COLOR_DARK_GREY)

        if song:
            r_subj.italic = True

        # Участник
        if participant_text:
            p2 = row.cells[2].paragraphs[0]
            p2.paragraph_format.line_spacing = 1.05
            p2.alignment = WD_ALIGN_PARAGRAPH.LEFT

            r_part = p2.add_run(participant_text)
            r_part.font.name = self.FONT_CONDENSED
            r_part.font.size = Pt(11)
            r_part.bold = True
            r_part.font.color.rgb = RGBColor.from_string("000000")

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
                    row.cells[1].merge(row.cells[2])
                    p = row.cells[1].paragraphs[0]
                    run = p.add_run(content)
                    run.font.name = self.FONT_CONDENSED
                    run.font.size = Pt(10)
                    run.italic = True
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
