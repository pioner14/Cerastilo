"""
Schedule domain service providing business logic for schedule operations.

This service uses repositories through dependency injection, following
Clean Architecture principles.

Reference: spec://services/schedule_domain
"""

import logging
from typing import Any, Dict, List, Optional

from core.database import DatabaseManager
from core.events import Event, EventBus
from core.repositories.assignment_repository import AssignmentRepository
from core.repositories.participant_repository import ParticipantRepository
from core.repositories.week_repository import WeekRepository

logger = logging.getLogger(__name__)


class ScheduleDomainService:
    """
    Domain service for schedule operations using repositories via DI.

    This service encapsulates business logic for schedule management,
    delegating data access to specialized repositories.

    Unlike the legacy ScheduleService in services.py, this class:
    - Uses repository pattern for data access
    - Follows Single Responsibility Principle
    - Supports dependency injection for testability

    Reference: spec://services/schedule_domain
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        event_bus: EventBus,
        week_repo: Optional[WeekRepository] = None,
        assignment_repo: Optional[AssignmentRepository] = None,
        participant_repo: Optional[ParticipantRepository] = None,
    ):
        """
        Initialize service with dependencies.

        Args:
            db_manager: Database manager for session creation
            event_bus: Event bus for publishing domain events
            week_repo: Week repository (optional, created if not provided)
            assignment_repo: Assignment repository (optional, created if not provided)
            participant_repo: Participant repository (optional, created if not provided)
        """
        self._db_manager = db_manager
        self._event_bus = event_bus

        # Lazy initialization of repositories if not provided
        self._week_repo = week_repo
        self._assignment_repo = assignment_repo
        self._participant_repo = participant_repo

    @property
    def week_repo(self) -> WeekRepository:
        """Lazy initialization of WeekRepository."""
        if self._week_repo is None:
            self._week_repo = WeekRepository(self._db_manager)
        return self._week_repo

    @property
    def assignment_repo(self) -> AssignmentRepository:
        """Lazy initialization of AssignmentRepository."""
        if self._assignment_repo is None:
            self._assignment_repo = AssignmentRepository(self._db_manager)
        return self._assignment_repo

    @property
    def participant_repo(self) -> ParticipantRepository:
        """Lazy initialization of ParticipantRepository."""
        if self._participant_repo is None:
            self._participant_repo = ParticipantRepository(self._db_manager)
        return self._participant_repo

    # ==================== Business Logic Methods ====================

    def set_slip_given(self, assignment_ids, given: bool) -> bool:
        """«🧾 Листок выдан» у пунктов (given=False — снять)."""
        success = self.assignment_repo.set_slip_given(assignment_ids, given)
        if success:
            self._event_bus.emit(Event.ASSIGNMENT_CHANGED)
        return success

    def restore_people(self, entries) -> bool:
        """Вернуть людей пунктов к записанному состоянию одной транзакцией."""
        success = self.assignment_repo.restore_people(entries)
        if success:
            self._event_bus.emit(Event.ASSIGNMENT_CHANGED)
        return success

    def swap_people(self, first_id: int, first_role: str, second_id: int, second_role: str) -> bool:
        """Поменять местами людей двух пунктов одной транзакцией."""
        success = self.assignment_repo.swap_people(first_id, first_role, second_id, second_role)
        if success:
            self._event_bus.emit(Event.ASSIGNMENT_CHANGED)
            logger.info(
                f"Swapped people of assignments {first_id} ({first_role}) and "
                f"{second_id} ({second_role})"
            )
        return success

    def assign_participant(
        self,
        assignment_id: int,
        participant_id: Optional[int],
        role: str = "participant",
    ) -> bool:
        """
        Assign a participant to an assignment.

        This method delegates to AssignmentRepository but adds:
        - Event publishing for UI updates
        - Logging for audit trail

        Args:
            assignment_id: ID of the assignment
            participant_id: ID of the participant (None to unassign)
            role: Either "participant" or "assistant"

        Returns:
            True if assignment was successful, False otherwise

        Reference: spec://services/schedule_domain#assign_participant
        """
        success = self.assignment_repo.assign_participant(assignment_id, participant_id, role)
        if success:
            self._event_bus.emit(Event.ASSIGNMENT_CHANGED)
            logger.info(
                f"Assigned participant {participant_id} to assignment {assignment_id} as {role}"
            )
        else:
            logger.warning(
                f"Failed to assign participant {participant_id} to assignment {assignment_id}"
            )
        return success

    def clear_week_assignments(self, week_id: int) -> bool:
        """
        Clear all assignments for a week, preserving disabled ones.

        This method implements business logic for:
        - Identifying affected participants
        - Clearing non-disabled assignments
        - Recalculating last_assignment_date for affected participants
        - Publishing domain events

        Args:
            week_id: ID of the week to clear

        Returns:
            True if clearing was successful, False otherwise

        Reference: spec://services/schedule_domain#clear_week_assignments
        """
        success, affected_ids = self.assignment_repo.clear_week_assignments_preserving_disabled(
            week_id
        )
        if success:
            self._event_bus.emit(Event.ASSIGNMENT_CHANGED, week_id=week_id)
            logger.info(
                f"Cleared assignments for week {week_id}, affected participants: {affected_ids}"
            )
        else:
            logger.warning(f"Failed to clear assignments for week {week_id}")
        return success

    def get_assignment_config(
        self,
        section: Optional[str] = None,
        position: Optional[str] = None,
    ) -> Any:
        """
        Get assignment configuration(s).

        If section and position are provided, returns a single config.
        Otherwise, returns all configurations.

        Args:
            section: Section name (e.g., "treasures", "ministry", "living")
            position: Position within section (e.g., "1", "2")

        Returns:
            Single AssignmentConfig or list of config dicts

        Reference: spec://services/schedule_domain#get_assignment_config
        """
        from sqlalchemy import and_, select

        from core.models import AssignmentConfig

        with self._db_manager.get_session() as session:
            if section and position:
                return session.execute(
                    select(AssignmentConfig).where(
                        and_(
                            AssignmentConfig.section == section,
                            AssignmentConfig.position == position,
                        )
                    )
                ).scalar()

            return [
                {
                    "section": c.section,
                    "position": c.position,
                    "assignment_name": c.assignment_name,
                    "required_qualification": c.required_qualification,
                    "is_brothers_only": c.is_brothers_only,
                    "needs_assistant": c.needs_assistant,
                }
                for c in session.execute(select(AssignmentConfig)).scalars().all()
            ]

    def prepare_future_year(self, year: int) -> Dict[str, Any]:
        """
        Prepare database for a future year: create missing empty weeks.

        Args:
            year: Year to prepare (e.g., 2027)

        Returns:
            {'success': True, 'year': год, 'created': сколько недель создано}

        Reference: spec://services/schedule_domain#prepare_future_year
        """
        from core.import_service import ImportService

        import_service = ImportService(self._db_manager, self._event_bus)
        return import_service.prepare_future_year(year)

    def plan_future_year(self) -> Dict[str, int]:
        """Год для кнопки «Будущий год» и число недостающих недель."""
        from core.import_service import ImportService

        return ImportService(self._db_manager, self._event_bus).plan_future_year()

    # ==================== Delegation Methods ====================
    # These methods delegate directly to repositories.

    def get_weeks_tree(self) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
        """
        Get weeks organized as a tree by year and month.

        Delegates to WeekRepository.get_weeks_tree().

        Returns:
            Dict with structure: {year: {month: [week_info, ...]}}
        """
        return self.week_repo.get_weeks_tree()

    def get_week_data(self, week_id: int) -> Optional[Dict[str, Any]]:
        """
        Get week data with assignments including participant names.

        Delegates to WeekRepository.get_week_data().

        Args:
            week_id: ID of the week

        Returns:
            Dict with 'week' and 'assignments' keys, or None if not found
        """
        return self.week_repo.get_week_data(week_id)

    def get_week_conflicts(self, week_id: int) -> List[int]:
        """
        Get participant IDs that appear more than once in a week.

        Delegates to AssignmentRepository.get_conflicts().

        Args:
            week_id: ID of the week

        Returns:
            List of participant IDs with conflicts
        """
        return self.assignment_repo.get_conflicts(week_id)

    def has_assignments(self, week_id: int) -> bool:
        """
        Check if a week has any assignments with participants.

        Delegates to AssignmentRepository.has_assignments().

        Args:
            week_id: ID of the week

        Returns:
            True if week has assignments, False otherwise
        """
        return self.assignment_repo.has_assignments(week_id)

    def get_participant_history(self, participant_id: int) -> List[Dict[str, Any]]:
        """
        Get assignment history for a participant.

        Delegates to AssignmentRepository.get_participant_history().

        Args:
            participant_id: ID of the participant

        Returns:
            List of assignment history records
        """
        return self.assignment_repo.get_participant_history(participant_id)
