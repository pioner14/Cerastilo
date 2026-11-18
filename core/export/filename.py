# core/export/filename.py
"""Имя файла расписания по умолчанию при экспорте (PDF, Word, TXT):
«Декабрь 2026 Встреча «Христианская жизнь и служение» 13.11.2026»."""

from datetime import date, datetime
from typing import Optional, Union

from core.i18n import _, language

DateLike = Union[date, datetime, str, None]


def month_names() -> dict:
    return {
        1: _("Январь"),
        2: _("Февраль"),
        3: _("Март"),
        4: _("Апрель"),
        5: _("Май"),
        6: _("Июнь"),
        7: _("Июль"),
        8: _("Август"),
        9: _("Сентябрь"),
        10: _("Октябрь"),
        11: _("Ноябрь"),
        12: _("Декабрь"),
    }


def format_output_date(value: date) -> str:
    """Дата для бланков и уведомлений без зависимости от системной локали."""
    if language() == "en":
        return f"{month_names()[value.month]} {value.day}, {value.year}"
    return value.strftime("%d.%m.%Y")


def _as_date(value: DateLike) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return None
    return None


def schedule_base_name(first: DateLike, last: DateLike, today: Optional[date] = None) -> str:
    """Имя без расширения. Месяц(ы) и год — по выбранным неделям, в конце —
    дата экспорта. Недели двух месяцев: «Ноябрь–Декабрь 2026 …», через год:
    «Декабрь 2026–Январь 2027 …»."""
    title = _("Встреча «Христианская жизнь и служение»")
    stamp = (today or date.today()).strftime("%d.%m.%Y" if language() == "ru" else "%Y-%m-%d")
    start, end = _as_date(first), _as_date(last)
    if not start:
        return f"{title} {stamp}"
    end = end or start
    months = month_names()
    if (start.year, start.month) == (end.year, end.month):
        period = f"{months[start.month]} {start.year}"
    elif start.year == end.year:
        period = f"{months[start.month]}–{months[end.month]} {start.year}"
    else:
        period = f"{months[start.month]} {start.year}–{months[end.month]} {end.year}"
    return f"{period} {title} {stamp}"
