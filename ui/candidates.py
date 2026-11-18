"""
Кандидаты на пункт программы: кто подходит (пол, квалификация, напарник —
одного пола или из семьи) и подсказки «сколько раз за полгода, когда последнее».

Общие для окна выбора участника (ui/schedule_view.py) и панели кандидатов
доски месяца (ui/month_board_view.py).
"""

from datetime import datetime
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMessageBox

from core.chairman_talk import ROLE_SETTINGS, is_chairman_talk, role_setting
from core.assignment_rules import (
    ELDER_SERVICE_TYPE,
    allowed_service_types,
    family_assistant_allowed,
    is_student_assignment,
    resolve_assignment_config,
)
from core.styles import palette
from core.i18n import _


def _same_family(p1: dict, p2: dict) -> bool:
    """True если два участника принадлежат одной семье.

    Дублирует логику AutoAssignmentService._same_family().
    Используется при ручном выборе напарника в UI.

    Правила:
      - Если p1 — глава семьи (family_group_id is None): члены его семьи
        имеют family_group_id == p1.id
      - Если p1 — член семьи: другие в той же семье имеют тот же
        family_group_id, ИЛИ голова семьи имеет id == p1.family_group_id
    """
    fid1 = p1.get("family_group_id")
    fid2 = p2.get("family_group_id")
    id1, id2 = p1["id"], p2["id"]

    if fid1 is None and fid2 is None:
        return False  # Оба — главы разных семей
    if fid1 is None:
        return fid2 == id1  # p1 — глава, p2 — член его семьи
    if fid2 is None:
        return fid1 == id2  # p2 — глава, p1 — член его семьи
    return fid1 == fid2  # Оба — члены одной семьи


# Цвета подсказок у кандидатов (из палитры темы): давно не выступал /
# недавно / уже занят на этой неделе
HINT_PALETTE_KEYS = {"rested": "text_success", "recent": "text_warning", "busy": "text_secondary"}
RECENT_WEEKS = 4
ELDER_STUDENT_NOTE = _("старейшина: учебное задание обычно не даётся")
RESTED_WEEKS = 8


def _parse_display_date(value):
    """Дата недели из get_week_data(): date или строка YYYY-MM-DD."""
    if value is None or hasattr(value, "year"):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def candidate_hint(
    stats: Optional[dict], weeks_since: Optional[int], weeks_until: Optional[int] = None
) -> tuple:
    """Подпись, подсказка и цвет кандидата в окне выбора участника.

    stats — запись из facade.get_candidate_stats(), weeks_since — сколько недель
    от последнего задания до выбранной недели (None — не выступал),
    weeks_until — через сколько недель следующее задание (None — его нет).
    """
    stats = stats or {}
    count = stats.get("count", 0)
    if stats.get("busy") or stats.get("away"):
        kind = "busy"
    elif weeks_since is None or weeks_since >= RESTED_WEEKS:
        kind = "rested"
    elif weeks_since < RECENT_WEEKS:
        kind = "recent"
    else:
        kind = None

    parts = [_("{count} за полгода", count=count)]
    if weeks_since is None:
        parts.append(_("не выступал"))
    else:
        parts.append(
            _(
                "{weeks_since} нед. назад ({v})",
                weeks_since=weeks_since,
                v=stats.get("last_text") or "—",
            )
        )
    if weeks_until is not None:
        parts.append(
            _(
                "дальше через {weeks_until} нед. ({v})",
                weeks_until=weeks_until,
                v=stats.get("next_text") or "—",
            )
        )
    if stats.get("away"):
        parts.append(_("недоступен на этой неделе (отпуск, график)"))
    if stats.get("busy"):
        parts.append(_("уже занят на этой неделе"))
    text = " · ".join(parts)

    last = stats.get("last_date")
    tooltip = _("Заданий за полгода: {count}\nПоследнее: ", count=count) + (
        f"{last.strftime('%d.%m.%Y')} — {stats.get('last_text') or '—'}"
        if last
        else _("не выступал")
    )
    following = stats.get("next_date")
    if following:
        tooltip += _(
            "\nСледующее: {v} — {v2}",
            v=following.strftime("%d.%m.%Y"),
            v2=stats.get("next_text") or "—",
        )
    return text, tooltip, kind


