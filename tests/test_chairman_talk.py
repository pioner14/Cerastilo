"""«Речь председателя программы» (тетрадь, неделя 22 февраля 2027): пункт
получает председатель недели, это не учебное задание."""

from datetime import date

from bs4 import BeautifulSoup
from sqlalchemy import select

from core.assignment_rules import is_student_assignment, resolve_assignment_config
from core.chairman_talk import counted_assignment
from core.epub_parser import WorkbookParser
from core.models import Assignment, Week
from core.week_layout import counsel_minutes
from tests.test_logic_orm import (  # noqa: F401 — фикстуры
    event_bus,
    p_service,
    s_service,
    test_db,
)

HTML = """
<h2>Оттачиваем навыки служения</h2>
<h3>4. Подготавливайте учеников</h3>
<p>(2 мин.) Речь председателя программы. Коротко рассмотри урок 11.</p>
<h3>5. Подготавливайте учеников</h3>
<p>(3 мин.) lff урок 30, вступление.</p>
<h3>6. Объясняйте свои взгляды</h3>
<p>(5 мин.) Речь. ijwbq статья 1.</p>
"""


def test_parser_marks_chairman_talk():
    items = WorkbookParser("/x.epub")._get_assignments(BeautifulSoup(HTML, "html.parser"))
    types = {a["number"]: a["type"] for a in items}
    assert types == {"4": "chairman_talk", "5": "student", "6": "teaching"}


def test_rules_chairman_talk_not_student():
    cfg = resolve_assignment_config(
        "ministry", "chairman_talk", "Подготавливайте учеников", None, "1", None, lambda s, p: None
    )
    assert cfg.kind == "chairman_talk"
    assert cfg.required_qualification == "chairman"
    assert cfg.needs_assistant is False and cfg.is_brothers_only is True
    assert not is_student_assignment({"section": "ministry", "assignment_type": "chairman_talk"})
    assert counsel_minutes({"section": "ministry", "type": "chairman_talk"}) == 0
    assert counsel_minutes({"section": "ministry", "type": "student"}) == 1


def _week(test_db, chairman_id=None, with_talk=True):
    with test_db.get_session() as s:
        w = Week(week_title="22—28 ФЕВРАЛЯ", start_date=date(2027, 2, 22))
        s.add(w)
        s.flush()
        chair = Assignment(
            week_id=w.id,
            assignment_number="chairman",
            assignment_text="Председатель",
            assignment_type="role",
            section="fixed",
            section_position="chairman",
            participant_id=chairman_id,
            status="assigned" if chairman_id else "empty",
        )
        s.add(chair)
        talk = None
        if with_talk:
            talk = _talk(w.id)
            s.add(talk)
        s.commit()
        return w.id, chair.id, talk.id if talk else None


def _talk(week_id):
    return Assignment(
        week_id=week_id,
        assignment_number="4",
        assignment_text="Подготавливайте учеников",
        assignment_type="chairman_talk",
        section="ministry",
        section_position="1",
        status="empty",
    )


def _people(test_db, talk_id):
    with test_db.get_session() as s:
        a = s.get(Assignment, talk_id)
        return a.participant_id, a.status


def test_talk_follows_chairman(test_db, p_service, s_service):
    p1 = p_service.add_participant("Брат 1", "male", "E", ["chairman"])
    p2 = p_service.add_participant("Брат 2", "male", "E", ["chairman"])
    week_id, chair_id, talk_id = _week(test_db)

    assert s_service.assign_participant(chair_id, p1)
    assert _people(test_db, talk_id) == (p1, "assigned")
    assert s_service.get_week_conflicts(week_id) == []

    s_service.assign_participant(chair_id, p2)
    assert _people(test_db, talk_id) == (p2, "assigned")

    s_service.assign_participant(chair_id, None)
    assert _people(test_db, talk_id)[0] is None


def test_manual_override_kept_until_chairman_changes(test_db, p_service, s_service):
    p1 = p_service.add_participant("Брат 1", "male", "E", ["chairman"])
    p2 = p_service.add_participant("Брат 2", "male", "E", ["chairman"])
    _, chair_id, talk_id = _week(test_db, chairman_id=p1)

    s_service.assign_participant(talk_id, p2)
    assert _people(test_db, talk_id)[0] == p2


def test_new_talk_gets_existing_chairman(test_db, p_service):
    p1 = p_service.add_participant("Брат 1", "male", "E", ["chairman"])
    week_id, _, _ = _week(test_db, chairman_id=p1, with_talk=False)
    with test_db.get_session() as s:
        talk = _talk(week_id)
        s.add(talk)
        s.commit()
        talk_id = talk.id
    assert _people(test_db, talk_id) == (p1, "assigned")


def test_talk_not_in_history(test_db, p_service):
    p1 = p_service.add_participant("Брат 1", "male", "E", ["chairman"])
    _, chair_id, talk_id = _week(test_db, chairman_id=p1)
    with test_db.get_session() as s:
        ids = set(s.execute(select(Assignment.id).where(counted_assignment(Assignment))).scalars())
    assert chair_id in ids and talk_id not in ids


