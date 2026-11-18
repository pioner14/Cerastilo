"""
Assignment repository providing data access for Assignment entities.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import and_, func, or_, select, update

from core.chairman_talk import is_chairman_talk
from core.database import DatabaseManager
from core.models import Assignment, AssignmentStatus, Participant, Week, utc_now
from core.utils import date_to_datetime

from .base import BaseRepository

logger = logging.getLogger(__name__)


class AssignmentRepository(BaseRepository[Assignment]):
    def __init__(self, db_manager: DatabaseManager = None, session=None):
        """
        Initialize AssignmentRepository.

        Args:
            db_manager: Database manager (optional if session is provided)
            session: External SQLAlchemy session for transaction participation
        """
        super().__init__(db_manager, Assignment, session)

    def get_by_week(self, week_id: int) -> List[Assignment]:
        """Get all assignments for a specific week."""
        return self.find(week_id=week_id)

    def get_by_participant(self, participant_id: int, status: str = None) -> List[Assignment]:
        """Get assignments where participant is either participant or assistant."""
        with self.get_session() as session:
            query = select(Assignment).where(
                or_(
                    Assignment.participant_id == participant_id,
                    Assignment.assistant_id == participant_id,
                )
            )
            if status:
                query = query.where(Assignment.status == status)
            return session.execute(query).scalars().all()

    def get_unassigned(self, week_id: int = None) -> List[Assignment]:
        """Get assignments with no participant assigned."""
        filters: Dict[str, Any] = {"participant_id": None}
        if week_id:
            filters["week_id"] = week_id
        return self.find(**filters)

    @staticmethod
    def _set_person(assignment: Assignment, participant_id: Optional[int], role: str) -> None:
        """Поставить участника или напарника и пересчитать статус пункта.

        Пункт «назначен», пока на нём есть хоть кто-то: снятый главный при
        оставшемся напарнике не делает пункт пустым — иначе напарник выпадал
        из истории (интервалы, статистика) и из списка уведомлений.
        Отключённый пункт напарник не включает (как и раньше).
        """
        if role == "participant":
            assignment.participant_id = participant_id
        else:
            assignment.assistant_id = participant_id
            if assignment.status == AssignmentStatus.DISABLED.value:
                return
        assignment.status = (
            AssignmentStatus.ASSIGNED.value
            if assignment.participant_id or assignment.assistant_id
            else AssignmentStatus.EMPTY.value
        )

    def set_slip_given(self, assignment_ids, given: bool) -> bool:
        """Отметить (или снять) «🧾 листок выдан» у пунктов. Время правки
        обновляется, чтобы отметка дошла при синхронизации ПК ↔ планшет."""
        ids = list(assignment_ids)
        if not ids:
            return False
        now = utc_now()
        with self.get_session() as session:
            session.execute(
                update(Assignment)
                .where(Assignment.id.in_(ids))
                .values(slip_given_at=now if given else None, updated_at=now)
            )
            self._persist(session)
        return True

    def restore_people(self, entries) -> bool:
        """Вернуть людей пунктов к записанному состоянию (отмена на доске месяца).

        entries — [{"id", "participant_id", "assistant_id"}]; всё одной транзакцией.
        """
        with self.get_session() as session:
            try:
                for entry in entries:
                    assignment = session.get(Assignment, entry["id"])
                    if not assignment:
                        continue
                    self._set_person(assignment, entry.get("participant_id"), "participant")
                    self._set_person(assignment, entry.get("assistant_id"), "assistant")
                self._persist(session)
                return True
            except Exception:
                logger.exception("Failed to restore assignments %s", [e.get("id") for e in entries])
                self._rollback(session)
                return False

    def swap_people(self, first_id: int, first_role: str, second_id: int, second_role: str) -> bool:
        """Поменять местами людей двух пунктов (роль — participant/assistant)
        одной транзакцией: при сбое не останется полуобмена."""
        with self.get_session() as session:
            try:
                first = session.get(Assignment, first_id)
                second = session.get(Assignment, second_id)
                if not first or not second:
                    return False

                def person(a, role):
                    return a.participant_id if role == "participant" else a.assistant_id

                a, b = person(first, first_role), person(second, second_role)
                if not a or not b:
                    return False
                self._set_person(first, b, first_role)
                self._set_person(second, a, second_role)
                self._persist(session)
                return True
            except Exception:
                logger.exception(
                    "Failed to swap people of assignments %s and %s", first_id, second_id
                )
                self._rollback(session)
                return False

    def assign_participant(
        self, assignment_id: int, participant_id: Optional[int], role: str = "participant"
    ) -> bool:
        """Assign a participant to an assignment (as participant or assistant)."""
        with self.get_session() as session:
            try:
                assignment = session.get(Assignment, assignment_id)
                if not assignment:
                    return False
                self._set_person(assignment, participant_id, role)
                self._persist(session)
                return True
            except Exception:
                logger.exception(
                    "Failed to assign participant %s to assignment %s",
                    participant_id,
                    assignment_id,
                )
                self._rollback(session)
                if self._external_session is not None:
                    raise
                return False

    def clear_week_assignments(self, week_id: int) -> bool:
        """Clear all participant assignments for a week."""
        with self.get_session() as session:
            session.execute(
                update(Assignment)
                .where(Assignment.week_id == week_id)
                .values(
                    participant_id=None,
                    assistant_id=None,
                    slip_given_at=None,
                    status=AssignmentStatus.EMPTY.value,
                    updated_at=utc_now(),
                )
            )
            self._persist(session)
            return True

    def get_conflicts(self, week_id: int) -> List[int]:
        """Get participant IDs that appear more than once in a week (conflicts)."""
        with self.get_session() as session:
            assignments = (
                session.execute(select(Assignment).where(Assignment.week_id == week_id))
                .scalars()
                .all()
            )
            ids = []
            for a in assignments:
                if is_chairman_talk(a):
                    continue  # председатель на своей речи — не двойное назначение
                if a.participant_id:
                    ids.append(a.participant_id)
                if a.assistant_id:
                    ids.append(a.assistant_id)
            from collections import Counter

            counts = Counter(ids)
            return [pid for pid, cnt in counts.items() if cnt > 1]

    def get_assignments_with_names(self, week_id: int) -> List[Dict[str, Any]]:
        """Get assignments with participant and assistant names."""
        with self.get_session() as session:
            # Create aliases for self-join
            participant_alias = Participant.__table__.alias("participant")
            assistant_alias = Participant.__table__.alias("assistant")

            query = (
                select(
                    Assignment,
                    participant_alias.c.name.label("participant_name"),
                    assistant_alias.c.name.label("assistant_name"),
                )
                .outerjoin(participant_alias, Assignment.participant_id == participant_alias.c.id)
                .outerjoin(assistant_alias, Assignment.assistant_id == assistant_alias.c.id)
                .where(Assignment.week_id == week_id)
            )
            results = session.execute(query).all()
            assignments = []
            for a, p_name, a_name in results:
                assignments.append(
                    {
                        "id": a.id,
                        "week_id": a.week_id,
                        "assignment_text": a.assignment_text,
                        "assignment_type": a.assignment_type,
                        "assignment_number": a.assignment_number,
                        "duration": a.duration,
                        "sort_order": a.sort_order,
                        "participant_id": a.participant_id,
                        "assistant_id": a.assistant_id,
                        "status": a.status,
                        "participant_name": p_name,
                        "assistant_name": a_name,
                    }
                )
            return assignments

    def has_assignments(self, week_id: int) -> bool:
        """Check if a week has any assignments with participants."""
        with self.get_session() as session:
            count = session.execute(
                select(func.count(Assignment.id)).where(
                    and_(Assignment.week_id == week_id, Assignment.participant_id != None)
                )
            ).scalar()
            return count > 0

    def get_participant_history(self, participant_id: int) -> List[Dict[str, Any]]:
        """Get assignment history for a participant (as participant or assistant)."""
        with self.get_session() as session:
            query = (
                select(Assignment, Week.start_date, Week.week_title)
                .join(Week, Assignment.week_id == Week.id)
                .where(
                    or_(
                        Assignment.participant_id == participant_id,
                        Assignment.assistant_id == participant_id,
                    )
                )
                .order_by(Week.start_date.desc())
            )
            results = session.execute(query).all()
            history = []
            for assignment, start_date, week_title in results:
                role = "главный" if assignment.participant_id == participant_id else "помощник"
                history.append(
                    {
                        "date": start_date,
                        "week_title": week_title,
                        "assignment_text": assignment.assignment_text,
                        "assignment_type": assignment.assignment_type,
                        "role": role,
                    }
                )
            return history

    def clear_week_assignments_preserving_disabled(self, week_id: int) -> Tuple[bool, Set[int]]:
        """
        Clear assignments for a week, preserving disabled ones.

        Returns:
            Tuple of (success, affected_participant_ids)
        """
        with self.get_session() as session:
            # 1. Find participants that will be cleared (non-disabled assignments only)
            to_clear = session.execute(
                select(Assignment.participant_id, Assignment.assistant_id).where(
                    and_(
                        Assignment.week_id == week_id,
                        Assignment.status != AssignmentStatus.DISABLED.value,
                    )
                )
            ).all()

            affected_ids: Set[int] = set()
            for pid, aid in to_clear:
                if pid:
                    affected_ids.add(pid)
                if aid:
                    affected_ids.add(aid)

            # 2. Clear assignments (except disabled)
            session.execute(
                update(Assignment)
                .where(
                    and_(
                        Assignment.week_id == week_id,
                        Assignment.status != AssignmentStatus.DISABLED.value,
                    )
                )
                .values(
                    participant_id=None,
                    assistant_id=None,
                    slip_given_at=None,
                    status=AssignmentStatus.EMPTY.value,
                    updated_at=utc_now(),
                )
            )

            # 3. Recalculate last_assignment_date for affected participants
            for pid in affected_ids:
                real_max_date = session.execute(
                    select(func.max(Week.start_date))
                    .join(Assignment, Assignment.week_id == Week.id)
                    .where(or_(Assignment.participant_id == pid, Assignment.assistant_id == pid))
                ).scalar()

                # Convert date to datetime for Participant.last_assignment_date
                real_max_date_dt = date_to_datetime(real_max_date)
                session.execute(
                    update(Participant)
                    .where(Participant.id == pid)
                    .values(last_assignment_date=real_max_date_dt)
                )

            try:
                self._persist(session)
                return True, affected_ids
            except Exception:
                logger.exception("Failed to clear assignments for week %s", week_id)
                self._rollback(session)
                if self._external_session is not None:
                    raise
                return False, set()

    @staticmethod
    def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
        """Parse date string. Priority: ISO 8601 (YYYY-MM-DD), fallback: DD.MM.YYYY."""
        if not date_str:
            return None
        for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        return None