def _hint_icon(kind: Optional[str]) -> QIcon:
    pixmap = QPixmap(12, 12)
    pixmap.fill(Qt.GlobalColor.transparent)
    if not kind:
        return QIcon(pixmap)  # пустой значок — чтобы имена стояли ровно
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(getattr(palette(), HINT_PALETTE_KEYS[kind])))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(1, 1, 10, 10)
    painter.end()
    return QIcon(pixmap)


def _quals(p: dict) -> list:
    quals = p.get("qualifications", [])
    if isinstance(quals, str):
        quals = quals.split(",") if quals else []
    return quals


def list_candidates(facade, assignment_id, role: str = "participant") -> List[Dict]:
    """Подходящие участники для пункта assignment_id в роли role.

    Returns:
        [{"id", "name", "hint", "tooltip", "kind", "weeks_since", "busy", "elder_warning",
          "pair_count"}] —
        в порядке facade.get_all_participants(); hint/tooltip/kind — из candidate_hint(),
        elder_warning — старейшина на учебном задании (допустимо, но с предупреждением),
        pair_count — сколько раз уже были парой с основным участником (для напарника)
        или с назначенным напарником (для основного).
    """
    # Определяем фильтры для заданий
    brothers_only = False
    required_qualification = None
    # Статус служения (только старейшины / старейшины и помощники) — как в автоназначении
    service_types = None
    # Для роли напарника: данные главного участника (для фильтра пол/семья)
    main_participant = None
    assignment = facade.get_assignment(assignment_id) if assignment_id else None

    if assignment:
        section = assignment.get("section")
        section_position = str(assignment.get("section_position", ""))
        if section and section_position:
            config = facade.get_assignment_config(section, section_position)
            # Те же поправки по типу пункта, что и в автоназначении: например,
            # ученическое задание на позиции 4 (в настройках — «Речь, только
            # братья») открыто для сестёр и требует «Учебные задания».
            config = resolve_assignment_config(
                section,
                assignment.get("assignment_type"),
                assignment.get("assignment_text"),
                assignment.get("discussion_marker"),
                section_position,
                config,
                facade.get_assignment_config,
            )
            if config:
                brothers_only = getattr(config, "is_brothers_only", False)
                required_qualification = getattr(config, "required_qualification", None)
            if role != "assistant":
                service_types = allowed_service_types(
                    section, section_position, config, assignment.get("assignment_text")
                )

        # При выборе напарника загружаем главного участника задания.
        # Согласно S-38 §7–§10: напарник должен быть одного пола
        # с выступающим или членом его семьи.
        if role == "assistant":
            main_id = assignment.get("participant_id")
            if main_id:
                main_participant = facade.get_participant(main_id)

    # Подсказки: сколько заданий за полгода, когда последнее, занят ли уже
    week_id = assignment.get("week_id") if assignment else None
    week_chairman_id = None  # кого поставить первым (председатель / брат по обязанности)
    preferred_hint = _("председатель этой недели")
    stats_by_id = facade.get_candidate_stats(week_id, assignment_id) if week_id else {}
    ref_date = None
    if week_id:
        week_data = facade.get_week_data(week_id) or {}
        ref_date = _parse_display_date((week_data.get("week") or {}).get("start_date"))
        if assignment and is_chairman_talk(assignment):
            # «Речь председателя»: председатель недели — первым в списке
            week_chairman_id = next(
                (
                    a.get("participant_id")
                    for a in week_data.get("assignments") or []
                    if str(a.get("section_position") or "") == "chairman"
                ),
                None,
            )
    if assignment and role_setting(assignment):
        # Речь ответственного за служение / секретаря / координатора —
        # брат из «Настройки» → «Обязанности в собрании» первым в списке
        key = role_setting(assignment)
        value = str(facade.get_setting(key, "") or "")
        if value.isdigit():
            week_chairman_id = int(value)
            preferred_hint = _(ROLE_SETTINGS[key]).lower()

    # Прошлые пары: для напарника — с основным участником, для основного —
    # с уже назначенным напарником (чтобы одни и те же пары не повторялись)
    pair_with = None
    if assignment and week_id:
        if role == "assistant":
            pair_with = main_participant
        elif assignment.get("assistant_id"):
            pair_with = facade.get_participant(assignment["assistant_id"])
    pair_history = facade.get_pair_history(pair_with["id"], week_id) if pair_with else {}

    student = bool(assignment) and is_student_assignment(assignment)
    result = []
    for p in facade.get_all_participants():
        # Фильтрация по полу для заданий только для братьев
        if brothers_only and p.get("gender") != "male":
            continue
        # Фильтрация по квалификации
        if required_qualification and required_qualification not in _quals(p):
            continue
        if service_types and p.get("service_type") not in service_types:
            continue
        # Напарник (S-38 §7–§11): квалификация "assistant", одного пола
        # с выступающим; член семьи — только где это разрешено
        if role == "assistant":
            if "assistant" not in _quals(p):
                continue
            if main_participant:
                # Исключить самого главного участника из списка напарников
                if p["id"] == main_participant["id"]:
                    continue
                if not (
                    p.get("gender") == main_participant.get("gender")
                    or (
                        family_assistant_allowed(assignment.get("assignment_text"))
                        and _same_family(main_participant, p)
                    )
                ):
                    continue

        stats = stats_by_id.get(p["id"])
        last = (stats or {}).get("last_date")
        weeks_since = (ref_date - last).days // 7 if (ref_date and last) else None
        following = (stats or {}).get("next_date")
        weeks_until = (following - ref_date).days // 7 if (ref_date and following) else None
        hint, tooltip, kind = candidate_hint(stats, weeks_since, weeks_until)
        if week_chairman_id and p["id"] == week_chairman_id:
            hint = preferred_hint + (f" · {hint}" if hint else "")
        elder_warning = student and p.get("service_type") == ELDER_SERVICE_TYPE
        if elder_warning:
            hint += f" · {ELDER_STUDENT_NOTE}"
            tooltip += f"\n{ELDER_STUDENT_NOTE}"
        pair = pair_history.get(p["id"])
        if pair:
            last_pair = pair["last_date"].strftime("%d.%m.%Y")
            hint += _(
                " · в паре {v} раз(а), посл. {last_pair}", v=pair["count"], last_pair=last_pair
            )
            tooltip += _(
                "\nВ паре с {v}: {v2} раз(а), последний — {last_pair}",
                v=pair_with.get("name", ""),
                v2=pair["count"],
                last_pair=last_pair,
            )
        result.append(
            {
                "id": p["id"],
                "name": p["name"],
                "hint": hint,
                "tooltip": tooltip,
                "kind": kind,
                "weeks_since": weeks_since,
                "busy": bool((stats or {}).get("busy") or (stats or {}).get("away")),
                "elder_warning": elder_warning,
                "pair_count": pair["count"] if pair else 0,
                "week_chairman": bool(week_chairman_id) and p["id"] == week_chairman_id,
            }
        )
    return result


