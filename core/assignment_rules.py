"""Действующие правила задания: настройки позиции с поправкой на тип пункта.

Конфигурация в assignment_config задаётся по (section, position), но в разделе
«Оттачиваем навыки» одна и та же позиция бывает разной по смыслу: позиция 4 —
обычно «Речь (только братья)», а иногда ученическое задание с напарником.
Поэтому правила уточняются по типу и тексту пункта. Ими пользуются и
автоназначение, и ручной выбор участника — чтобы они не расходились.
"""

import re
from types import SimpleNamespace
from typing import Any, Callable, Optional

from core.chairman_talk import (
    CHAIRMAN_TALK_NAME,
    CHAIRMAN_TALK_TYPE,
    is_role_talk,
    role_talk_name,
)


def is_what_would_you_say(text: Optional[str]) -> bool:
    """Пункт «Что бы вы сказали?» в русской или английской тетради."""
    text = (text or "").lower()
    return "что бы вы сказали" in text or "what would you say" in text


def resolve_assignment_config(
    section: Optional[str],
    assignment_type: Optional[str],
    assignment_text: Optional[str],
    discussion_marker: Optional[str],
    section_position: Any,
    base_config: Any,
    get_config: Callable[[str, str], Any],
) -> Any:
    """Вернуть действующую конфигурацию пункта.

    base_config — запись assignment_config для (section, position) или None;
    get_config(section, position) — поиск другой записи (нужен для речи).
    Результат: base_config без изменений или объект с теми же полями
    (required_qualification, is_brothers_only, needs_assistant, is_exclusive, ...)
    и полем kind — какое исключение сработало.
    """
    text = assignment_text or ""
    position = str(section_position) if section_position else "1"

    role_name = role_talk_name({"assignment_type": assignment_type})
    if role_name and assignment_type != CHAIRMAN_TALK_TYPE:
        # Речь ответственного за служение / секретаря / координатора — брат из
        # «Обязанностей в собрании» (core/chairman_talk.py); в ручном выборе —
        # старейшины, выбранный брат первым.
        return SimpleNamespace(
            kind=assignment_type,
            id=getattr(base_config, "id", None),
            section=section,
            position=position,
            assignment_name=role_name,
            required_qualification=None,
            is_brothers_only=True,
            needs_assistant=False,
            is_exclusive=True,
            elder_position_gap=None,
            is_talk_item=True,
            is_elder_only=True,
        )

    if section == "ministry" and assignment_type == CHAIRMAN_TALK_TYPE:
        # «Речь председателя программы» — проводит председатель недели
        # (автораспределение ставит его само, core/chairman_talk.py). В ручном
        # выборе — те, кто может быть председателем, без «Учебных заданий».
        return SimpleNamespace(
            kind="chairman_talk",
            id=getattr(base_config, "id", None),
            section="ministry",
            position=position,
            assignment_name=CHAIRMAN_TALK_NAME,
            required_qualification="chairman",
            is_brothers_only=True,
            needs_assistant=False,
            is_exclusive=True,
            elder_position_gap=None,
            is_talk_item=True,  # не учебное: без student-фильтров
            is_chairman_talk=True,
        )

    what_would_you_say = is_what_would_you_say(text)
    if (
        section == "ministry"
        and assignment_type == "student"
        and (what_would_you_say or discussion_marker)
    ):
        # «Что бы вы сказали» и «(N мин.) Обсуждение» (с сентября 2025) — пункты
        # с участием аудитории: ведёт один старейшина или служебный помощник,
        # без напарника (S-38, абз. 6 и 9)
        return SimpleNamespace(
            kind="what_would_you_say" if what_would_you_say else "discussion",
            id=getattr(base_config, "id", None),
            section="ministry",
            position=position,
            assignment_name=(
                "Что бы вы сказали (только E/MS)" if what_would_you_say else "Обсуждение"
            ),
            # Не «Учебные задания»: это квалификация учеников, у старейшин её
            # обычно нет — и пункт оставался пустым, когда все помощники с ней
            # уже были заняты (февраль 2027). Достаточно статуса E/MS.
            required_qualification=None,
            is_brothers_only=True,
            needs_assistant=False,
            is_exclusive=True,
            elder_position_gap=None,
            is_discussion_item=True,  # не обычное ученическое: без student-фильтров
            is_elder_ms_only=True,
        )

    if section == "ministry" and assignment_type == "student":
        # Ученическое задание: открыто для сестёр, нужен напарник —
        # даже на позиции 4, которая в настройках записана как речь
        return SimpleNamespace(
            kind="student",
            id=getattr(base_config, "id", None),
            section="ministry",
            position=position,
            assignment_name="Учебное задание",
            required_qualification="ministry_item",
            is_brothers_only=False,
            needs_assistant=True,
            is_exclusive=True,
            elder_position_gap=None,
        )

    if section == "ministry" and (
        assignment_type == "teaching"
        or "Речь" in text
        or "Talk" in text
        or re.search(r"\btalk\b", text, re.IGNORECASE)
    ):
        talk_config = get_config("ministry", "4")
        if talk_config:
            return SimpleNamespace(
                kind="talk",
                id=getattr(talk_config, "id", None),
                section="ministry",
                position="4",
                assignment_name="Речь (только братья)",
                required_qualification=talk_config.required_qualification,
                is_brothers_only=True,
                needs_assistant=False,
                is_exclusive=True,
                elder_position_gap=None,
                is_talk_item=True,
            )

    return base_config


