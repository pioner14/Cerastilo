"""
Mappers for transforming data between different layers.

Mappers convert:
- ORM Entities → DTOs (from database)
- DTOs → UI dictionaries (for backward compatibility)
- DTOs → Domain objects (for business logic)
"""

from typing import List
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from core.dto import ParticipantDTO, AssignmentDTO
from core.models import Participant, Assignment, participant_qualifications, AssignmentStatus


class ParticipantMapper:
    """Transforms participant data between layers."""

    @staticmethod
    def from_db_with_stats(
        session: Session, participant: Participant, total_assignments: int = 0
    ) -> ParticipantDTO:
        """
        Convert ORM Entity + statistics → DTO

        Args:
            session: Active SQLAlchemy session
            participant: Participant ORM entity
            total_assignments: Pre-calculated assignment count

        Returns:
            Immutable ParticipantDTO
        """
        # Load qualifications for this participant
        quals = (
            session.execute(
                select(participant_qualifications.c.qualification_name).where(
                    participant_qualifications.c.participant_id == participant.id
                )
            )
            .scalars()
            .all()
        )

        return ParticipantDTO(
            id=participant.id,
            name=participant.name,
            gender=participant.gender,
            service_type=participant.service_type,
            family_group_id=participant.family_group_id,
            is_active=participant.is_active,
            last_assignment_date=participant.last_assignment_date,
            last_main_date=participant.last_main_date,
            total_assignments=total_assignments,
            qualifications=list(quals),
            personal_gap=participant.personal_gap,
            is_minor=bool(participant.is_minor),
            unavailable_from=participant.unavailable_from,
            unavailable_to=participant.unavailable_to,
            email=participant.email,
            phone=participant.phone,
        )

    @staticmethod
    def to_ui_dict(dto: ParticipantDTO) -> dict:
        """
        Convert DTO → UI format dictionary (backward compatibility)

        This ensures UI gets all expected fields, including legacy ones
        like 'last_assignment_date_real'

        Args:
            dto: ParticipantDTO

        Returns:
            Dictionary with all fields UI expects
        """
        # Форматируем дату для UI в формате DD.MM.YYYY
        date_str = None
        if dto.last_assignment_date:
            date_str = dto.last_assignment_date.strftime("%d.%m.%Y")

        return {
            "id": dto.id,
            "name": dto.name,
            "gender": dto.gender,
            "service_type": dto.service_type,
            "is_active": dto.is_active,
            "last_assignment_date": date_str,
            "last_assignment_date_real": date_str,  # UI compatibility
            "total_assignments": dto.total_assignments,
            "qualifications": dto.qualifications,
            "family_group_id": dto.family_group_id,
            "personal_gap": dto.personal_gap,
            "is_minor": dto.is_minor,
            "unavailable_from": dto.unavailable_from,
            "unavailable_to": dto.unavailable_to,
            "email": dto.email,
            "phone": dto.phone,
        }

    @staticmethod
    def bulk_load_with_stats(session: Session, active_only: bool = True) -> List[ParticipantDTO]:
        """
        Efficiently load all participants with stats in one query (NO N+1)

        Args:
            session: Active SQLAlchemy session
            active_only: Only return active participants

        Returns:
            List of ParticipantDTOs
        """
        # Single query with subquery to count BOTH participant and assistant roles
        # Подсчёт: участник мог быть и основным, и ассистентом
        participant_counts = (
            select(Assignment.participant_id.label("pid"), func.count().label("cnt"))
            .where(Assignment.status == AssignmentStatus.ASSIGNED.value)
            .where(Assignment.participant_id.isnot(None))
            .group_by(Assignment.participant_id)
        ).subquery()

        assistant_counts = (
            select(Assignment.assistant_id.label("pid"), func.count().label("cnt"))
            .where(Assignment.status == AssignmentStatus.ASSIGNED.value)
            .where(Assignment.assistant_id.isnot(None))
            .group_by(Assignment.assistant_id)
        ).subquery()

        query = (
            select(
                Participant,
                (
                    func.coalesce(participant_counts.c.cnt, 0)
                    + func.coalesce(assistant_counts.c.cnt, 0)
                ).label("total"),
            )
            .outerjoin(participant_counts, participant_counts.c.pid == Participant.id)
            .outerjoin(assistant_counts, assistant_counts.c.pid == Participant.id)
        )

        if active_only:
            query = query.where(Participant.is_active == True)

        results = session.execute(query).all()

        # Bulk load all qualifications in ONE query (NO N+1)
        participant_ids = [p.id for p, _ in results]
        if participant_ids:
            quals_query = select(
                participant_qualifications.c.participant_id,
                participant_qualifications.c.qualification_name,
            ).where(participant_qualifications.c.participant_id.in_(participant_ids))

            quals_results = session.execute(quals_query).all()

            # Group qualifications by participant_id
            quals_by_participant = {}
            for p_id, qual_name in quals_results:
                if p_id not in quals_by_participant:
                    quals_by_participant[p_id] = []
                quals_by_participant[p_id].append(qual_name)
        else:
            quals_by_participant = {}

        # Build DTOs
        dtos = []
        for participant, total in results:
            dto = ParticipantDTO(
                id=participant.id,
                name=participant.name,
                gender=participant.gender,
                service_type=participant.service_type,
                family_group_id=participant.family_group_id,
                is_active=participant.is_active,
                last_assignment_date=participant.last_assignment_date,
                last_main_date=participant.last_main_date,
                total_assignments=total,
                qualifications=quals_by_participant.get(participant.id, []),
                personal_gap=participant.personal_gap,
                is_minor=bool(participant.is_minor),
                unavailable_from=participant.unavailable_from,
                unavailable_to=participant.unavailable_to,
                email=participant.email,
                phone=participant.phone,
            )
            dtos.append(dto)

        return dtos


class AssignmentMapper:
    """Transforms assignment data between layers."""

    @staticmethod
    def from_db(
        assignment: Assignment, participant_name: str = None, assistant_name: str = None
    ) -> AssignmentDTO:
        """
        Convert ORM Entity → DTO

        Args:
            assignment: Assignment ORM entity
            participant_name: Optional pre-loaded participant name
            assistant_name: Optional pre-loaded assistant name

        Returns:
            Immutable AssignmentDTO
        """
        return AssignmentDTO(
            id=assignment.id,
            week_id=assignment.week_id,
            assignment_number=assignment.assignment_number,
            assignment_text=assignment.assignment_text,
            assignment_type=assignment.assignment_type,
            section=assignment.section,
            section_position=(
                str(assignment.section_position)
                if assignment.section_position is not None
                else None
            ),
            participant_id=assignment.participant_id,
            participant_name=participant_name,
            assistant_id=assignment.assistant_id,
            assistant_name=assistant_name,
            status=assignment.status,
            duration=assignment.duration,
        )
