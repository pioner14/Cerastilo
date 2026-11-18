"""core.statistics: выборка выступлений для вкладки «Статистика»."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import Assignment, Base, Participant, Week
from core.statistics import assignment_stats, category


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_category_mapping():
    assert category("fixed", "prayer_open", False) == "prayer"
    assert category("fixed", "chairman", False) == "chairman"
    assert category("ministry", "1", True) == "assistant"
    assert category("living", "2", False) == "living"
    assert category("fixed", "other", False) is None


def test_stats_groups_by_week_and_includes_people_without_assignments(session):
    bro = Participant(name="Брат", gender="male", service_type="MS", is_active=True)
    sis = Participant(name="Сестра", gender="female", service_type="PUB", is_active=True)
    idle = Participant(name="Без заданий", gender="male", service_type="MS", is_active=True)
    gone = Participant(name="Неактивный", gender="male", service_type="MS", is_active=False)
    w1 = Week(week_title="W1", start_date=date(2026, 9, 7))
    w2 = Week(week_title="W2", start_date=date(2026, 9, 14))
    session.add_all([bro, sis, idle, gone, w1, w2])
    session.flush()
    session.add_all(
        [
            Assignment(
                week_id=w1.id,
                assignment_text="Пункт",
                assignment_number="pr",
                section="fixed",
                section_position="prayer_open",
                participant_id=bro.id,
                status="assigned",
            ),
            Assignment(
                week_id=w1.id,
                assignment_text="Пункт",
                assignment_number="7",
                section="living",
                section_position="1",
                participant_id=bro.id,
                status="assigned",
            ),
            Assignment(
                week_id=w2.id,
                assignment_text="Пункт",
                assignment_number="4",
                section="ministry",
                section_position="1",
                participant_id=sis.id,
                assistant_id=bro.id,
                status="assigned",
            ),
            Assignment(
                week_id=w2.id,
                assignment_text="Пункт",
                assignment_number="5",
                section="ministry",
                section_position="2",
                participant_id=sis.id,
                status="unassigned",
            ),
        ]
    )
    session.commit()

    r = assignment_stats(session, date(2026, 9, 1), date(2026, 9, 30))
    assert r["weeks"] == [date(2026, 9, 7), date(2026, 9, 14)]
    people = {p["name"]: p for p in r["people"]}
    assert set(people) == {"Брат", "Сестра", "Без заданий"}  # неактивный без заданий скрыт
    b = people["Брат"]
    assert b["weeks"][date(2026, 9, 7)] == ["living", "prayer"]  # порядок категорий
    assert b["counts"] == {"living": 1, "prayer": 1, "assistant": 1}
    assert b["total"] == 3
    assert people["Сестра"]["total"] == 1  # unassigned не считается
    assert people["Без заданий"]["total"] == 0

    only_sisters = assignment_stats(session, date(2026, 9, 1), date(2026, 9, 30), "female")
    assert [p["name"] for p in only_sisters["people"]] == ["Сестра"]
