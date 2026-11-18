"""Доска месяца: раскладка пунктов по строкам, давность и отметки."""

from datetime import date
from types import SimpleNamespace

from core.month_board import build_month_board


def _a(aid, number, section, atype, text, pid=None, name=None, aid2=None, name2=None):
    return {
        "id": aid,
        "assignment_number": number,
        "section": section,
        "assignment_type": atype,
        "assignment_text": text,
        "participant_id": pid,
        "participant_name": name,
        "assistant_id": aid2,
        "assistant_name": name2,
        "status": "assigned" if pid else "empty",
    }


def _week(wid, start, assignments, special=None):
    return {
        "week": {
            "id": wid,
            "week_title": f"неделя {wid}",
            "start_date": start,
            "special_event": special,
        },
        "assignments": assignments,
    }


def _rows(board):
    return [row["label"] for row in board["rows"]]


def test_rows_merge_weeks_with_different_ministry_count():
    w1 = _week(
        1,
        "2026-11-02",
        [
            _a(1, "chairman", "fixed", "role", "Председатель", 10, "Белых Дмитрий"),
            _a(2, "3", "treasures", "reading", "Чтение Библии", 11, "Тарасюк Тимур"),
            _a(
                3,
                "4",
                "ministry",
                "student",
                "Начинайте разговор",
                12,
                "Белых Ольга",
                13,
                "Медведева Людмила",
            ),
            _a(4, "8", "cbs", "cbs", "Изучение Библии в собрании", 10, "Белых Дмитрий"),
            _a(5, "prayer_close", "fixed", "role", "Молитва (закрытие)", 14, "Ларцев Василий"),
        ],
    )
    w2 = _week(
        2,
        "2026-11-09",
        [
            _a(6, "chairman", "fixed", "role", "Председатель"),
            _a(7, "3", "treasures", "reading", "Чтение Библии", 11, "Тарасюк Тимур"),
            _a(8, "4", "ministry", "student", "Начинайте разговор", 15, "Орлова Полина"),
            _a(9, "5", "ministry", "teaching", "Речь", 16, "Крылов Владимир"),
        ],
    )
    history = [
        (10, date(2026, 11, 2)),
        (10, date(2026, 10, 26)),
        (11, date(2026, 11, 2)),
        (11, date(2026, 11, 9)),
        (12, date(2026, 8, 24)),
    ]
    board = build_month_board([w1, w2], history, elder_ids=[10], conflicts={1: [10]})

    assert _rows(board) == [
        "Председатель",
        "Чтение Библии",
        "Служение · 1",
        "Служение · 2",
        "Изучение Библии",
        "Молитва (конец)",
    ]
    cells = {row["label"]: board["cells"][i] for i, row in enumerate(board["rows"])}

    # нет такого пункта на неделе — None, а не «пусто»
    assert cells["Служение · 2"][0] is None
    assert cells["Служение · 2"][1]["people"][0]["short"] == "Крылов В."
    # пустая клетка
    assert cells["Председатель"][1]["flags"] == ["empty"]
    # давность: 10 недель назад, напарник раньше не выступал
    pair = cells["Служение · 1"][0]["people"]
    assert [p["weeks_since"] for p in pair] == [10, None]
    assert pair[1]["role"] == "assistant"
    # подряд — у брата, не у старейшины; дважды за неделю — из conflicts
    assert "consecutive" in cells["Чтение Библии"][1]["flags"]
    assert "consecutive" not in cells["Председатель"][0]["flags"]
    assert "double" in cells["Председатель"][0]["flags"]
    assert board["summary"] == {
        "assigned": 8,
        "total": 9,
        "empty": 1,
        "double": 2,
        "consecutive": 1,
        "elder_student": 0,
    }


