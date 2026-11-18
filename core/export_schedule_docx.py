import logging
from docx import Document
from docx.enum.text import WD_BREAK
from docx.shared import Pt


# Новые модули
from core.i18n import _
from core.export.configurator import DocumentConfigurator
from core.export.fetcher import DataFetcher
from core.export.compact_builder import CompactTableBuilder
from core.export.compact_v2_builder import CompactV2TableBuilder
from core.export.modern_builder import ModernTableBuilder
from core.export.full_modern_builder import FullModernTableBuilder

logger = logging.getLogger(__name__)

COLOR_TEXT_BLACK = "000000"


class CustomScheduleExporter:
    """
    Генератор расписания для доски объявлений (Custom Design).
    Создает DOCX с нуля, используя python-docx.

    Рефакторинг (ISSUE-11):
    - Логика построения таблиц вынесена в билдеры
    - Настройка документа в DocumentConfigurator
    - Загрузка данных в DataFetcher

    См. spec://export/docx#architecture
    """

    # Цвета (RGB) — Compact/Full (используются в билдерах)
    COLOR_HEADER_BG = "0070C0"
    COLOR_TREASURES_BG = "006064"
    COLOR_MINISTRY_BG = "B87300"
    COLOR_LIVING_BG = "B71C1C"
    COLOR_TEXT_WHITE = "FFFFFF"

    def __init__(self):
        self._configurator = DocumentConfigurator()
        self._fetcher = DataFetcher()
        self._builders = {
            "compact": CompactTableBuilder(),
            "compact_modern": CompactV2TableBuilder(),
            "modern": ModernTableBuilder(),
            "full_modern": FullModernTableBuilder(),
        }

    def export(self, week_ids, output_path, session, mode="compact"):
        """Экспорт выбранных недель в один DOCX файл."""
        try:
            doc = Document()

            # Настройка документа через конфигуратор
            self._configurator.configure(doc, mode)

            # Загрузка данных через фетчер
            weeks_data = self._fetcher.fetch_weeks(session, week_ids)
            settings = weeks_data[0]["settings"] if weeks_data else {}

            # Группируем недели (Compact = 2 недели, Full = 1 неделя)
            chunk_size = 1 if mode in ("full", "full_modern") else 2
            chunks = [weeks_data[i : i + chunk_size] for i in range(0, len(weeks_data), chunk_size)]

            for page_idx, chunk in enumerate(chunks):
                if page_idx > 0:
                    # Minimal page break (no ghost blank page)
                    bp = doc.add_paragraph()
                    bp.paragraph_format.space_before = Pt(0)
                    bp.paragraph_format.space_after = Pt(0)
                    bp.paragraph_format.line_spacing = Pt(1)
                    run = bp.add_run()
                    run.font.size = Pt(1)
                    run.add_break(WD_BREAK.PAGE)

                # Общая шапка на странице (кроме modern форматов)
                if mode not in ("full_modern", "compact_modern"):
                    self._add_page_header(doc, settings, mode)

                # Таблица(ы) недель через билдеры
                builder = self._get_builder(mode)
                if hasattr(builder, "fit_columns"):
                    builder.fit_columns(chunk)
                for i, week_data in enumerate(chunk):
                    builder.build(doc, week_data)

                    # Отступ между таблицами
                    if (mode in ("compact", "compact_modern")) and i < len(chunk) - 1:
                        spacer = doc.add_paragraph()
                        spacer.paragraph_format.space_before = Pt(0)
                        spacer.paragraph_format.space_after = Pt(0)
                        spacer.paragraph_format.line_spacing = Pt(1)
                        spacer.add_run("").font.size = Pt(1)

            doc.save(output_path)
            return {"success": True, "path": output_path, "count": len(weeks_data)}

        except Exception as e:
            logger.error(f"Export error: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def _get_builder(self, mode: str):
        """Получить билдер для режима."""
        builder = self._builders.get(mode)
        if builder is None:
            # Fallback на компактный формат
            logger.warning(f"Unknown mode '{mode}', using 'compact'")
            return self._builders["compact"]
        return builder

    def _add_page_header(self, doc, settings, mode="compact"):
        """Добавляет общую шапку страницы (Расписание... | Собрание)."""
        from docx.shared import Inches, RGBColor
        from docx.enum.text import WD_TAB_ALIGNMENT, WD_TAB_LEADER

        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(4)

        # Color based on mode
        color_hex = "1A237E" if mode in ("compact_modern", "full_modern") else "4A148C"

        # Левая часть
        run = p.add_run(_("Расписание встречи в будние дни"))
        run.bold = True
        run.font.size = Pt(14)
        run.font.color.rgb = RGBColor.from_string(color_hex)

        # Правая часть (Название собрания)
        cong_name = settings.get("cong_name", "").strip().upper()
        if cong_name:
            p.paragraph_format.tab_stops.add_tab_stop(
                Inches(7.0), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.SPACES
            )
            run = p.add_run(f"\t{cong_name}")
            run.bold = True
            run.font.size = Pt(14)
            run.font.color.rgb = RGBColor.from_string(color_hex)

    # =================================================================
    #  LEGACY METHODS (для обратной совместимости)
    #  Используются напрямую в тестах и старом коде
    # =================================================================

    def _fetch_data(self, session, week_ids):
        """Legacy метод загрузки данных. Делегирует в DataFetcher."""
        return self._fetcher.fetch_weeks(session, week_ids)

    def _create_week_table(self, doc, week_data):
        """Legacy метод создания таблицы. Делегирует в CompactTableBuilder."""
        builder = self._builders["compact"]
        builder.build(doc, week_data)

    def _create_week_table_compact_v2(self, doc, week_data):
        """Legacy метод. Делегирует в CompactV2TableBuilder."""
        builder = self._builders["compact_modern"]
        builder.build(doc, week_data)

    def _create_week_table_modern(self, doc, week_data):
        """Legacy метод. Делегирует в ModernTableBuilder."""
        builder = self._builders["modern"]
        builder.build(doc, week_data)

    def _create_week_table_full_modern(self, doc, week_data):
        """Legacy метод. Делегирует в FullModernTableBuilder."""
        builder = self._builders["full_modern"]
        builder.build(doc, week_data)
