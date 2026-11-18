"""
Утилиты для работы с датами.

Reference: spec://utils/date_utils
"""

from datetime import date, datetime
from typing import Optional


def date_to_datetime(d: Optional[date]) -> Optional[datetime]:
    """Конвертирует date в datetime для совместимости с Participant.last_assignment_date.

    Args:
        d: Объект date или None

    Returns:
        datetime с временем 00:00:00 или None
    """
    if d is None:
        return None
    return datetime.combine(d, datetime.min.time())


def format_date_for_display(d) -> str:
    """Форматирует дату для отображения в UI.

    Args:
        d: date объект, строка или None

    Returns:
        Строка в формате YYYY-MM-DD или пустая строка
    """
    if d is None:
        return ""
    if hasattr(d, "strftime"):
        # Это date или datetime объект
        return d.strftime("%Y-%m-%d")
    return str(d)