def test_special_week_is_skipped_and_co_week_shows_talk():
    talk = _a(1, "8", "cbs", "cbs", "Изучение Библии в собрании", 5, "Дятлов Леонид")
    reader = _a(2, "8_reader", "cbs", "cbs_reader", "Чтец", 6, "Глебов Алексей")
    co = _week(1, "2026-11-16", [talk, reader], special="circuit_overseer")
    assembly = _week(
        2,
        "2026-11-30",
        [_a(3, "chairman", "fixed", "role", "Председатель")],
        special="circuit_assembly",
    )
    board = build_month_board([co, assembly], [])

    assert board["columns"][1]["special"] == "Районный конгресс"
    assert board["columns"][0]["circuit_overseer"]
    assert _rows(board) == ["Изучение Библии"]
    assert board["cells"][0][0]["people"][0]["name"] == "Районный старейшина"
    assert board["cells"][0][1] is None
    assert board["summary"]["empty"] == 0 and board["summary"]["total"] == 1


def test_get_month_board_reads_history_and_elders():
    from core.database import DatabaseManager
    from core.facade import ApplicationFacade
    from core.models import Assignment, Participant, Week

    db = DatabaseManager(":memory:")
    with db.get_session() as s:
        s.add_all(
            [
                Participant(
                    id=1, name="Старейшина Один", gender="male", is_active=True, service_type="E"
                ),
                Participant(
                    id=2, name="Брат Два", gender="male", is_active=True, service_type="PUB"
                ),
                Week(id=1, week_title="прошлая", start_date=date(2026, 11, 2)),
                Week(id=2, week_title="эта", start_date=date(2026, 11, 9)),
                Assignment(
                    id=1,
                    week_id=1,
                    participant_id=1,
                    assistant_id=2,
                    assignment_text="Беседа",
                    assignment_number="4",
                    section="ministry",
                    status="assigned",
                ),
                Assignment(
                    id=2,
                    week_id=2,
                    participant_id=1,
                    assignment_text="Председатель",
                    assignment_number="chairman",
                    section="fixed",
                    status="assigned",
                ),
                Assignment(
                    id=3,
                    week_id=2,
                    participant_id=2,
                    assignment_text="Чтение Библии",
                    assignment_number="3",
                    section="treasures",
                    status="assigned",
                ),
            ]
        )
        s.commit()

    facade = ApplicationFacade.__new__(ApplicationFacade)
    facade.schedule = SimpleNamespace(
        db=db,
        get_week_data=lambda wid: _week_data(db, wid),
        get_week_conflicts=lambda wid: [],
    )
    board = facade.get_month_board([2])
    cells = {row["label"]: board["cells"][i][0] for i, row in enumerate(board["rows"])}
    assert cells["Председатель"]["people"][0]["elder"]
    assert cells["Председатель"]["flags"] == []
    assert cells["Чтение Библии"]["people"][0]["weeks_since"] == 1
    assert cells["Чтение Библии"]["flags"] == ["consecutive"]


def _week_data(db, week_id):
    from core.repositories.week_repository import WeekRepository

    return WeekRepository(db).get_week_data(week_id)


def test_elder_on_student_assignment_is_flagged():
    from core.assignment_rules import is_student_assignment

    w1 = _week(
        1,
        "2026-11-23",
        [
            _a(1, "3", "treasures", "reading", "Чтение Библии", 93, "Беликов Михаил"),
            _a(2, "4", "ministry", "student", "Начинайте разговор", 12, "Белых Ольга"),
            _a(3, "1", "treasures", "treasures", "Речь", 93, "Беликов Михаил"),
        ],
    )
    board = build_month_board([w1], [], elder_ids=[93])
    flags = [row[0]["flags"] for row in board["cells"]]
    labels = _rows(board)
    assert "elder_student" in flags[labels.index("Чтение Библии")]
    assert "elder_student" not in flags[labels.index("Речь «Сокровища»")]
    assert board["summary"]["elder_student"] == 1
    # обсуждение в «Служении» ведёт старейшина — это не учебное задание
    assert not is_student_assignment(
        {"section": "ministry", "discussion_marker": "(5 мин.) Обсуждение"}
    )


