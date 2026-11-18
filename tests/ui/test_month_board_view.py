"""Доска месяца: панель кандидатов и назначение прямо с доски."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from PySide6.QtCore import Qt

from core.month_board import build_month_board
from ui.candidates import by_rest, list_candidates
from ui.month_board_view import MonthBoardView

PEOPLE = [
    {"id": 1, "name": "Белых Дмитрий", "gender": "male", "qualifications": "reading"},
    {"id": 2, "name": "Тарасюк Тимур", "gender": "male", "qualifications": "reading"},
    {"id": 3, "name": "Белых Ольга", "gender": "female", "qualifications": "reading"},
    {"id": 4, "name": "Новиков Пётр", "gender": "male", "qualifications": "reading"},
    {"id": 5, "name": "Ершов Иван", "gender": "male", "qualifications": ""},
    {
        "id": 6,
        "name": "Беликов Михаил",
        "gender": "male",
        "qualifications": "reading",
        "service_type": "E",
    },
]


def _facade():
    """Две недели: чтение Библии (только братья, квалификация reading); вторая — конгресс."""
    weeks = [
        {
            "week": {
                "id": 10,
                "week_title": "2–8 ноября",
                "start_date": "2026-11-02",
                "special_event": None,
            },
            "assignments": [
                {
                    "id": 100,
                    "assignment_number": "3",
                    "section": "treasures",
                    "assignment_type": "reading",
                    "assignment_text": "Чтение Библии",
                    "participant_id": None,
                    "participant_name": None,
                    "status": "empty",
                }
            ],
        },
        {
            "week": {
                "id": 11,
                "week_title": "9–15 ноября",
                "start_date": "2026-11-09",
                "special_event": "circuit_assembly",
            },
            "assignments": [],
        },
    ]
    facade = MagicMock()
    facade.get_month_board.side_effect = lambda ids: build_month_board(weeks, [])
    facade.get_assignment.return_value = {
        "id": 100,
        "week_id": 10,
        "section": "treasures",
        "section_position": "3",
        "assignment_type": "reading",
        "assignment_text": "Чтение Библии",
        "participant_id": None,
    }
    facade.get_assignment_config.return_value = SimpleNamespace(
        is_brothers_only=True, required_qualification="reading"
    )
    facade.get_week_data.return_value = weeks[0]
    facade.get_participant.side_effect = lambda pid: next(p for p in PEOPLE if p["id"] == pid)
    facade.get_all_participants.return_value = PEOPLE
    facade.get_candidate_stats.return_value = {
        1: {"count": 5, "last_date": date(2026, 10, 26), "last_text": "Чтение", "busy": False},
        2: {"count": 2, "last_date": date(2026, 8, 3), "last_text": "Чтение", "busy": False},
        4: {"count": 1, "last_date": None, "last_text": "", "busy": True},
    }
    return facade


def test_candidates_filtered_and_longest_rested_first():
    names = [c["name"] for c in by_rest(list_candidates(_facade(), 100))]
    # сестра и брат без квалификации отсеяны; Тарасюк не выступал дольше всех,
    # занятый на этой неделе — в конце
    # старейшина на учебном задании (чтение Библии) — в самом конце, с пометкой
    assert names == ["Тарасюк Тимур", "Белых Дмитрий", "Новиков Пётр", "Беликов Михаил"]
    elder = by_rest(list_candidates(_facade(), 100))[-1]
    assert elder["elder_warning"] and "старейшина" in elder["hint"]


def test_double_click_candidate_assigns_to_selected_cell(qapp):
    facade = _facade()
    view = MonthBoardView(facade)
    view.show_weeks([10, 11])
    view.table.setCurrentCell(0, 0)
    assert view.selected == (0, 0)
    first = view.candidates.item(0)
    assert first.data(Qt.ItemDataRole.UserRole) == 2
    view._on_candidate_double_clicked(first)
    facade.assign_participant.assert_called_once_with(100, 2, "participant")
    assert view.selected == (0, 0)  # после перерисовки клетка осталась выбранной


def test_drop_assigns_only_on_real_cells(qapp):
    facade = _facade()
    view = MonthBoardView(facade)
    view.show_weeks([10, 11])
    assert view._assignment_id_at(0, 1) is None  # конгресс — встречи нет
    view.table.participant_dropped.emit(0, 0, 1)
    facade.assign_participant.assert_called_once_with(100, 1, "participant")


def test_drop_on_other_cell_rechecks_eligibility(qapp):
    """Кандидаты — для выбранной клетки; бросить на другую можно только подходящего."""
    from unittest.mock import patch

    facade = _facade()
    view = MonthBoardView(facade)
    view.show_weeks([10, 11])
    assert view.selected is None
    with patch("ui.month_board_view.QMessageBox.information") as info:
        view.table.participant_dropped.emit(0, 0, 3)  # сестра на «Чтение Библии»
    info.assert_called_once()
    facade.assign_participant.assert_not_called()


def test_no_selection_shows_prompt(qapp):
    view = MonthBoardView(_facade())
    view.show_weeks([10, 11])
    assert view.selected is None
    assert view.candidates.count() == 1
    assert view.candidates.item(0).data(Qt.ItemDataRole.UserRole) is None


def test_elder_on_student_assignment_asks_before_assigning(qapp):
    from unittest.mock import patch

    from PySide6.QtWidgets import QMessageBox

    facade = _facade()
    view = MonthBoardView(facade)
    view.show_weeks([10, 11])
    with patch(
        "ui.candidates.QMessageBox.question", return_value=QMessageBox.StandardButton.No
    ) as ask:
        view.table.participant_dropped.emit(0, 0, 6)
    ask.assert_called_once()
    facade.assign_participant.assert_not_called()
    with patch("ui.candidates.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
        view.table.participant_dropped.emit(0, 0, 6)
    facade.assign_participant.assert_called_once_with(100, 6, "participant")


def test_candidate_list_has_no_horizontal_scroll(qapp):
    view = MonthBoardView(_facade())
    policy = view.candidates.horizontalScrollBarPolicy()
    assert policy == Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def test_empty_week_ids_skips_started_and_special_weeks(qapp):
    def week(wid, start, pid=None, special=None):
        assignments = (
            []
            if special
            else [
                {
                    "id": wid * 10,
                    "assignment_number": "3",
                    "section": "treasures",
                    "assignment_type": "reading",
                    "assignment_text": "Чтение Библии",
                    "participant_id": pid,
                    "participant_name": "Тарасюк Тимур" if pid else None,
                    "status": "assigned" if pid else "empty",
                },
                {
                    "id": wid * 10 + 1,
                    "assignment_number": "chairman",
                    "section": "fixed",
                    "assignment_type": "role",
                    "assignment_text": "Председатель",
                    "participant_id": None,
                    "participant_name": None,
                    "status": "empty",
                },
            ]
        )
        return {
            "week": {
                "id": wid,
                "week_title": str(wid),
                "start_date": start,
                "special_event": special,
            },
            "assignments": assignments,
        }

    weeks = [
        week(1, "2026-11-02", pid=2),
        week(2, "2026-11-09"),
        week(3, "2026-11-16", special="memorial"),
        week(4, "2026-11-23"),
    ]
    facade = MagicMock()
    facade.get_month_board.side_effect = lambda ids: build_month_board(weeks, [])
    view = MonthBoardView(facade)
    view.show_weeks([1, 2, 3, 4])
    # неделя 1 начата (один пункт назначен), 3 — Вечеря: не трогаем
    assert view.empty_week_ids() == [2, 4]


def test_auto_assign_weeks_runs_in_order_and_stops_on_error():
    from core.base_facade import BaseApplicationFacade

    calls = []

    def auto_assign_week(week_id):
        calls.append(week_id)
        return {"success": week_id != 3, "count": 5, "error": "нет кандидатов"}

    fake = SimpleNamespace(auto_assign_week=auto_assign_week)
    ok = BaseApplicationFacade.auto_assign_weeks(fake, [1, 2])
    assert ok == {"success": True, "count": 10, "weeks": 2, "error": None}
    calls.clear()
    bad = BaseApplicationFacade.auto_assign_weeks(fake, [2, 3, 4])
    assert calls == [2, 3]  # после ошибки дальше не идём
    assert bad == {"success": False, "count": 5, "weeks": 1, "error": "нет кандидатов"}


def test_notify_button_sends_only_to_not_notified(qapp, monkeypatch):
    """«✉ Уведомить» в сводке: письма тем, кому не писали; недели — без особых."""
    week = {
        "week": {
            "id": 10,
            "week_title": "2–8 ноября",
            "start_date": "2026-11-02",
            "special_event": None,
        },
        "assignments": [
            {
                "id": 100,
                "assignment_number": "3",
                "section": "treasures",
                "assignment_type": "reading",
                "assignment_text": "Чтение Библии",
                "participant_id": 1,
                "participant_name": "Белых Дмитрий",
                "status": "assigned",
            },
            {
                "id": 101,
                "assignment_number": "4",
                "section": "ministry",
                "assignment_type": "student",
                "assignment_text": "Разговор",
                "participant_id": 3,
                "participant_name": "Белых Ольга",
                "assistant_id": 2,
                "assistant_name": "Тарасюк Тимур",
                "status": "assigned",
            },
        ],
    }
    special = {
        "week": {
            "id": 11,
            "week_title": "9–15 ноября",
            "start_date": "2026-11-09",
            "special_event": "circuit_assembly",
        },
        "assignments": [],
    }
    notices = {
        10: {1: {"status": "success", "response": None}, 2: {"status": "error", "response": None}}
    }
    facade = MagicMock()
    facade.get_month_board.side_effect = lambda ids: build_month_board(
        [week, special], [], notifications=notices
    )
    sent = []

    class FakeDialog:
        def __init__(self, facade, week_ids, parent=None, only_participant_ids=None):
            sent.append((week_ids, only_participant_ids))

        def exec(self):
            return 1

    monkeypatch.setattr("ui.notification_dialog.NotificationDialog", FakeDialog)
    view = MonthBoardView(facade)
    view.show_weeks([10, 11])
    view.notify_not_notified()
    # Белых Д. уже уведомлён; Тарасюк — письмо не ушло, Белых О. — не писали
    assert sent == [([10], [3, 2])]


def test_weeks_with_gaps_includes_started_weeks(qapp):
    """«Авто» в месяце: недели, где есть хоть один пустой пункт, в том числе начатые."""

    def week(wid, start, pids=(None, None), special=None):
        assignments = (
            []
            if special
            else [
                {
                    "id": wid * 10 + i,
                    "assignment_number": str(i),
                    "section": "treasures",
                    "assignment_type": "reading",
                    "assignment_text": "Чтение Библии",
                    "participant_id": pid,
                    "participant_name": "Тарасюк Тимур" if pid else None,
                    "status": "assigned" if pid else "empty",
                }
                for i, pid in enumerate(pids)
            ]
        )
        return {
            "week": {
                "id": wid,
                "week_title": str(wid),
                "start_date": start,
                "special_event": special,
            },
            "assignments": assignments,
        }

    weeks = [
        week(1, "2026-11-02", pids=(2, None)),
        week(2, "2026-11-09", pids=(2, 3)),
        week(3, "2026-11-16", special="memorial"),
        week(4, "2026-11-23"),
    ]
    facade = MagicMock()
    facade.get_month_board.side_effect = lambda ids: build_month_board(weeks, [])
    view = MonthBoardView(facade)
    view.show_weeks([1, 2, 3, 4])
    assert view.weeks_with_gaps() == [1, 4]  # 2 — заполнена, 3 — Вечеря


def test_check_month_lists_problems_and_jumps_to_cell(qapp, monkeypatch):
    """«🔍 Проверить месяц»: список проблем, выбор строки выделяет клетку."""
    import ui.month_board_view as mbv

    weeks = [
        {
            "week": {"id": 1, "week_title": "1", "start_date": "2026-11-02", "special_event": None},
            "assignments": [
                {
                    "id": 10,
                    "assignment_number": "3",
                    "section": "treasures",
                    "assignment_type": "reading",
                    "assignment_text": "Чтение Библии",
                    "participant_id": 2,
                    "participant_name": "Тарасюк Тимур",
                    "status": "assigned",
                },
                {
                    "id": 11,
                    "assignment_number": "chairman",
                    "section": "fixed",
                    "assignment_type": "role",
                    "assignment_text": "Председатель",
                    "participant_id": None,
                    "participant_name": None,
                    "status": "empty",
                },
            ],
        },
    ]
    facade = MagicMock()
    facade.get_month_board.side_effect = lambda ids: build_month_board(weeks, [])
    # Тарасюк не проходит фильтр кандидатов своего пункта
    monkeypatch.setattr(
        mbv,
        "list_candidates",
        lambda f, aid, role: [
            {
                "id": 99,
                "name": "Другой",
                "hint": "",
                "tooltip": "",
                "kind": None,
                "weeks_since": None,
                "busy": False,
                "elder_warning": False,
                "pair_count": 0,
            }
        ],
    )
    view = MonthBoardView(facade)
    view.show_weeks([1])

    view.check_month()
    dialog = view._check_dialog
    texts = [dialog.list.item(i).text() for i in range(dialog.list.count())]
    assert any("пусто" in t for t in texts)
    assert any("не подходит" in t for t in texts)
    target = next(
        i for i in range(dialog.list.count()) if "не подходит" in dialog.list.item(i).text()
    )
    dialog.list.setCurrentRow(target)
    row, col = dialog.list.item(target).data(Qt.ItemDataRole.UserRole)
    assert (view.table.currentRow(), view.table.currentColumn()) == (row, col)
    dialog.close()


def _one_week_view(notifications=None):
    weeks = [
        {
            "week": {"id": 1, "week_title": "1", "start_date": "2026-11-02", "special_event": None},
            "assignments": [
                {
                    "id": 10,
                    "assignment_number": "3",
                    "section": "treasures",
                    "assignment_type": "reading",
                    "assignment_text": "Чтение Библии",
                    "participant_id": 2,
                    "participant_name": "Тарасюк Тимур",
                    "status": "assigned",
                }
            ],
        },
    ]
    facade = MagicMock()
    facade.get_month_board.side_effect = lambda ids: build_month_board(
        weeks, [], notifications=notifications or {}
    )
    view = MonthBoardView(facade)
    view.show_weeks([1])
    return view, facade


def test_keyboard_delete_asks_then_clears(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    view, facade = _one_week_view()
    facade.get_assignment.return_value = {"id": 10}
    view.table.setCurrentCell(0, 0)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
    view._on_key_delete()
    facade.assign_participant.assert_not_called()
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    view._on_key_delete()
    facade.assign_participant.assert_called_with(10, None, "participant")


def test_keyboard_enter_opens_choice(qapp, monkeypatch):
    view, _facade = _one_week_view()
    chosen = []
    monkeypatch.setattr(view, "_choose", lambda row, col, role: chosen.append((row, col, role)))
    view.table.setCurrentCell(0, 0)
    view._on_key_enter()
    assert chosen == [(0, 0, "participant")]


def test_remind_waiting_writes_only_to_waiting(qapp, monkeypatch):
    from datetime import datetime

    view, _facade = _one_week_view(
        {1: {2: {"status": "success", "sent_at": datetime(2026, 10, 30)}}}
    )
    sent = []
    monkeypatch.setattr(view, "_notify", lambda weeks, ids: sent.append((weeks, ids)))
    assert view.week_waiting_ids(0) == [2]
    view.remind_waiting(0)
    assert sent == [([1], [2])]


def _two_week_view():
    def week(wid, start, pid, name):
        return {
            "week": {"id": wid, "week_title": str(wid), "start_date": start, "special_event": None},
            "assignments": [
                {
                    "id": wid * 10,
                    "assignment_number": "3",
                    "section": "treasures",
                    "assignment_type": "reading",
                    "assignment_text": "Чтение Библии",
                    "participant_id": pid,
                    "participant_name": name,
                    "status": "assigned",
                }
            ],
        }

    weeks = [week(1, "2026-11-02", 2, "Тарасюк Тимур"), week(2, "2026-11-09", 3, "Соколов Юрий")]
    facade = MagicMock()
    facade.get_month_board.side_effect = lambda ids: build_month_board(weeks, [])
    view = MonthBoardView(facade)
    view.show_weeks([1, 2])
    return view, facade


def _all_suitable(monkeypatch, ids=(2, 3)):
    import ui.month_board_view as mbv

    monkeypatch.setattr(
        mbv,
        "list_candidates",
        lambda f, aid, role: [
            {
                "id": i,
                "name": "",
                "hint": "",
                "tooltip": "",
                "kind": None,
                "weeks_since": None,
                "busy": False,
                "elder_warning": False,
                "pair_count": 0,
            }
            for i in ids
        ],
    )


def test_swap_two_people_between_weeks(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    view, facade = _two_week_view()
    _all_suitable(monkeypatch)
    asked = []
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a: asked.append(a[2]) or QMessageBox.StandardButton.Yes
    )
    view.start_swap(0, 0, "participant")
    assert view.swap_hint.isVisibleTo(view)
    view._on_cell_clicked(0, 1)
    assert "Тарасюк Т." in asked[0] and "не подходит" not in asked[0]
    # Обмен — одна операция фасада (одна транзакция), а не два назначения
    facade.swap_people.assert_called_once_with(10, "participant", 20, "participant")
    facade.assign_participant.assert_not_called()
    assert view._swap_from is None


def test_swap_warns_if_unsuitable_and_can_cancel(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    view, facade = _two_week_view()
    _all_suitable(monkeypatch, ids=(3,))  # Тарасюк (2) на этот пункт не подходит
    asked = []
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a: asked.append(a[2]) or QMessageBox.StandardButton.No
    )
    view.start_swap(0, 0, "participant")
    view._on_cell_clicked(0, 1)
    assert "не подходит" in asked[0]
    facade.assign_participant.assert_not_called()
    facade.swap_people.assert_not_called()
    view.cancel_swap()
    assert view._swap_from is None and not view.swap_hint.isVisibleTo(view)


def test_month_digest_sends_all_weeks_with_month_subject(qapp, monkeypatch):
    view, _facade = _two_week_view()
    view.title = "Ноябрь 2026"
    sent = []
    monkeypatch.setattr(
        view, "_notify", lambda weeks, ids, subject=None: sent.append((weeks, ids, subject))
    )
    view.send_month_digest()
    assert sent == [([1, 2], None, "Ваши задания на ноябрь 2026")]


def test_notification_dialog_default_subject_keeps_own_subject():
    from types import SimpleNamespace

    from ui.notification_dialog import NotificationDialog

    fake = SimpleNamespace(
        default_subject="Ваши задания на ноябрь 2026",
        custom_messages={2: {"subject": "Своя тема", "note": "привет"}, 3: {"subject": ""}},
    )
    messages = NotificationDialog._messages_for(fake, [1, 2, 3])
    assert messages[1] == {"subject": "Ваши задания на ноябрь 2026"}
    assert messages[2]["subject"] == "Своя тема" and messages[2]["note"] == "привет"
    assert messages[3]["subject"] == "Ваши задания на ноябрь 2026"
    fake.default_subject = None
    assert NotificationDialog._messages_for(fake, [1]) is fake.custom_messages


def test_candidate_search_filters_by_name_and_survives_cell_change(qapp):
    view = MonthBoardView(_facade())
    view.show_weeks([10, 11])
    view.table.setCurrentCell(0, 0)
    visible = lambda: [
        view.candidates.item(i).data(Qt.ItemDataRole.UserRole)  # noqa: E731
        for i in range(view.candidates.count())
        if not view.candidates.item(i).isHidden()
    ]
    everyone = visible()
    view.candidate_search.setText("тара")  # без учёта регистра
    assert visible() == [2]
    view._show_candidates()  # перерисовка (другая клетка) — фильтр остаётся
    assert visible() == [2]
    view.candidate_search.clear()
    assert visible() == everyone


def test_board_undo_and_redo_restore_people(qapp):
    facade = _facade()
    facade.restore_people.return_value = True
    view = MonthBoardView(facade)
    view.show_weeks([10, 11])
    view.table.setCurrentCell(0, 0)
    assert not view.can_undo()

    view.assign(0, 0, 2)  # в клетке было пусто
    assert view.can_undo() and not view.can_redo()

    facade.get_assignment.return_value = {**facade.get_assignment.return_value, "participant_id": 2}
    view.undo()
    facade.restore_people.assert_called_with(
        [{"id": 100, "participant_id": None, "assistant_id": None}]
    )
    assert view.can_redo() and not view.can_undo()

    view.redo()
    facade.restore_people.assert_called_with(
        [{"id": 100, "participant_id": 2, "assistant_id": None}]
    )
    assert view.can_undo()


def test_board_swap_is_one_undo_step_and_month_change_clears_history(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    view, facade = _two_week_view()
    facade.get_assignment.side_effect = lambda aid: {"id": aid, "participant_id": aid // 10 + 1}
    _all_suitable(monkeypatch)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    view.start_swap(0, 0, "participant")
    view._on_cell_clicked(0, 1)
    assert len(view._undo) == 1 and [e["id"] for e in view._undo[0]] == [10, 20]

    view.show_weeks([3, 4])  # другой месяц
    assert not view.can_undo()


def test_slip_menu_marks_cell_and_whole_week(qapp):
    view, facade = _two_week_view()
    facade.set_slip_given.return_value = True
    assert view.week_slip_ids(0) == [10]
    view.set_slip([10], True)
    facade.set_slip_given.assert_called_once_with([10], True)


def test_slip_mark_is_drawn_in_cell_and_header(qapp):
    from ui.month_board_view import _header_text

    view, _facade_ = _two_week_view()
    cell = dict(view.board["cells"][0][0], slip=True)
    widget = view._cell_widget(cell, "treasures")
    assert "🧾" in widget.text() and "Листок выдан" in widget.toolTip()
    assert "🧾 1/2" in _header_text(
        {"title": "1–7", "circuit_overseer": False, "slips_given": 1, "slips_total": 2}
    )


def test_select_dialog_lists_longest_rested_first(qapp):
    """Окно выбора участника в «Расписании» — тот же порядок, что на доске:
    новый (ни разу не выступал) сверху, недавние ниже, занятые и старейшины в конце."""
    from ui.schedule_widgets import ParticipantSelectDialog

    facade = _facade()
    newcomer = {"id": 7, "name": "Яковлев Олег", "gender": "male", "qualifications": "reading"}
    facade.get_all_participants.return_value = PEOPLE + [newcomer]
    dialog = ParticipantSelectDialog(None, facade, assignment_id=100)
    try:
        names = [
            dialog.combo.itemText(i).split("  —  ", 1)[0] for i in range(1, dialog.combo.count())
        ]
        assert names == [
            "Яковлев Олег",
            "Тарасюк Тимур",
            "Белых Дмитрий",
            "Новиков Пётр",
            "Беликов Михаил",
        ]
        assert dialog.combo.itemData(0) is None
        assert "не выступал" in dialog.combo.itemText(1)
    finally:
        dialog.close()
