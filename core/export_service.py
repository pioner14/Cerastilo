"""
Export Service - Business logic for exporting schedule data.

This service handles exporting schedules to various formats (DOCX, S-89).

Reference: spec://services/export
"""

import logging
from typing import List, Optional, Tuple

from core.export.compact_layout import (
    SPECIAL_EVENT_MESSAGES,
    SPECIAL_EVENT_TITLES,
    format_week_title,
)
from core.i18n import _, language
from core.week_layout import assignment_label
from core.database import DatabaseManager
from core.events import EventBus

logger = logging.getLogger(__name__)


class ExportService:
    """
    Service for exporting schedule data.

    Responsibilities:
    - Export to DOCX (standard schedule)
    - Export to S-89 form
    - Export custom DOCX formats
    - Generate HTML preview

    Reference: spec://services/export
    """

    def __init__(self, db: DatabaseManager, event_bus: EventBus, schedule_service=None):
        """
        Initialize the service.

        Args:
            db: Database manager instance
            event_bus: Event bus for notifications
            schedule_service: Optional ScheduleService for preview generation
        """
        self.db = db
        self.event_bus = event_bus
        self._schedule_service = schedule_service

    @property
    def schedule_service(self):
        """Lazy initialization of ScheduleService reference."""
        return self._schedule_service

    @schedule_service.setter
    def schedule_service(self, value):
        self._schedule_service = value

    def export_to_s89(self, week_ids: List[int], output_path: str) -> bool:
        """
        Export weeks to S-89 form.

        Args:
            week_ids: List of week IDs to export
            output_path: Output file path

        Returns:
            True if successful, False otherwise
        """
        from core.export_s89 import S89Exporter

        exporter = S89Exporter()
        with self.db.get_session() as session:
            return exporter.export(session, week_ids, output_path)

    def export_custom_docx(
        self, week_ids: List[int], output_path: str, mode: str = "compact_modern"
    ) -> bool:
        """
        Export weeks to custom DOCX format.

        Args:
            week_ids: List of week IDs to export
            output_path: Output file path
            mode: Export mode (defaults to 'compact_modern')

        Returns:
            True if successful, False otherwise
        """
        from core.export_schedule_docx import CustomScheduleExporter

        exporter = CustomScheduleExporter()
        with self.db.get_session() as session:
            return exporter.export(week_ids, output_path, session, mode=mode)

    def export_to_txt(self, week_ids: List[int], output_path: str) -> bool:
        """
        Export weeks to a plain text file (.txt).

        Args:
            week_ids: List of week IDs to export
            output_path: Output file path

        Returns:
            True if successful, False otherwise
        """
        try:
            lines = []
            lines.append("=" * 70)
            lines.append(_("РАСПИСАНИЕ ВСТРЕЧ: НАША ХРИСТИАНСКАЯ ЖИЗНЬ И СЛУЖЕНИЕ"))
            lines.append("=" * 70)
            lines.append("")

            for week_id in week_ids:
                data = self.schedule_service.get_week_data(week_id)
                if not data:
                    continue

                week = data.get("week", {})
                assignments = data.get("assignments", [])

                # Header
                title = week.get("week_title", "").upper()
                if language() == "en" and week.get("start_date"):
                    title = format_week_title(week["start_date"])
                lines.append(_("📅 НЕДЕЛЯ: {title}", title=title))
                if week.get("bible_reading"):
                    lines.append(_("📖 Чтение Библии: {reading}", reading=week["bible_reading"]))

                special_event = week.get("special_event")
                if special_event and special_event != "circuit_overseer":
                    label = _(
                        SPECIAL_EVENT_TITLES.get(special_event) or "Особое событие: {event}",
                        event=special_event,
                    )
                    message = _(SPECIAL_EVENT_MESSAGES.get(special_event, ""))
                    lines.append(f"⚠️ {label}")
                    if message:
                        lines.append(f"   {message}")
                    lines.append("")
                    lines.append("-" * 70)
                    lines.append("")
                    continue  # Пропускаем пункты программы для этой недели

                if special_event == "circuit_overseer":
                    lines.append("👔 " + _("ОСОБОЕ СОБЫТИЕ: Посещение районного старейшины (РС)"))

                lines.append("")

                # Group assignments by section
                sections = {"fixed": [], "treasures": [], "ministry": [], "living": []}

                # Подписи разделов в текстовом экспорте.
                section_names = {
                    "fixed": "📌 " + _("ВВОДНАЯ ЧАСТЬ"),
                    "treasures": "💎 " + _("СОКРОВИЩА ИЗ СЛОВА БОГА"),
                    "ministry": "🌱 " + _("ОТТАЧИВАЕМ НАВЫКИ В СЛУЖЕНИИ"),
                    "living": "❤️ " + _("ХРИСТИАНСКАЯ ЖИЗНЬ"),
                }

                is_co = special_event == "circuit_overseer"

                for a in assignments:
                    sec = a.get("section", "fixed")
                    # На неделе РС Изучение Библии в собрании опускается
                    if is_co and (
                        sec == "cbs" or a.get("assignment_type") in ("cbs", "cbs_reader")
                    ):
                        continue
                    if sec in sections:
                        sections[sec].append(a)
                    else:
                        sections["fixed"].append(a)

                if is_co:
                    sections["living"].append(
                        {
                            "assignment_text": _("Служебная речь РС (30 мин.)"),
                            "participant_name": _("Районный старейшина"),
                            "assistant_name": None,
                            "section_position": 99,
                            "assignment_number": "",
                        }
                    )

                # Print section-by-section
                for sec_key in ["fixed", "treasures", "ministry", "living"]:
                    sec_assignments = sections[sec_key]
                    if not sec_assignments:
                        continue

                    # Sort assignments by number/position
                    sec_assignments.sort(
                        key=lambda x: (
                            x.get("section_position") or 0,
                            x.get("assignment_number") or 0,
                        )
                    )

                    lines.append(section_names[sec_key])
                    for i, a in enumerate(sec_assignments):
                        char = "├─" if i < len(sec_assignments) - 1 else "└─"
                        text = assignment_label(a.get("assignment_text") or "")
                        p_name = a.get("participant_name") or "—"
                        a_name = a.get("assistant_name")

                        line = f"{char} {text}: {p_name}"
                        if a_name:
                            line += _(" [Ассистент: {name}]", name=a_name)
                        lines.append(line)
                    lines.append("")

                lines.append("-" * 70)
                lines.append("")

            with open(output_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

            return True
        except Exception as e:
            logger.error(f"Error exporting schedule to TXT: {e}")
            return False

    def export_to_pdf(self, week_ids: List[int], output_path: str) -> bool:
        """
        Export weeks to a PDF file by converting custom modern DOCX.

        Args:
            week_ids: List of week IDs to export
            output_path: Output file path

        Returns:
            True if successful, False otherwise
        """
        import tempfile
        import os
        from core.utils import convert_docx_to_pdf
        from core.utils.android_storage import is_android

        if is_android():
            # На Android нет ни python-docx, ни LibreOffice для конвертации.
            return self._export_pdf_qt(week_ids, output_path)

        temp_docx = None
        actual_temp_docx = None
        try:
            fd, temp_docx = tempfile.mkstemp(suffix=".docx")
            os.close(fd)

            result = self.export_custom_docx(week_ids, temp_docx, mode="compact_modern")
            if isinstance(result, dict):
                success = result.get("success", False)
                actual_temp_docx = result.get("path", temp_docx)
            else:
                success = bool(result)
                actual_temp_docx = temp_docx

            if not success:
                logger.error("Failed to generate intermediate DOCX for PDF export.")
                return False

            success_pdf = convert_docx_to_pdf(actual_temp_docx, output_path)
            return success_pdf
        except Exception as e:
            logger.error(f"Error exporting schedule to PDF: {e}")
            return False
        finally:
            if temp_docx and os.path.exists(temp_docx):
                try:
                    os.remove(temp_docx)
                except Exception as e:
                    logger.warning(f"Could not remove temporary DOCX: {e}")
            if (
                actual_temp_docx
                and actual_temp_docx != temp_docx
                and os.path.exists(actual_temp_docx)
            ):
                try:
                    os.remove(actual_temp_docx)
                except Exception as e:
                    logger.warning(f"Could not remove actual temporary DOCX: {e}")

    def print_schedule(self, week_ids: List[int], printer) -> bool:
        """Напечатать расписание на принтер (QPrinter) — то же оформление,
        что у PDF средствами Qt: две недели на лист."""
        from core.export.fetcher import DataFetcher
        from core.export.qt_pdf import paint_compact

        try:
            with self.db.get_session() as session:
                weeks_data = DataFetcher().fetch_weeks(session, week_ids)
                return paint_compact(printer, weeks_data)
        except Exception as e:
            logger.error(f"Error printing schedule: {e}", exc_info=True)
            return False

    def _export_pdf_qt(self, week_ids: List[int], output_path: str) -> bool:
        """
        PDF средствами Qt в том же оформлении, что PDF на ПК (две недели на лист).
        Используется на Android, где нет python-docx и конвертации DOCX → PDF.
        """
        from core.export.fetcher import DataFetcher
        from core.export.qt_pdf import render_compact_pdf

        try:
            with self.db.get_session() as session:
                weeks_data = DataFetcher().fetch_weeks(session, week_ids)
                ok = render_compact_pdf(weeks_data, output_path)
            if not ok:
                logger.error(f"Cannot open PDF for writing: {output_path}")
            return ok
        except Exception as e:
            logger.error(f"Error exporting schedule to PDF via Qt: {e}", exc_info=True)
            return False

    def generate_preview_html(self, week_id: int) -> str:
        """
        Generate HTML preview of a week's schedule.

        Args:
            week_id: Week ID to preview

        Returns:
            HTML string of the preview
        """
        from core.schedule_preview import generate_week_html

        if not self._schedule_service:
            return "<h2>" + _("Ошибка: ScheduleService не инициализирован") + "</h2>"

        data = self._schedule_service.get_week_data(week_id)
        if not data:
            return "<h2>" + _("Ошибка загрузки данных") + "</h2>"

        return generate_week_html(data, self.db.get_setting("meeting_time", "19:00"))

    def get_weeks_date_range(self, week_ids: List[int]) -> Tuple[Optional[str], Optional[str]]:
        """
        Get date range for specified weeks.

        Args:
            week_ids: List of week IDs

        Returns:
            Tuple of (min_date, max_date) or (None, None) if no weeks
        """
        from core.models import Week
        from sqlalchemy import select

        with self.db.get_session() as session:
            weeks = session.execute(select(Week).where(Week.id.in_(week_ids))).scalars().all()

            if not weeks:
                return None, None

            dates = [w.start_date for w in weeks if w.start_date]
            if not dates:
                return None, None

            return min(dates), max(dates)
