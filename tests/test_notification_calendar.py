from datetime import date, datetime, timezone
from email.mime.multipart import MIMEMultipart

from core.notification_service import (
    NotificationService,
    _calculate_meeting_datetime,
    _generate_google_calendar_url,
    _build_ics_content,
    _build_html,
    _build_plain_text,
    _parse_meeting_time,
)


def test_parse_meeting_time():
    assert _parse_meeting_time("19:00") == (19, 0)
    assert _parse_meeting_time("18:30") == (18, 30)
    assert _parse_meeting_time("19.45") == (19, 45)
    assert _parse_meeting_time("") == (19, 0)
    assert _parse_meeting_time("invalid") == (19, 0)


def test_calculate_meeting_datetime_thursday():
    # Понедельник 7 сентября 2026
    start_monday = date(2026, 9, 7)
    dt_start, dt_end, display_str = _calculate_meeting_datetime(
        start_monday, meeting_day_str="Четверг", meeting_time_str="19:00"
    )
    assert dt_start == datetime(2026, 9, 10, 19, 0)
    assert dt_end == datetime(2026, 9, 10, 20, 45)
    assert "Четверг" in display_str
    assert "10.09.2026" in display_str


def test_calculate_meeting_datetime_wednesday():
    start_monday = date(2026, 9, 7)
    dt_start, dt_end, display_str = _calculate_meeting_datetime(
        start_monday, meeting_day_str="Среда", meeting_time_str="18:30"
    )
    assert dt_start == datetime(2026, 9, 9, 18, 30)
    assert dt_end == datetime(2026, 9, 9, 20, 15)
    assert "Среда" in display_str
    assert "09.09.2026" in display_str


def test_calculate_meeting_datetime_default_fallback():
    start_monday = date(2026, 9, 7)
    # Пустой день встречи -> по умолчанию четверг 19:00
    dt_start, dt_end, _ = _calculate_meeting_datetime(start_monday, "", "")
    assert dt_start == datetime(2026, 9, 10, 19, 0)
    assert dt_end == datetime(2026, 9, 10, 20, 45)

    # Без даты недели
    assert _calculate_meeting_datetime(None) == (None, None, "")


def test_generate_google_calendar_url():
    dt_start = datetime(2026, 9, 10, 19, 0)
    dt_end = datetime(2026, 9, 10, 20, 45)
    url = _generate_google_calendar_url(
        title="Встреча собрания — Иван",
        dt_start=dt_start,
        dt_end=dt_end,
        details="Задания:\n• Чтение Библии",
        location="Зал Царства",
    )
    assert url.startswith("https://calendar.google.com/calendar/render?action=TEMPLATE")
    assert "dates=20260910T190000%2F20260910T204500" in url
    assert "location=%D0%97%D0%B0%D0%BB+%D0%A6%D0%B0%D1%80%D1%81%D1%82%D0%B2%D0%B0" in url


def test_build_ics_content():
    events = [
        {
            "uid": "test-uid-123@nhjs",
            "dt_start": datetime(2026, 9, 10, 19, 0),
            "dt_end": datetime(2026, 9, 10, 20, 45),
            "summary": "Встреча собрания: Чтение Библии",
            "description": "Задания:\n• Чтение Библии (4 мин.)",
            "location": "Зал Царства, Центральное",
        }
    ]
    ics_text = _build_ics_content(events, cong_name="Центральное")

    assert "BEGIN:VCALENDAR\r\n" in ics_text
    assert "VERSION:2.0\r\n" in ics_text
    assert "METHOD:PUBLISH\r\n" in ics_text
    assert "BEGIN:VEVENT\r\n" in ics_text
    assert "UID:test-uid-123@nhjs\r\n" in ics_text
    # Время в UTC с «Z», из местного времени компьютера
    start_utc = datetime(2026, 9, 10, 19, 0).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    end_utc = datetime(2026, 9, 10, 20, 45).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    assert f"DTSTART:{start_utc}\r\n" in ics_text
    assert f"DTEND:{end_utc}\r\n" in ics_text
    assert "SUMMARY:Встреча собрания: Чтение Библии\r\n" in ics_text
    assert "LOCATION:Зал Царства\\, Центральное\r\n" in ics_text
    # Проверка наличия напоминаний
    assert "BEGIN:VALARM\r\nTRIGGER:-P1D\r\n" in ics_text
    assert "BEGIN:VALARM\r\nTRIGGER:-PT2H\r\n" in ics_text
    assert "END:VEVENT\r\n" in ics_text
    assert "END:VCALENDAR\r\n" in ics_text


