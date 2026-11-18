"""Направление 3: история пар (напарников) и файл календаря .ics участника."""

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.database import DatabaseManager
from core.facade import ApplicationFacade
from core.models import Assignment, Participant, Week


@pytest.fixture
def facade():
    db = DatabaseManager(":memory:")
    f = ApplicationFacade.__new__(ApplicationFacade)
    f.schedule = SimpleNamespace(db=db)
    settings = {"meeting_day": "Четверг", "meeting_time": "19:00", "cong_name": "Север"}
    f.get_setting = lambda key, default=None: settings.get(key, default)
    with db.get_session() as s:
        s.add_all(
            [
                Participant(id=1, name="Иванова Анна", gender="female", is_active=True),
                Participant(id=2, name="Петрова Мария", gender="female", is_active=True),
                Participant(id=3, name="Сидорова Ольга", gender="female", is_active=True),
                Week(id=1, week_title="5–11 января", start_date=date(2026, 1, 5)),
                Week(id=2, week_title="2–8 марта", start_date=date(2026, 3, 2)),
                Week(id=3, week_title="7–13 сентября", start_date=date(2026, 9, 7)),
                Week(id=4, week_title="2–8 ноября", start_date=date(2026, 11, 2)),
                # Анна и Мария — пара дважды, в разных ролях
                Assignment(
                    id=1,
                    week_id=1,
                    participant_id=1,
                    assistant_id=2,
                    assignment_text="Начинаем разговор",
                    status="assigned",
                ),
                Assignment(
                    id=2,
                    week_id=2,
                    participant_id=2,
                    assistant_id=1,
                    assignment_text="Развиваем интерес",
                    status="assigned",
                ),
                Assignment(
                    id=3,
                    week_id=3,
                    participant_id=1,
                    assistant_id=3,
                    assignment_text="Подготавливаем учеников",
                    status="assigned",
                ),
                # Неделя, для которой выбирают, и после неё — не считаются
                Assignment(
                    id=4,
                    week_id=4,
                    participant_id=1,
                    assistant_id=2,
                    assignment_text="Начинаем разговор",
                    duration=3,
                    status="assigned",
                ),
            ]
        )
        s.commit()
    yield f
    db.close()


def test_pair_history_counts_both_roles_before_week(facade):
    pairs = facade.get_pair_history(1, 4)

    assert pairs == {
        2: {"count": 2, "last_date": date(2026, 3, 2)},
        3: {"count": 1, "last_date": date(2026, 9, 7)},
    }
    # до сентября пары с Ольгой ещё не было
    assert 3 not in facade.get_pair_history(1, 3)
    assert facade.get_pair_history(None, 4) == {}


def test_participant_calendar_has_event_with_meeting_time(facade):
    ics = facade.participant_calendar_ics(1, [4])

    assert ics.startswith("BEGIN:VCALENDAR")
    assert ics.count("BEGIN:VEVENT") == 1
    # четверг недели 2–8 ноября, 19:00 местного времени — в файле в UTC
    start_utc = datetime(2026, 11, 5, 19, 0).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    assert f"DTSTART:{start_utc}\r\n" in ics
    # длинные строки .ics перенесены (RFC 5545) — сверяем развёрнутый текст
    assert "Начинаем разговор" in ics.replace("\r\n ", "")
    assert "LOCATION:Север" in ics
    assert facade.participant_calendar_ics(3, [4]) == ""


def _candidates_facade(role_assignment):
    people = [
        {"id": 1, "name": "Иванова Анна", "gender": "female", "qualifications": "assistant"},
        {"id": 2, "name": "Петрова Мария", "gender": "female", "qualifications": "assistant"},
        {"id": 3, "name": "Сидорова Ольга", "gender": "female", "qualifications": "assistant"},
    ]
    f = MagicMock()
    f.get_assignment.return_value = role_assignment
    f.get_assignment_config.return_value = None
    f.get_participant.side_effect = lambda pid: next(p for p in people if p["id"] == pid)
    f.get_all_participants.return_value = people
    f.get_candidate_stats.return_value = {}
    f.get_week_data.return_value = {"week": {"start_date": "2026-11-02"}}
    f.get_pair_history.side_effect = lambda pid, week_id: (
        {2: {"count": 2, "last_date": date(2026, 3, 2)}} if pid == 1 else {}
    )
    return f


def test_assistant_candidates_show_pairs_with_main_participant():
    from ui.candidates import list_candidates

    f = _candidates_facade(
        {
            "id": 4,
            "week_id": 4,
            "participant_id": 1,
            "assistant_id": None,
            "assignment_text": "Начинаем разговор",
        }
    )
    by_name = {c["name"]: c for c in list_candidates(f, 4, role="assistant")}

    f.get_pair_history.assert_called_once_with(1, 4)
    assert "Иванова Анна" not in by_name  # сам основной участник
    maria = by_name["Петрова Мария"]
    assert maria["pair_count"] == 2
    assert "в паре 2 раз(а), посл. 02.03.2026" in maria["hint"]
    assert "В паре с Иванова Анна" in maria["tooltip"]
    assert by_name["Сидорова Ольга"]["pair_count"] == 0
    assert "в паре" not in by_name["Сидорова Ольга"]["hint"]


def test_main_candidates_show_pairs_with_assigned_assistant():
    from ui.candidates import list_candidates

    f = _candidates_facade(
        {
            "id": 4,
            "week_id": 4,
            "participant_id": None,
            "assistant_id": 1,
            "assignment_text": "Начинаем разговор",
        }
    )
    by_name = {c["name"]: c for c in list_candidates(f, 4, role="participant")}

    f.get_pair_history.assert_called_once_with(1, 4)
    assert by_name["Петрова Мария"]["pair_count"] == 2


def test_no_pair_lookup_without_partner():
    from ui.candidates import list_candidates

    f = _candidates_facade(
        {
            "id": 5,
            "week_id": 4,
            "participant_id": None,
            "assistant_id": None,
            "assignment_text": "Чтение Библии",
        }
    )
    list_candidates(f, 5, role="participant")

    f.get_pair_history.assert_not_called()


def test_save_participant_calendar_writes_crlf_file(tmp_path, monkeypatch):
    import ui.email_preview_dialog as dlg
    import ui.file_dialogs as fd

    target = tmp_path / "anna"
    monkeypatch.setattr(fd, "get_save_file_name", lambda *a: str(target))
    shown = []
    monkeypatch.setattr(dlg.QMessageBox, "information", lambda _p, _t, text: shown.append(text))
    f = MagicMock()
    f.participant_calendar_ics.return_value = "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"

    path = dlg.save_participant_calendar(None, f, 1, "Иванова Анна", [4])

    assert path == str(target) + ".ics"
    assert open(path, "rb").read() == b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"
    f.participant_calendar_ics.assert_called_once_with(1, [4])
    assert "сохранён" in shown[0]


def test_save_participant_calendar_without_assignments(monkeypatch):
    import ui.email_preview_dialog as dlg
    import ui.file_dialogs as fd

    asked = []
    monkeypatch.setattr(fd, "get_save_file_name", lambda *a: asked.append(a) or "x.ics")
    monkeypatch.setattr(dlg.QMessageBox, "information", lambda *a: None)
    f = MagicMock()
    f.participant_calendar_ics.return_value = ""

    assert dlg.save_participant_calendar(None, f, 3, "Сидорова Ольга", [4]) is None
    assert asked == []
