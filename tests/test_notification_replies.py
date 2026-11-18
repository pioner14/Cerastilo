"""Ответы на уведомления: метка в теме, кнопки mailto, разбор ответа и запись в базу."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import unquote

from core.notification_replies import CONFIRMED, DECLINED, Reply, make_tag, mailto_url, parse_reply


def test_tag_and_button_reply_round_trip():
    tag = make_tag(93, [64, 63])
    assert tag == "[NHJS-93-63.64]"
    url = unquote(mailto_url("sender@example.com", "Ваши задания", tag, DECLINED))
    assert url.startswith(
        "mailto:sender@example.com?subject=Не смогу: Ваши задания [NHJS-93-63.64-NO]"
    )
    subject = url.split("subject=")[1].split("&")[0]
    assert parse_reply(subject) == Reply(93, [63, 64], DECLINED)


def test_plain_reply_uses_first_line_of_body():
    subject = "Re: Ваши задания на встрече собрания [NHJS-5-7]"
    assert parse_reply(subject, "Да, конечно\n\n> Дорогой брат…") == Reply(5, [7], CONFIRMED)
    assert parse_reply(subject, "Нет, не смогу, уезжаю") == Reply(5, [7], DECLINED)
    assert (
        parse_reply(subject, "Можно поменяться на другую неделю?") is None
    )  # непонятно — не угадываем
    assert parse_reply("Re: другое письмо", "да") is None


def test_message_has_tag_and_buttons():
    from core.notification_service import NotificationService

    service = NotificationService(smtp_user="sender@example.com", sender_name="Николай")
    p_data = {
        "name": "Тарасюк Тимур",
        "email": "t@example.com",
        "weeks": [
            {
                "week_id": 63,
                "week_title": "23—29 ноября",
                "date_str": "",
                "items": ["Чтение Библии"],
            }
        ],
    }
    msg = service._build_message("t@example.com", p_data, participant_id=93)
    assert msg["Subject"].endswith("[NHJS-93-63]")
    html = (
        next(p for p in msg.walk() if p.get_content_type() == "text/html")
        .get_payload(decode=True)
        .decode()
    )
    assert "mailto:sender@example.com" in html and "Подтверждаю" in html and "Не смогу" in html


def _facade_with_db():
    from core.database import DatabaseManager
    from core.facade import ApplicationFacade
    from core.models import NotificationHistory

    db = DatabaseManager(":memory:")
    with db.get_session() as s:
        s.add(
            NotificationHistory(
                participant_id=93,
                week_id=63,
                status="success",
                sent_at=datetime(2026, 11, 1, 10, 0),
            )
        )
        s.commit()
    facade = ApplicationFacade.__new__(ApplicationFacade)
    facade.schedule = SimpleNamespace(db=db)
    facade.events = MagicMock()
    return facade


def test_apply_replies_respects_send_time_and_newest_answer():
    facade = _facade_with_db()
    old = (datetime(2026, 10, 30), Reply(93, [63], CONFIRMED))  # ответ на прежнее письмо
    assert facade.apply_notification_replies([old]) == 0
    yes = (datetime(2026, 11, 1, 12, 0), Reply(93, [63], CONFIRMED))
    no = (datetime(2026, 11, 2, 9, 0), Reply(93, [63], DECLINED))
    assert facade.apply_notification_replies([yes, no]) == 2
    assert facade.get_week_notification_statuses(63)[93]["response"] == DECLINED
    assert facade.apply_notification_replies([yes]) == 0  # более старый ответ не перебивает


def test_manual_response_set_and_clear():
    facade = _facade_with_db()
    facade.set_notification_response(93, 63, CONFIRMED)
    assert facade.get_week_notification_statuses(63)[93]["response"] == CONFIRMED
    facade.set_notification_response(93, 63, None)
    assert facade.get_week_notification_statuses(63)[93]["response"] is None


def test_imap_date_ignores_locale():
    """Месяц в IMAP SEARCH — всегда по-английски, даже при русской локали Qt."""
    import locale

    from core.notification_service import _imap_date

    try:
        locale.setlocale(locale.LC_TIME, "ru_RU.UTF-8")
    except locale.Error:
        pass
    try:
        assert _imap_date(datetime(2026, 10, 1)) == "01-Oct-2026"
    finally:
        locale.setlocale(locale.LC_TIME, "C")


def test_no_problem_phrases_mean_yes():
    tag = "[NHJS-93-63]"
    assert parse_reply(f"Re: Задания {tag}", "Нет проблем, буду").response == CONFIRMED
    assert parse_reply(f"Re: Задания {tag}", "Без проблем!").response == CONFIRMED
    assert parse_reply(f"Re: Задания {tag}", "Нет, не смогу").response == DECLINED


def test_reply_from_foreign_address_is_ignored():
    from core.models import Participant

    facade = _facade_with_db()
    with facade.schedule.db.get_session() as s:
        s.add(Participant(id=93, name="Тарасюк Тимур", gender="male", email="Timur@example.com"))
        s.commit()
    when = datetime(2026, 11, 1, 12, 0)
    stranger = (when, Reply(93, [63], DECLINED, sender="other@example.com"))
    assert facade.apply_notification_replies([stranger]) == 0
    own = (when, Reply(93, [63], CONFIRMED, sender="timur@example.com"))
    assert facade.apply_notification_replies([own]) == 1


def test_reply_date_compared_in_utc_like_sent_at():
    """sent_at пишется в UTC (CURRENT_TIMESTAMP) — дата ответа тоже в UTC."""
    import email.utils

    from core.notification_service import _utc_naive

    when = _utc_naive(email.utils.parsedate_to_datetime("Sun, 01 Nov 2026 12:30:00 +0100"))
    assert when == datetime(2026, 11, 1, 11, 30)


def test_gmail_reply_without_dots_matches_card_with_dots():
    from core.models import Participant

    facade = _facade_with_db()
    with facade.schedule.db.get_session() as s:
        s.add(Participant(id=93, name="Тарасюк Тимур", gender="male", email="Timur.T@gmail.com"))
        s.commit()
    when = datetime(2026, 11, 1, 12, 0)
    other = (when, Reply(93, [63], CONFIRMED, sender="timur.t@example.com"))
    assert facade.apply_notification_replies([other]) == 0  # точки не значат ничего только у Gmail
    own = (when, Reply(93, [63], CONFIRMED, sender="timurt+x@googlemail.com"))
    assert facade.apply_notification_replies([own]) == 1


def test_imap_host_follows_smtp_host():
    """«Проверить ответы» — не только Gmail: IMAP-сервер берётся по SMTP."""
    from core.notification_service import NotificationService

    def imap(smtp):
        return NotificationService(smtp_host=smtp).imap_host

    assert imap("smtp.gmail.com") == "imap.gmail.com"
    assert imap("smtp.yandex.ru") == "imap.yandex.ru"
    assert imap("smtp.mail.ru") == "imap.mail.ru"
    assert imap("smtp.office365.com") == "outlook.office365.com"
    assert imap("mail.example.org") == "mail.example.org"  # общий сервер
    assert imap("") == "imap.gmail.com"