ELDER_SERVICE_TYPE = "E"
ELDER_TYPES = ("E", "elder")
ELDER_MS_TYPES = ("E", "elder", "MS")


def allowed_service_types(
    section: Optional[str], position: Any, config: Any, assignment_text: Optional[str]
) -> Optional[tuple]:
    """Кому можно поручить пункт по статусу служения (None — без ограничения).

    Только старейшина: председатель, ведущий ИБС, «Местные потребности».
    Старейшина или служебный помощник: «Вступительная речь», «Духовные
    жемчужины», «Что бы вы сказали» и обсуждения, пункты «Христианской жизни»
    (S-38, абз. 3, 4, 6, 9, 16, 17, 25). Общее для автоназначения и ручного выбора.
    """
    position = str(position or "")
    req_qual = getattr(config, "required_qualification", None)
    name = getattr(config, "assignment_name", None)
    name = name.lower() if isinstance(name, str) else ""
    text = (assignment_text or "").lower()
    if getattr(config, "is_elder_only", False) is True:
        return ELDER_TYPES
    if (
        req_qual in ("cbs_conductor", "chairman")
        or position == "chairman"
        or (
            section == "living"
            and any(part in name or part in text for part in ("местные потребности", "local needs"))
        )
    ):
        return ELDER_TYPES
    if (
        getattr(config, "is_elder_ms_only", False) is True
        or (section == "treasures" and position in ("1", "2"))
        or section == "living"
    ):
        return ELDER_MS_TYPES
    return None


def is_student_assignment(assignment: dict) -> bool:
    """Учебное задание: «Чтение Библии» и пункты «Оттачиваем навыки», кроме
    обсуждений (их ведёт брат-старейшина). Старейшинам такие задания обычно
    не дают — допустимо в маленьких собраниях, но с предупреждением."""
    section = assignment.get("section")
    if section == "treasures":
        return assignment.get("assignment_type") == "reading"
    if is_role_talk(assignment):
        return False
    return section == "ministry" and not assignment.get("discussion_marker")


def needs_slip(assignment: Any) -> bool:
    """Нужен ли бланк S-89: только учебные задания. Речи по обязанности,
    «Что бы вы сказали?» и обсуждения (пункты с участием аудитории, S-38,
    абз. 6 и 9) проводят старейшины и помощники — бланк им не нужен."""

    def get(key):
        if isinstance(assignment, dict):
            return assignment.get(key)
        return getattr(assignment, key, None)

    if is_role_talk(assignment):
        return False
    if get("section") == "ministry" and (
        get("discussion_marker") or is_what_would_you_say(get("assignment_text"))
    ):
        return False
    return True


# S-38, абз. 8 и 10: в «Развивайте интерес» и «Подготавливайте учеников»
# напарник — только того же пола; в остальных заданиях с напарником
# («Начинайте разговор», «Объясняйте свои взгляды», абз. 7 и 11) можно и члена
# семьи. Прежние названия: «Повторное посещение», «Изучение Библии».
SAME_GENDER_ONLY_PARTS = (
    "развивайте интерес",
    "подготавливайте учеников",
    "повторное посещение",
    "изучение библии",
    "following up",
    "making disciples",
    "return visit",
    "bible study",
)


def family_assistant_allowed(assignment_text: Optional[str]) -> bool:
    """Можно ли взять в напарники члена семьи другого пола."""
    text = (assignment_text or "").lower()
    return not any(part in text for part in SAME_GENDER_ONLY_PARTS)