def test_auto_assign_puts_chairman_on_talk(test_db, p_service, s_service):
    from core.models import AssignmentConfig, Setting

    with test_db.get_session() as s:
        s.add(
            AssignmentConfig(
                section="fixed",
                position="chairman",
                assignment_name="Председатель",
                required_qualification="chairman",
                is_brothers_only=True,
            )
        )
        s.add(Setting(key="min_assignment_gap", value="0"))
        s.commit()
    p_service.add_participant("Брат 1", "male", "E", ["chairman"])
    week_id, chair_id, talk_id = _week(test_db)

    s_service.auto_assign_week(week_id)
    with test_db.get_session() as s:
        chairman = s.get(Assignment, chair_id).participant_id
    assert chairman is not None
    assert _people(test_db, talk_id) == (chairman, "assigned")


# --- Речи по обязанности: ответственный за служение, секретарь, координатор ---


def test_role_talk_type_from_text():
    from core.chairman_talk import role_talk_type

    assert role_talk_type("(5 мин.) Речь ответственного за служение. Расскажи") == (
        "service_overseer_talk"
    )
    assert role_talk_type("(3 мин.) Речь секретаря.") == "secretary_talk"
    assert role_talk_type("(4 мин.) Речь координатора совета старейшин.") == "coordinator_talk"
    assert role_talk_type("(5 мин.) Речь. ijwbq статья 1") is None


def test_parser_marks_living_role_talk():
    html = """
    <h2>Христианская жизнь</h2>
    <h3>9. Кампания по приглашению на Вечерю</h3>
    <p>(5 мин.) Речь ответственного за служение. Расскажи, как будет организовано служение.</p>
    """
    items = WorkbookParser("/x.epub")._get_assignments(BeautifulSoup(html, "html.parser"))
    assert [(a["number"], a["type"]) for a in items] == [("9", "service_overseer_talk")]


def test_role_talk_rules_elders_only():
    from core.assignment_rules import allowed_service_types, needs_slip

    cfg = resolve_assignment_config(
        "living", "service_overseer_talk", "Кампания", None, "2", None, lambda s, p: None
    )
    assert cfg.kind == "service_overseer_talk" and cfg.needs_assistant is False
    assert allowed_service_types("living", "2", cfg, "Кампания") == ("E", "elder")
    assert not needs_slip({"section": "living", "assignment_type": "service_overseer_talk"})


def test_needs_slip_only_student_parts():
    from core.assignment_rules import needs_slip

    assert needs_slip({"section": "ministry", "assignment_type": "student"})
    assert not needs_slip({"section": "ministry", "assignment_type": "chairman_talk"})
    assert not needs_slip(
        {"section": "ministry", "assignment_type": "student", "discussion_marker": "(5 мин.)"}
    )
    assert not needs_slip(
        {
            "section": "ministry",
            "assignment_type": "student",
            "assignment_text": "Что бы вы сказали?",
        }
    )


def _living_week(test_db):
    with test_db.get_session() as s:
        w = Week(week_title="22—28 ФЕВРАЛЯ", start_date=date(2027, 2, 22))
        s.add(w)
        s.flush()
        talk = Assignment(
            week_id=w.id,
            assignment_number="9",
            assignment_text="Кампания",
            assignment_type="living",
            section="living",
            section_position="2",
            status="empty",
        )
        s.add(talk)
        s.commit()
        return w.id, talk.id


def test_reimport_retype_gives_role_holder(test_db, p_service):
    from core.models import Setting

    overseer = p_service.add_participant("Ответственный", "male", "E", [])
    with test_db.get_session() as s:
        s.add(Setting(key="role_service_overseer", value=str(overseer)))
        s.commit()
    _, talk_id = _living_week(test_db)
    with test_db.get_session() as s:
        s.get(Assignment, talk_id).assignment_type = "service_overseer_talk"
        s.commit()
    assert _people(test_db, talk_id) == (overseer, "assigned")


def test_role_talk_without_holder_keeps_manual(test_db, p_service, s_service):
    brother = p_service.add_participant("Брат", "male", "E", [])
    _, talk_id = _living_week(test_db)
    s_service.assign_participant(talk_id, brother)
    with test_db.get_session() as s:
        s.get(Assignment, talk_id).assignment_type = "service_overseer_talk"
        s.commit()
    assert _people(test_db, talk_id)[0] == brother


def test_auto_assign_gives_role_holder(test_db, p_service, s_service):
    from core.models import Setting

    overseer = p_service.add_participant("Ответственный", "male", "E", [])
    with test_db.get_session() as s:
        s.add(Setting(key="min_assignment_gap", value="0"))
        s.commit()
    week_id, talk_id = _living_week(test_db)
    with test_db.get_session() as s:
        s.get(Assignment, talk_id).assignment_type = "service_overseer_talk"
        s.add(Setting(key="role_service_overseer", value=str(overseer)))
        s.commit()
    s_service.assign_participant(talk_id, None)
    s_service.auto_assign_week(week_id)
    assert _people(test_db, talk_id) == (overseer, "assigned")
