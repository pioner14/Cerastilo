"""Обмен местами одной транзакцией и статус пункта, когда на нём остался только напарник."""

from datetime import date

import pytest

from core.database import DatabaseManager
from core.models import Assignment, Participant, Week
from core.repositories.assignment_repository import AssignmentRepository


@pytest.fixture
def db():
    db = DatabaseManager(":memory:")
    with db.get_session() as s:
        s.add_all(
            [
                Participant(id=1, name="Анна", gender="female", is_active=True),
                Participant(id=2, name="Мария", gender="female", is_active=True),
                Participant(id=3, name="Ольга", gender="female", is_active=True),
                Week(id=1, week_title="1–7 марта", start_date=date(2027, 3, 1)),
                Assignment(
                    id=10,
                    week_id=1,
                    section="ministry",
                    assignment_text="Беседа",
                    participant_id=1,
                    assistant_id=2,
                    status="assigned",
                ),
                Assignment(
                    id=20,
                    week_id=1,
                    section="ministry",
                    assignment_text="Повторное",
                    participant_id=3,
                    status="assigned",
                ),
            ]
        )
        s.commit()
    yield db
    db.close()


def _row(db, aid):
    with db.get_session() as s:
        a = s.get(Assignment, aid)
        return a.participant_id, a.assistant_id, a.status


def test_removing_main_keeps_item_assigned_while_assistant_stays(db):
    repo = AssignmentRepository(db)
    assert repo.assign_participant(10, None, "participant")
    assert _row(db, 10) == (None, 2, "assigned")
    # Сняли и напарника — пункт пустой
    assert repo.assign_participant(10, None, "assistant")
    assert _row(db, 10) == (None, None, "empty")


def test_assistant_alone_makes_empty_item_assigned(db):
    repo = AssignmentRepository(db)
    repo.assign_participant(20, None, "participant")
    assert _row(db, 20) == (None, None, "empty")
    repo.assign_participant(20, 2, "assistant")
    assert _row(db, 20) == (None, 2, "assigned")


def test_swap_main_with_assistant_of_other_item(db):
    repo = AssignmentRepository(db)
    assert repo.swap_people(20, "participant", 10, "assistant")
    assert _row(db, 20) == (2, None, "assigned")
    assert _row(db, 10) == (1, 3, "assigned")


def test_swap_failure_leaves_both_items_untouched(db, monkeypatch):
    repo = AssignmentRepository(db)
    calls = []
    original = AssignmentRepository._set_person

    def flaky(assignment, pid, role):
        calls.append(pid)
        if len(calls) == 2:
            raise RuntimeError("сбой посреди обмена")
        original(assignment, pid, role)

    monkeypatch.setattr(AssignmentRepository, "_set_person", staticmethod(flaky))
    assert repo.swap_people(10, "participant", 20, "participant") is False
    assert _row(db, 10) == (1, 2, "assigned")
    assert _row(db, 20) == (3, None, "assigned")


def test_restore_people_returns_both_roles_in_one_step(db):
    repo = AssignmentRepository(db)
    repo.assign_participant(10, None, "participant")
    repo.assign_participant(10, None, "assistant")
    assert repo.restore_people([{"id": 10, "participant_id": 1, "assistant_id": 2}])
    assert _row(db, 10) == (1, 2, "assigned")
