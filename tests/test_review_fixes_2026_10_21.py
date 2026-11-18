"""Регрессии мелких багов из ревью 2026-10-18."""

from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace

import pytest

from core.candidate_filter_service import CandidateFilterService


@pytest.mark.parametrize(
    "config",
    [
        SimpleNamespace(required_qualification="X", is_brothers_only=False),
        SimpleNamespace(required_qualification=None, is_brothers_only=True),
    ],
)
def test_filter_without_logger_does_not_crash_when_empty(config):
    """Пустой список кандидатов без logger не должен падать на logger.warning."""
    participants = [
        {
            "id": 1,
            "name": "А",
            "gender": "female",
            "qualifications": [],
            "service_type": None,
            "personal_gap": None,
        }
    ]
    result = CandidateFilterService(min_gap=2).filter_candidates(
        participants,
        set(),
        config,
        datetime(2026, 10, 19),
        {},
        "fixed",
        "chairman",
    )
    assert result == []


def test_history_failure_keeps_email_sent(monkeypatch):
    from core.notification_service import NotificationService

    service = NotificationService(
        smtp_host="h",
        smtp_port=465,
        smtp_user="u@example.com",
        smtp_password="p",
        sender_name="S",
        meeting_day="Четверг",
        meeting_time="19:00",
        cong_name="C",
    )
    server = SimpleNamespace(sendmail=lambda *a: None, quit=lambda: None)
    monkeypatch.setattr(service, "_connect_smtp", lambda: server)
    monkeypatch.setattr(
        service,
        "_collect_assignments",
        lambda *a: {
            1: {"name": "Иван", "email": "i@example.com", "weeks": []},
        },
    )
    monkeypatch.setattr(
        service, "_build_message", lambda *a, **k: SimpleNamespace(as_string=lambda: "")
    )

    class BrokenDb:
        @contextmanager
        def get_session(self):
            raise RuntimeError("база недоступна")
            yield

    result = service.send_assignment_notifications([10], BrokenDb())
    assert result.sent == 1
    assert result.failed == 0
    assert result.failed_names == []


def test_history_only_for_participant_weeks(monkeypatch):
    """История «уведомлён» — только на недели с заданиями участника."""
    from core.notification_service import NotificationService

    service = NotificationService(
        smtp_host="h",
        smtp_port=465,
        smtp_user="u@example.com",
        smtp_password="p",
        sender_name="S",
        meeting_day="Четверг",
        meeting_time="19:00",
        cong_name="C",
    )
    server = SimpleNamespace(sendmail=lambda *a: None, quit=lambda: None)
    monkeypatch.setattr(service, "_connect_smtp", lambda: server)
    monkeypatch.setattr(
        service,
        "_collect_assignments",
        lambda *a: {
            1: {"name": "Иван", "email": "i@example.com", "weeks": [{"week_id": 11}]},
        },
    )
    monkeypatch.setattr(
        service, "_build_message", lambda *a, **k: SimpleNamespace(as_string=lambda: "")
    )

    added = []

    class Db:
        @contextmanager
        def get_session(self):
            yield SimpleNamespace(add=added.append, commit=lambda: None)

    service.send_assignment_notifications([10, 11, 12], Db())
    assert [h.week_id for h in added] == [11]


def test_backup_uses_db_path_env(tmp_path, monkeypatch):
    """На Android рабочая база задаётся DB_PATH — бэкап и восстановление берут её."""
    import sqlite3
    import zipfile

    from core.backup_logic import create_backup, restore_backup

    db = tmp_path / "data.db"
    conn = sqlite3.connect(db)
    for table in ("participants", "weeks", "assignments"):
        conn.execute(f"CREATE TABLE {table} (x)")
    conn.commit()
    conn.close()
    monkeypatch.setenv("DB_PATH", str(db))

    archive = tmp_path / "b.zip"
    assert create_backup(str(archive))["success"]
    assert zipfile.ZipFile(archive).read("scheduler.db") == db.read_bytes()

    original = db.read_bytes()
    db.write_bytes(b"")
    assert restore_backup(str(archive))["success"]
    assert db.read_bytes() == original


def test_candidate_hint_text_and_color():
    from datetime import date

    from ui.schedule_view import candidate_hint

    text, tip, kind = candidate_hint(
        {"count": 7, "last_date": date(2026, 9, 7), "last_text": "Чтение Библии", "busy": False}, 2
    )
    assert text == "7 за полгода · 2 нед. назад (Чтение Библии)"
    assert kind == "recent" and "07.09.2026" in tip

    assert candidate_hint(None, None)[2] == "rested"
    assert "не выступал" in candidate_hint(None, None)[0]
    assert candidate_hint({"count": 1, "busy": True}, 10)[2] == "busy"
    assert candidate_hint({"count": 3, "last_date": date(2026, 1, 1)}, 5)[2] is None


def test_get_candidate_stats_counts_window_and_busy(tmp_path):
    from datetime import date

    from core.facade import ApplicationFacade
    from core.models import Assignment, Participant, Week

    facade = ApplicationFacade.__new__(ApplicationFacade)
    from core.database import DatabaseManager

    db = DatabaseManager(":memory:")
    facade.schedule = SimpleNamespace(db=db)
    with db.get_session() as s:
        s.add_all(
            [
                Participant(id=1, name="А", gender="male", is_active=True),
                Participant(id=2, name="Б", gender="male", is_active=True),
                Week(id=1, week_title="старая", start_date=date(2025, 1, 6)),
                Week(id=2, week_title="прошлая", start_date=date(2026, 9, 7)),
                Week(id=3, week_title="эта", start_date=date(2026, 9, 21)),
                Assignment(
                    id=1, week_id=1, participant_id=1, assignment_text="Речь", status="assigned"
                ),
                Assignment(
                    id=2,
                    week_id=2,
                    participant_id=2,
                    assistant_id=1,
                    assignment_text="Беседа",
                    status="assigned",
                ),
                Assignment(
                    id=3, week_id=3, participant_id=2, assignment_text="Чтение", status="assigned"
                ),
            ]
        )
        s.commit()

    stats = facade.get_candidate_stats(3)
    assert stats[1]["count"] == 1  # старая неделя вне окна 26 недель
    assert stats[1]["last_date"] == date(2026, 9, 7)
    assert stats[1]["last_text"] == "Беседа (напарник)"
    assert not stats[1]["busy"]
    assert stats[2]["busy"] and stats[2]["count"] == 1
    # пункт, для которого выбирают, не делает его участника «занятым»
    assert not facade.get_candidate_stats(3, exclude_assignment_id=3)[2]["busy"]


def test_open_file_on_android_lists_export_dir(tmp_path, monkeypatch):
    """На Android выбор файла — список из «Загрузки/Cerastilo», новые сверху."""
    import os

    import ui.file_dialogs as fd

    (tmp_path / "old.zip").write_bytes(b"1")
    (tmp_path / "new.zip").write_bytes(b"2")
    (tmp_path / "note.pdf").write_bytes(b"3")
    os.utime(tmp_path / "old.zip", (1, 1))
    monkeypatch.setattr(fd, "is_android", lambda: True)
    monkeypatch.setattr(fd, "export_dir", lambda: str(tmp_path))
    shown = {}

    def fake_get_item(parent, title, label, items, current, editable):
        shown["items"] = list(items)
        return items[0], True

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getItem", fake_get_item)
    path = fd.get_open_file_name(None, "Бэкап", "ZIP Files (*.zip)")
    assert shown["items"] == ["new.zip", "old.zip"]
    assert path == str(tmp_path / "new.zip")
