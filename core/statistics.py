"""Статистика выступлений для вкладки «Статистика».

Без Qt: только выборка из БД и группировка, чтобы её можно было тестировать
и использовать в мобильной версии.
"""

from collections import Counter
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, select

from core.models import Assignment, AssignmentStatus, Participant, Week
from core.i18n import _

# Порядок категорий — он же порядок в легенде и в полосах нагрузки
CATEGORIES = ["chairman", "treasures", "ministry", "living", "cbs", "assistant", "prayer"]

CATEGORY_NAMES = {
    "chairman": _("Председатель"),
    "treasures": _("Сокровища"),
    "ministry": _("Оттачиваем навыки"),
    "living": _("Христианская жизнь"),
    "cbs": _("Изучение Библии"),
    "assistant": _("Напарник"),
    "prayer": _("Молитва"),
}

# Группы фильтра: (подпись, условие на участника)
GROUPS = {
    "all": _("Все"),
    "E": _("Старейшины"),
    "MS": _("Служебные помощники"),
    "PUB": _("Возвещатели"),
    "male": _("Братья"),
    "female": _("Сёстры"),
}


def category(section: Optional[str], position: Any, is_assistant: bool) -> Optional[str]:
    """Категория выступления для цвета на графиках."""
    if is_assistant:
        return "assistant"
    pos = str(position or "")
    if section == "fixed":
        if pos.startswith("prayer"):
            return "prayer"
        if pos == "chairman":
            return "chairman"
        return None
    if section in ("treasures", "ministry", "living", "cbs"):
        return section
    return None


def _in_group(p: Participant, group: str) -> bool:
    if group == "all":
        return True
    if group in ("male", "female"):
        return p.gender == group
    st = p.service_type or ""
    if group == "E":
        return st in ("E", "elder")
    if group == "PUB":
        return st not in ("E", "elder", "MS")
    return st == group


def assignment_stats(session, start: date, end: date, group: str = "all") -> Dict[str, Any]:
    """Выступления за период [start, end].

    Возвращает:
      weeks — даты начала недель периода (по порядку);
      people — [{id, name, weeks: {date: [категории]}, counts: {категория: n}, total}],
               включая активных участников без заданий (total = 0).
    """
    weeks: List[date] = list(
        session.execute(
            select(Week.start_date)
            .where(and_(Week.start_date >= start, Week.start_date <= end))
            .order_by(Week.start_date)
        ).scalars()
    )

    rows = session.execute(
        select(
            Assignment.participant_id,
            Assignment.assistant_id,
            Assignment.section,
            Assignment.section_position,
            Week.start_date,
        )
        .join(Week, Assignment.week_id == Week.id)
        .where(
            and_(
                Assignment.status == AssignmentStatus.ASSIGNED.value,
                Week.start_date >= start,
                Week.start_date <= end,
            )
        )
    ).all()

    by_person: Dict[int, Dict[date, List[str]]] = {}
    for pid, aid, sec, pos, wk in rows:
        for person, is_asst in ((pid, False), (aid, True)):
            if not person:
                continue
            cat = category(sec, pos, is_asst)
            if cat:
                by_person.setdefault(person, {}).setdefault(wk, []).append(cat)

    participants = session.execute(select(Participant)).scalars().all()
    people = []
    for p in participants:
        if not _in_group(p, group):
            continue
        p_weeks = by_person.get(p.id, {})
        if not p_weeks and not p.is_active:
            continue  # неактивные без выступлений в периоде не нужны
        for cats in p_weeks.values():
            cats.sort(key=CATEGORIES.index)
        counts = Counter(c for cats in p_weeks.values() for c in cats)
        people.append(
            {
                "id": p.id,
                "name": p.name,
                "weeks": p_weeks,
                "counts": dict(counts),
                "total": sum(counts.values()),
            }
        )

    people.sort(key=lambda r: r["name"])
    return {"weeks": weeks, "people": people}
