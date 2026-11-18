"""
Порядок пунктов недели и время их начала — одинаково для таблицы расписания
(ui/schedule_view.py) и для просмотра недели / PDF (core/schedule_preview.py).
"""

import re
from typing import Dict, List, Tuple

from core.i18n import _, language
from core.assignment_rules import is_what_would_you_say
from core.chairman_talk import is_role_talk

SECTION_KEYS = ("fixed", "treasures", "ministry", "living", "cbs")
OTHER_SECTION = "other"
DEFAULT_MEETING_START = 19 * 60


def assignment_label(text: str) -> str:
    """Локализовать служебные подписи и единицу времени в тексте задания."""
    if text in _FIXED_LABELS:
        return _(text)
    if language() == "en":
        return re.sub(r"\((\d+)\s*мин\.?\)", lambda m: _("({n} мин.)", n=m[1]), text)
    return text


_FIXED_LABELS = {
    "Председатель",
    "Молитва (открытие)",
    "Молитва (закрытие)",
    "Чтец (Изучение Библии)",
}


def apply_circuit_overseer_week(week: Dict, assignments: List[Dict]) -> Tuple[List[Dict], bool]:
    """Неделя посещения районного старейшины: вместо Изучения Библии в собрании
    (и без его чтеца) — Служебная речь РС, 30 мин."""
    if week.get("special_event") != "circuit_overseer":
        return assignments, False

    result = []
    cbs_replaced = False
    for a in assignments:
        atype = a.get("assignment_type")
        if atype == "cbs_reader":
            continue
        if atype == "cbs" or a.get("section") == "cbs":
            if not cbs_replaced:
                co_item = dict(a)
                co_item["assignment_text"] = _("Служебная речь РС (30 мин.)")
                co_item["assignment_type"] = "circuit_overseer_talk"
                co_item["section"] = "living"
                co_item["duration"] = 30
                co_item["participant_name"] = _("Районный старейшина")
                co_item["assistant_name"] = None
                result.append(co_item)
                cbs_replaced = True
            continue
        result.append(a)
    return result, True


def order_week_assignments(assignments: List[Dict], classifier=None) -> List[Tuple[str, Dict]]:
    """Пункты недели в порядке показа: [(ключ раздела, пункт)].

    Если порядок задан вручную (sort_order) — по нему; иначе по разделам.
    Пункты вне известных разделов получают ключ OTHER_SECTION.
    """
    if classifier is None:
        from core.assignment_classifier import AssignmentClassifier

        classifier = AssignmentClassifier()

    ordered: List[Tuple[str, Dict]] = []
    if any(a.get("sort_order") is not None for a in assignments):
        for a in sorted(
            assignments,
            key=lambda item: (item.get("sort_order") is None, item.get("sort_order") or 0),
        ):
            section = a.get("section")
            ordered.append((section if section in SECTION_KEYS else OTHER_SECTION, a))
        return ordered

    seen_ids = set()
    sections = classifier.classify(assignments)
    for section_key in SECTION_KEYS:
        for a in sections[section_key]:
            assignment_id = a.get("id", id(a))
            if assignment_id in seen_ids:
                continue
            seen_ids.add(assignment_id)
            ordered.append((section_key, a))

    for a in assignments:
        assignment_id = a.get("id", id(a))
        if a.get("status") == "disabled" or assignment_id in seen_ids:
            continue
        seen_ids.add(assignment_id)
        ordered.append((OTHER_SECTION, a))
    # Заключительная молитва — в конце программы, как на встрече
    closing = [item for item in ordered if _position(item[1]) == "prayer_close"]
    return [item for item in ordered if _position(item[1]) != "prayer_close"] + closing


def parse_meeting_start(value) -> int:
    """'19:00' / '19.00' → минуты от полуночи; при ошибке — 19:00."""
    try:
        hour, minute = (int(part) for part in str(value).replace(".", ":").split(":", 1))
        return (hour * 60 + minute) % (24 * 60)
    except (TypeError, ValueError):
        return DEFAULT_MEETING_START


# Тайминг программы, как в экспорте (core/export/compact_layout.py):
# председатель — начало, песня и молитва — через 1 мин, вступительные слова
# (1 мин, S-38 абз. 2) — через 5, «Сокровища» — через 6; после учебного задания —
# минута на похвалу и совет (абз. 19); песня перед «Жизнью» — 5 мин;
# заключительные слова — 3 мин, затем песня и молитва
PRAYER_OPEN_OFFSET = 1
INTRO_MINUTES = 6
MIDDLE_SONG_MINUTES = 5
CONCLUSION_MINUTES = 3
COUNSEL_MINUTES = 1


def counsel_minutes(a: Dict) -> int:
    """Минута совета председателя после учебного задания: чтение Библии и
    задания «Оттачиваем навыки», кроме обсуждений («Что бы вы сказали» и т.п.).
    Понимает и пункты из базы, и строки экспорта (type/raw_text/text)."""
    section = a.get("section")
    atype = a.get("assignment_type") or a.get("type")
    text = (a.get("assignment_text") or a.get("raw_text") or a.get("text") or "").lower()
    if section == "treasures":
        return COUNSEL_MINUTES if atype == "reading" else 0
    if is_role_talk(a):  # речь по обязанности — не учебное, без совета
        return 0
    if section == "ministry" and not a.get("discussion_marker") and not is_what_would_you_say(text):
        return COUNSEL_MINUTES
    return 0


def _position(a: Dict) -> str:
    return str(a.get("section_position") or a.get("assignment_number") or "")


def start_minutes(assignments: List[Dict], meeting_start: int) -> List[int]:
    """Время начала каждого пункта: следующий начинается после длительности предыдущего.

    Председатель и молитвы считаются по фиксированному таймингу встречи (их
    длительность не показывается и не меняется); чтец ИБС идёт вместе с ведущим —
    его длительность время не сдвигает.
    """
    result: List[int] = []
    closing = []
    current = meeting_start + INTRO_MINUTES
    middle_song = False
    for i, a in enumerate(assignments):
        position = _position(a)
        if position == "chairman":
            result.append(meeting_start)
            continue
        if position == "prayer_open":
            result.append(meeting_start + PRAYER_OPEN_OFFSET)
            continue
        if position == "prayer_close":
            result.append(0)  # время — после всех пунктов
            closing.append(i)
            continue
        if a.get("section") in ("living", "cbs") and not middle_song:
            current += MIDDLE_SONG_MINUTES
            middle_song = True
        result.append(current)
        if a.get("assignment_type") == "cbs_reader":
            continue
        duration = a.get("duration")
        try:
            duration_value = int(duration) if duration not in (None, "") else 0
        except (TypeError, ValueError):
            duration_value = 0
        current += duration_value + counsel_minutes(a)
    for i in closing:
        result[i] = current + CONCLUSION_MINUTES
    return [minutes % (24 * 60) for minutes in result]


def format_minutes(total_minutes: int) -> str:
    total_minutes %= 24 * 60
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"
