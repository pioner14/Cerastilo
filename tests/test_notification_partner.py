"""Партнёр/помощник в пунктах уведомления."""

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
                Participant(id=1, name="Иванова Мария", gender="female", is_active=True),
                Participant(id=2, name="Петрова Анна", gender="female", is_active=True),
                Participant(id=3, name="Иванов Пётр", gender="male", is_active=True),
                Week(id=1, week_title="8–14 февраля", start_date=date(2027, 2, 8)),
                Assignment(
                    id=1,
                    week_id=1,
                    participant_id=1,
                    assistant_id=2,
                    section="ministry",
                    section_position="6",
                    assignment_text="Начинайте разговор",
                    duration=3,
                    status="assigned",
                    sort_order=0,
                ),
                Assignment(
                    id=2,
                    week_id=1,
                    participant_id=3,
                    section="treasures",
                    assignment_text="Речь",
                    duration=10,
                    status="assigned",
                    sort_order=1,
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


def test_participant_item_contains_partner_assistant(db):
    data = _service()._collect_assignments([1], db)
    items = data[1]["weeks"][0]["items"]
    assert any(
        "Начинайте разговор (3 мин.) — помощница: Петрова Анна" in it for it in items
    ), items


def test_assistant_item_contains_participant(db):
    data = _service()._collect_assignments([1], db)
    items = data[2]["weeks"][0]["items"]
    assert any(
        "Начинайте разговор (3 мин.) (помощница) — учащаяся: Иванова Мария" in it for it in items
    ), items


def test_item_without_partner_has_no_partner_marks(db):
    data = _service()._collect_assignments([1], db)
    items = data[3]["weeks"][0]["items"]
    assert not any(" — помощ" in it for it in items), items
    assert not any("учащ" in it for it in items), items


def test_filtered_collection_still_shows_participant_for_assistant(db):
    data = _service()._collect_assignments([1], db, participant_ids=[2])
    items = data[2]["weeks"][0]["items"]
    assert any("Иванова Мария" in it for it in items), items