def test_notice_status_per_person_and_summary():
    w1 = _week(
        1,
        "2026-11-02",
        [
            _a(1, "chairman", "fixed", "role", "Председатель", 10, "Белых Дмитрий"),
            _a(2, "3", "treasures", "reading", "Чтение Библии", 11, "Тарасюк Тимур"),
            _a(
                3,
                "4",
                "ministry",
                "student",
                "Начинайте разговор",
                12,
                "Белых Ольга",
                13,
                "Медведева Людмила",
            ),
            _a(4, "8", "cbs", "cbs", "Изучение Библии в собрании", 10, "Белых Дмитрий"),
        ],
    )
    notifications = {
        1: {
            10: {"status": "success", "response": "confirmed"},
            11: {"status": "success", "response": None},
            12: {"status": "success", "response": "declined"},
            13: {"status": "error", "response": None},
        }
    }
    board = build_month_board([w1], [], notifications=notifications)
    people = {
        p["id"]: p["notice"]
        for row in board["cells"]
        for cell in row
        if cell
        for p in cell["people"]
    }
    assert people == {10: "confirmed", 11: "waiting", 12: "declined", 13: "error"}
    ministry = next(
        cell for row in board["cells"] for cell in row if cell and cell["people"][0]["id"] == 12
    )
    assert "declined" in ministry["flags"]
    # Белых Дмитрий дважды на неделе, но в сводке — один раз
    assert board["columns"][0]["notice"] == {"not_notified": 1, "waiting": 1, "declined": 1}
    assert board["notice_summary"] == {"not_notified": 1, "waiting": 1, "declined": 1}


def test_cell_notice_colours_whole_cell():
    from core.month_board import cell_notice

    def people(*notices):
        return [{"id": i + 1, "notice": n} for i, n in enumerate(notices)]

    assert cell_notice([]) == cell_notice([{"id": None, "notice": None}]) is None
    assert cell_notice(people("confirmed", "confirmed")) == "confirmed"
    assert cell_notice(people("confirmed", "waiting")) == "waiting"
    assert cell_notice(people("waiting", None)) is None  # кто-то ещё не уведомлён
    assert cell_notice(people("waiting", "error")) is None
    assert cell_notice(people("confirmed", "declined")) == "declined"

    w1 = _week(
        1,
        "2026-11-02",
        [
            _a(1, "chairman", "fixed", "role", "Председатель", 10, "Белых Дмитрий"),
            _a(2, "3", "treasures", "reading", "Чтение Библии", 11, "Тарасюк Тимур"),
        ],
    )
    board = build_month_board(
        [w1], [], notifications={1: {10: {"status": "success", "response": "confirmed"}}}
    )
    notices = {
        cell["people"][0]["id"]: cell["notice"] for row in board["cells"] for cell in row if cell
    }
    assert notices == {10: "confirmed", 11: None}


def test_notify_week_picks_not_notified_of_that_week(qapp, monkeypatch):
    from ui.month_board_view import MonthBoardView

    weeks = [
        _week(
            1,
            "2026-11-02",
            [
                _a(1, "chairman", "fixed", "role", "Председатель", 10, "Белых Дмитрий"),
                _a(2, "3", "treasures", "reading", "Чтение Библии", 11, "Тарасюк Тимур"),
            ],
        ),
        _week(
            2, "2026-11-09", [_a(3, "chairman", "fixed", "role", "Председатель", 12, "Белых Ольга")]
        ),
    ]
    view = MonthBoardView.__new__(MonthBoardView)
    view.board = build_month_board(weeks, [], notifications={1: {10: {"status": "success"}}})
    calls = []
    monkeypatch.setattr(
        view, "_notify", lambda week_ids, ids: calls.append((week_ids, ids)), raising=False
    )
    view.notify_week(0)
    view.board = build_month_board(
        weeks, [], notifications={1: {10: {"status": "success"}, 11: {"status": "success"}}}
    )
    view.notify_week(0)  # уведомлены все — окно без отбора
    assert calls == [([1], [11]), ([1], None)]


def test_away_flag_marks_person_and_cell():
    """away={week_id: [pid]} ставит флаг 'away' у человека и у клетки."""
    from core.month_board import build_month_board

    w1 = _week(
        1,
        "2026-11-02",
        [
            _a(1, "chairman", "fixed", "role", "Председатель", 10, "Белых Дмитрий"),
            _a(2, "3", "treasures", "reading", "Чтение Библии", 11, "Тарасюк Тимур"),
            _a(3, "4", "ministry", "student", "Начинайте разговор", 12, "Белых Ольга"),
        ],
    )
    board = build_month_board([w1], [], away={1: [12]})
    cells = {row["label"]: board["cells"][i][0] for i, row in enumerate(board["rows"])}

    assert "away" in cells["Служение · 1"]["people"][0]["flags"]
    assert "away" in cells["Служение · 1"]["flags"]
    assert "away" not in cells["Председатель"]["flags"]
    assert "away" not in cells["Председатель"]["people"][0]["flags"]


