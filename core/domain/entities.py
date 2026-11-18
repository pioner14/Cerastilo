"""
Domain Entities for NHJS Scheduler.

Domain entities contain business logic and are independent of frameworks.
They don't inherit from SQLAlchemy Base or contain UI-specific code.

See: spec://domain/entities
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional, List, Dict, Set
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


class AssignmentStatus(str, Enum):
    """Assignment status enumeration."""

    ASSIGNED = "assigned"
    UNASSIGNED = "unassigned"
    DISABLED = "disabled"
    EMPTY = "empty"

    @classmethod
    def from_string(cls, value: str) -> "AssignmentStatus":
        """Конвертировать строку в Enum, возвращать UNASSIGNED по умолчанию."""
        try:
            return cls(value)
        except ValueError:
            return cls.UNASSIGNED


class Section(str, Enum):
    """Meeting section enumeration."""

    FIXED = "fixed"
    TREASURES = "treasures"
    MINISTRY = "ministry"
    LIVING = "living"
    CBS = "cbs"


@dataclass
class Qualification:
    """
    Qualification entity.

    Represents a skill or privilege a participant can have.
    """

    name: str
    display_name: str
    is_brothers_only: bool = False
    description: Optional[str] = None

    # Business logic
    def can_assign_to(self, participant: "Participant") -> bool:
        """Check if participant can be assigned to this qualification."""
        if self.is_brothers_only and participant.gender != Gender.MALE:
            return False
        return participant.is_active


@dataclass
class Participant:
    """
    Participant domain entity.

    Contains business logic for participant-related operations.
    Independent of ORM and UI.
    """

    id: int
    name: str
    gender: str
    service_type: str
    family_group_id: Optional[int] = None
    is_active: bool = True
    last_assignment_date: Optional[datetime] = None
    created_at: Optional[datetime] = None
    qualifications: Set[str] = field(default_factory=set)

    # Business logic properties
    @property
    def is_brother(self) -> bool:
        """Check if participant is male."""
        return self.gender == Gender.MALE.value

    @property
    def is_sister(self) -> bool:
        """Check if participant is female."""
        return self.gender == Gender.FEMALE.value

    @property
    def is_elder(self) -> bool:
        """Check if participant is elder."""
        return self.service_type == ServiceType.ELDER.value

    @property
    def is_ministerial_servant(self) -> bool:
        """Check if participant is ministerial servant."""
        return self.service_type == ServiceType.MINISTERIAL_SERVANT.value

    @property
    def is_pioneer(self) -> bool:
        """Check if participant is pioneer."""
        return self.service_type in [
            ServiceType.REGULAR_PIONEER.value,
            ServiceType.AUXILIARY_PIONEER.value,
        ]

    @property
    def can_serve_as_chairman(self) -> bool:
        """Check if participant can serve as chairman."""
        return self.is_active and self.is_brother and "chairman" in self.qualifications

    def has_qualification(self, qual_name: str) -> bool:
        """Check if participant has specific qualification."""
        return qual_name in self.qualifications

    def add_qualification(self, qual_name: str) -> None:
        """Add qualification to participant."""
        self.qualifications.add(qual_name)

    def remove_qualification(self, qual_name: str) -> None:
        """Remove qualification from participant."""
        self.qualifications.discard(qual_name)

    def can_be_assigned_to(self, config: "AssignmentConfig") -> bool:
        """
        Check if participant can be assigned to specific assignment.

        Args:
            config: Assignment configuration

        Returns:
            True if participant meets requirements
        """
        if not self.is_active:
            return False

        if config.is_brothers_only and not self.is_brother:
            return False

        if config.required_qualification:
            if not self.has_qualification(config.required_qualification):
                return False

        return True

    def days_since_last_assignment(self, reference_date: Optional[date] = None) -> Optional[int]:
        """
        Calculate days since last assignment.

        Args:
            reference_date: Date to calculate from (default: today)

        Returns:
            Number of days or None if no assignments
        """
        if not self.last_assignment_date:
            return None

        ref = reference_date or date.today()
        last = (
            self.last_assignment_date.date()
            if isinstance(self.last_assignment_date, datetime)
            else self.last_assignment_date
        )
        return (ref - last).days


@dataclass
class Assignment:
    """
    Assignment domain entity.

    Contains business logic for assignment-related operations.
    """

    id: int
    week_id: int
    assignment_number: str
    assignment_text: str
    assignment_type: str
    section: str
    section_position: int
    duration: int = 0
    participant_id: Optional[int] = None
    assistant_id: Optional[int] = None
    status: str = AssignmentStatus.UNASSIGNED.value

    # Business logic properties
    @property
    def is_assigned(self) -> bool:
        """Check if assignment has participant."""
        return self.status == AssignmentStatus.ASSIGNED.value

    @property
    def is_disabled(self) -> bool:
        """Check if assignment is disabled."""
        return self.status == AssignmentStatus.DISABLED.value

    @property
    def needs_assistant(self) -> bool:
        """Check if assignment needs assistant."""
        return self.assignment_type in ["student", "ministry_item"]

    @property
    def is_brothers_only(self) -> bool:
        """Check if assignment is for brothers only."""
        return self.section in [Section.FIXED.value, Section.TREASURES.value, Section.CBS.value]

    def assign_participant(self, participant_id: int) -> None:
        """Assign participant to this assignment."""
        self.participant_id = participant_id
        self.status = AssignmentStatus.ASSIGNED.value

    def assign_assistant(self, assistant_id: int) -> None:
        """Assign assistant to this assignment."""
        self.assistant_id = assistant_id

    def clear_participant(self) -> None:
        """Clear participant assignment."""
        self.participant_id = None
        if self.assistant_id:
            self.assistant_id = None
        self.status = AssignmentStatus.EMPTY.value

    def disable(self) -> None:
        """Disable this assignment."""
        self.status = AssignmentStatus.DISABLED.value
        self.participant_id = None
        self.assistant_id = None

    def enable(self) -> None:
        """Enable this assignment."""
        self.status = AssignmentStatus.UNASSIGNED.value

    def has_conflict_with(self, other: "Assignment") -> bool:
        """
        Check if this assignment conflicts with another.

        Conflicts occur when same participant is assigned to multiple
        assignments in the same week.
        """
        if self.week_id != other.week_id:
            return False

        if self.participant_id and self.participant_id == other.participant_id:
            return True

        if self.assistant_id and self.assistant_id == other.assistant_id:
            return True

        return False


@dataclass
class Week:
    """
    Week domain entity.

    Contains business logic for week-related operations.
    """

    id: int
    week_title: str
    start_date: Optional[date]
    bible_reading: Optional[str] = None
    month: Optional[str] = None
    year: int = 0
    workbook_source: Optional[str] = None
    special_event: Optional[str] = None
    announcement: Optional[str] = None
    songs: Optional[str] = None
    assignments: List[Assignment] = field(default_factory=list)

    # Business logic properties
    @property
    def end_date(self) -> Optional[date]:
        """Calculate week end date (Sunday)."""
        if self.start_date:
            return self.start_date + timedelta(days=6)
        return None

    @property
    def has_special_event(self) -> bool:
        """Check if week has special event."""
        return bool(self.special_event)

    @property
    def is_memorial_week(self) -> bool:
        """Check if this is Memorial week."""
        return self.special_event == SpecialEventType.MEMORIAL.value

    @property
    def assignment_count(self) -> int:
        """Get number of assignments."""
        return len(self.assignments)

    @property
    def assigned_count(self) -> int:
        """Get number of assigned assignments."""
        return sum(1 for a in self.assignments if a.is_assigned)

    @property
    def completion_percentage(self) -> float:
        """Calculate completion percentage."""
        if not self.assignments:
            return 0.0
        return (self.assigned_count / self.assignment_count) * 100

    def get_assignment_by_number(self, number: str) -> Optional[Assignment]:
        """Get assignment by number."""
        for assignment in self.assignments:
            if assignment.assignment_number == number:
                return assignment
        return None

    def get_assignments_by_section(self, section: str) -> List[Assignment]:
        """Get all assignments for a section."""
        return [a for a in self.assignments if a.section == section]

    def get_conflicts(self) -> List[Dict]:
        """
        Find conflicts in this week's assignments.

        Returns:
            List of conflict dictionaries with participant info
        """
        conflicts = []
        participant_assignments: Dict[int, List[Assignment]] = {}

        for assignment in self.assignments:
            if assignment.participant_id:
                if assignment.participant_id not in participant_assignments:
                    participant_assignments[assignment.participant_id] = []
                participant_assignments[assignment.participant_id].append(assignment)

            if assignment.assistant_id:
                if assignment.assistant_id not in participant_assignments:
                    participant_assignments[assignment.assistant_id] = []
                participant_assignments[assignment.assistant_id].append(assignment)

        for p_id, assignments in participant_assignments.items():
            if len(assignments) > 1:
                conflicts.append(
                    {
                        "participant_id": p_id,
                        "assignments": [a.assignment_text for a in assignments],
                        "count": len(assignments),
                    }
                )

        return conflicts

    def is_complete(self) -> bool:
        """Check if all assignments are filled."""
        return self.assigned_count == self.assignment_count

    def can_auto_assign(self) -> bool:
        """Check if week can be auto-assigned."""
        return not self.has_special_event and self.assignment_count > 0


@dataclass
class AssignmentConfig:
    """
    Assignment configuration entity.

    Defines requirements for specific assignment types.
    """

    id: int
    section: str
    position: str
    assignment_name: Optional[str] = None
    required_qualification: Optional[str] = None
    is_brothers_only: bool = False
    needs_assistant: bool = False

    def matches(self, section: str, position: str) -> bool:
        """Check if config matches given section and position."""
        return self.section == section and self.position == position

    def is_compatible_with(self, participant: Participant) -> bool:
        """Check if this config is compatible with participant."""
        if self.is_brothers_only and not participant.is_brother:
            return False

        if self.required_qualification:
            if not participant.has_qualification(self.required_qualification):
                return False

        return participant.is_active


# Import SpecialEventType at the end to avoid circular imports
class SpecialEventType(str, Enum):
    """Special event type enumeration."""

    MEMORIAL = "memorial"
    CIRCUIT_ASSEMBLY = "circuit_assembly"
    REGIONAL_CONVENTION = "regional_convention"
