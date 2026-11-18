import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, delete, select, update

from core.database import DatabaseManager
from core.events import Event, EventBus
from core.models import Assignment, Participant, participant_qualifications, utc_now

logger = logging.getLogger(__name__)


class ParticipantService:
    def __init__(self, db: DatabaseManager, event_bus: EventBus, schedule_domain_service=None):
        self.db = db
        self.event_bus = event_bus
        self._schedule_domain_service = schedule_domain_service

    @property
    def schedule_domain_service(self):
        """Lazy initialization of ScheduleDomainService."""
        if self._schedule_domain_service is None:
            from core.schedule_service import ScheduleDomainService

            self._schedule_domain_service = ScheduleDomainService(
                db_manager=self.db,
                event_bus=self.event_bus,
            )
        return self._schedule_domain_service

    def get_all_participants(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """
        Get all participants with statistics.

        Uses DTOs and Mappers for consistent data format and NO N+1 queries.
        """
        from core.mappers import ParticipantMapper

        with self.db.get_session() as session:
            # Bulk load participants with stats (NO N+1!)
            participants_dto = ParticipantMapper.bulk_load_with_stats(session, active_only)

            # Convert DTOs → UI format for backward compatibility
            return [ParticipantMapper.to_ui_dict(dto) for dto in participants_dto]

    def get_participant_history(self, p_id: int):
        """Returns history of assignments for a participant."""
        return self.schedule_domain_service.get_participant_history(p_id)

    def get_participant(self, p_id: int) -> Optional[Dict[str, Any]]:
        from core.mappers import ParticipantMapper

        with self.db.get_session() as session:
            p = session.get(Participant, p_id)
            if not p:
                return None
            dto = ParticipantMapper.from_db_with_stats(session, p)
            return ParticipantMapper.to_ui_dict(dto)

    def add_participant(
        self,
        name: str,
        gender: str,
        service_type: str,
        quals: List[str],
        family_id: Optional[int] = None,
        personal_gap: Optional[int] = None,
        is_minor: bool = False,
        unavailable_from: Optional[Any] = None,
        unavailable_to: Optional[Any] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
    ):
        with self.db.get_session() as session:
            try:
                # Check for existing name
                existing = session.execute(
                    select(Participant).where(Participant.name == name)
                ).scalar()
                if existing:
                    return None

                p = Participant(
                    name=name,
                    gender=gender,
                    service_type=service_type,
                    family_group_id=family_id,
                    personal_gap=personal_gap,
                    is_minor=is_minor,
                    unavailable_from=unavailable_from,
                    unavailable_to=unavailable_to,
                    email=email.strip() if email else None,
                    phone=phone.strip() if phone else None,
                )
                session.add(p)
                session.flush()

                for q_name in set(quals):
                    session.execute(
                        participant_qualifications.insert().values(
                            participant_id=p.id, qualification_name=q_name
                        )
                    )

                session.commit()
                logger.info(f"Added participant {p.id}: {name}")
                self.event_bus.emit(Event.PARTICIPANT_CHANGED, p_id=p.id)
                return p.id
            except Exception as e:
                session.rollback()
                logger.error(f"Error adding participant '{name}': {e}")
                return None

    def update_participant(
        self,
        p_id: int,
        name: str,
        gender: str,
        service_type: str,
        quals: List[str],
        family_id: Optional[int] = None,
        personal_gap: Optional[int] = None,
        is_minor: bool = False,
        unavailable_from: Optional[Any] = None,
        unavailable_to: Optional[Any] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
    ):
        with self.db.get_session() as session:
            try:
                p = session.get(Participant, p_id)
                if not p:
                    return False

                p.name = name
                p.gender = gender
                p.service_type = service_type
                p.family_group_id = family_id
                p.personal_gap = personal_gap
                p.is_minor = is_minor
                p.unavailable_from = unavailable_from
                p.unavailable_to = unavailable_to
                p.email = email.strip() if email else None
                p.phone = phone.strip() if phone else None
                # Квалификации в отдельной таблице — их правка сама время не ставит
                p.updated_at = utc_now()

                session.execute(
                    participant_qualifications.delete().where(
                        participant_qualifications.c.participant_id == p_id
                    )
                )
                for q_name in quals:
                    session.execute(
                        participant_qualifications.insert().values(
                            participant_id=p_id, qualification_name=q_name
                        )
                    )

                session.commit()
                self.event_bus.emit(Event.PARTICIPANT_CHANGED, p_id=p_id)
                return True
            except Exception as e:
                session.rollback()
                logger.error(f"Error updating participant {p_id}: {e}")
                return False

    def set_unavailable(self, p_id: int, unavailable_from, unavailable_to) -> bool:
        """Отпуск «с … по …» одного участника (None, None — снять)."""
        with self.db.get_session() as session:
            p = session.get(Participant, p_id)
            if not p:
                return False
            p.unavailable_from, p.unavailable_to = unavailable_from, unavailable_to
            session.commit()
        self.event_bus.emit(Event.PARTICIPANT_CHANGED, p_id=p_id)
        return True

    def delete_participant(self, p_id: int):
        with self.db.get_session() as session:
            try:
                p = session.get(Participant, p_id)
                if not p:
                    return False

                # Delete associated qualifications first
                session.execute(
                    participant_qualifications.delete().where(
                        participant_qualifications.c.participant_id == p_id
                    )
                )

                # Чтобы синхронизация не вернула удалённого с другого устройства
                from core import participant_tombstones

                participant_tombstones.record(session, p.name)

                session.delete(p)
                session.commit()
                self.event_bus.emit(Event.PARTICIPANT_CHANGED, p_id=p_id)
                return True
            except Exception as e:
                session.rollback()
                logger.error(f"Error deleting participant {p_id}: {e}")
                return False

    # ==================== Excluded Weeks (Periodic Unavailability) ====================

    def get_excluded_weeks(self, p_id: int) -> List[Any]:
        """Get list of excluded week dates for a participant.

        Returns a sorted list of date objects representing weeks
        when the participant is unavailable.
        """
        from core.models import ParticipantExcludedWeek

        with self.db.get_session() as session:
            rows = (
                session.execute(
                    select(ParticipantExcludedWeek.week_start)
                    .where(ParticipantExcludedWeek.participant_id == p_id)
                    .order_by(ParticipantExcludedWeek.week_start)
                )
                .scalars()
                .all()
            )
            return list(rows)

    def add_excluded_week(self, p_id: int, week_date: Any) -> bool:
        """Add a single week exclusion for a participant.

        Args:
            p_id: Participant ID
            week_date: Date (date object or date string YYYY-MM-DD) of the week to exclude
        Returns:
            True if added, False if already exists or error.
        """
        from datetime import date as date_type

        from core.models import ParticipantExcludedWeek

        if isinstance(week_date, str):
            from datetime import date as date_class

            week_date = date_class.fromisoformat(week_date)
        with self.db.get_session() as session:
            try:
                existing = session.execute(
                    select(ParticipantExcludedWeek).where(
                        ParticipantExcludedWeek.participant_id == p_id,
                        ParticipantExcludedWeek.week_start == week_date,
                    )
                ).scalar()
                if existing:
                    return True  # Already excluded
                row = ParticipantExcludedWeek(participant_id=p_id, week_start=week_date)
                session.add(row)
                session.commit()
                self.event_bus.emit(Event.PARTICIPANT_CHANGED, p_id=p_id)
                return True
            except Exception as e:
                session.rollback()
                logger.error(f"Error adding excluded week for participant {p_id}: {e}")
                return False

    def remove_excluded_week(self, p_id: int, week_date: Any) -> bool:
        """Remove a single week exclusion for a participant."""
        from core.models import ParticipantExcludedWeek

        if isinstance(week_date, str):
            from datetime import date as date_class

            week_date = date_class.fromisoformat(week_date)
        with self.db.get_session() as session:
            try:
                session.execute(
                    ParticipantExcludedWeek.__table__.delete().where(
                        ParticipantExcludedWeek.participant_id == p_id,
                        ParticipantExcludedWeek.week_start == week_date,
                    )
                )
                session.commit()
                self.event_bus.emit(Event.PARTICIPANT_CHANGED, p_id=p_id)
                return True
            except Exception as e:
                session.rollback()
                logger.error(f"Error removing excluded week for participant {p_id}: {e}")
                return False

    def set_excluded_weeks_from_pattern(
        self,
        p_id: int,
        start_date: Any,
        interval_weeks: int,
        count: int,
        replace: bool = False,
    ) -> int:
        """Generate and save excluded weeks from a recurring pattern.

        Args:
            p_id: Participant ID.
            start_date: First excluded week date.
            interval_weeks: Repeat every N weeks (e.g. 2 = every other week).
            count: Number of occurrences to generate.
            replace: If True, clear all existing exclusions before saving.
        Returns:
            Number of new records added.
        """
        from datetime import date as date_class
        from datetime import timedelta

        from core.models import ParticipantExcludedWeek

        if isinstance(start_date, str):
            start_date = date_class.fromisoformat(start_date)

        dates_to_add = [start_date + timedelta(weeks=i * interval_weeks) for i in range(count)]

        with self.db.get_session() as session:
            try:
                if replace:
                    session.execute(
                        ParticipantExcludedWeek.__table__.delete().where(
                            ParticipantExcludedWeek.participant_id == p_id
                        )
                    )

                added = 0
                for d in dates_to_add:
                    existing = session.execute(
                        select(ParticipantExcludedWeek).where(
                            ParticipantExcludedWeek.participant_id == p_id,
                            ParticipantExcludedWeek.week_start == d,
                        )
                    ).scalar()
                    if not existing:
                        session.add(ParticipantExcludedWeek(participant_id=p_id, week_start=d))
                        added += 1

                session.commit()
                self.event_bus.emit(Event.PARTICIPANT_CHANGED, p_id=p_id)
                return added
            except Exception as e:
                session.rollback()
                logger.error(f"Error setting excluded weeks pattern for participant {p_id}: {e}")
                return 0

    def clear_excluded_weeks(self, p_id: int) -> bool:
        """Remove all excluded week records for a participant."""
        from core.models import ParticipantExcludedWeek

        with self.db.get_session() as session:
            try:
                session.execute(
                    ParticipantExcludedWeek.__table__.delete().where(
                        ParticipantExcludedWeek.participant_id == p_id
                    )
                )
                session.commit()
                self.event_bus.emit(Event.PARTICIPANT_CHANGED, p_id=p_id)
                return True
            except Exception as e:
                session.rollback()
                logger.error(f"Error clearing excluded weeks for participant {p_id}: {e}")
                return False

    def set_excluded_weeks(self, p_id: int, dates: List[Any]) -> bool:
        """Set the list of excluded weeks for a participant.

        Clears all existing excluded weeks and adds the new ones.
        """
        from datetime import date as date_class

        from core.models import ParticipantExcludedWeek

        parsed_dates = []
        for d in dates:
            if isinstance(d, str):
                parsed_dates.append(date_class.fromisoformat(d))
            else:
                parsed_dates.append(d)

        # Deduplicate
        parsed_dates = sorted(list(set(parsed_dates)))

        with self.db.get_session() as session:
            try:
                # Delete existing
                session.execute(
                    ParticipantExcludedWeek.__table__.delete().where(
                        ParticipantExcludedWeek.participant_id == p_id
                    )
                )
                # Insert new ones
                for d in parsed_dates:
                    session.add(ParticipantExcludedWeek(participant_id=p_id, week_start=d))
                session.commit()
                self.event_bus.emit(Event.PARTICIPANT_CHANGED, p_id=p_id)
                return True
            except Exception as e:
                session.rollback()
                logger.error(f"Error setting excluded weeks for participant {p_id}: {e}")
                return False


class ScheduleService:
    """
    Core schedule service handling week data and assignments.

    Import and Export functionality delegated to ImportService and ExportService.

    This service now uses ScheduleDomainService for schedule operations.

    Reference: spec://services/schedule
    """

    def __init__(
        self,
        db: DatabaseManager,
        event_bus: EventBus,
        auto_assignment_service=None,
        import_service=None,
        export_service=None,
        schedule_domain_service=None,
    ):
        self.db = db
        self.event_bus = event_bus
        self._auto_assignment_service = auto_assignment_service
        self._import_service = import_service
        self._export_service = export_service
        self._schedule_domain_service = schedule_domain_service
        self._assignment_config_repo = None

    @property
    def auto_assignment_service(self):
        """Lazy initialization of AutoAssignmentService."""
        if self._auto_assignment_service is None:
            from core.auto_assignment_service import AutoAssignmentService

            self._auto_assignment_service = AutoAssignmentService(
                session_factory=self.db.get_session
            )
        return self._auto_assignment_service

    @property
    def import_service(self):
        """Lazy initialization of ImportService."""
        if self._import_service is None:
            from core.import_service import ImportService

            self._import_service = ImportService(self.db, self.event_bus)
        return self._import_service

    @property
    def export_service(self):
        """Lazy initialization of ExportService."""
        if self._export_service is None:
            from core.export_service import ExportService

            self._export_service = ExportService(self.db, self.event_bus, self)
        return self._export_service

    @property
    def schedule_domain_service(self):
        """Lazy initialization of ScheduleDomainService."""
        if self._schedule_domain_service is None:
            from core.schedule_service import ScheduleDomainService

            self._schedule_domain_service = ScheduleDomainService(
                db_manager=self.db,
                event_bus=self.event_bus,
            )
        return self._schedule_domain_service

    # ==================== Core Schedule Methods ====================

    def get_week_data(self, week_id: int) -> Optional[Dict[str, Any]]:
        """Get week data with assignments.

        Reference: spec://services/schedule#get_week_data
        """
        return self.schedule_domain_service.get_week_data(week_id)

    def get_week_conflicts(self, week_id: int):
        """Get participant IDs that appear more than once in a week.

        Reference: spec://services/schedule#get_week_conflicts
        """
        return self.schedule_domain_service.get_week_conflicts(week_id)

    def get_assignment(self, assignment_id: int) -> Optional[Dict[str, Any]]:
        """Get assignment data by ID including section and section_position."""
        from core.models import Assignment

        with self.db.get_session() as session:
            a = session.get(Assignment, assignment_id)
            if not a:
                return None
            return {
                "id": a.id,
                "week_id": a.week_id,
                "assignment_text": a.assignment_text,
                "assignment_type": a.assignment_type,
                "section": a.section,
                "section_position": a.section_position,
                "discussion_marker": a.discussion_marker,
                "participant_id": a.participant_id,
                "assistant_id": a.assistant_id,
            }

    def get_assignment_stats(self, start, end, group: str = "all"):
        """Выступления за период для вкладки «Статистика» (см. core/statistics)."""
        from core.statistics import assignment_stats

        with self.db.get_session() as session:
            return assignment_stats(session, start, end, group)

    def auto_assign_week(self, week_id: int, only_empty: bool = False):
        """Auto-assign participants to a week using AutoAssignmentService.

        only_empty — заполнить только пустые пункты, назначенных не трогать.
        Reference: spec://services/auto_assignment#auto_assign_week
        """
        result = self.auto_assignment_service.auto_assign_week(week_id, only_empty=only_empty)
        if result.get("success"):
            self.event_bus.emit(Event.ASSIGNMENT_CHANGED, week_id=week_id)
        return result

    def set_special_event(self, week_id: int, event_type: str):
        success = self.db.set_week_special_event(week_id, event_type)
        if success:
            self.event_bus.emit(Event.ASSIGNMENT_CHANGED, week_id=week_id)
        return success

    def set_slip_given(self, assignment_ids, given: bool) -> bool:
        """«🧾 Листок выдан» у пунктов (given=False — снять)."""
        return self.schedule_domain_service.set_slip_given(assignment_ids, given)

    def restore_people(self, entries) -> bool:
        """Отмена правки на доске месяца: люди пунктов как были."""
        return self.schedule_domain_service.restore_people(entries)

    def swap_people(self, first_id: int, first_role: str, second_id: int, second_role: str) -> bool:
        """Поменять местами людей двух пунктов (доска месяца, «⇄ Поменять местами»)."""
        return self.schedule_domain_service.swap_people(
            first_id, first_role, second_id, second_role
        )

    def assign_participant(
        self, assignment_id: int, participant_id: Optional[int], role: str = "participant"
    ):
        """Assign a participant to an assignment.

        Reference: spec://services/schedule#assign_participant
        """
        return self.schedule_domain_service.assign_participant(assignment_id, participant_id, role)

    def update_assignment_duration(self, assignment_id: int, duration: int) -> bool:
        """Update an assignment duration in minutes."""
        from core.models import Assignment

        try:
            with self.db.get_session() as session:
                assignment = session.get(Assignment, assignment_id)
                if not assignment:
                    return False
                assignment.duration = max(int(duration or 0), 0)
                week_id = assignment.week_id
                session.commit()
        except Exception:
            logger.exception("Failed to update duration for assignment %s", assignment_id)
            return False

        self.event_bus.emit(Event.ASSIGNMENT_CHANGED, week_id=week_id)
        return True

    @staticmethod
    def _next_assignment_number(session, week_id: int, section: str) -> int:
        rows = session.execute(
            select(Assignment.assignment_number, Assignment.section).where(
                Assignment.week_id == week_id
            )
        ).all()
        numeric_numbers = []
        for number, assignment_section in rows:
            if assignment_section != section:
                continue
            digits = ""
            for character in str(number or ""):
                if not character.isdigit():
                    break
                digits += character
            if digits:
                numeric_numbers.append(int(digits))
        return max(numeric_numbers, default=0) + 1

    def add_manual_assignment(
        self,
        week_id: int,
        text: str,
        section: str,
        duration: int,
        participant_id: Optional[int] = None,
    ) -> Optional[int]:
        """Add a custom assignment to a week."""
        from core.models import Assignment, AssignmentStatus, Week

        text = (text or "").strip()
        if not text or section not in {"treasures", "ministry", "living", "cbs"}:
            return None

        try:
            with self.db.get_session() as session:
                if not session.get(Week, week_id):
                    return None

                next_number = self._next_assignment_number(session, week_id, section)
                existing = (
                    session.execute(select(Assignment).where(Assignment.week_id == week_id))
                    .scalars()
                    .all()
                )
                has_manual_order = any(
                    existing_assignment.sort_order is not None for existing_assignment in existing
                )
                sort_order = None
                if has_manual_order:
                    ordered = sorted(
                        existing,
                        key=lambda item: (
                            item.sort_order is None,
                            item.sort_order if item.sort_order is not None else 0,
                        ),
                    )
                    insert_index = len(ordered)
                    for index, existing_assignment in enumerate(ordered):
                        if existing_assignment.section == section:
                            insert_index = index + 1
                    sort_order = insert_index
                assignment = Assignment(
                    week_id=week_id,
                    assignment_text=text,
                    assignment_type="custom",
                    assignment_number=str(next_number),
                    section=section,
                    section_position=f"custom_{next_number}",
                    duration=max(int(duration or 0), 0),
                    sort_order=sort_order,
                    participant_id=participant_id,
                    status=(
                        AssignmentStatus.ASSIGNED.value
                        if participant_id
                        else AssignmentStatus.EMPTY.value
                    ),
                )
                session.add(assignment)
                if has_manual_order:
                    ordered.insert(insert_index, assignment)
                    for index, ordered_assignment in enumerate(ordered):
                        ordered_assignment.sort_order = index
                session.flush()
                assignment_id = assignment.id
                session.commit()
        except Exception:
            logger.exception("Failed to add manual assignment for week %s", week_id)
            return None

        self.event_bus.emit(Event.ASSIGNMENT_CHANGED, week_id=week_id)
        return assignment_id

    def update_manual_assignment(
        self,
        assignment_id: int,
        text: str,
        section: str,
        duration: int,
        participant_id: Optional[int] = None,
    ) -> bool:
        """Update a custom assignment."""
        from core.models import AssignmentStatus

        text = (text or "").strip()
        if not text or section not in {"treasures", "ministry", "living", "cbs"}:
            return False

        try:
            with self.db.get_session() as session:
                assignment = session.get(Assignment, assignment_id)
                if not assignment or assignment.assignment_type != "custom":
                    return False
                assignment.assignment_text = text
                assignment.section = section
                assignment.duration = max(int(duration or 0), 0)
                assignment.participant_id = participant_id
                assignment.status = (
                    AssignmentStatus.ASSIGNED.value
                    if participant_id
                    else AssignmentStatus.EMPTY.value
                )
                week_id = assignment.week_id
                session.commit()
        except Exception:
            logger.exception("Failed to update manual assignment %s", assignment_id)
            return False

        self.event_bus.emit(Event.ASSIGNMENT_CHANGED, week_id=week_id)
        return True

    def delete_manual_assignment(self, assignment_id: int) -> bool:
        """Delete a custom assignment."""
        try:
            with self.db.get_session() as session:
                assignment = session.get(Assignment, assignment_id)
                if not assignment or assignment.assignment_type != "custom":
                    return False
                week_id = assignment.week_id
                session.delete(assignment)
                session.commit()
        except Exception:
            logger.exception("Failed to delete manual assignment %s", assignment_id)
            return False

        self.event_bus.emit(Event.ASSIGNMENT_CHANGED, week_id=week_id)
        return True

    def duplicate_manual_assignment(self, assignment_id: int) -> Optional[int]:
        """Duplicate a custom assignment without its participant."""
        from core.models import AssignmentStatus

        try:
            with self.db.get_session() as session:
                source = session.get(Assignment, assignment_id)
                if not source or source.assignment_type != "custom":
                    return None
                next_number = self._next_assignment_number(
                    session,
                    source.week_id,
                    source.section,
                )
                duplicate = Assignment(
                    week_id=source.week_id,
                    assignment_text=source.assignment_text,
                    assignment_type="custom",
                    assignment_number=str(next_number),
                    section=source.section,
                    section_position=f"custom_{next_number}",
                    duration=source.duration,
                    participant_id=None,
                    status=AssignmentStatus.EMPTY.value,
                )
                session.add(duplicate)
                session.flush()
                duplicate_id = duplicate.id
                week_id = source.week_id
                session.commit()
        except Exception:
            logger.exception("Failed to duplicate manual assignment %s", assignment_id)
            return None

        self.event_bus.emit(Event.ASSIGNMENT_CHANGED, week_id=week_id)
        return duplicate_id

    def reorder_week_assignments(self, week_id: int, ordered_ids: List[int]) -> bool:
        """Persist manual assignment order for a week."""
        if not ordered_ids:
            return False
        try:
            with self.db.get_session() as session:
                assignments = (
                    session.execute(select(Assignment).where(Assignment.week_id == week_id))
                    .scalars()
                    .all()
                )
                by_id = {assignment.id: assignment for assignment in assignments}
                if any(assignment_id not in by_id for assignment_id in ordered_ids):
                    return False
                for sort_order, assignment_id in enumerate(ordered_ids):
                    by_id[assignment_id].sort_order = sort_order
                session.commit()
        except Exception:
            logger.exception("Failed to reorder assignments for week %s", week_id)
            return False

        self.event_bus.emit(Event.ASSIGNMENT_CHANGED, week_id=week_id)
        return True

    def replace_week_assignments(self, week_id: int, assignments: List[Dict[str, Any]]) -> bool:
        """Replace all assignments of a week with a stored snapshot."""
        try:
            with self.db.get_session() as session:
                session.execute(delete(Assignment).where(Assignment.week_id == week_id))
                session.flush()
                for data in assignments:
                    session.add(
                        Assignment(
                            id=data.get("id"),
                            week_id=week_id,
                            assignment_text=data.get("assignment_text") or "Назначение",
                            assignment_type=data.get("assignment_type"),
                            assignment_number=data.get("assignment_number"),
                            section=data.get("section"),
                            section_position=data.get("section_position"),
                            duration=data.get("duration"),
                            sort_order=data.get("sort_order"),
                            discussion_marker=data.get("discussion_marker"),
                            participant_id=data.get("participant_id"),
                            assistant_id=data.get("assistant_id"),
                            status=data.get("status") or "empty",
                            slip_given_at=data.get("slip_given_at"),
                        )
                    )
                session.commit()
        except Exception:
            logger.exception("Failed to restore assignments for week %s", week_id)
            return False

        self.event_bus.emit(Event.ASSIGNMENT_CHANGED, week_id=week_id)
        return True

    def clear_week_assignments(self, week_id: int):
        """Clear all assignments for a week.

        Reference: spec://services/schedule#clear_week_assignments
        """
        return self.schedule_domain_service.clear_week_assignments(week_id)

    def has_assignments(self, week_id: int):
        """Check if a week has any assignments with participants.

        Reference: spec://services/schedule#has_assignments
        """
        return self.schedule_domain_service.has_assignments(week_id)

    def get_weeks_tree(self):
        """Get weeks organized as a tree by year and month.

        Reference: spec://services/schedule#get_weeks_tree
        """
        return self.schedule_domain_service.get_weeks_tree()

    def get_participant_history(self, p_id: int):
        """Get assignment history for a participant.

        Reference: spec://services/schedule#get_participant_history
        """
        return self.schedule_domain_service.get_participant_history(p_id)

    def auto_assign_all(self):
        """Auto-assign participants for all weeks using AutoAssignmentService.

        Reference: spec://services/auto_assignment#auto_assign_all
        """
        result = self.auto_assignment_service.auto_assign_all()
        if result.get("success"):
            self.event_bus.emit(Event.ASSIGNMENT_CHANGED)
        return result

    # ==================== Delegated Import Methods ====================

    def import_workbook(self, file_path: str):
        """Delegate to ImportService. Kept for backward compatibility."""
        return self.import_service.import_workbook(file_path)

    def prepare_future_year(self, year: int):
        """Delegate to ImportService. Kept for backward compatibility."""
        return self.import_service.prepare_future_year(year)

    def plan_future_year(self):
        """Год для кнопки «Будущий год» и число недостающих недель (ImportService)."""
        return self.import_service.plan_future_year()

    # ==================== Delegated Export Methods ====================

    def generate_preview_html(self, week_id: int):
        """Delegate to ExportService. Kept for backward compatibility."""
        return self.export_service.generate_preview_html(week_id)

    def export_to_s89(self, week_ids: List[int], output_path: str):
        """Delegate to ExportService. Kept for backward compatibility."""
        return self.export_service.export_to_s89(week_ids, output_path)

    def export_custom_docx(self, week_ids: List[int], output_path: str, mode: str = "compact"):
        """Delegate to ExportService. Kept for backward compatibility."""
        return self.export_service.export_custom_docx(week_ids, output_path, mode)

    def export_to_txt(self, week_ids: List[int], output_path: str):
        """Delegate to ExportService. Kept for backward compatibility."""
        return self.export_service.export_to_txt(week_ids, output_path)

    def export_to_pdf(self, week_ids: List[int], output_path: str):
        """Delegate to ExportService. Kept for backward compatibility."""
        return self.export_service.export_to_pdf(week_ids, output_path)

    def print_schedule(self, week_ids: List[int], printer) -> bool:
        """Напечатать расписание на принтер (QPrinter)."""
        return self.export_service.print_schedule(week_ids, printer)

    def get_weeks_date_range(self, week_ids: List[int]):
        """Delegate to ExportService. Kept for backward compatibility."""
        return self.export_service.get_weeks_date_range(week_ids)

    # ==================== Settings Methods ====================

    def get_setting(self, key: str, default: Any = None):
        return self.db.get_setting(key, default)

    def save_setting(self, key: str, value: Any):
        return self.db.save_setting(key, value)

    def get_week_special_event(self, week_id: int):
        return self.db.get_week_special_event(week_id)

    @property
    def assignment_config_repo(self):
        if self._assignment_config_repo is None:
            from core.repositories.assignment_config_repository import AssignmentConfigRepository

            self._assignment_config_repo = AssignmentConfigRepository(db_manager=self.db)
        return self._assignment_config_repo

    def get_assignment_config(self, section: Optional[str] = None, position: Optional[str] = None):
        """Get assignment configurations. If section+position specified, return one; otherwise all."""
        return self.assignment_config_repo.get_config(section, position)

    def save_assignment_config(self, config_list):
        return self.assignment_config_repo.save_configs(config_list)

    def get_week_announcement(self, week_id: int) -> str:
        from core.models import Week

        with self.db.get_session() as session:
            w = session.get(Week, week_id)
            return w.announcement if w and w.announcement else ""

    def save_week_announcement(self, week_id: int, text: str):
        from core.models import Week

        with self.db.get_session() as session:
            try:
                w = session.get(Week, week_id)
                if w:
                    w.announcement = text
                    session.commit()
                    return True
            except Exception as e:
                logger.error(f"Error saving announcement: {e}")
            return False
