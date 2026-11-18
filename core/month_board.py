"""
Доска месяца: недели месяца колонками, пункты программы строками.

Чистая логика без Qt и без базы — данные готовит
BaseApplicationFacade.get_month_board(), рисует ui/month_board_view.py.
"""

from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

from core.assignment_rules import is_student_assignment, needs_slip
from core.chairman_talk import is_role_talk, role_talk_name
from core.week_layout import (
    OTHER_SECTION,
    apply_circuit_overseer_week,
    assignment_label,
    order_week_assignments,
)
from core.i18n import _, tr

# Особые недели, когда встречи по программе нет (неделя РС — обычная встреча)
NO_MEETING_EVENTS = ("memorial", "circuit_assembly", "regional_convention")
EVENT_NAMES = {
    "memorial": _("Вечеря Господня"),
    "circuit_assembly": _("Районный конгресс"),
    "regional_convention": _("Региональный конгресс"),
}
ELDER = "E"

TREASURES_LABELS = (_("Речь «Сокровища»"), _("Духовные жемчужины"), _("Чтение Библии"))
TREASURES_TYPES = ("treasures", "gems", "reading")
FIXED_KEYS = {
    "chairman": _("Председатель"),
    "prayer_open": _("Молитва (начало)"),
    "prayer_close": _("Молитва (конец)"),
}

SlotKey = Tuple[str, int]


def _as_date(value) -> Optional[date]:
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def on_leave(unavailable_from, unavailable_to, week_start: date) -> bool:
    """Неделя с week_start попадает в отпуск «с … по …» из карточки участника
    (то же правило, что в автоназначении: одна граница — открытый период)."""
    if not (unavailable_from or unavailable_to) or week_start is None:
        return False
    week_end = week_start + timedelta(days=6)
    if unavailable_from and week_end < unavailable_from:
        return False
    if unavailable_to and week_start > unavailable_to:
        return False
    return True


def _short_name(name: Optional[str]) -> str:
    """«Тарасюк Тимур» → «Тарасюк Т.»; одно слово остаётся как есть."""
    parts = (name or "").split()
    if len(parts) < 2:
        return name or ""
    return f"{parts[0]} " + " ".join(f"{p[0]}." for p in parts[1:])


def _week_slots(assignments: List[Dict]) -> List[Tuple[SlotKey, Dict]]:
    """Пункты недели с ключом строки доски: (раздел, номер по порядку)."""
    slots = []
    counters: Dict[str, int] = {}
    for section, a in order_week_assignments(assignments):
        if a.get("status") == "disabled":
            continue
        number = str(a.get("assignment_number") or "")
        atype = a.get("assignment_type")
        if number in FIXED_KEYS:
            key = (number, 0)
        elif atype in ("cbs", "circuit_overseer_talk"):
            key = ("cbs", 0)
        elif atype == "cbs_reader":
            key = ("cbs", 1)
        elif section == "treasures" and atype in TREASURES_TYPES:
            key = ("treasures", TREASURES_TYPES.index(atype))
        else:
            if section == "cbs":
                section = OTHER_SECTION
            # прочие пункты «Сокровищ» — после трёх постоянных
            index = counters.get(section, len(TREASURES_TYPES) if section == "treasures" else 0)
            counters[section] = index + 1
            key = (section, index)
        slots.append((key, a))
    return slots


ROW_ORDER = (
    "chairman",
    "prayer_open",
    "treasures",
    "ministry",
    "living",
    "cbs",
    OTHER_SECTION,
    "fixed",
    "prayer_close",
)


def _row_label(key: SlotKey, sample: Dict) -> str:
    section, index = key
    if section in FIXED_KEYS:
        return FIXED_KEYS[section]
    if section == "treasures" and index < len(TREASURES_LABELS):
        return TREASURES_LABELS[index]
    if section == "ministry":
        return _("Служение · {v}", v=index + 1)
    if section == "living":
        return _("Жизнь · {v}", v=index + 1)
    if section == "cbs":
        return _("Изучение Библии") if index == 0 else _("Чтец ИБС")
    return assignment_label(sample.get("assignment_text") or _("Пункт"))


def _notice(info: Optional[Dict]) -> Optional[str]:
    """Статус уведомления человека на неделе: ответ важнее факта отправки."""
    if not info:
        return None
    if info.get("response") in ("confirmed", "declined"):
        return info["response"]
    return {"success": "waiting", "error": "error"}.get(info.get("status"))


