# core/export/compact_builder.py
"""
Билдер для компактного формата расписания (2 колонки).

Формат: 2 колонки, 2 недели на страницу.
Секции с цветными заголовками.

См. spec://export/docx#compact-builder
"""

from datetime import timedelta

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

from core.export.base_builder import BaseTableBuilder
from core.i18n import _, language
from core.week_layout import counsel_minutes


class CompactTableBuilder(BaseTableBuilder):
    """
    Компактный формат расписания (2 колонки).

    Особенности:
    - 2 колонки: [Время] Тема | Участник
    - Цветные заголовки секций
    - 2 недели на страницу

    См. spec://export/docx#compact-builder
    """

    def build(self, doc: Document, week_data: dict) -> None:
        """
        Построить таблицу для недели в компактном формате.

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
        table = doc.add_table(rows=0, cols=2)
        table.style = "Table Grid"

        # Расчет времени
        start_time_str = settings.get("meeting_time", "19:00").replace(".", ":")
        t = self._parse_time(start_time_str)

        # Парсим номера песен
        songs = self._parse_songs(week.songs)

        # ═══ 1. ЗАГОЛОВОК НЕДЕЛИ (Blue, объединенная строка) ═══
        row = table.add_row()
        row.cells[0].merge(row.cells[1])
        cell = row.cells[0]

        date_str = self._parse_date(week.start_date)
        reading = week.bible_reading or ""

        self._set_cell_bg(cell, self.COLOR_HEADER_BG)
        p = cell.paragraphs[0]
        r = p.add_run(f"{date_str}       {reading}")
        r.font.color.rgb = self._parse_rgb(self.COLOR_TEXT_WHITE)
        r.bold = True
        r.font.size = Pt(12)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER

        # ═══ 2. ПРЕДСЕДАТЕЛЬ И МОЛИТВА ═══
        chairman = self._get_assignment_by_position(asses, "chairman")
        prayer_open = self._get_assignment_by_position(asses, "prayer_open")

        c_name = chairman["participant"] if chairman else "—"
        po_name = prayer_open["participant"] if prayer_open else "—"

        time_str = self._fmt_time(t)
        row = table.add_row()
        row.cells[0].text = f"[{time_str}] " + _("Председатель: {name}", name=c_name)
        row.cells[1].text = _("Молитва: {name}", name=po_name)
        row.cells[1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT

        t += timedelta(minutes=1)

        # ═══ ПЕСНЯ 1 + Молитва ═══
        song1 = songs[0] if len(songs) > 0 else ""
        time_str = self._fmt_time(t)
        row = table.add_row()
        row.cells[0].merge(row.cells[1])
        row.cells[0].text = f"[{time_str}] 🎵 " + _("Песня {n} и молитва", n=song1)
        row.cells[0].paragraphs[0].runs[0].italic = True
        if language() == "en":
            opening_time = t + timedelta(minutes=4)
            row = table.add_row()
            row.cells[0].text = f"[{self._fmt_time(opening_time)}] " + _(
                "Вступительные слова (1 мин.)"
            )
        t += timedelta(minutes=5)  # песня и молитва + вступительные слова (1 мин)

        # ═══ 3. СОКРОВИЩА ИЗ СЛОВА БОГА (Teal) ═══
        self._add_section_header(
            table, "💎 " + _("СОКРОВИЩА ИЗ СЛОВА БОГА"), self.COLOR_TREASURES_BG
        )

        treasures = self._get_section_assignments(asses, "treasures")

        for item in treasures:
            time_str = self._fmt_time(t)
            row = table.add_row()
            row.cells[0].text = f"[{time_str}] {item['text']}"
            row.cells[1].text = item["participant"] or ""
            row.cells[1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
            t += timedelta(minutes=item["duration"] + counsel_minutes(item))

        # ═══ 4. ОТТАЧИВАЕМ НАВЫКИ СЛУЖЕНИЯ (Orange) ═══
        self._add_section_header(
            table, "🌾 " + _("ОТТАЧИВАЕМ НАВЫКИ СЛУЖЕНИЯ"), self.COLOR_MINISTRY_BG
        )

        ministry = self._get_section_assignments(asses, "ministry")

        for item in ministry:
            time_str = self._fmt_time(t)
            part = item["participant"] or ""
            if item["assistant"]:
                part += f" / {item['assistant']}"

            row = table.add_row()
            row.cells[0].text = f"[{time_str}] {item['text']}"
            row.cells[1].text = part
            row.cells[1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
            t += timedelta(minutes=item["duration"] + counsel_minutes(item))

        # ═══ ПЕСНЯ 2 (середина) ═══
        song2 = songs[1] if len(songs) > 1 else ""
        time_str = self._fmt_time(t)
        row = table.add_row()
        row.cells[0].merge(row.cells[1])
        row.cells[0].text = f"[{time_str}] 🎵 " + _("Песня {n}", n=song2)
        row.cells[0].paragraphs[0].runs[0].italic = True
        t += timedelta(minutes=5)

        # ═══ 5. ХРИСТИАНСКАЯ ЖИЗНЬ (Red) ═══
        self._add_section_header(table, "🐑 " + _("ХРИСТИАНСКАЯ ЖИЗНЬ"), self.COLOR_LIVING_BG)

        # Включаем living и cbs, но исключаем cbs_reader (он объединяется с cbs)
        living = sorted(
            [a for a in asses if a["section"] in ("living", "cbs") and a["type"] != "cbs_reader"],
            key=lambda x: str(x["position"]),
        )
        # Находим чтеца CBS отдельно
        cbs_reader = self._get_assignment_by_type(asses, "cbs_reader")

        is_co = getattr(week, "special_event", None) == "circuit_overseer"

        for item in living:
            time_str = self._fmt_time(t)
            is_cbs = item["type"] == "cbs"

            if is_co and is_cbs:
                row = table.add_row()
                row.cells[0].text = f"[{time_str}] " + _("Служебная речь РС (30 мин.)")
                row.cells[1].text = _("Районный старейшина")
                row.cells[1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
                t += timedelta(minutes=30)
                continue

            part = item["participant"] or ""
            if is_cbs:
                # Ведущий и чтец на отдельных строках
                reader_name = cbs_reader["participant"] if cbs_reader else ""
                if part and reader_name:
                    part = _(
                        "Ведущий: {conductor}\nЧтец: {reader}", conductor=part, reader=reader_name
                    )
                elif reader_name:
                    part = _("Чтец: {name}", name=reader_name)

            row = table.add_row()
            row.cells[0].text = f"[{time_str}] {item['text']}"
            row.cells[1].text = part
            row.cells[1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
            t += timedelta(minutes=item["duration"] + counsel_minutes(item))

        # ═══ 6. ЗАКЛЮЧЕНИЕ ═══
        time_str = self._fmt_time(t)
        row = table.add_row()
        row.cells[0].text = f"[{time_str}] " + _("Заключительные слова (3 мин.)")
        row.cells[1].text = ""
        t += timedelta(minutes=3)

        # ═══ ПЕСНЯ 3 + Молитва ═══
        song3 = songs[2] if len(songs) > 2 else ""
        prayer_close = self._get_assignment_by_position(asses, "prayer_close")
        pc_name = prayer_close["participant"] if prayer_close else "—"

        time_str = self._fmt_time(t)
        row = table.add_row()
        row.cells[0].text = f"[{time_str}] 🎵 " + _("Песня {n} и молитва", n=song3)
        row.cells[0].paragraphs[0].runs[0].italic = True
        row.cells[1].text = _("Молитва: {name}", name=pc_name)
        row.cells[1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT

        # --- MODULES CONTENT ---
        self._add_module_content(table, week, settings)

    def _add_section_header(self, table, text: str, color_hex: str) -> None:
        """Добавить заголовок секции с цветным фоном."""
        from docx.shared import RGBColor

        row = table.add_row()
        row.cells[0].merge(row.cells[1])
        self._set_cell_bg(row.cells[0], color_hex)
        p = row.cells[0].paragraphs[0]
        run = p.add_run(text)
        run.font.color.rgb = RGBColor.from_string(self.COLOR_TEXT_WHITE)
        run.bold = True
        run.font.size = Pt(10)

    def _parse_rgb(self, hex_color: str):
        """Парсить HEX цвет в RGBColor."""
        from docx.shared import RGBColor

        return RGBColor.from_string(hex_color)
