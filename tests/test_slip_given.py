"""«🧾 Листок выдан»: отметка у пункта, сброс при смене человека, доска и синхронизация."""

from datetime import date, datetime

import pytest

from core.database import DatabaseManager
from core.models import Assignment, Participant, Week
from core.month_board import build_month_board
from core.repositories.assignment_repository import AssignmentRepository


def _fill(db):
    with db.get_session() as s:
        s.add_all(
            [
                Participant(id=1, name="Анна Петрова", gender="female", is_active=True),
                Participant(id=2, name="Мария Сидорова", gender="female", is_active=True),
                Week(id=1, week_title="1–7 марта", start_date=date(2027, 3, 1)),
                Assignment(
                    id=10,
                    week_id=1,
                    section="ministry",
                    assignment_text="Беседа",
                    assignment_number="4",
                    section_position="1",
                    participant_id=1,
                    status="assigned",
                ),
                Assignment(
                    id=20,
                    week_id=1,
                    section="ministry",
                    assignment_text="Повторное",
                    assignment_number="5",
                    section_position="2",
                    status="empty",
                ),
            ]
        )
        s.commit()


@pytest.fixture
def db():
    db = DatabaseManager(":memory:")
    _fill(db)
    yield db
    db.close()


def _slip(db, aid):
    with db.get_session() as s:
        return s.get(Assignment, aid).slip_given_at


def test_mark_and_unmark(db):
    repo = AssignmentRepository(db)
    assert repo.set_slip_given([10], True)
    assert _slip(db, 10) is not None
    assert repo.set_slip_given([10], False)
    assert _slip(db, 10) is None


def test_changing_person_clears_mark_but_other_edits_do_not(db):
    repo = AssignmentRepository(db)
    repo.set_slip_given([10], True)
    with db.get_session() as s:
        s.get(Assignment, 10).duration = 7  # не про человека — отметка остаётся
        s.commit()
    assert _slip(db, 10) is not None
    repo.assign_participant(10, 2, "participant")  # другой человек — нужен новый листок
    assert _slip(db, 10) is None


def test_board_shows_mark_and_week_counter(db):
    from core.repositories.week_repository import WeekRepository

    AssignmentRepository(db).set_slip_given([10], True)
    data = WeekRepository(db).get_week_data(1)
    board = build_month_board([data], [])
    cells = [row[0] for row in board["cells"] if row[0]]
    by_id = {c["assignment_id"]: c for c in cells}
    assert by_id[10]["slip"] is True
    assert by_id[20]["slip"] is False  # пустой пункт — листка нет
    column = board["columns"][0]
    assert (column["slips_given"], column["slips_total"]) == (1, 1)


def test_newer_mark_on_tablet_reaches_pc(tmp_path):
    from core.sync_service import DatabaseMerger

    pc, tablet = str(tmp_path / "pc.db"), str(tmp_path / "tablet.db")
    for path in (pc, tablet):
        db = DatabaseManager(path)
        _fill(db)
        db.close()
    db = DatabaseManager(tablet)
    AssignmentRepository(db).set_slip_given([10], True)
    db.close()

    assert DatabaseMerger(pc, tablet).merge()

    db = DatabaseManager(pc)
    assert _slip(db, 10) is not None
    db.close()