def cell_notice(people: List[Dict]) -> Optional[str]:
    """Статус клетки целиком (её заливка): отказ важнее всего; пока кто-то
    не уведомлён — статуса нет; «confirmed» — только если подтвердили все."""
    notices = [p.get("notice") for p in people if p.get("id")]
    if not notices:
        return None
    if "declined" in notices:
        return "declined"
    if any(n in (None, "error") for n in notices):
        return None
    return "confirmed" if all(n == "confirmed" for n in notices) else "waiting"


def build_month_board(
    weeks: List[Dict],
    history: Iterable[Tuple[int, object]],
    elder_ids: Iterable[int] = (),
    conflicts: Optional[Dict[int, Iterable[int]]] = None,
    notifications: Optional[Dict[int, Dict[int, Dict]]] = None,
    away: Optional[Dict[int, Iterable[int]]] = None,
) -> Dict:
    """Собрать доску месяца.

    weeks — результаты get_week_data() (dict с 'week' и 'assignments'),
    history — все назначения (participant_id, start_date недели), включая
    напарников, elder_ids — старейшины (им «подряд» не отмечается),
    conflicts — {week_id: [participant_id, назначенный дважды за неделю]},
    notifications — {week_id: get_week_notification_statuses(week_id)}; по ним
    у человека "notice": None (не уведомлён), "error", "waiting", "confirmed", "declined",
    away — {week_id: [participant_id в отпуске или с исключённой неделей]}:
    его задание на этой неделе помечается "away" (нужна замена).
    """
    elder_ids = set(elder_ids)
    conflicts = conflicts or {}
    notifications = notifications or {}
    away = away or {}
    dates_by_person: Dict[int, List[date]] = {}
    for pid, start in history:
        start = _as_date(start)
        if pid and start:
            dates_by_person.setdefault(pid, []).append(start)
    busy_weeks = {pid: set(ds) for pid, ds in dates_by_person.items()}

    columns = []
    cells: Dict[Tuple[SlotKey, int], Dict] = {}
    labels: Dict[SlotKey, str] = {}
    summary = {
        "assigned": 0,
        "total": 0,
        "empty": 0,
        "double": 0,
        "consecutive": 0,
        "elder_student": 0,
    }
    notice_summary = {"not_notified": 0, "waiting": 0, "declined": 0}

    for col, data in enumerate(weeks):
        week = dict(data["week"])
        start = _as_date(week.get("start_date"))
        event = week.get("special_event")
        column = {
            "week_id": week.get("id"),
            "title": week.get("week_title") or "",
            "start_date": start,
            "special": (
                EVENT_NAMES.get(event, tr("Особое событие")) if event in NO_MEETING_EVENTS else None
            ),
            "circuit_overseer": event == "circuit_overseer",
        }
        columns.append(column)
        if column["special"]:
            continue

        assignments, _co_note = apply_circuit_overseer_week(week, data.get("assignments") or [])
        week_conflicts = set(conflicts.get(week.get("id"), ()))
        week_away = set(away.get(week.get("id"), ()))
        week_notices = notifications.get(week.get("id")) or {}
        counted = set()  # человек считается в сводке раз за неделю
        column["notice"] = {"not_notified": 0, "waiting": 0, "declined": 0}
        previous_week = start - timedelta(days=7) if start else None

        for key, a in _week_slots(assignments):
            labels.setdefault(key, _row_label(key, a))
            people = []
            flags = set()
            student = is_student_assignment(a)
            for pid, name, role in (
                (a.get("participant_id"), a.get("participant_name"), "main"),
                (a.get("assistant_id"), a.get("assistant_name"), "assistant"),
            ):
                if not pid and not (role == "main" and name):
                    continue
                earlier = [d for d in dates_by_person.get(pid, ()) if start and d < start]
                weeks_since = (start - max(earlier)).days // 7 if earlier else None
                elder = pid in elder_ids
                person_flags = set()
                if pid in week_conflicts:
                    person_flags.add("double")
                if pid and not elder and previous_week in busy_weeks.get(pid, ()):
                    person_flags.add("consecutive")
                if elder and student:
                    person_flags.add("elder_student")
                if pid and pid in week_away:
                    person_flags.add("away")
                flags |= person_flags
                info = week_notices.get(pid) if pid else None
                notice = _notice(info)
                if notice == "declined":
                    flags.add("declined")
                if pid and pid not in counted:
                    counted.add(pid)
                    key_name = {None: "not_notified", "error": "not_notified"}.get(notice, notice)
                    if key_name in column["notice"]:
                        column["notice"][key_name] += 1
                        notice_summary[key_name] += 1
                people.append(
                    {
                        "id": pid,
                        "name": name or "",
                        "short": _short_name(name),
                        "role": role,
                        "weeks_since": weeks_since if pid else None,
                        "elder": elder,
                        "flags": sorted(person_flags),
                        "notice": notice,
                        "sent_at": (info or {}).get("sent_at"),
                    }
                )
            filled = any(p["role"] == "main" for p in people)
            if not filled:
                flags.add("empty")
            summary["total"] += 1
            summary["assigned"] += 1 if filled else 0
            for flag in ("empty", "double", "consecutive", "elder_student"):
                if flag in flags:
                    summary[flag] += 1
            cells[(key, col)] = {
                "assignment_id": a.get("id"),
                "text": (
                    _(role_talk_name(a))
                    if is_role_talk(a)
                    else assignment_label(a.get("assignment_text") or "")
                ),
                "people": people,
                "flags": sorted(flags),
                "notice": cell_notice(people),
                # «🧾 листок выдан» — только у заполненного пункта
                "slip": bool(a.get("slip_given_at")) and bool(people),
            }
            if people and needs_slip(a):  # листок — только учебным заданиям
                column["slips_total"] = column.get("slips_total", 0) + 1
                if cells[(key, col)]["slip"]:
                    column["slips_given"] = column.get("slips_given", 0) + 1

    keys = sorted(
        labels, key=lambda k: (ROW_ORDER.index(k[0]) if k[0] in ROW_ORDER else len(ROW_ORDER), k[1])
    )
    rows = [{"key": k, "label": labels[k], "section": k[0]} for k in keys]
    grid = [[cells.get((row["key"], col)) for col in range(len(columns))] for row in rows]
    return {
        "columns": columns,
        "rows": rows,
        "cells": grid,
        "summary": summary,
        "notice_summary": notice_summary,
    }


