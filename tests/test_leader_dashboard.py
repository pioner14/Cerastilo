"""Пульт руководителя встречи: список дел и ближайшая встреча."""

from datetime import date, datetime

from core.leader_dashboard import build_todos, next_meeting
from core.month_board import build_month_board
from tests.test_month_board import _a, _week

TODAY = date(2026, 11, 4)


def _board(notifications=None):
    weeks = [
        _week(
            1,
            "2026-11-02",
            [
                _a(1, "chairman", "fixed", "role", "Председатель", 10, "Белых Дмитрий"),
                _a(2, "3", "treasures", "reading", "Чтение Библии", 11, "Тарасюк Тимур"),
                _a(3, "4", "ministry", "student", "Начинайте разговор", 12, "Белых Ольга"),
            ],
        ),
        _week(
            2,
            "2026-11-09",
            [
                _a(4, "chairman", "fixed", "role", "Председатель"),
                _a(5, "3", "treasures", "reading", "Чтение Библии", 13, "Орлова Полина"),
            ],
        ),
        _week(3, "2026-11-16", [], special="circuit_assembly"),
    ]
    return build_month_board(weeks, [], notifications=notifications or {})


def _kinds(todos):
    return [t["kind"] for t in todos]


def test_todos_in_order_of_importance():
    board = _board(
        {
            1: {
                10: {"status": "success", "response": "declined", "sent_at": datetime(2026, 11, 1)},
                11: {"status": "success", "sent_at": datetime(2026, 10, 30)},  # 5 дней без ответа
                12: {"status": "success", "sent_at": datetime(2026, 11, 3)},
            },  # вчера — ждём
        }
    )
    todos = build_todos(
        board, TODAY, {"title": "Декабрь 2026", "week_ids": [7], "assigned": 0, "total": 9}
    )
    assert _kinds(todos) == ["declined", "empty", "waiting", "not_notified", "unassigned"]
    by_kind = {t["kind"]: t for t in todos}
    assert "Белых Дмитрий" in by_kind["declined"]["text"]
    assert by_kind["declined"]["week_ids"] == [1]
    assert by_kind["empty"]["week_ids"] == [2]
    assert by_kind["not_notified"]["participant_ids"] == [13]
    assert by_kind["waiting"]["participant_ids"] == [11]


def test_not_notified_only_for_coming_week():
    """О заданиях сообщают листками; «не уведомлены» — только за неделю до начала."""
    board = _board(
        {1: {pid: {"status": "success", "response": "confirmed"} for pid in (10, 11, 12)}}
    )
    assert "not_notified" in _kinds(build_todos(board, TODAY))  # 09.11 — через 5 дней
    assert "not_notified" not in _kinds(build_todos(board, date(2026, 10, 30)))  # через 10 дней


def test_next_month_without_program_and_all_done():
    board = _board(
        {
            1: {pid: {"status": "success", "response": "confirmed"} for pid in (10, 11, 12)},
            2: {13: {"status": "success", "response": "confirmed"}},
        }
    )
    no_program = build_todos(
        board, TODAY, {"title": "Декабрь 2026", "week_ids": [], "assigned": 0, "total": 0}
    )
    assert _kinds(no_program) == ["empty", "no_program"]
    done = build_todos(
        board, TODAY, {"title": "Декабрь 2026", "week_ids": [7], "assigned": 3, "total": 9}
    )
    assert _kinds(done) == ["empty"]  # частично распределённый месяц — не дело


def test_next_meeting_is_current_week_and_skips_special():
    board = _board()
    meeting = next_meeting(board, TODAY)
    assert meeting["column"]["week_id"] == 1
    assert [i["label"] for i in meeting["items"]] == [
        "Председатель",
        "Чтение Библии",
        "Служение · 1",
    ]
    # с 16.11 — неделя конгресса, встречи нет и дальше недель нет
    assert next_meeting(board, date(2026, 11, 16)) is None
    assert next_meeting(board, date(2026, 11, 10))["column"]["week_id"] == 2