def by_rest(candidates: List[Dict]) -> List[Dict]:
    """Сначала свободные на этой неделе, среди них — кто дольше не выступал
    (новые — первыми), занятые — в конце, старейшины на учебном — в самом конце."""
    return sorted(
        candidates,
        key=lambda c: (
            not c.get("week_chairman", False),
            c.get("elder_warning", False),
            c["busy"],
            c["weeks_since"] is not None,
            -(c["weeks_since"] or 0),
            c["name"],
        ),
    )


def confirm_assignment(parent, facade, assignment_id, participant_id) -> bool:
    """Спросить «Всё равно назначить?», если старейшину ставят на учебное задание.
    True — назначать (предупреждать не о чем или пользователь согласился)."""
    if not participant_id or not assignment_id:
        return True
    assignment = facade.get_assignment(assignment_id) or {}
    participant = facade.get_participant(participant_id) or {}
    if not (
        is_student_assignment(assignment) and participant.get("service_type") == ELDER_SERVICE_TYPE
    ):
        return True
    answer = QMessageBox.question(
        parent,
        _("Старейшина на учебном задании"),
        _(
            "{v} — старейшина. Учебные задания старейшинам обычно не дают (допустимо в маленьких собраниях).\n\nВсё равно назначить?",
            v=participant.get("name", ""),
        ),
    )
    return answer == QMessageBox.StandardButton.Yes