# «Проверка месяца»: что показать по флагу человека и клетки
_PERSON_PROBLEMS = {
    "away": _("не будет на встрече — нужна замена"),
    "double": _("назначен дважды за неделю"),
    "consecutive": _("задание две недели подряд"),
    "elder_student": _("старейшина на учебном задании"),
}


def month_problems(board: Dict, unsuitable: Iterable[Tuple[int, int]] = ()) -> List[Dict]:
    """Список проблем доски месяца для «Проверить месяц» — по неделям, сверху вниз.

    unsuitable — пары (assignment_id, participant_id): человек не подходит пункту
    по полу, квалификации или статусу (считает интерфейс через кандидатов).
    Каждая проблема: {"row", "col", "kind", "text"}.
    """
    unsuitable = set(unsuitable)
    columns, rows = board.get("columns", []), board.get("rows", [])
    problems = []
    for col, column in enumerate(columns):
        if column.get("special"):
            continue
        when = (
            column["start_date"].strftime("%d.%m")
            if column.get("start_date")
            else column.get("title", "")
        )
        for row_index, row in enumerate(rows):
            cell = board["cells"][row_index][col]
            if cell is None:
                continue
            where = f"{when} · {row['label']}"

            def add(kind, message, row_index=row_index, where=where):
                problems.append(
                    {"row": row_index, "col": col, "kind": kind, "text": f"{where}: {message}"}
                )

            if "empty" in cell["flags"]:
                add("empty", _("пусто"))
            for person in cell["people"]:
                if not person.get("id"):
                    continue
                name = person["short"] + (_(" (напарник)") if person["role"] == "assistant" else "")
                if person.get("notice") == "declined":
                    add("declined", _("{name} — ответил: не сможет", name=name))
                for flag in ("away", "double", "consecutive", "elder_student"):
                    if flag in person["flags"]:
                        add(flag, f"{name} — {_PERSON_PROBLEMS[flag]}")
                if (cell.get("assignment_id"), person["id"]) in unsuitable:
                    add(
                        "unsuitable",
                        _("{name} — не подходит (пол, квалификация или статус)", name=name),
                    )
    return problems
