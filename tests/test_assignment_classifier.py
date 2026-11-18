"""Tests for AssignmentClassifier."""

import unittest

from core.assignment_classifier import (
    SECTION_CBS,
    SECTION_FIXED,
    SECTION_LIVING,
    SECTION_MINISTRY,
    SECTION_TREASURES,
    AssignmentClassifier,
)


class TestAssignmentClassifier(unittest.TestCase):
    """Test cases for assignment classification logic."""

    def setUp(self):
        self.classifier = AssignmentClassifier()
        self.sample_assignments = [
            {
                "id": 1,
                "section": "fixed",
                "section_position": "chairman",
                "assignment_type": "role",
                "assignment_number": "chairman",
                "assignment_text": "Председатель",
                "status": "unassigned",
            },
            {
                "id": 2,
                "section": "fixed",
                "section_position": "prayer_open",
                "assignment_type": "role",
                "assignment_number": "prayer_open",
                "assignment_text": "Молитва (открытие)",
                "status": "unassigned",
            },
            {
                "id": 3,
                "assignment_type": "treasures_talk",
                "assignment_number": "1",
                "assignment_text": "1. Сокровища",
                "status": "unassigned",
            },
            {
                "id": 4,
                "assignment_type": "gems",
                "assignment_number": "2",
                "assignment_text": "2. Жемчужины",
                "status": "unassigned",
            },
            {
                "id": 5,
                "assignment_type": "reading",
                "assignment_number": "3",
                "assignment_text": "3. Чтение Библии",
                "status": "unassigned",
            },
            {
                "id": 6,
                "assignment_type": "student",
                "assignment_number": "4",
                "assignment_text": "4. Задание",
                "status": "unassigned",
            },
            {
                "id": 7,
                "assignment_type": "teaching",
                "assignment_number": "5",
                "assignment_text": "5. Речь",
                "status": "unassigned",
            },
            {
                "id": 8,
                "assignment_type": "student",
                "assignment_number": "6",
                "assignment_text": "6. Задание 2",
                "status": "unassigned",
            },
            {
                "id": 9,
                "assignment_type": "living",
                "assignment_number": "8",
                "assignment_text": "8. Часть ХЖС",
                "status": "unassigned",
            },
            {
                "id": 10,
                "assignment_type": "living",
                "assignment_number": "9",
                "assignment_text": "9. Часть ХЖС 2",
                "status": "unassigned",
            },
            {
                "id": 11,
                "assignment_type": "cbs",
                "assignment_number": "10",
                "assignment_text": "10. Изучение Библии",
                "status": "unassigned",
            },
            {
                "id": 12,
                "assignment_type": "cbs_reader",
                "assignment_number": "10_reader",
                "assignment_text": "Чтец",
                "status": "unassigned",
            },
        ]

    def test_classify_returns_all_sections(self):
        sections = self.classifier.classify(self.sample_assignments)
        self.assertIn(SECTION_FIXED, sections)
        self.assertIn(SECTION_TREASURES, sections)
        self.assertIn(SECTION_MINISTRY, sections)
        self.assertIn(SECTION_LIVING, sections)
        self.assertIn(SECTION_CBS, sections)

    def test_fixed_section_filtering(self):
        sections = self.classifier.classify(self.sample_assignments)
        fixed = sections[SECTION_FIXED]
        self.assertEqual(len(fixed), 2)
        positions = {a["section_position"] for a in fixed}
        self.assertIn("chairman", positions)
        self.assertIn("prayer_open", positions)

    def test_treasures_section_filtering(self):
        sections = self.classifier.classify(self.sample_assignments)
        treasures = sections[SECTION_TREASURES]
        self.assertEqual(len(treasures), 3)
        numbers = [a["assignment_number"] for a in treasures]
        self.assertEqual(numbers, ["1", "2", "3"])

    def test_ministry_section_filtering(self):
        sections = self.classifier.classify(self.sample_assignments)
        ministry = sections[SECTION_MINISTRY]
        self.assertEqual(len(ministry), 3)
        numbers = [a["assignment_number"] for a in ministry]
        self.assertEqual(numbers, ["4", "5", "6"])

    def test_living_section_filtering(self):
        sections = self.classifier.classify(self.sample_assignments)
        living = sections[SECTION_LIVING]
        self.assertEqual(len(living), 2)
        numbers = [a["assignment_number"] for a in living]
        self.assertEqual(numbers, ["8", "9"])

    def test_cbs_section_filtering(self):
        sections = self.classifier.classify(self.sample_assignments)
        cbs = sections[SECTION_CBS]
        self.assertEqual(len(cbs), 2)
        types = {a["assignment_type"] for a in cbs}
        self.assertIn("cbs", types)
        self.assertIn("cbs_reader", types)

    def test_disabled_assignments_excluded(self):
        assignments = self.sample_assignments.copy()
        assignments[2]["status"] = "disabled"  # treasures item
        sections = self.classifier.classify(assignments)
        treasures = sections[SECTION_TREASURES]
        self.assertEqual(len(treasures), 2)

    def test_fallback_type_classification(self):
        """Test that assignments with None/empty type are classified by number."""
        assignments = [
            {
                "id": 1,
                "assignment_type": None,
                "assignment_number": "1",
                "assignment_text": "Item 1",
                "status": "unassigned",
            },
            {
                "id": 2,
                "assignment_type": "",
                "assignment_number": "4",
                "assignment_text": "Item 4",
                "status": "unassigned",
            },
            {
                "id": 3,
                "assignment_type": None,
                "assignment_number": "8",
                "assignment_text": "Item 8",
                "status": "unassigned",
            },
            {
                "id": 4,
                "assignment_type": None,
                "assignment_number": "10",
                "assignment_text": "Item 10",
                "status": "unassigned",
            },
        ]
        sections = self.classifier.classify(assignments)
        self.assertEqual(len(sections[SECTION_TREASURES]), 1)
        self.assertEqual(len(sections[SECTION_MINISTRY]), 1)
        self.assertEqual(len(sections[SECTION_LIVING]), 1)
        self.assertEqual(len(sections[SECTION_CBS]), 1)

    def test_custom_assignment_uses_selected_section(self):
        custom = {
            "id": 99,
            "section": "living",
            "section_position": "custom_9",
            "assignment_type": "custom",
            "assignment_number": "9",
            "assignment_text": "Внеочередной пункт",
            "status": "unassigned",
        }

        sections = self.classifier.classify([custom])

        self.assertEqual(sections[SECTION_LIVING], [custom])
        self.assertEqual(sections[SECTION_MINISTRY], [])
        self.assertEqual(sections[SECTION_CBS], [])

    def test_custom_number_is_sorted_after_standard_living_item(self):
        standard = {
            "id": 1,
            "section": "living",
            "assignment_type": "living",
            "assignment_number": "8",
            "status": "unassigned",
        }
        custom = {
            "id": 2,
            "section": "living",
            "section_position": "custom_10",
            "assignment_type": "custom",
            "assignment_number": "10",
            "status": "unassigned",
        }

        living = self.classifier.classify([custom, standard])[SECTION_LIVING]

        self.assertEqual([item["id"] for item in living], [1, 2])

    def test_needs_assistant_student_type(self):
        assignment = {"assignment_type": "student", "assignment_number": "4"}
        self.assertTrue(self.classifier.needs_assistant(assignment))

    def test_needs_assistant_fallback_number(self):
        assignment = {"assignment_type": "", "assignment_number": "5"}
        self.assertTrue(self.classifier.needs_assistant(assignment))

    def test_needs_assistant_not_needed(self):
        assignment = {"assignment_type": "treasures_talk", "assignment_number": "1"}
        self.assertFalse(self.classifier.needs_assistant(assignment))

    def test_needs_assistant_false_for_discussion_marker(self):
        # Пункт-обсуждение («(N мин.) Обсуждение») — одна ячейка, без напарника
        assignment = {
            "assignment_type": "student",
            "assignment_number": "6",
            "discussion_marker": "(6 мин.) Обсуждение",
        }
        self.assertFalse(self.classifier.needs_assistant(assignment))

    def test_needs_assistant_true_when_no_marker(self):
        # Без маркера обычный student → напарник нужен
        assignment = {"assignment_type": "student", "assignment_number": "6"}
        self.assertTrue(self.classifier.needs_assistant(assignment))

    def test_strip_leading_number(self):
        self.assertEqual(
            AssignmentClassifier.strip_leading_number("4. Начинайте разговор", "4"),
            "Начинайте разговор",
        )
        self.assertEqual(
            AssignmentClassifier.strip_leading_number("4 Начинайте разговор", "4"),
            "Начинайте разговор",
        )
        self.assertEqual(
            AssignmentClassifier.strip_leading_number("Начинайте разговор", "4"),
            "Начинайте разговор",
        )
        self.assertEqual(AssignmentClassifier.strip_leading_number("", "4"), "")


if __name__ == "__main__":
    unittest.main()
