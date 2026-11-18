"""Речи по обязанности: «Речь председателя программы», «Речь ответственного
за служение», «Речь секретаря», «Речь координатора совета старейшин».

С февраля 2027 года (неделя 22–28 февраля) в тетради бывает пункт
«Подготавливайте учеников (2 мин.) Речь председателя программы». Это не
учебное задание: его проводит председатель этой недели. Поэтому:

- импорт даёт пункту тип ``chairman_talk`` (core/epub_parser.py);
- автораспределение не подбирает кандидатов, а ставит председателя недели;
- смена председателя недели (вручную, обменом, откатом, синхронизацией)
  тут же переносится на этот пункт — хук ``before_flush`` ниже;
- пункт не учебный: без бланка S-89, без минуты совета, без пометок
  «учебное задание» и не идёт в историю заданий для справедливости.

Речи ответственного за служение, секретаря и координатора (бывают и в
«Христианской жизни») получает брат, выбранный в «Настройки» → «Обязанности
в собрании» (настройки ``role_*`` — id участника). Если никто не выбран,
пункт распределяется как обычно, а ручное назначение не трогается.
"""

import re
from typing import Any, Optional

from sqlalchemy import event, select
from sqlalchemy.orm import Session

CHAIRMAN_TALK_TYPE = "chairman_talk"
CHAIRMAN_TALK_NAME = "Речь председателя"
_MARKER = "речь председателя"


# тип пункта → (слова после «Речь» в тетради, настройка с id брата, подпись)
ROLE_TALKS = {
    CHAIRMAN_TALK_TYPE: ("председателя", None, CHAIRMAN_TALK_NAME),
    "service_overseer_talk": (
        "ответственного за служение",
        "role_service_overseer",
        "Речь ответственного за служение",
    ),
    "secretary_talk": ("секретаря", "role_secretary", "Речь секретаря"),
    "coordinator_talk": ("координатора", "role_coordinator", "Речь координатора"),
}
# настройка → обязанность (для «Настроек» и подсказки в выборе участника)
ROLE_SETTINGS = {
    "role_coordinator": "Координатор совета старейшин",
    "role_secretary": "Секретарь",
    "role_service_overseer": "Ответственный за служение",
}
_ROLE_RE = re.compile(
    r"^\s*(?:\(\d+\s*мин\.?\)\s*)?Речь\s+("
    + "|".join(words for words, _, _ in ROLE_TALKS.values())
    + ")",
    re.IGNORECASE,
)

_EN_ROLE_TALKS = {
    "chairman": CHAIRMAN_TALK_TYPE,
    "service overseer": "service_overseer_talk",
    "secretary": "secretary_talk",
    "coordinator": "coordinator_talk",
}
_EN_ROLE_RE = re.compile(
    r"^\s*(?:\(\d+\s*min\.?\)\s*)?Talk\s+by\s+(?:the\s+)?(" + "|".join(_EN_ROLE_TALKS) + r")\b",
    re.IGNORECASE,
)
_EN_CHAIRMAN_TEXT = re.compile(r"\btalk\s+by\s+(?:the\s+)?chairman\b", re.IGNORECASE)


def role_talk_type(body: Optional[str]) -> Optional[str]:
    """Тип пункта по началу текста под заголовком: «(2 мин.) Речь председателя
    программы…» → chairman_talk; не речь по обязанности → None."""
    m = _ROLE_RE.match(body or "")
    if not m:
        english = _EN_ROLE_RE.match(body or "")
        return _EN_ROLE_TALKS[english[1].lower()] if english else None
    found = m.group(1).lower()
    return next(t for t, (words, _, _) in ROLE_TALKS.items() if words == found)


def _atype(assignment: Any) -> Optional[str]:
    if isinstance(assignment, dict):
        return assignment.get("assignment_type") or assignment.get("type")
    return getattr(assignment, "assignment_type", None)


def is_role_talk(assignment: Any) -> bool:
    """Речь по обязанности (включая речь председателя)."""
    return _atype(assignment) in ROLE_TALKS


def role_talk_name(assignment: Any) -> Optional[str]:
    """Подпись пункта («Речь секретаря») или None."""
    entry = ROLE_TALKS.get(_atype(assignment))
    return entry[2] if entry else None


def role_setting(assignment: Any) -> Optional[str]:
    """Настройка с братом для этого пункта (у речи председателя — None)."""
    entry = ROLE_TALKS.get(_atype(assignment))
    return entry[1] if entry else None