def test_build_html_with_calendar():
    weeks = [
        {
            "week_id": 1,
            "week_title": "8-14 сентября 2026",
            "date_str": "08.09.2026",
            "items": ["Чтение Библии (4 мин.)"],
            "start_date": date(2026, 9, 7),
        }
    ]
    html = _build_html(
        recipient_name="Иван Иванов",
        sender_name="Николай",
        assignments_by_week=weeks,
        meeting_day="Четверг",
        meeting_time="19:00",
        cong_name="Собрание Северное",
    )
    assert "calendar.google.com/calendar/render" in html
    assert "assignments.ics" in html
    assert "Четверг, 10.09.2026 (начало встречи в 19:00)" in html
    assert "Чтение Библии (4 мин.)" in html


def test_build_plain_text_with_calendar():
    weeks = [
        {
            "week_id": 1,
            "week_title": "8-14 сентября 2026",
            "date_str": "08.09.2026",
            "items": ["Чтение Библии (4 мин.)"],
            "start_date": date(2026, 9, 7),
        }
    ]
    plain = _build_plain_text(
        recipient_name="Иван",
        sender_name="Николай",
        assignments_by_week=weeks,
        meeting_day="Четверг",
        meeting_time="19:00",
        cong_name="Собрание Северное",
    )
    assert "calendar.google.com/calendar/render" in plain
    assert "assignments.ics" in plain
    assert "Четверг, 10.09.2026 (начало встречи в 19:00)" in plain


def test_build_html_backward_compatibility_tuples():
    # Старый формат кортежей без start_date
    weeks = [("8-14 сентября", "08.09.2026", ["Чтение Библии"])]
    html = _build_html(
        recipient_name="Иван",
        sender_name="Николай",
        assignments_by_week=weeks,
    )
    assert "8-14 сентября" in html
    assert "Чтение Библии" in html


def test_build_message_mixed_with_ics_attachment():
    service = NotificationService(
        smtp_host="smtp.gmail.com",
        smtp_port=465,
        smtp_user="test@gmail.com",
        smtp_password="password",
        sender_name="Служитель",
        meeting_day="Четверг",
        meeting_time="19:00",
        cong_name="Зал Царства",
    )

    p_data = {
        "id": 42,
        "name": "Сергей Петров",
        "email": "sergey@example.com",
        "weeks": [
            {
                "week_id": 10,
                "week_title": "8-14 сентября 2026",
                "date_str": "08.09.2026",
                "items": ["Чтение Библии (4 мин.)"],
                "start_date": date(2026, 9, 7),
            }
        ],
    }

    msg = service._build_message("sergey@example.com", p_data)
    assert isinstance(msg, MIMEMultipart)
    assert msg.get_content_type() == "multipart/mixed"
    assert msg["To"] == "sergey@example.com"
    assert msg["Subject"] == "Ваши задания на встрече собрания"

    # Структура: alternative (plain + html) и одно вложение .ics.
    # Календаря внутри alternative быть не должно: iOS Mail принимает его за
    # приглашение и не сохраняет событие по «Добавить».
    parts = msg.get_payload()
    assert len(parts) == 2
    alt_part = parts[0]
    assert alt_part.get_content_type() == "multipart/alternative"
    alt_subparts = alt_part.get_payload()
    assert [p.get_content_type() for p in alt_subparts] == ["text/plain", "text/html"]

    # Вложение
    att_part = parts[1]
    assert att_part.get_content_type() == "text/calendar"
    # Без method: иначе iOS Mail считает вложение приглашением и не даёт «Добавить»
    assert att_part.get_param("method") is None
    assert att_part.get_content_charset() == "utf-8"
    assert att_part.get_filename() == "assignments.ics"
    assert att_part.get_content_disposition() == "attachment"
    ics = att_part.get_payload(decode=True).decode("utf-8")
    assert ics.startswith("BEGIN:VCALENDAR\r\n")
    assert "UID:nhjs-p42-w10-20260910@nhjs\r\n" in ics

    # Во всём письме ровно одна календарная часть
    calendars = [p for p in msg.walk() if p.get_content_type() == "text/calendar"]
    assert len(calendars) == 1


