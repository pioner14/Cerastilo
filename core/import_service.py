"""
Import Service - Business logic for importing schedule data.

This service handles importing workbook data (EPUB) and preparing future years.

Reference: spec://services/import
"""

import logging
from typing import Dict, Any
from core.database import DatabaseManager
from core.events import EventBus, Event

logger = logging.getLogger(__name__)


class ImportService:
    """
    Service for importing schedule data.

    Responsibilities:
    - Import workbook (EPUB) files
    - Prepare future year schedules

    Reference: spec://services/import
    """

    def __init__(self, db: DatabaseManager, event_bus: EventBus):
        """
        Initialize the service.

        Args:
            db: Database manager instance
            event_bus: Event bus for notifications
        """
        self.db = db
        self.event_bus = event_bus

    def import_workbook(self, file_path: str) -> Dict[str, Any]:
        """
        Import workbook from EPUB file.

        Args:
            file_path: Path to the EPUB file

        Returns:
            Dict with 'success' and optional 'error' or week count
        """
        from core.epub_parser import WorkbookParser
        from core.workbook_import import save_weeks_to_db

        parser = WorkbookParser(file_path)
        weeks = parser.parse()

        if not weeks:
            return {"success": False, "error": "EPUB не содержит данных"}

        with self.db.get_session() as session:
            result = save_weeks_to_db(session, weeks, file_path)
            self.event_bus.emit(Event.SCHEDULE_IMPORTED)
            return {"success": True, **result}

    @staticmethod
    def _year_mondays(year: int):
        """Понедельники года: неделя относится к году своего понедельника.

        Так же лежат недели из тетрадей: «28 декабря — 3 января» — в декабре
        прошлого года, а не в январе следующего.
        """
        from datetime import date, timedelta

        monday = date(year, 1, 1)
        monday += timedelta(days=(7 - monday.weekday()) % 7)
        while monday.year == year:
            yield monday
            monday += timedelta(weeks=1)

    def _existing_start_dates(self, session) -> set:
        from sqlalchemy import select
        from core.models import Week

        return {d for d in session.execute(select(Week.start_date)).scalars() if d is not None}

    def plan_future_year(self, today=None) -> Dict[str, int]:
        """Какой год предложить кнопке «Будущий год» и сколько недель создать.

        Берётся первый год после текущего, где есть не все недели (например,
        из тетради импортированы только январь–февраль), иначе — год после
        последнего. Пропуски текущего и прошлых лет не трогаем: там недели
        могли удалить нарочно.

        Returns:
            {'year': год, 'missing': сколько пустых недель будет создано}
        """
        from datetime import date

        today = today or date.today()
        with self.db.get_session() as session:
            existing = self._existing_start_dates(session)
        last_year = max([d.year for d in existing] + [today.year])
        for year in range(today.year + 1, last_year + 2):
            missing = sum(1 for m in self._year_mondays(year) if m not in existing)
            if missing:
                return {"year": year, "missing": missing}
        # Сюда не попадаем: год после последнего всегда пуст
        return {"year": last_year + 1, "missing": 0}

    def prepare_future_year(self, year: int) -> Dict[str, Any]:
        """
        Создать пустые недели года — только те, которых ещё нет.

        Неделя с тем же понедельником, уже лежащая в базе (в том числе
        «28 декабря — 3 января» прошлого года), не дублируется. Позднее
        импорт тетради заполнит эти пустые недели (workbook_import ищет
        пустую неделю по дате начала).

        Args:
            year: Year to prepare (e.g., 2027)

        Returns:
            {'success': True, 'year': год, 'created': сколько недель создано}
        """
        from datetime import timedelta

        from core.models import Week

        # Родительный падеж для заголовка: «3–9 марта»
        MONTHS_GEN = [
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

        with self.db.get_session() as session:
            existing = self._existing_start_dates(session)
            weeks_created = 0
            for monday in self._year_mondays(year):
                if monday in existing:
                    continue
                week_end = monday + timedelta(days=6)
                if monday.month == week_end.month:
                    week_title = f"{monday.day}–{week_end.day} {MONTHS_GEN[monday.month - 1]}"
                else:
                    week_title = (
                        f"{monday.day} {MONTHS_GEN[monday.month - 1]} – "
                        f"{week_end.day} {MONTHS_GEN[week_end.month - 1]}"
                    )
                session.add(
                    Week(
                        week_title=week_title,
                        start_date=monday,
                        month=monday.month,
                        year=year,
                        workbook_source="manual",
                    )
                )
                weeks_created += 1
            session.commit()

        if weeks_created:
            self.event_bus.emit(Event.SCHEDULE_IMPORTED)
        logger.info(f"Created {weeks_created} empty weeks for year {year}")
        return {"success": True, "year": year, "created": weeks_created}
