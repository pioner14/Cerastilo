"""
Data Transfer Objects (DTOs) for NHJS Scheduler.

DTOs are immutable data contracts that define the structure of data
passed between layers (Database → Services → UI).

This eliminates KeyError/AttributeError issues by ensuring all layers
use the same, well-defined data structures.

See: spec://domain/dto
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from enum import Enum


class Gender(str, Enum):
    """Gender enumeration."""

    MALE = "male"
    FEMALE = "female"


class ServiceType(str, Enum):
    """Service type enumeration."""

    ELDER = "E"
    MINISTERIAL_SERVANT = "MS"
    PUBLISHER = "PUB"
    REGULAR_PIONEER = "RP"
    AUXILIARY_PIONEER = "AP"


from core.domain.entities import AssignmentStatus  # noqa: E402,F401  (единое определение)


class MeetingType(str, Enum):
    """Meeting type enumeration."""

    MIDWEEK = "midweek"
    WEEKEND = "weekend"


class SpecialEventType(str, Enum):
    """Special event type enumeration."""

    MEMORIAL = "memorial"
    CIRCUIT_ASSEMBLY = "circuit_assembly"
    REGIONAL_CONVENTION = "regional_convention"


@dataclass(frozen=True)
class ParticipantDTO:
    """
    Immutable data contract for participant information.

    Attributes:
        id: Unique participant identifier
        name: Full name
        gender: Gender (male/female)
        service_type: Spiritual status (E/MS/PUB/etc.)
        family_group_id: Family group identifier (head of family)
        is_active: Active participant flag
        last_assignment_date: Date of last assignment
        total_assignments: Total number of assignments
        qualifications: List of qualification names
    """

    id: int
    name: str
    gender: str  # 'male' or 'female'
    service_type: Optional[str]
    family_group_id: Optional[int]
    is_active: bool
    last_assignment_date: Optional[datetime]
    total_assignments: int
    qualifications: List[str]
    last_main_date: Optional[datetime] = None  # Дата последней роли ГЛАВНОГО (не напарника)
    personal_gap: Optional[int] = None  # NULL=авто, 0=всегда доступен, N=раз в N нед.
    is_minor: bool = False  # Несовершеннолетний участник
    unavailable_from: Optional[date] = None  # Временно недоступен с
    unavailable_to: Optional[date] = None  # Временно недоступен по
    email: Optional[str] = None  # Email для уведомлений
    phone: Optional[str] = None  # Номер телефона

    @property
    def is_brother(self) -> bool:
        """Check if participant is male."""
        return self.gender == Gender.MALE.value

    @property
    def is_elder(self) -> bool:
        """Check if participant is elder."""
        return self.service_type == ServiceType.ELDER.value

    @property
    def is_ministerial_servant(self) -> bool:
        """Check if participant is ministerial servant."""
        return self.service_type == ServiceType.MINISTERIAL_SERVANT.value


@dataclass(frozen=True)
class AssignmentDTO:
    """
    Immutable data contract for assignment information.

    Attributes:
        id: Unique assignment identifier
        week_id: Reference to week
        assignment_number: Assignment number (1, 2, 3, etc.)
        assignment_text: Assignment description
        assignment_type: Type of assignment
        section: Section name (treasures/ministry/living/cbs)
        section_position: Position within section
        participant_id: Assigned participant ID
        participant_name: Assigned participant name
        assistant_id: Assistant participant ID
        assistant_name: Assistant participant name
        status: Assignment status
        duration: Duration in minutes
    """

    id: int
    week_id: int
    assignment_number: str
    assignment_text: str
    assignment_type: str
    section: Optional[str]
    section_position: Optional[str]
    participant_id: Optional[int]
    participant_name: Optional[str]
    assistant_id: Optional[int]
    assistant_name: Optional[str]
    status: str
    duration: int


@dataclass(frozen=True)
class WeekDTO:
    """
    Immutable data contract for week information.

    Attributes:
        id: Unique week identifier
        week_title: Week title (e.g., "3-9 марта")
        start_date: Week start date (Monday)
        bible_reading: Bible reading assignment
        month: Month name
        year: Year
        workbook_source: Source workbook file
        special_event: Special event type (if any)
        announcement: Weekly announcement
        songs: Song numbers (comma-separated)
    """

    id: int
    week_title: str
    start_date: Optional[date]
    bible_reading: Optional[str]
    month: Optional[str]
    year: int
    workbook_source: Optional[str]
    special_event: Optional[str]
    announcement: Optional[str]
    songs: Optional[str]

    @property
    def end_date(self) -> Optional[date]:
        """Calculate week end date (Sunday)."""
        if self.start_date:
            from datetime import timedelta

            return self.start_date + timedelta(days=6)
        return None

    @property
    def has_special_event(self) -> bool:
        """Check if week has special event."""
        return bool(self.special_event)


@dataclass(frozen=True)
class AssignmentConfigDTO:
    """
    Immutable data contract for assignment configuration.

    Attributes:
        id: Unique identifier
        section: Section name
        position: Position within section
        assignment_name: Assignment name
        required_qualification: Required qualification name
        is_brothers_only: Only brothers can be assigned
        needs_assistant: Assignment requires assistant
    """

    id: int
    section: str
    position: str
    assignment_name: Optional[str]
    required_qualification: Optional[str]
    is_brothers_only: bool = False
    needs_assistant: bool = False


@dataclass(frozen=True)
class StatisticsDTO:
    """
    DTO for participant statistics.

    Attributes:
        participant_id: Participant ID
        total_assignments: Total assignments count
        assignments_by_type: Dict of assignment type -> count
        last_assignment_date: Date of last assignment
        first_assignment_date: Date of first assignment
        assignments_this_year: Count of assignments this year
    """

    participant_id: int
    total_assignments: int = 0
    assignments_by_type: Dict[str, int] = field(default_factory=dict)
    last_assignment_date: Optional[date] = None
    first_assignment_date: Optional[date] = None
    assignments_this_year: int = 0


@dataclass(frozen=True)
class ConflictDTO:
    """
    DTO for scheduling conflicts.

    Attributes:
        participant_id: Participant ID
        participant_name: Participant name
        week_start: Week start date
        conflict_type: Type of conflict
        conflicting_assignments: List of conflicting assignment descriptions
    """

    participant_id: int
    participant_name: str
    week_start: date
    conflict_type: str
    conflicting_assignments: List[str]