def test_away_absent_by_default():
    """Без away флага нет."""
    from core.month_board import build_month_board

    w1 = _week(
        1, "2026-11-02", [_a(1, "chairman", "fixed", "role", "Председатель", 10, "Белых Дмитрий")]
    )
    board = build_month_board([w1], [])
    cell = board["cells"][0][0]
    assert "away" not in cell["flags"]
    assert "away" not in cell["people"][0]["flags"]


def test_on_leave_inside_period():
    """Неделя целиком внутри отпуска — True."""
    from core.month_board import on_leave

    assert on_leave(date(2026, 10, 1), date(2026, 10, 31), date(2026, 10, 12))


def test_on_leave_overlaps_by_edge():
    """Неделя пересекается с отпуском краем — True."""
    from core.month_board import on_leave

    # отпуск начинается в середине недели
    assert on_leave(date(2026, 11, 4), date(2026, 11, 30), date(2026, 11, 2))
    # отпуск заканчивается в середине недели
    assert on_leave(date(2026, 10, 1), date(2026, 11, 4), date(2026, 11, 2))


def test_on_leave_before_and_after_period():
    """Неделя вне отпуска — False."""
    from core.month_board import on_leave

    # неделя раньше отпуска
    assert not on_leave(date(2026, 12, 1), date(2026, 12, 31), date(2026, 11, 2))
    # неделя позже отпуска
    assert not on_leave(date(2026, 9, 1), date(2026, 9, 30), date(2026, 11, 2))


def test_on_leave_open_ended():
    """Открытые границы: только from / только to."""
    from core.month_board import on_leave

    assert on_leave(date(2026, 11, 5), None, date(2026, 11, 2))
    assert not on_leave(date(2026, 11, 9), None, date(2026, 11, 2))
    assert on_leave(None, date(2026, 11, 5), date(2026, 11, 2))
    assert not on_leave(None, date(2026, 10, 1), date(2026, 11, 2))


def test_on_leave_both_none():
    """Обе границы None — не в отпуске."""
    from core.month_board import on_leave

    assert not on_leave(None, None, date(2026, 11, 2))


def test_month_problems_lists_flags_by_week():
    from core.month_board import month_problems

    w1 = _week(
        1,
        "2026-11-02",
        [
            _a(1, "3", "treasures", "reading", "Чтение Библии", 11, "Тарасюк Тимур"),
            _a(2, "chairman", "fixed", "role", "Председатель"),
        ],
    )
    w2 = _week(
        2,
        "2026-11-09",
        [
            _a(3, "3", "treasures", "reading", "Чтение Библии", 11, "Тарасюк Тимур"),
        ],
    )
    board = build_month_board([w1, w2], [(11, "2026-11-02"), (11, "2026-11-09")], away={2: [11]})
    problems = month_problems(board, unsuitable=[(1, 11)])
    kinds = [(p["col"], p["kind"]) for p in problems]
    assert (0, "empty") in kinds  # председатель 02.11 пуст
    assert (0, "unsuitable") in kinds  # передано как неподходящий
    assert (1, "away") in kinds and (1, "consecutive") in kinds
    assert [p["col"] for p in problems] == sorted(p["col"] for p in problems)  # по неделям
    assert all(p["text"].startswith(("02.11", "09.11")) for p in problems)


def test_role_talk_cell_label():
    """Клетка речи по обязанности подписана ролью; падения на доске нет (12.11)."""
    w = _week(
        1,
        "2027-02-22",
        [
            {
                "id": 7,
                "section": "ministry",
                "section_position": "1",
                "assignment_type": "chairman_talk",
                "assignment_text": "Подготавливайте учеников",
                "participant_id": 5,
                "participant_name": "Иванов Иван",
            },
        ],
    )
    board = build_month_board([w], [])
    cell = [c for row in board["cells"] for c in row if c][0]
    assert cell["text"] == "Речь председателя"
