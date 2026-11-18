"""Время пункта в уведомлении — как в таблице расписания, а не начало встречи."""

from datetime import date

import pytest

from core.database import DatabaseManager
from core.models import Assignment, Participant, Week
from core.notification_service import NotificationService


@pytest.fixture
def db():
    db = DatabaseManager(":memory:")
    with db.get_session() as s:
        s.add_all(
            [
                Participant(
                    id=1, name="Григорий Тестов", gender="male", is_active=True, email="g@example.com"
                ),
                Participant(id=2, name="Иван Ведущий", gender="male", is_active=True),
                Participant(id=3, name="Пётр Чтец", gender="male", is_active=True),
                Week(id=1, week_title="23–29 ноября", start_date=date(2026, 11, 23)),
                Assignment(
                    id=1,
                    week_id=1,
                    participant_id=2,
                    section="fixed",
                    section_position="chairman",
                    assignment_text="Председатель",
                    status="assigned",
                    sort_order=0,
                ),
                Assignment(
                    id=2,
                    week_id=1,
                    participant_id=1,
                    section="fixed",
                    section_position="prayer_open",
                    assignment_text="Молитва (вступ.)",
                    status="assigned",
                    sort_order=1,
                ),
                Assignment(
                    id=3,
                    week_id=1,
                    participant_id=2,
                    section="treasures",
                    assignment_text="Речь",
                    duration=10,
                    status="assigned",
                    sort_order=2,
                ),
                Assignment(
                    id=4,
                    week_id=1,
                    participant_id=2,
                    section="cbs",
                    assignment_type="cbs",
                    assignment_text="Изучение Библии в собрании",
                    duration=30,
                    status="assigned",
                    sort_order=3,
                ),
                Assignment(
                    id=5,
                    week_id=1,
                    participant_id=3,
                    section="cbs",
                    assignment_type="cbs_reader",
                    assignment_text="Чтец ИБС",
                    status="assigned",
                    sort_order=4,
                ),
                Assignment(
                    id=6,
                    week_id=1,
                    participant_id=1,
                    section="fixed",
                    section_position="prayer_close",
                    assignment_text="Молитва (закл.)",
                    status="assigned",
                    sort_order=5,
                ),
            ]
        )
        s.commit()
    yield db
    db.close()


def _service():
    return NotificationService(
        smtp_host="",
        smtp_port=465,
        smtp_user="",
        smtp_password="",
        meeting_day="Среда",
        meeting_time="19:00",
    )


def test_closing_prayer_gets_its_own_time_not_meeting_start(db):
    data = _service()._collect_assignments([1], db)
    items = data[1]["weeks"][0]["items"]
    # 19:00 + 6 (вступление) + 10 (речь) + 5 (песня) + 30 (ИБС) + 3 (закл. слова) = 19:54
    assert any(it.startswith("в 19:54 — ") and "Молитва (закл.)" in it for it in items), items
    assert any(it.startswith("в 19:01 — ") and "Молитва (вступ.)" in it for it in items), items


def test_cbs_reader_gets_cbs_start_time(db):
    data = _service()._collect_assignments([1], db)
    items = data[3]["weeks"][0]["items"]
    # ИБС начинается после речи и песни: 19:00 + 6 + 10 + 5 = 19:21
    assert items[0].startswith("в 19:21 — "), items


def test_ics_summary_carries_item_time(db):
    service = _service()
    data = service._collect_assignments([1], db)
    ics = service._build_ics_for_participant(data[3]).replace("\r\n ", "")
    assert "SUMMARY:Встреча собрания: в 19:21 — " in ics
