"""«Авто» заполняет только пустые пункты: ручные назначения и замены не трогает."""

from datetime import date

from core.models import Assignment, AssignmentConfig, Setting, Week
from tests.test_logic_orm import (  # noqa: F401 — фикстуры
    event_bus,
    p_service,
    s_service,
    test_db,
)


def _gems_week(test_db, participant_id=None):
    with test_db.get_session() as s:
        w = Week(week_title="W", start_date=date(2024, 1, 1))
        s.add(w)
        s.flush()
        s.add(
            Assignment(
                week_id=w.id,
                assignment_number="1",
                assignment_text="Жемчужины",
                assignment_type="talk",
                section="treasures",
                section_position=2,
                status="assigned" if participant_id else "empty",
                participant_id=participant_id,
            )
        )
        s.add(
            Assignment(
                week_id=w.id,
                assignment_number="2",
                assignment_text="Жемчужины 2",
                assignment_type="talk",
                section="treasures",
                section_position=2,
                status="empty",
            )
        )
        s.commit()
        return w.id


def _setup_gems(test_db, p_service, n=4):
    with test_db.get_session() as s:
        s.add(
            AssignmentConfig(
                section="treasures",
                position="2",
                assignment_name="G",
                required_qualification="gems",
                is_brothers_only=True,
            )
        )
        s.add(Setting(key="min_assignment_gap", value="0"))
        s.commit()
    return [p_service.add_participant(f"Брат {i}", "male", "MS", ["gems"]) for i in range(n)]


def _people(s_service, week_id):
    return {
        a["assignment_number"]: a["participant_id"]
        for a in s_service.get_week_data(week_id)["assignments"]
    }


def test_only_empty_keeps_manual_and_does_not_double_book(s_service, p_service, test_db):
    ids = _setup_gems(test_db, p_service)
    week_id = _gems_week(test_db, participant_id=ids[3])
    for _ in range(5):  # выбор кандидата зависит от очереди — повторяем
        res = s_service.auto_assign_week(week_id, only_empty=True)
        assert res["success"]
        people = _people(s_service, week_id)
        assert people["1"] == ids[3]  # ручное назначение на месте
        assert people["2"] not in (None, ids[3])  # пустой заполнен, и не тем же братом


def test_without_only_empty_week_is_redistributed(s_service, p_service, test_db):
    """Полное перераспределение (как «распределить всё») остаётся доступным."""
    ids = _setup_gems(test_db, p_service)
    week_id = _gems_week(test_db, participant_id=ids[3])
    res = s_service.auto_assign_week(week_id)
    assert res["success"] and res["count"] == 2


def test_only_empty_fills_missing_assistant(s_service, p_service, test_db):
    with test_db.get_session() as s:
        s.add(
            AssignmentConfig(
                section="ministry",
                position="1",
                assignment_name="M",
                required_qualification="ministry_item",
                needs_assistant=True,
            )
        )
        s.add(Setting(key="min_assignment_gap", value="0"))
        s.commit()
    main = p_service.add_participant(
        "Сестра А", "female", "publisher", ["ministry_item", "assistant"]
    )
    helper = p_service.add_participant("Сестра Б", "female", "publisher", ["assistant"])
    with test_db.get_session() as s:
        w = Week(week_title="W", start_date=date(2024, 1, 1))
        s.add(w)
        s.flush()
        s.add(
            Assignment(
                week_id=w.id,
                assignment_number="4",
                assignment_text="Начинайте разговор",
                assignment_type="student",
                section="ministry",
                section_position=1,
                status="assigned",
                participant_id=main,
            )
        )
        s.commit()
        week_id = w.id

    res = s_service.auto_assign_week(week_id, only_empty=True)

    a = s_service.get_week_data(week_id)["assignments"][0]
    assert res["success"] and res["count"] == 1
    assert a["participant_id"] == main and a["assistant_id"] == helper


