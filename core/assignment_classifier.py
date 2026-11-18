"""
Assignment classifier for schedule sections.

Extracts business logic from ScheduleView for classifying assignments
into sections (fixed, treasures, ministry, living, cbs).

Reference: spec://services/assignment_classification
"""

from typing import Any, Dict, List

SECTION_FIXED = "fixed"
SECTION_TREASURES = "treasures"
SECTION_MINISTRY = "ministry"
SECTION_LIVING = "living"
SECTION_CBS = "cbs"

TREASURES_TYPES = {"treasures", "gems", "reading", "treasures_talk", "bible_reading"}
MINISTRY_TYPES = {"student", "teaching", "chairman_talk"}
LIVING_TYPES = {"living"}
CBS_TYPES = {"cbs", "cbs_reader"}

TREASURES_NUMBERS = {"1", "2", "3"}
MINISTRY_NUMBERS = {"4", "5", "6", "7"}
LIVING_NUMBERS = {"8", "9"}
CBS_NUMBERS = {"10", "10_reader"}

FALLBACK_TYPES = {None, ""}


def _assignment_sort_key(assignment: Dict[str, Any]):
    value = str(assignment.get("assignment_number") or "")
    digits = ""
    for character in value:
        if not character.isdigit():
            break
        digits += character
    return (int(digits) if digits else 10**9, value)


class AssignmentClassifier:
    """Classifies assignments into schedule sections.

    Extracts the filtering logic from ScheduleView._load_week_form()
    into a testable, reusable service.

    Usage:
        classifier = AssignmentClassifier()
        sections = classifier.classify(assignments)

        for section_name, items in sections.items():
            # section_name: "fixed", "treasures", "ministry", "living", "cbs"
            # items: list of assignment dicts
    """

    def classify(self, assignments: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Classify assignments into sections.

        Args:
            assignments: List of assignment dicts from get_week_data()

        Returns:
            Dict mapping section names to lists of assignments.
            Keys: "fixed", "treasures", "ministry", "living", "cbs"
        """
        active = [a for a in assignments if a.get("status") != "disabled"]

        return {
            SECTION_FIXED: self._filter_fixed(active),
            SECTION_TREASURES: self._filter_treasures(active),
            SECTION_MINISTRY: self._filter_ministry(active),
            SECTION_LIVING: self._filter_living(active),
            SECTION_CBS: self._filter_cbs(active),
        }

    def _filter_fixed(self, assignments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter fixed role assignments (chairman, prayers)."""
        fixed_keys = {"chairman", "prayer_open", "prayer_close"}
        return [
            a
            for a in assignments
            if a.get("section") == SECTION_FIXED or str(a.get("section_position", "")) in fixed_keys
        ]

    def _filter_treasures(self, assignments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter treasures section assignments."""
        items = [
            a
            for a in assignments
            if a.get("section") == SECTION_TREASURES
            or a.get("assignment_type") in TREASURES_TYPES
            or (
                a.get("assignment_number") in TREASURES_NUMBERS
                and a.get("assignment_type") in FALLBACK_TYPES
            )
        ]
        items.sort(key=_assignment_sort_key)
        return items

    def _filter_ministry(self, assignments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter ministry section assignments."""
        items = [
            a
            for a in assignments
            if a.get("section") == SECTION_MINISTRY
            or a.get("assignment_type") in MINISTRY_TYPES
            or (
                a.get("assignment_number") in MINISTRY_NUMBERS
                and a.get("assignment_type") in FALLBACK_TYPES
            )
        ]
        items.sort(key=_assignment_sort_key)
        return items

    def _filter_living(self, assignments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter living section assignments."""
        items = [
            a
            for a in assignments
            if a.get("section") == SECTION_LIVING
            or a.get("assignment_type") in LIVING_TYPES
            or (
                a.get("assignment_number") in LIVING_NUMBERS
                and a.get("assignment_type") in FALLBACK_TYPES
            )
        ]
        items.sort(key=_assignment_sort_key)
        return items

    def _filter_cbs(self, assignments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter CBS (Congregation Bible Study) assignments."""
        items = [
            a
            for a in assignments
            if a.get("section") == SECTION_CBS
            or a.get("assignment_type") in CBS_TYPES
            or (
                a.get("assignment_number") in CBS_NUMBERS
                and a.get("assignment_type") in FALLBACK_TYPES
            )
        ]
        return items

    def needs_assistant(self, assignment: Dict[str, Any]) -> bool:
        """Check if an assignment needs an assistant.

        Args:
            assignment: Assignment dict

        Returns:
            True if the assignment needs an assistant
        """
        # Пункт-обсуждение (marcer "(N мин.) Обсуждение" в EPUB-теле) —
        # ведёт один брат, напарника нет.
        if assignment.get("discussion_marker"):
            return False
        atype = assignment.get("assignment_type")
        if atype == "student":
            return True
        anum = assignment.get("assignment_number", "")
        if anum in MINISTRY_NUMBERS and assignment.get("assignment_type") in FALLBACK_TYPES:
            return True
        return False

    @staticmethod
    def strip_leading_number(text: str, num: str) -> str:
        """Remove duplicate leading number from assignment text.

        If assignment_text='4. Start conversation' and num='4',
        returns 'Start conversation' (without duplicate '4. 4. ...')
        """
        if not text:
            return ""
        prefix = f"{num}."
        prefix_space = f"{num} "
        if text.startswith(prefix) or text.startswith(prefix_space):
            return text[len(prefix) :].strip()
        return text.strip()
