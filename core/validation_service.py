"""
Validation Service for NHJS.
Centralizes logic for validating assignments, sections, and numbers.
This prevents logic duplication between Parser, UI, and Database.
"""


class ValidationService:
    # Определяем допустимые номера заданий для каждого раздела
    # Номер 7 разрешён в ministry (задание "Речь") и в living (вариативные пункты)
    # Это связано с разной структурой недель в EPUB
    SECTION_RULES = {
        "treasures": ["1", "2", "3"],
        "ministry": ["4", "5", "6", "7"],
        "living": ["7", "8", "9", "10", "11", "12", "13", "14", "15"],
    }

    @staticmethod
    def is_valid_assignment(section, number):
        """
        Проверяет, может ли задание с таким номером находиться в данном разделе.
        example: is_valid_assignment('treasures', '7') -> False
        """
        if not section or not number:
            return False

        # Нормализация
        section = section.lower()
        if section not in ValidationService.SECTION_RULES:
            return False

        valid_numbers = ValidationService.SECTION_RULES[section]

        # Для Life раздела допускаем виртуальные номера LX
        if section == "living" and str(number).startswith("L"):
            return True

        return str(number) in valid_numbers

    @staticmethod
    def identify_section(text):
        """
        Определяет тип раздела по заголовку H2.
        """
        if not text:
            return None
        text_lower = text.lower()

        if "сокровища" in text_lower or "treasures from god's word" in text_lower.replace("’", "'"):
            return "treasures"
        if (
            "оттачиваем" in text_lower
            or "служения" in text_lower
            or "apply yourself to the field ministry" in text_lower
        ):
            return "ministry"
        if "христианская жизнь" in text_lower or "living as christians" in text_lower:
            return "living"
        return None