def test_facade_week_and_month_auto_fill_only_empty():
    from types import SimpleNamespace

    from core.base_facade import BaseApplicationFacade

    calls = []
    fake = SimpleNamespace(
        schedule=SimpleNamespace(
            auto_assign_week=lambda wid, only_empty: calls.append((wid, only_empty))
            or {"success": True}
        )
    )
    BaseApplicationFacade.auto_assign_week(fake, 5)
    assert calls == [(5, True)]


def test_vacation_assignments_released_and_replaced(s_service, p_service, test_db):
    """Отпуск одним окном: задания на неделях отпуска снимаются, место
    занимает другой, задания вне отпуска остаются."""
    from core.facade import ApplicationFacade
    from core.models import Participant

    ids = _setup_gems(test_db, p_service, n=3)
    with test_db.get_session() as s:
        weeks = []
        for start in (date(2030, 3, 4), date(2030, 3, 11)):
            w = Week(week_title=str(start), start_date=start)
            s.add(w)
            s.flush()
            s.add(
                Assignment(
                    week_id=w.id,
                    assignment_number="1",
                    assignment_text="Жемчужины",
                    assignment_type="talk",
                    section="treasures",
                    section_position=2,
                    status="assigned",
                    participant_id=ids[0],
                )
            )
            weeks.append(w.id)
        p = s.get(Participant, ids[0])
        p.unavailable_from, p.unavailable_to = date(2030, 3, 11), date(
            2030, 3, 15
        )  # только 2-я неделя
        s.commit()

    facade = ApplicationFacade.__new__(ApplicationFacade)
    facade.schedule = s_service
    items = facade.get_away_assignments(ids[0], today=date(2030, 3, 1))
    assert [i["week_id"] for i in items] == [weeks[1]] and items[0]["role"] == "participant"

    result = facade.replace_away_assignments(items)

    assert result["released"] == 1
    assert result["replacements"][0]["name"] in ("Брат 1", "Брат 2")
    assert _people(s_service, weeks[0])["1"] == ids[0]  # вне отпуска — на месте
    assert _people(s_service, weeks[1])["1"] in (ids[1], ids[2])


def test_only_empty_refills_main_and_keeps_assistant(s_service, p_service, test_db):
    with test_db.get_session() as s:
        s.add(
            AssignmentConfig(
                section="ministry",
                position="1",
                assignment_name="M",
                required_qualification="ministry_item",
                needs_assistant=True,
            )
        )
        s.add(Setting(key="min_assignment_gap", value="0"))
        s.commit()
    main = p_service.add_participant("Сестра А", "female", "publisher", ["ministry_item"])
    helper = p_service.add_participant(
        "Сестра Б", "female", "publisher", ["ministry_item", "assistant"]
    )
    with test_db.get_session() as s:
        w = Week(week_title="W", start_date=date(2024, 1, 1))
        s.add(w)
        s.flush()
        s.add(
            Assignment(
                week_id=w.id,
                assignment_number="4",
                assignment_text="Начинайте разговор",
                assignment_type="student",
                section="ministry",
                section_position=1,
                status="empty",
                assistant_id=helper,
            )
        )
        s.commit()
        week_id = w.id

    s_service.auto_assign_week(week_id, only_empty=True)

    a = s_service.get_week_data(week_id)["assignments"][0]
    assert a["participant_id"] == main and a["assistant_id"] == helper


def test_set_unavailable_sets_and_clears(p_service):
    pid = p_service.add_participant("Брат", "male", "MS", [])
    assert p_service.set_unavailable(pid, date(2030, 3, 1), date(2030, 3, 9))
    p = p_service.get_participant(pid)
    assert (str(p["unavailable_from"])[:10], str(p["unavailable_to"])[:10]) == (
        "2030-03-01",
        "2030-03-09",
    )
    assert p_service.set_unavailable(pid, None, None)
    assert p_service.get_participant(pid)["unavailable_from"] is None
