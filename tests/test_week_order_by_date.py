"""Недели в письмах и в списке недель участника идут по дате, а не по номеру записи.

В рабочей базе номер недели с датой не совпадает (недели добавляются из тетрадей
и «Будущего года» вперемешку): например, 22.02.2027 — номер 130, 01.03.2027 — 77.
"""

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
                    id=1, name="Иван Тестов", gender="male", is_active=True, email="i@example.com"
                ),
                # Номер записи у поздней недели меньше, чем у ранней
                Week(id=77, week_title="1–7 марта", start_date=date(2027, 3, 1)),
                Week(id=130, week_title="22–28 февраля", start_date=date(2027, 2, 22)),
                Assignment(
                    id=1,
                    week_id=77,
                    participant_id=1,
                    section="treasures",
                    assignment_text="Речь",
                    duration=10,
                    status="assigned",
                    sort_order=0,
                ),
                Assignment(
                    id=2,
                    week_id=130,
                    participant_id=1,
                    section="treasures",
                    assignment_text="Речь",
                    duration=10,
                    status="assigned",
                    sort_order=0,
                ),
            ]
        )
        s.commit()
    yield db
    db.close()


def test_notification_weeks_are_in_date_order(db):
    service = NotificationService(
        smtp_host="",
        smtp_port=465,
        smtp_user="",
        smtp_password="",
        meeting_day="Среда",
        meeting_time="19:00",
    )
    data = service._collect_assignments([77, 130], db)
    assert [w["week_id"] for w in data[1]["weeks"]] == [130, 77]


def test_participant_week_list_is_in_date_order(db):
    from core.base_facade import BaseApplicationFacade

    class _Facade:
        schedule = type("S", (), {"db": db})()

    get = BaseApplicationFacade.get_participant_assignment_week_ids
    assert get(_Facade(), 1) == [130, 77]
    # От текущей недели 22.02: сначала она и будущие по возрастанию даты
    assert get(_Facade(), 1, current_week_id=130) == [130, 77]
    # От 01.03: она, потом прошлые по убыванию
    assert get(_Facade(), 1, current_week_id=77) == [77, 130]
