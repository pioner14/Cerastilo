"""Язык бланков и уведомлений, включая неизменность русского вывода."""

import hashlib
import re
from datetime import date, datetime, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote_plus, urlsplit
from zipfile import ZipFile

from docx import Document

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core import notification_service
from core.export_s89 import S89Exporter
from core.i18n import set_language
from core.models import Assignment, Base, Participant, Week
from core.notification_replies import CONFIRMED, DECLINED, mailto_url, parse_reply
from core.notification_service import NotificationService, meeting_day_display


@pytest.fixture
def assignment_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory.begin() as session:
        session.add_all(
            [
                Week(id=1, week_title="1—7 МАРТА", start_date=date(2027, 3, 1)),
                Participant(id=1, name="Анна Иванова", gender="female"),
                Participant(id=2, name="Мария Петрова", gender="female"),
                Assignment(
                    week_id=1,
                    participant_id=1,
                    assistant_id=2,
                    assignment_text="Начинайте разговор",
                    assignment_number="4",
                    section="ministry",
                    section_position="1",
                    duration=3,
                    status="assigned",
                ),
            ]
        )
    try:
        yield SimpleNamespace(get_session=session_factory)
    finally:
        set_language("ru")
        engine.dispose()


def assert_no_cyrillic(text):
    for content in ("Анна Иванова", "Иванова", "Мария Петрова", "Начинайте разговор"):
        text = text.replace(content, "")
    assert not re.search(r"[А-Яа-яЁё]", text)


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_s89_output_language(assignment_db, tmp_path, lang):
    set_language(lang)
    path = tmp_path / "s89.docx"
    with assignment_db.get_session() as session:
        assert S89Exporter().export(session, [1], path)["success"]
    if lang == "ru":
        # XML документа без переменных меток времени ZIP.
        with ZipFile(path) as doc:
            assert hashlib.sha256(doc.read("word/document.xml")).hexdigest() == (
                "3e1854bf87c6ad177a665b3baa5ef1ff31eb5344d2405a3f4ee2bfdd358a0e44"
            )
        return

    cell = Document(path).tables[0].cell(0, 0)
    assert cell.paragraphs[0].text.replace("\n", " ") == (
        "OUR CHRISTIAN LIFE AND MINISTRY MEETING ASSIGNMENT"
    )
    assert [[field.text for field in row.cells] for row in cell.tables[0].rows] == [
        ["Name:", "Анна Иванова"],
        ["Assistant:", "Мария Петрова"],
        ["Date:", "March 1-7, 2027"],
        ["Part no.:", "4"],
    ]
    assert cell.paragraphs[-3].text == (
        "To be given in:\n ☑ Main hall\n ☐ Auxiliary classroom 1\n ☐ Auxiliary classroom 2"
    )
    assert cell.paragraphs[-2].text == (
        "Note to student: The source material and study point for your assignment can be found "
        "in the Life and Ministry Meeting Workbook. Please review the instructions for the part "
        "as outlined in Instructions for Our Christian Life and Ministry Meeting (S-38)."
    )
    assert cell.paragraphs[-1].text == "S-89-E 11/23"
    assert_no_cyrillic(cell.text)


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_notification_output_language(assignment_db, monkeypatch, lang):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 18, tzinfo=tz)

        def astimezone(self, tz=None):
            if self.tzinfo is None:
                return self.replace(tzinfo=timezone.utc).astimezone(tz)
            return super().astimezone(tz)

    monkeypatch.setattr(notification_service, "datetime", FixedDatetime)
    service = NotificationService(
        smtp_user="sender@example.com", sender_name="Alex", meeting_day="Пятница"
    )
    set_language(lang)
    data = service.collect_participant_assignments([1], assignment_db, 1)
    message = service._build_message(
        "student@example.com", data, custom_note="Note", participant_id=1
    )
    payloads = {
        part.get_content_type(): part.get_payload(decode=True)
        for part in message.walk()
        if not part.is_multipart()
    }
    if lang == "ru":
        assert message["Subject"] == "Ваши задания на встрече собрания [NHJS-1-1]"
        assert {kind: hashlib.sha256(value).hexdigest() for kind, value in payloads.items()} == {
            "text/plain": "5f4c264e49c656cc4e1b5677abc817a83a0f41cb14368c12188eea781c4eca8a",
            "text/html": "27bb1bf05c0cac94d2cb3f503b1adb858ca82c24e5b0274ff32962756e069d70",
            "text/calendar": "dc1c1e9f0d916dfe5f5c6f5ebe37697c584e7442eb791a143f2a1441af91f061",
        }
        return

    assert message["Subject"] == "Your meeting assignments [NHJS-1-1]"
    plain, html, ics = (payloads[f"text/{kind}"].decode() for kind in ("plain", "html", "calendar"))
    ics = ics.replace("\r\n ", "")
    for body in (plain, html):
        assert "Week of March 1, 2027 — Friday, March 5, 2027 (meeting starts at 19:00)" in body
        assert "Dear Иванова," in body
        assert "With Christian love," in body
        assert "(3 min.) — Assistant: Мария Петрова" in body
    assert '<html lang="en">' in html
    assert "I confirm" in html
    assert "I can't make it" in html
    assert "Add to calendar" in html
    assert "SUMMARY:Meeting Assignment:" in ics
    assert "DESCRIPTION:Assignment reminder (1 day before)" in ics
    assert "DESCRIPTION:Assignment reminder (2 hours before)" in ics
    for body in (plain, html, ics):
        assert_no_cyrillic(unquote_plus(body))


@pytest.mark.parametrize(
    "body, response",
    [
        ("I confirm, thanks!", CONFIRMED),
        ("No problem, I can make it.", CONFIRMED),
        ("I can't make it this week.", DECLINED),
        ("I can’t make it this week.", DECLINED),
        ("I cannot make it this week.", DECLINED),
    ],
)
def test_english_free_text_replies(body, response):
    assert parse_reply("Re: Your meeting assignments [NHJS-1-1]", body).response == response


@pytest.mark.parametrize(
    "response, word, tag",
    [
        (CONFIRMED, "I confirm", "[NHJS-1-1-OK]"),
        (DECLINED, "I can't make it", "[NHJS-1-1-NO]"),
    ],
)
def test_english_reply_links(response, word, tag):
    try:
        set_language("en")
        assert meeting_day_display("пт") == "Friday"
        url = mailto_url("sender@example.com", "Your meeting assignments", "[NHJS-1-1]", response)
        query = parse_qs(urlsplit(url).query)
        assert query["body"] == [word]
        assert query["subject"] == [f"{word}: Your meeting assignments {tag}"]
        assert parse_reply(query["subject"][0]).response == response
        assert parse_reply(f"{word} [NHJS-1-1]").response == response
    finally:
        set_language("ru")
