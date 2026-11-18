"""
Week repository providing data access for Week entities.
"""

from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, asc, desc, select

from core.database import DatabaseManager
from core.models import Assignment, Week
from core.utils import format_date_for_display

from .base import BaseRepository


class WeekRepository(BaseRepository[Week]):
    def __init__(self, db_manager: DatabaseManager = None, session=None):
        """
        Initialize WeekRepository.

        Args:
            db_manager: Database manager (optional if session is provided)
            session: External SQLAlchemy session for transaction participation
        """
        super().__init__(db_manager, Week, session)

    def get_by_year_month(self, year: int, month: Optional[int] = None) -> List[Week]:
        """Get weeks for a given year (and optionally month)."""
        filters = {"year": year}
        if month is not None:
            filters["month"] = int(month)
        return self.find(**filters)

    def get_by_date_range(self, start_date: date, end_date: date) -> List[Week]:
        """Get weeks within a date range.

        Args:
            start_date: Начальная дата (date объект)
            end_date: Конечная дата (date объект)
        """
        with self.get_session() as session:
            query = (
                select(Week)
                .where(and_(Week.start_date >= start_date, Week.start_date <= end_date))
                .order_by(Week.start_date)
            )
            return session.execute(query).scalars().all()

    def get_with_assignments(self, week_id: int) -> Optional[Week]:
        """Get week with eager-loaded assignments."""
        with self.get_session() as session:
            query = (
                select(Week)
                .where(Week.id == week_id)
                .options(
                    # SQLAlchemy will automatically load relationship if accessed
                )
            )
            week = session.execute(query).scalar()
            if week:
                # Trigger lazy load
                _ = week.assignments
            return week

    def get_special_event(self, week_id: int) -> Optional[str]:
        """Get special event type for a week."""
        week = self.get_by_id(week_id)
        return week.special_event if week else None

    def set_special_event(self, week_id: int, event_type: str) -> bool:
        """Set special event for a week."""
        week = self.get_by_id(week_id)
        if week:
            week.special_event = event_type
            with self.get_session() as session:
                session.add(week)
                self._persist(session)
                return True
        return False

    def get_weeks_tree(self) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
        """Organize weeks into a tree by year and month."""
        # Названия месяцев по номерам (1..12)
        month_names = [
            "",
            "Январь",
            "Февраль",
            "Март",
            "Апрель",
            "Май",
            "Июнь",
            "Июль",
            "Август",
            "Сентябрь",
            "Октябрь",
            "Ноябрь",
            "Декабрь",
        ]

        def parse_month_num(m_val, start_date) -> int:
            if start_date:
                return start_date.month
            if not m_val:
                return 1
            m_str = str(m_val).strip().lower()
            if m_str.isdigit():
                val = int(m_str)
                if 1 <= val <= 12:
                    return val
            for idx in range(1, 13):
                name = month_names[idx].lower()
                if name in m_str or m_str in name:
                    return idx
            return 1

        with self.get_session() as session:
            weeks = session.execute(select(Week)).scalars().all()

            # Сортируем недели по (year, month_num, start_date)
            sorted_weeks = sorted(
                weeks,
                key=lambda w: (
                    w.year or (w.start_date.year if w.start_date else 0),
                    parse_month_num(w.month, w.start_date),
                    w.start_date or date.min,
                ),
            )

            tree: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
            for w in sorted_weeks:
                y = str(w.year or (w.start_date.year if w.start_date else "Неизвестно"))
                m_num = parse_month_num(w.month, w.start_date)
                m_display = month_names[m_num]

                if y not in tree:
                    tree[y] = {}
                if m_display not in tree[y]:
                    tree[y][m_display] = []

                tree[y][m_display].append(
                    {
                        "id": w.id,
                        "title": w.week_title,
                        "date": format_date_for_display(w.start_date),
                        "start_date": w.start_date.isoformat() if w.start_date else None,
                        "special": w.special_event,
                    }
                )
            return tree

    def delete_with_assignments(self, week_id: int) -> bool:
        """Delete week and all its assignments (cascade)."""
        with self.get_session() as session:
            week = session.get(Week, week_id)
            if week:
                session.delete(week)
                self._persist(session)
                return True
            return False

    def get_week_data(self, week_id: int) -> Optional[Dict[str, Any]]:
        """
        Get week data with assignments including participant names.

        Returns dict with 'week' and 'assignments' keys, or None if week not found.
        """
        from core.models import Participant

        with self.get_session() as session:
            week = session.get(Week, week_id)
            if not week:
                return None

            # Get assignments with participant names (JOIN)
            assistant_table = Participant.__table__.alias("assistant")
            query = (
                select(
                    Assignment,
                    Participant.name.label("participant_name"),
                    assistant_table.c.name.label("assistant_name"),
                )
                .outerjoin(Participant, Assignment.participant_id == Participant.id)
                .outerjoin(assistant_table, Assignment.assistant_id == assistant_table.c.id)
                .where(Assignment.week_id == week_id)
            )
            results = session.execute(query).all()

            assignments = []
            for a, p_name, a_name in results:
                assignments.append(
                    {
                        "id": a.id,
                        "assignment_text": a.assignment_text,
                        "assignment_type": a.assignment_type,
                        "assignment_number": a.assignment_number,
                        "section": a.section,
                        "section_position": a.section_position,
                        "duration": a.duration,
                        "sort_order": a.sort_order,
                        "discussion_marker": a.discussion_marker,
                        "participant_id": a.participant_id,
                        "assistant_id": a.assistant_id,
                        "status": a.status,
                        "slip_given_at": a.slip_given_at,
                        "participant_name": p_name,
                        "assistant_name": a_name,
                    }
                )

            return {
                "week": {
                    "id": week.id,
                    "week_title": week.week_title,
                    "start_date": format_date_for_display(week.start_date),
                    "bible_reading": week.bible_reading,
                    "special_event": week.special_event,
                },
                "assignments": assignments,
            }