def test_get_leader_dashboard_reads_upcoming_and_next_month():
    from types import SimpleNamespace

    from core.database import DatabaseManager
    from core.facade import ApplicationFacade
    from core.models import Assignment, Participant, Week
    from tests.test_month_board import _week_data

    db = DatabaseManager(":memory:")
    with db.get_session() as s:
        s.add_all(
            [
                Participant(
                    id=1, name="Брат Один", gender="male", is_active=True, service_type="PUB"
                ),
                Week(id=1, week_title="прошлая", start_date=date(2026, 10, 26)),
                Week(id=2, week_title="эта", start_date=date(2026, 11, 2)),
                Week(id=3, week_title="декабрь", start_date=date(2026, 12, 7)),
                Assignment(
                    id=1,
                    week_id=2,
                    participant_id=1,
                    assignment_text="Председатель",
                    assignment_number="chairman",
                    section="fixed",
                    status="assigned",
                ),
                Assignment(
                    id=2,
                    week_id=3,
                    assignment_text="Председатель",
                    assignment_number="chairman",
                    section="fixed",
                    status="empty",
                ),
            ]
        )
        s.commit()

    facade = ApplicationFacade.__new__(ApplicationFacade)
    facade.schedule = SimpleNamespace(
        db=db,
        get_week_data=lambda wid: _week_data(db, wid),
        get_week_conflicts=lambda wid: [],
        get_weeks_tree=lambda: {
            "2026": {
                "Октябрь": [{"id": 1, "title": "прошлая", "start_date": "2026-10-26"}],
                "Ноябрь": [{"id": 2, "title": "эта", "start_date": "2026-11-02"}],
                "Декабрь": [{"id": 3, "title": "декабрь", "start_date": "2026-12-07"}],
            }
        },
    )
    data = facade.get_leader_dashboard(today=TODAY)
    assert [c["week_id"] for c in data["board"]["columns"]] == [2, 3]  # прошлая неделя не смотрится
    assert data["meeting"]["column"]["week_id"] == 2
    kinds = _kinds(data["todos"])
    assert kinds == ["empty", "not_notified", "unassigned"]
    assert data["todos"][-1]["text"] == "Декабрь 2026: не распределён"


def test_dashboard_view_renders_and_routes_actions(qapp):
    from ui.leader_dashboard_view import LeaderDashboardView

    board = _board()
    data = {
        "todos": build_todos(board, TODAY, None),
        "meeting": next_meeting(board, TODAY),
        "board": board,
    }

    class Facade:
        def get_leader_dashboard(self):
            return data

    view = LeaderDashboardView(Facade())
    view.load_data()
    assert view.todo_box.count() == 2  # пустой пункт, не уведомлены
    assert view.meeting_grid.rowCount() >= 3

    opened = []
    view.open_month.connect(opened.append)
    view.run_todo(data["todos"][0])
    assert opened == [2]

    data["todos"] = []
    view.load_data()
    assert view.todo_box.count() == 1  # «Всё готово»


def test_first_steps_until_everything_is_filled():
    from core.leader_dashboard import first_steps

    empty = first_steps({})
    assert [s["key"] for s in empty] == [
        "congregation",
        "participants",
        "qualifications",
        "program",
        "assigned",
    ]
    assert not any(s["done"] for s in empty)
    partial = first_steps({"has_congregation": True, "participants": 5, "weeks": 3})
    assert {s["key"]: s["done"] for s in partial} == {
        "congregation": True,
        "participants": True,
        "qualifications": False,
        "program": True,
        "assigned": False,
    }
    assert (
        first_steps(
            {
                "has_congregation": True,
                "participants": 5,
                "with_qualifications": 5,
                "weeks": 3,
                "assigned": 1,
            }
        )
        == []
    )


def test_first_steps_counts_on_real_database():
    from types import SimpleNamespace

    from core.database import DatabaseManager
    from core.facade import ApplicationFacade
    from core.models import Participant, participant_qualifications

    db = DatabaseManager(":memory:")
    facade = ApplicationFacade.__new__(ApplicationFacade)
    facade.schedule = SimpleNamespace(db=db)
    assert facade._first_steps_counts()["participants"] == 0
    with db.get_session() as s:
        s.add(Participant(id=1, name="Брат Один", gender="male", is_active=True))
        s.flush()
        s.execute(
            participant_qualifications.insert().values(
                participant_id=1, qualification_name="prayer"
            )
        )
        s.commit()
    counts = facade._first_steps_counts()
    assert (counts["participants"], counts["with_qualifications"], counts["assigned"]) == (1, 1, 0)


def test_dashboard_shows_first_steps_and_opens_tab(qapp):
    from core.leader_dashboard import first_steps
    from ui.leader_dashboard_view import LeaderDashboardView

    data = {
        "todos": [],
        "meeting": None,
        "board": None,
        "first_steps": first_steps({"has_congregation": True}),
    }

    class Facade:
        def get_leader_dashboard(self):
            return data

    view = LeaderDashboardView(Facade())
    view.load_data()
    assert not view.steps_title.isHidden() and view.steps_box.count() == 5
    opened = []
    view.open_tab.connect(opened.append)
    from PySide6.QtWidgets import QPushButton

    view.steps_box.itemAt(1).widget().findChild(QPushButton).click()
    assert opened == ["participants"]

    data["first_steps"] = []
    view.load_data()
    assert view.steps_title.isHidden() and view.steps_box.count() == 0
