# core/export/base_builder.py
"""
Базовый класс для билдеров таблиц расписания.

См. spec://export/docx#base-builder
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Pt

from core.export.compact_layout import SPECIAL_EVENT_MESSAGES, SPECIAL_EVENT_TITLES, parse_date
from core.i18n import _

if TYPE_CHECKING:
    from docx.table import Table


class BaseTableBuilder(ABC):
    """
    Абстрактный базовый класс для построения таблиц расписания.

    Каждый конкретный билдер реализует свой формат таблицы:
    - CompactTableBuilder: 2 колонки, компактный формат
    - CompactV2TableBuilder: 3 колонки, современный компактный
    - ModernTableBuilder: 3 колонки с цветными полосами
    - FullModernTableBuilder: полный современный формат

    См. spec://export/docx#builders
    """

    # Цвета по умолчанию (могут переопределяться в подклассах)
    COLOR_HEADER_BG = "0070C0"  # Blue
    COLOR_TREASURES_BG = "006064"  # Teal
    COLOR_MINISTRY_BG = "B87300"  # Dark Amber
    COLOR_LIVING_BG = "B71C1C"  # Deep Red
    COLOR_TEXT_WHITE = "FFFFFF"
    COLOR_TEXT_BLACK = "000000"

    @abstractmethod
    def build(self, doc: Document, week_data: dict) -> None:
        """
        Построить таблицу для недели.

        Args:
            doc: Документ python-docx
            week_data: Данные недели с ключами:
                - 'week': объект Week
                - 'assignments': список назначений
                - 'settings': словарь настроек
        """

    # =================================================================
    #  SPECIAL EVENT — общая заглушка для недель конгресса/вечери
    # =================================================================

    def _try_build_special_event(self, doc: Document, week_data: dict) -> bool:
        """Если неделя помечена как особое событие (конгресс, вечеря) — вставить заглушку и вернуть True.

        Возвращает False, если special_event не задан или если это circuit_overseer (посещение РС),
        для которого строится обычная таблица с замененным CBS.
        """
        week = week_data["week"]
        event = getattr(week, "special_event", None)
        if not event or event == "circuit_overseer":
            return False

        from docx.shared import RGBColor

        # Цвета фона заголовка по типу события
        event_colors = {
            "memorial": "7B1FA2",  # фиолетовый
            "circuit_assembly": "1565C0",  # синий
            "regional_convention": "2E7D32",  # зелёный
        }
        bg_color = event_colors.get(event, "455A64")  # серый по умолчанию

        title_text = _(SPECIAL_EVENT_TITLES.get(event, "Особое событие"))
        message_text = _(SPECIAL_EVENT_MESSAGES.get(event, ""))

        settings = week_data.get("settings", {})
        date_str = self._parse_date(week.start_date)

        # --- Заголовочная строка с датой ---
        table = doc.add_table(rows=2, cols=1)
        table.style = "Table Grid"
        table.autofit = False

        # Строка 1 — дата
        date_cell = table.rows[0].cells[0]
        self._set_cell_bg(date_cell, bg_color)
        p = date_cell.paragraphs[0]
        r = p.add_run(f"{date_str}  —  {title_text}")
        r.bold = True
        r.font.size = Pt(14)
        r.font.color.rgb = RGBColor.from_string("FFFFFF")
        p.alignment = 1  # WD_ALIGN_PARAGRAPH.CENTER

        # Строка 2 — сообщение
        msg_cell = table.rows[1].cells[0]
        p = msg_cell.paragraphs[0]
        r = p.add_run(message_text)
        r.font.size = Pt(12)
        r.italic = True
        p.alignment = 1  # CENTER

        return True

    # =================================================================
    #  ЗАЩИЩЁННЫЕ ХЕЛПЕРЫ (используются в подклассах)
    # =================================================================

    def _set_cell_bg(self, cell, color_hex: str) -> None:
        """Установить цвет фона ячейки."""
        shading_elm = parse_xml(r'<w:shd {} w:fill="{}" />'.format(nsdecls("w"), color_hex))
        cell._tc.get_or_add_tcPr().append(shading_elm)

    def _set_cell_bg_oxml(self, cell, color_hex: str) -> None:
        """Установить цвет фона ячейки через OxmlElement (альтернативный метод)."""
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), color_hex)
        tcPr.append(shd)

    def _fmt_time(self, dt: datetime) -> str:
        """Форматировать время в HH:MM."""
        return dt.strftime("%H:%M")

    def _parse_time(self, time_str: str, default: str = "19:00") -> datetime:
        """Парсить строку времени, вернуть datetime с сегодняшней датой."""
        time_str = time_str.replace(".", ":")
        try:
            return datetime.strptime(time_str, "%H:%M")
        except ValueError:
            return datetime.strptime(default, "%H:%M")

    def _parse_date(self, date_obj) -> str:
        return parse_date(date_obj)

    def _parse_songs(self, songs_str: str) -> list:
        """Парсить строку песен "23,45,67" в список ['23', '45', '67']."""
        return [s.strip() for s in (songs_str or "").split(",") if s.strip()]

    def _get_assignment_by_position(self, assignments: list, position: str) -> dict:
        """Найти назначение по позиции."""
        return next((a for a in assignments if a["position"] == position), None)

    def _get_assignment_by_type(self, assignments: list, atype: str) -> dict:
        """Найти назначение по типу."""
        return next((a for a in assignments if a["type"] == atype), None)

    def _get_section_assignments(self, assignments: list, section: str) -> list:
        """Получить назначения секции, отсортированные по позиции."""
        return sorted(
            [a for a in assignments if a["section"] == section], key=lambda x: str(x["position"])
        )

    def _add_module_content(self, table, week, settings: dict) -> None:
        """Добавить контент модулей в таблицу."""
        from modules.announcement import AnnouncementModule
        from modules.registry import ModuleRegistry

        registry = ModuleRegistry()
        registry.register(AnnouncementModule())

        for module in registry.get_all():
            if settings.get(f"module_{module.id}", "true") == "true":
                content = module.get_export_content(week, None)
                if content:
                    row = table.add_row()
                    row.cells[0].merge(row.cells[-1])  # Объединить все ячейки
                    p = row.cells[0].paragraphs[0]
                    run = p.add_run(content)
                    run.font.size = Pt(10)
                    run.italic = True

    def _create_table_with_borders(
        self, doc: Document, cols: int, border_color: str = "D0D3D4"
    ) -> "Table":
        """
        Создать таблицу с настроенными границами.

        Args:
            doc: Документ
            cols: Количество колонок
            border_color: Цвет горизонтальных границ

        Returns:
            Table с настроенными границами
        """
        table = doc.add_table(rows=0, cols=cols)
        table.style = "Table Grid"

        # Настройка границ через XML
        tbl = table._tbl
        tblPr = tbl.tblPr
        tblBorders = OxmlElement("w:tblBorders")

        for border_name in ("top", "left", "bottom", "right", "insideV"):
            border = OxmlElement(f"w:{border_name}")
            border.set(qn("w:val"), "nil")
            tblBorders.append(border)

        # Горизонтальные границы
        insideH = OxmlElement("w:insideH")
        insideH.set(qn("w:val"), "single")
        insideH.set(qn("w:sz"), "4")
        insideH.set(qn("w:color"), border_color)
        tblBorders.append(insideH)

        tblPr.append(tblBorders)

        return table

    def _set_cell_padding(self, table, padding_twips: int = 28) -> None:
        """Установить отступы в ячейках таблицы."""
        tblPr = table._tbl.tblPr
        cellMar = OxmlElement("w:tblCellMar")

        for side in ("top", "bottom", "left", "right"):
            el = OxmlElement(f"w:{side}")
            el.set(qn("w:w"), str(padding_twips))
            el.set(qn("w:type"), "dxa")
            cellMar.append(el)

        tblPr.append(cellMar)

    def _center_cell_content(self, cell) -> None:
        """Центрировать содержимое ячейки по вертикали и горизонтали."""
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