def test_ics_long_lines_are_folded_to_75_octets():
    """RFC 5545 3.1: строки не длиннее 75 октетов, кириллица не разрывается."""
    long_text = "Задания: " + "Чтение Библии, начальная беседа, повторное посещение. " * 5
    events = [
        {
            "uid": "fold@nhjs",
            "dt_start": datetime(2026, 9, 10, 19, 0),
            "dt_end": datetime(2026, 9, 10, 20, 45),
            "summary": "Встреча собрания — Задания (3): " + long_text[:80],
            "description": long_text,
        }
    ]
    ics = _build_ics_content(events, cong_name="Центральное")

    assert ics.endswith("\r\n")
    raw_lines = ics.split("\r\n")[:-1]
    for line in raw_lines:
        # Каждая строка — целые UTF-8 символы и не длиннее 75 октетов
        assert len(line.encode("utf-8")) <= 75, line
    # Голых \n (без \r) в файле нет
    assert "\n" not in ics.replace("\r\n", "")

    # Развёртка (RFC 5545: CRLF + пробел убираются) возвращает исходную строку
    unfolded = ics.replace("\r\n ", "")
    assert "DESCRIPTION:" + long_text.replace(",", "\\,") + "\r\n" in unfolded


def test_build_html_with_custom_note():
    weeks = [("8-14 сентября", "08.09.2026", ["Чтение Библии"])]
    html = _build_html(
        recipient_name="Иван Иванов",
        sender_name="Служитель",
        assignments_by_week=weeks,
        custom_note="Пожалуйста, подготовь микрофон 1",
    )
    assert "💬 Примечание:" in html
    assert "Пожалуйста, подготовь микрофон 1" in html
    assert "Чтение Библии" in html


def test_build_html_with_custom_body():
    weeks = [("8-14 сентября", "08.09.2026", ["Чтение Библии"])]
    html = _build_html(
        recipient_name="Иван Иванов",
        sender_name="Служитель",
        assignments_by_week=weeks,
        custom_body="Привет, Иван! Вот особое сообщение для тебя.",
    )
    assert "Привет, Иван! Вот особое сообщение для тебя." in html
    assert "Ниже ваши задания" not in html


def test_build_plain_text_with_custom_note():
    weeks = [("8-14 сентября", "08.09.2026", ["Чтение Библии"])]
    text = _build_plain_text(
        recipient_name="Иван Иванов",
        sender_name="Служитель",
        assignments_by_week=weeks,
        custom_note="Не забудь взять брошюру",
    )
    assert "💬 Примечание: Не забудь взять брошюру" in text
    assert "Чтение Библии" in text


def test_build_message_with_custom_subject_and_note():
    service = NotificationService(
        smtp_host="smtp.gmail.com",
        smtp_port=465,
        smtp_user="test@gmail.com",
        smtp_password="password",
        sender_name="Служитель",
    )
    p_data = {
        "id": 1,
        "name": "Иван",
        "email": "ivan@example.com",
        "weeks": [
            {
                "week_id": 1,
                "week_title": "1-7 Сентября",
                "items": ["Пункт 1"],
                "start_date": date(2026, 9, 1),
            }
        ],
    }
    msg = service._build_message(
        "ivan@example.com",
        p_data,
        custom_subject="Специальное напоминание о пункте",
        custom_note="Личная просьба",
    )
    assert msg["Subject"] == "Специальное напоминание о пункте"


def test_ics_times_are_utc_not_floating(monkeypatch):
    """Без пояса iPhone (добавление из Почты) читал время как UTC — сдвиг на час."""
    import time as _time

    monkeypatch.setenv("TZ", "Europe/Paris")
    _time.tzset()
    try:
        ics = _build_ics_content(
            [
                {
                    "uid": "tz@nhjs",
                    "dt_start": datetime(2026, 11, 25, 19, 0),  # зимнее время, UTC+1
                    "dt_end": datetime(2026, 11, 25, 20, 45),
                    "summary": "Встреча собрания",
                    "description": "",
                }
            ]
        )
    finally:
        monkeypatch.undo()
        _time.tzset()
    assert "DTSTART:20261125T180000Z\r\n" in ics
    assert "DTEND:20261125T194500Z\r\n" in ics
