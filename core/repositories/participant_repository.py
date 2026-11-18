"""
Participant repository providing data access for Participant entities.

Reference: spec://repositories/participant
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, func, select, update

from core.chairman_talk import counted_assignment
from core.database import DatabaseManager
from core.models import (
    Assignment,
    AssignmentStatus,
    Participant,
    Week,
    participant_qualifications,
    utc_now,
)
from core.utils import date_to_datetime

from .base import BaseRepository


class ParticipantRepository(BaseRepository[Participant]):
    """Repository for Participant entity operations."""

    def __init__(self, db_manager: DatabaseManager = None, session=None):
        """
        Initialize repository.

        Args:
            db_manager: Database manager (optional if session is provided)
            session: External SQLAlchemy session for transaction participation
        """
        super().__init__(db_manager, Participant, session)

    def get_by_name(self, name: str) -> Optional[Participant]:
        """Find participant by exact name."""
        with self.get_session() as session:
            query = select(Participant).where(Participant.name == name)
            return session.execute(query).scalar()

    def get_active(self) -> List[Participant]:
        """Get all active participants."""
        return self.find(is_active=True)

    def get_by_family(self, family_group_id: int) -> List[Participant]:
        """Get participants belonging to a family group."""
        return self.find(family_group_id=family_group_id)

    def get_qualifications(self, participant_id: int) -> List[str]:
        """Get qualification names for a participant."""
        with self.get_session() as session:
            query = select(participant_qualifications.c.qualification_name).where(
                participant_qualifications.c.participant_id == participant_id
            )
            return session.execute(query).scalars().all()

    def get_qualifications_batch(self, participant_ids: List[int]) -> Dict[int, List[str]]:
        """Get qualifications for multiple participants in a single query.

        Args:
            participant_ids: List of participant IDs to fetch qualifications for.

        Returns:
            Dict mapping participant_id to list of qualification names.
        """
        if not participant_ids:
            return {}

        with self.get_session() as session:
            query = select(
                participant_qualifications.c.participant_id,
                participant_qualifications.c.qualification_name,
            ).where(participant_qualifications.c.participant_id.in_(participant_ids))

            results = session.execute(query).all()

            # Group by participant_id
            quals_map: Dict[int, List[str]] = {}
            for participant_id, qual_name in results:
                quals_map.setdefault(participant_id, []).append(qual_name)

            return quals_map

    def set_qualifications(self, participant_id: int, qualifications: List[str]) -> bool:
        """Replace participant's qualifications."""
        with self.get_session() as session:
            # Delete existing
            session.execute(
                participant_qualifications.delete().where(
                    participant_qualifications.c.participant_id == participant_id
                )
            )
            # Insert new
            for q_name in set(qualifications):
                session.execute(
                    participant_qualifications.insert().values(
                        participant_id=participant_id, qualification_name=q_name
                    )
                )
            self._touch(session, participant_id)
            self._persist(session)
            return True

    @staticmethod
    def _touch(session, participant_id: int) -> None:
        """Время правки карточки — для синхронизации (квалификации в своей таблице)."""
        session.execute(
            update(Participant).where(Participant.id == participant_id).values(updated_at=utc_now())
        )

    def add_qualification(self, participant_id: int, qualification: str) -> bool:
        """Add a single qualification if not already present."""
        with self.get_session() as session:
            existing = session.execute(
                select(participant_qualifications).where(
                    and_(
                        participant_qualifications.c.participant_id == participant_id,
                        participant_qualifications.c.qualification_name == qualification,
                    )
                )
            ).first()
            if not existing:
                session.execute(
                    participant_qualifications.insert().values(
                        participant_id=participant_id, qualification_name=qualification
                    )
                )
                self._touch(session, participant_id)
                self._persist(session)
                return True
            return False

    def get_with_stats(self) -> List[Dict[str, Any]]:
        """Get participants with assignment statistics."""
        with self.get_session() as session:
            query = (
                select(Participant, func.count(Assignment.id).label("total_assignments"))
                .outerjoin(
                    Assignment,
                    and_(
                        Assignment.participant_id == Participant.id,
                        counted_assignment(Assignment),
                    ),
                )
                .where(Participant.is_active.is_(True))
                .group_by(Participant.id)
                .order_by(Participant.name.asc())
            )
            results = session.execute(query).all()
            # Форматируем дату для UI в формате DD.MM.YYYY
            formatted_results = []
            for p, total in results:
                date_str = None
                if p.last_assignment_date:
                    date_str = p.last_assignment_date.strftime("%d.%m.%Y")
                formatted_results.append(
                    {
                        "id": p.id,
                        "name": p.name,
                        "gender": p.gender,
                        "service_type": p.service_type,
                        "is_active": p.is_active,
                        "last_assignment_date": date_str,
                        "family_group_id": p.family_group_id,
                        "total_assignments": total,
                    }
                )
            return formatted_results

    def get_assignment_dates_map(self, session=None) -> Dict[int, List[datetime]]:
        """
        Get mapping of participant_id to list of assignment dates.

        Replaces text() SQL query in AutoAssignmentService.
        Reference: spec://repositories/participant#assignment_dates_map

        Args:
            session: Optional SQLAlchemy session. If None, creates new session.

        Returns:
            Dict mapping participant_id to sorted list of assignment dates.
        """
        should_close = session is None
        if session is None:
            session = self.db.get_session()

        try:
            # ORM query replacing text("SELECT a.participant_id, a.assistant_id, w.start_date ...")
            query = (
                select(Assignment.participant_id, Assignment.assistant_id, Week.start_date)
                .join(Week, Assignment.week_id == Week.id)
                .where(counted_assignment(Assignment))
            )
            results = session.execute(query).all()

            dates_map: Dict[int, List[datetime]] = {}
            for participant_id, assistant_id, start_date in results:
                dt = date_to_datetime(start_date)
                if not dt:
                    continue

                if participant_id:
                    dates_map.setdefault(participant_id, []).append(dt)
                if assistant_id:
                    dates_map.setdefault(assistant_id, []).append(dt)

            # Sort dates for each participant
            for pid in dates_map:
                dates_map[pid].sort()

            return dates_map
        finally:
            if should_close:
                session.close()

    def get_main_assignment_dates_map(self, session=None) -> Dict[int, List[datetime]]:
        """
        Get mapping of participant_id to list of main assignment dates.
        Only considers assignments where participant was the main assignee.

        Args:
            session: Optional SQLAlchemy session. If None, creates new session.

        Returns:
            Dict mapping participant_id to sorted list of main assignment dates.
        """
        should_close = session is None
        if session is None:
            session = self.db.get_session()

        try:
            query = (
                select(Assignment.participant_id, Week.start_date)
                .join(Week, Assignment.week_id == Week.id)
                .where(counted_assignment(Assignment))
                .where(Assignment.participant_id.isnot(None))
            )
            results = session.execute(query).all()

            dates_map: Dict[int, List[datetime]] = {}
            for participant_id, start_date in results:
                dt = date_to_datetime(start_date)
                if not dt:
                    continue

                dates_map.setdefault(participant_id, []).append(dt)

            # Sort dates for each participant
            for pid in dates_map:
                dates_map[pid].sort()

            return dates_map
        finally:
            if should_close:
                session.close()

    def get_position_dates_map(
        self, session=None, configs: list = None
    ) -> Dict[Tuple[int, str, str], List[datetime]]:
        """
        Get mapping of (participant_id, section, position) to list of assignment dates.

        Replaces text() SQL query in AutoAssignmentService.
        Reference: spec://repositories/participant#position_dates_map

        The position key is the **canonical string** from ``assignment_config.position``
        (e.g. ``'chairman'``, ``'reader'``, ``'1'``), not the raw integer
        ``section_position``.  This ensures consistency with ``participant_position_configs``
        and the filtering logic in ``CandidateFilterService``.

        Args:
            session: Optional SQLAlchemy session. If None, creates new session.
            configs: Optional list of already-loaded AssignmentConfig ORM objects.
                     When provided, skips the extra SELECT on assignment_config,
                     avoiding an N+1 query.

        Returns:
            Dict mapping (participant_id, section, position) to sorted list of dates.
        """
        from core.models import AssignmentConfig  # local import to avoid circularity

        should_close = session is None
        if session is None:
            session = self.db.get_session()

        try:
            # Build a canonical position lookup from assignment_config.
            # Use pre-loaded configs if provided (avoids extra DB query).
            if configs is None:
                from core.models import AssignmentConfig  # local import to avoid circularity

                config_rows = session.execute(select(AssignmentConfig)).scalars().all()
            else:
                config_rows = configs
            # Map: (section, numeric_str) -> canonical_position for numeric positions
            numeric_pos_map: Dict[Tuple[str, str], str] = {}
            for cr in config_rows:
                if cr.section and cr.position:
                    # Numeric positions stored as '1','2','3' can be looked up directly
                    numeric_pos_map[(cr.section, cr.position)] = cr.position

            # ORM query for all assigned assignments with week start dates
            query = (
                select(
                    Assignment.participant_id,
                    Assignment.assistant_id,
                    Assignment.section,
                    Assignment.section_position,
                    Assignment.assignment_text,
                    Week.start_date,
                )
                .join(Week, Assignment.week_id == Week.id)
                .where(counted_assignment(Assignment))
            )
            results = session.execute(query).all()

            position_dates_map: Dict[Tuple[int, str, str], List[datetime]] = {}
            for (
                participant_id,
                assistant_id,
                section,
                section_position,
                assignment_text,
                start_date,
            ) in results:
                dt = date_to_datetime(start_date)
                if not dt or not section:
                    continue

                # Resolve the canonical position key:
                # 1. If section_position is a number, its string form IS the config position.
                # 2. If section_position is NULL, derive from assignment_text (named positions).
                if section_position is not None:
                    pos_key = str(section_position)
                else:
                    # Named position: derive from assignment_text
                    text_lower = (assignment_text or "").lower()
                    if "председатель" in text_lower or "chairman" in text_lower:
                        pos_key = "chairman"
                    elif (
                        "изучение библии" in text_lower
                        or "conductor" in text_lower
                        or "руководитель" in text_lower
                    ):
                        pos_key = "conductor"
                    elif "чтец" in text_lower or "reader" in text_lower:
                        pos_key = "reader"
                    elif "молитва" in text_lower and "открыт" in text_lower:
                        pos_key = "prayer_open"
                    elif "молитва" in text_lower and "закрыт" in text_lower:
                        pos_key = "prayer_close"
                    else:
                        # Unknown named position: skip (can't determine canonical key)
                        continue

                key_sec_pos = (section, pos_key)

                if participant_id:
                    key = (participant_id, *key_sec_pos)
                    position_dates_map.setdefault(key, []).append(dt)
                if assistant_id:
                    key = (assistant_id, *key_sec_pos)
                    position_dates_map.setdefault(key, []).append(dt)

            # Sort dates for each key
            for key in position_dates_map:
                position_dates_map[key].sort()

            return position_dates_map
        finally:
            if should_close:
                session.close()

    def get_recent_pairs_map(self, session=None) -> Dict[Tuple[int, int], List[datetime]]:
        """
        Get mapping of unordered participant pairs (p1, p2) to assignment dates.
        Tracks when two participants worked together as main and assistant.

        Returns:
            Dict mapping (min(p1, p2), max(p1, p2)) to sorted list of assignment dates.
        """
        should_close = session is None
        if session is None:
            session = self.db.get_session()

        try:
            query = (
                select(Assignment.participant_id, Assignment.assistant_id, Week.start_date)
                .join(Week, Assignment.week_id == Week.id)
                .where(counted_assignment(Assignment))
                .where(Assignment.participant_id.isnot(None))
                .where(Assignment.assistant_id.isnot(None))
            )
            results = session.execute(query).all()

            pairs_map: Dict[Tuple[int, int], List[datetime]] = {}
            for p1_id, p2_id, start_date in results:
                dt = date_to_datetime(start_date)
                if not dt or not p1_id or not p2_id:
                    continue
                pair_key = (min(p1_id, p2_id), max(p1_id, p2_id))
                pairs_map.setdefault(pair_key, []).append(dt)

            for key in pairs_map:
                pairs_map[key].sort()

            return pairs_map
        finally:
            if should_close:
                session.close()