def role_holders(session: Session) -> dict:
    """{настройка role_*: id брата} — только выбранные."""
    from core.models import Setting

    with session.no_autoflush:
        rows = session.execute(
            select(Setting.key, Setting.value).where(Setting.key.in_(list(ROLE_SETTINGS)))
        ).all()
    return {k: int(v) for k, v in rows if v and str(v).isdigit()}


def is_chairman_talk_text(text: Optional[str]) -> bool:
    """Есть ли в тексте тетради пометка «Речь председателя (программы)»."""
    return _MARKER in (text or "").lower() or bool(_EN_CHAIRMAN_TEXT.search(text or ""))


def is_chairman_talk(assignment: Any) -> bool:
    """Пункт — «Речь председателя» (dict из базы/экспорта или объект Assignment)."""
    return _atype(assignment) == CHAIRMAN_TALK_TYPE


def _is_chairman_slot(a: Any) -> bool:
    return str(getattr(a, "section_position", "") or "") == "chairman"


def _apply(talk: Any, chairman_id: Optional[int]) -> bool:
    """Поставить председателя на пункт; True, если что-то поменялось."""
    from core.models import AssignmentStatus

    if talk.status == AssignmentStatus.DISABLED.value:
        return False
    status = AssignmentStatus.ASSIGNED.value if chairman_id else AssignmentStatus.EMPTY.value
    if talk.participant_id == chairman_id and talk.assistant_id is None and talk.status == status:
        return False
    talk.participant_id = chairman_id
    talk.assistant_id = None
    talk.status = status
    return True


def sync_week(session: Session, week_id: int) -> int:
    """Поставить председателя недели на её «Речи председателя». Вернуть число
    изменённых пунктов (без commit)."""
    from core.models import Assignment

    with session.no_autoflush:
        rows = list(
            session.execute(select(Assignment).where(Assignment.week_id == week_id)).scalars()
        )
    # ещё не записанные в базу пункты (импорт новой недели)
    rows += [
        a
        for a in session.new
        if isinstance(a, Assignment) and a.week_id == week_id and a not in rows
    ]
    return sync_rows(rows)


def sync_rows(rows, holders: Optional[dict] = None, only_empty: bool = False) -> int:
    """То же, что sync_week, по уже загруженным пунктам одной недели.

    holders — {настройка: id брата}: тогда и речи по обязанности получают
    выбранного брата (при only_empty — только пустые)."""
    rows = list(rows)
    chairman = next((a for a in rows if _is_chairman_slot(a)), None)
    chairman_id = chairman.participant_id if chairman else None
    changed = sum(_apply(a, chairman_id) for a in rows if is_chairman_talk(a))
    for a in rows:
        holder = (holders or {}).get(role_setting(a))
        if holder and not (only_empty and a.participant_id):
            changed += _apply(a, holder)
    return changed


@event.listens_for(Session, "before_flush")
def _follow_chairman(session: Session, flush_context, instances) -> None:
    """Сменился председатель недели или появилась/переразмечена «Речь
    председателя» — подтянуть на неё председателя этой недели."""
    from sqlalchemy import inspect as sa_inspect

    from core.models import Assignment

    weeks = set()
    role_talks = []
    for obj in list(session.new) + list(session.dirty):
        if not isinstance(obj, Assignment) or obj.week_id is None:
            continue
        state = sa_inspect(obj)
        if _is_chairman_slot(obj):
            if not state.has_identity or state.attrs.participant_id.history.has_changes():
                weeks.add(obj.week_id)
        elif is_role_talk(obj):
            if not state.has_identity or state.attrs.assignment_type.history.has_changes():
                if is_chairman_talk(obj):
                    weeks.add(obj.week_id)
                else:
                    role_talks.append(obj)
    for week_id in weeks:
        sync_week(session, week_id)
    if role_talks:
        # новый или переразмеченный импортом пункт — брату из «Обязанностей»
        holders = role_holders(session)
        for talk in role_talks:
            holder = holders.get(role_setting(talk))
            if holder:
                _apply(talk, holder)


def counted_assignment(assignment_cls):
    """Условие SQL «назначенный пункт, который идёт в историю заданий»:
    речи по обязанности не считаются — их проводит определённый брат,
    справедливость распределения от них не меняется."""
    from sqlalchemy import and_, or_

    from core.models import AssignmentStatus

    return and_(
        assignment_cls.status == AssignmentStatus.ASSIGNED.value,
        or_(
            assignment_cls.assignment_type.is_(None),
            assignment_cls.assignment_type.notin_(list(ROLE_TALKS)),
        ),
    )
