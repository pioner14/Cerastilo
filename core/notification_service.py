"""
NotificationService — сервис отправки email-уведомлений участникам.

Отправляет каждому участнику персональное письмо с его заданиям
на выбранные недели через SMTP (Gmail или любой другой сервер).

Использование:
    service = NotificationService(
        smtp_host='smtp.gmail.com',
        smtp_port=465,
        smtp_user='name@gmail.com',
        smtp_password='app_password_here',
        sender_name='Иван Иванов',
    )
    result = service.send_assignment_notifications(week_ids=[1, 2, 3], db_manager=db)
"""

import email
import email.utils
import imaplib
import logging
import smtplib
from core import tls
import urllib.parse
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.header import decode_header, make_header
from email.mime.text import MIMEText
from html import escape as html_escape
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, text

from core.export.filename import format_output_date
from core.i18n import _, language
from core.models import (
    Assignment,
    NotificationHistory,
    NotificationResponse,
    Participant,
    Week,
    utc_now,
)
from core.notification_replies import CONFIRMED, DECLINED, Reply, make_tag, mailto_url, parse_reply
from core.week_layout import (
    apply_circuit_overseer_week,
    assignment_label,
    format_minutes,
    order_week_assignments,
    parse_meeting_start,
    start_minutes,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class NotificationResult:
    """Результат рассылки уведомлений."""

    sent: int = 0
    failed: int = 0
    skipped_no_email: int = 0
    failed_names: List[str] = field(default_factory=list)
    skipped_names: List[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.sent + self.failed + self.skipped_no_email

    def summary(self) -> str:
        lines = [
            _("✅ Отправлено: {count}", count=self.sent),
            _("❌ Ошибки: {count}", count=self.failed),
            _("⚠️  Без email: {count}", count=self.skipped_no_email),
        ]
        if self.failed_names:
            lines.append(_("\nНе удалось отправить:"))
            for name in self.failed_names:
                lines.append(f"  • {name}")
        if self.skipped_names:
            lines.append(_("\nБез email (пропущены):"))
            for name in self.skipped_names:
                lines.append(f"  • {name}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Assignment data helpers
# ---------------------------------------------------------------------------

SECTION_LABELS = {
    "fixed": "Постоянная часть",
    "treasures": "Сокровища из Слова Бога",
    "ministry": "Оттачиваем навыки служения",
    "living": "Христианская жизнь",
    "cbs": "Изучение Библии",
}

POSITION_LABELS = {
    "chairman": "Председатель",
    "prayer_open": "Молитва (открывающая)",
    "prayer_close": "Молитва (заключительная)",
    "reader": "Чтец",
    "conductor": "Ведущий",
}


def _role_word(role: str, gender: Optional[str]) -> str:
    """«учащийся»/«учащаяся» для основного участника, «помощник»/«помощница»
    для напарника — как в S-38; пол неизвестен — мужской род."""
    female = gender == "female"
    if role == "assistant":
        return _("помощница") if female else _("помощник")
    return _("учащаяся") if female else _("учащийся")


def _format_assignment(
    assignment_text: str,
    duration: Optional[int],
    role: str,
    gender: Optional[str] = None,
    partner_name: Optional[str] = None,
    partner_gender: Optional[str] = None,
) -> str:
    """Форматирует строку задания для письма.

    Если в пункте двое (учащийся и помощник), каждому пишется, с кем он:
    «Начинайте разговор (3 мин.) — помощница: Петрова Анна» и
    «Начинайте разговор (3 мин.) (помощница) — учащаяся: Иванова Мария».
    """
    role_suffix = f" ({_role_word('assistant', gender)})" if role == "assistant" else ""
    dur_suffix = _(" ({n} мин.)", n=duration) if duration else ""
    label = assignment_text
    if language() == "en":
        if label in POSITION_LABELS.values() or label in SECTION_LABELS.values():
            label = _(label)
        else:
            label = assignment_label(label)
    text = f"{label}{dur_suffix}{role_suffix}"
    if partner_name:
        partner_role = "participant" if role == "assistant" else "assistant"
        text += f" — {_role_word(partner_role, partner_gender)}: {partner_name}"
    return text


DAY_NAME_TO_WEEKDAY = {
    "понедельник": 0,
    "пн": 0,
    "monday": 0,
    "mon": 0,
    "вторник": 1,
    "вт": 1,
    "tuesday": 1,
    "tue": 1,
    "среда": 2,
    "ср": 2,
    "wednesday": 2,
    "wed": 2,
    "четверг": 3,
    "чт": 3,
    "thursday": 3,
    "thu": 3,
    "пятница": 4,
    "пт": 4,
    "friday": 4,
    "fri": 4,
    "суббота": 5,
    "сб": 5,
    "saturday": 5,
    "sat": 5,
    "воскресенье": 6,
    "вс": 6,
    "sunday": 6,
    "sun": 6,
}

RU_WEEKDAYS = {
    0: "Понедельник",
    1: "Вторник",
    2: "Среда",
    3: "Четверг",
    4: "Пятница",
    5: "Суббота",
    6: "Воскресенье",
}


def _meeting_day_key(value: str) -> str:
    return (value or "").strip().lower()


def meeting_day_display(value: str) -> str:
    """Показывает сохранённый день на языке интерфейса."""
    weekday = DAY_NAME_TO_WEEKDAY.get(_meeting_day_key(value))
    if weekday is None:
        return value
    return _(RU_WEEKDAYS[weekday])


def _parse_meeting_time(time_str: str) -> Tuple[int, int]:
    """Парсит строку времени ('19:00', '19.00', '18:30') в (часы, минуты). По умолчанию (19, 0)."""
    if not time_str:
        return (19, 0)
    cleaned = str(time_str).strip().replace(".", ":")
    try:
        parts = cleaned.split(":")
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        if 0 <= h < 24 and 0 <= m < 60:
            return (h, m)
    except Exception:
        pass
    return (19, 0)


def _format_greeting_name(full_name: str) -> str:
    """
    Форматирует имя для приветствия в письме.
    Если имя в формате "Фамилия Имя" (например "Вишневский Григорий") -> берет Имя ("Григорий").
    Если только одно слово или не удается определить -> берет как есть.
    """
    if not full_name:
        return ""
    parts = full_name.strip().split()
    if len(parts) >= 2:
        # В русскоязычной базе почти всегда "Фамилия Имя" (или "Фамилия Имя Отчество")
        # Берем второе слово (Имя)
        return parts[1]
    return parts[0]


def _calculate_meeting_datetime(
    week_start: Optional[date],
    meeting_day_str: str = "",
    meeting_time_str: str = "",
) -> Tuple[Optional[datetime], Optional[datetime], str]:
    """
    Вычисляет (dt_start, dt_end, display_date_str) для встречи.
    По умолчанию встреча длится 105 минут (1 час 45 минут).
    Если week_start отсутствует, возвращает (None, None, '').
    """
    if not week_start:
        return (None, None, "")

    # Приводим к понедельнику текущей недели
    monday = week_start - timedelta(days=week_start.weekday())
    target_weekday = DAY_NAME_TO_WEEKDAY.get(
        _meeting_day_key(meeting_day_str), 3
    )  # Четверг по умолчанию

    actual_meeting_date = monday + timedelta(days=target_weekday)
    h, m = _parse_meeting_time(meeting_time_str)

    dt_start = datetime.combine(actual_meeting_date, time(h, m))
    dt_end = dt_start + timedelta(minutes=105)

    weekday = _(RU_WEEKDAYS[target_weekday])
    display_str = f"{weekday}, {format_output_date(actual_meeting_date)}"
    return (dt_start, dt_end, display_str)


def _generate_google_calendar_url(
    title: str,
    dt_start: datetime,
    dt_end: datetime,
    details: str,
    location: str = "",
) -> str:
    """Генерирует веб-ссылку для добавления события в Google Календарь."""
    start_str = dt_start.strftime("%Y%m%dT%H%M%S")
    end_str = dt_end.strftime("%Y%m%dT%H%M%S")
    params = {
        "action": "TEMPLATE",
        "text": title,
        "dates": f"{start_str}/{end_str}",
        "details": details,
    }
    if location:
        params["location"] = location
    return f"https://calendar.google.com/calendar/render?{urllib.parse.urlencode(params)}"


def _generate_outlook_calendar_url(
    title: str,
    dt_start: datetime,
    dt_end: datetime,
    details: str,
    location: str = "",
) -> str:
    """Генерирует веб-ссылку для добавления события в Outlook Web / Office 365."""
    # Outlook Web Calendar URL формат (ISO-8601)
    params = {
        "path": "/calendar/action/compose",
        "rru": "addevent",
        "subject": title,
        "startdt": dt_start.strftime("%Y-%m-%dT%H:%M:%S"),
        "enddt": dt_end.strftime("%Y-%m-%dT%H:%M:%S"),
        "body": details,
    }
    if location:
        params["location"] = location
    return f"https://outlook.live.com/calendar/0/action/compose?{urllib.parse.urlencode(params)}"


def _escape_ics_text(text: str) -> str:
    """Экранирует специальные символы по RFC 5545."""
    if not text:
        return ""
    text = text.replace("\\", "\\\\")
    text = text.replace(";", "\\;")
    text = text.replace(",", "\\,")
    text = text.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
    return text


def _ics_utc(dt: datetime) -> str:
    """Время для .ics в UTC с «Z». Время без пояса считается местным временем
    компьютера (пояс собрания). «Плавающее» время без пояса iPhone при добавлении
    из Почты читал как UTC — событие съезжало на час (Франция, 30.10)."""
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _fold_ics_line(line: str) -> str:
    """Переносит строку .ics по RFC 5545 (3.1): не длиннее 75 октетов,
    продолжение начинается с пробела. UTF-8 символ не разрывается."""
    limit = 75
    out = []
    current = ""
    current_len = 0
    for ch in line:
        ch_len = len(ch.encode("utf-8"))
        if current_len + ch_len > limit:
            out.append(current)
            current = " " + ch
            current_len = 1 + ch_len
        else:
            current += ch
            current_len += ch_len
    out.append(current)
    return "\r\n".join(out)


def _build_ics_content(
    events_data: List[dict],
    cong_name: str = "",
) -> str:
    """
    Генерирует содержимое файла .ics (RFC 5545) с событиями и напоминаниями (VALARM).

    events_data: список словарей с ключами:
        - uid: str
        - dt_start: datetime
        - dt_end: datetime
        - summary: str
        - description: str
        - location: str (опционально)
    """
    if not events_data:
        return ""

    now_utc_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:-//NHJS//Meeting Schedule//{language().upper()}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    for ev in events_data:
        dt_start: datetime = ev["dt_start"]
        dt_end: datetime = ev["dt_end"]
        uid = ev.get("uid", f"{uuid.uuid4()}@nhjs")
        summary = _escape_ics_text(ev.get("summary", _("Встреча собрания — Задание")))
        description = _escape_ics_text(ev.get("description", ""))
        location = _escape_ics_text(ev.get("location") or cong_name or "")

        start_str = _ics_utc(dt_start)
        end_str = _ics_utc(dt_end)

        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{now_utc_str}",
                f"DTSTART:{start_str}",
                f"DTEND:{end_str}",
                f"SUMMARY:{summary}",
                f"DESCRIPTION:{description}",
            ]
        )
        if location:
            lines.append(f"LOCATION:{location}")
        lines.extend(
            [
                "STATUS:CONFIRMED",
                # Напоминание 1: за 1 день (24 часа)
                "BEGIN:VALARM",
                "TRIGGER:-P1D",
                "ACTION:DISPLAY",
                "DESCRIPTION:" + _("Напоминание о задании на встрече собрания (за 1 день)"),
                "END:VALARM",
                # Напоминание 2: за 2 часа
                "BEGIN:VALARM",
                "TRIGGER:-PT2H",
                "ACTION:DISPLAY",
                "DESCRIPTION:" + _("Напоминание о задании на встрече собрания (через 2 часа)"),
                "END:VALARM",
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold_ics_line(line) for line in lines) + "\r\n"


# ---------------------------------------------------------------------------
# Email template
# ---------------------------------------------------------------------------


def _confirm_buttons_html(confirm_links: Optional[Tuple[str, str]]) -> str:
    """Кнопки «Подтверждаю» / «Не смогу» — ссылки mailto: с меткой письма."""
    if not confirm_links:
        return ""
    yes_url, no_url = (html_escape(u, quote=True) for u in confirm_links)
    button = (
        "display:inline-block; padding:10px 18px; margin:4px 8px 4px 0; border-radius:6px; "
        "color:#ffffff; text-decoration:none; font-weight:bold;"
    )
    return f"""
  <div style="margin: 20px 0; text-align: center;">
    <p style="margin-bottom: 8px;">{_('Пожалуйста, ответьте, сможете ли вы выполнить задание:')}</p>
    <a href="{yes_url}" style="{button} background:#16a34a;">✅ {_('Подтверждаю')}</a>
    <a href="{no_url}" style="{button} background:#dc2626;">❌ {_('Не смогу')}</a>
    <p style="color:#777; font-size:12px;">{_('Откроется ответное письмо — просто отправьте его.')}</p>
  </div>"""


def _week_email_data(item: Any) -> tuple:
    if isinstance(item, dict):
        week_title = item.get("week_title", "")
        date_str = item.get("date_str", "")
        items = item.get("items", [])
        start_date = item.get("start_date")
    else:
        week_title, date_str, items = item[:3] if len(item) >= 3 else ("", "", [])
        start_date = item[3] if len(item) >= 4 else None

    if language() == "en":
        if not start_date and date_str:
            for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
                try:
                    start_date = datetime.strptime(date_str, fmt).date()
                except ValueError:
                    continue
                break
        if start_date:
            week_title = _("Неделя от {date}", date=format_output_date(start_date))
        elif isinstance(item, dict) and item.get("week_id"):
            week_title = _("Неделя {week}", week=item["week_id"])
        else:
            week_title = _("Неделя")
        date_str = ""
    return week_title, date_str, items, start_date


def _build_html(
    recipient_name: str,
    sender_name: str,
    assignments_by_week: List[Any],
    meeting_day: str = "",
    meeting_time: str = "19:00",
    cong_name: str = "",
    custom_note: Optional[str] = None,
    custom_body: Optional[str] = None,
    confirm_links: Optional[Tuple[str, str]] = None,
) -> str:
    """
    Генерирует HTML-письмо с поддержкой кнопки добавления в Google Календарь.

    Args:
        recipient_name: Имя получателя (первое слово из ФИО).
        sender_name: Имя отправителя.
        assignments_by_week: список недель (dict или tuple).
        meeting_day: День встречи из настроек.
        meeting_time: Время встречи из настроек.
        cong_name: Название собрания.
        custom_note: Персональное примечание к стандартному шаблону.
        custom_body: Полный произвольный текст письма (заменяет стандартный).

    Returns:
        HTML-строка письма.
    """
    first_name = _format_greeting_name(recipient_name)

    weeks_html = ""
    for item in assignments_by_week:
        week_title, date_str, items, start_date = _week_email_data(item)

        items_html = "".join(f"<li>{it}</li>" for it in items)

        # Вычисляем дату встречи и ссылку на Google Календарь
        dt_start, dt_end, display_date = _calculate_meeting_datetime(
            start_date, meeting_day, meeting_time
        )

        cal_btn_html = ""
        if dt_start and dt_end:
            title = _("Встреча собрания — {name}", name=first_name)
            details = _("Ваши задания на встрече собрания:\n") + "\n".join(
                f"• {it}" for it in items
            )
            gcal_url = _generate_google_calendar_url(title, dt_start, dt_end, details, cong_name)
            outlook_url = _generate_outlook_calendar_url(
                title, dt_start, dt_end, details, cong_name
            )
            time_display = dt_start.strftime("%H:%M")
            date_header_suffix = _(
                " — {date} (начало встречи в {time})", date=display_date, time=time_display
            )

            apple_instructions = _(
                "нажмите на файл <b>assignments.ics</b> внизу письма ⬇ и затем «Добавить»."
                "<br>Если кнопки «Добавить» нет: «Поделиться» → «Сохранить в Файлы», "
                "откройте файл в приложении «Файлы» → «Добавить в календарь»."
            )
            cal_btn_html = f"""
            <div style="margin-top: 12px; padding-top: 10px; border-top: 1px solid #e2e8f0; font-size: 12px;">
                <div style="margin-bottom: 8px; font-weight: bold; color: #475569; font-size: 12px;">
                    🗓️ {_('Добавить напоминание в календарь:')}
                </div>
                <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 6px;">
                    <a href="{gcal_url}" target="_blank" style="display: inline-block; background-color: #1a73e8; color: #ffffff; text-decoration: none; padding: 6px 12px; border-radius: 6px; font-weight: bold; font-size: 11px; margin-right: 6px; margin-bottom: 4px;">
                        📅 {_('Google Календарь')}
                    </a>
                    <a href="{outlook_url}" target="_blank" style="display: inline-block; background-color: #0078d4; color: #ffffff; text-decoration: none; padding: 6px 12px; border-radius: 6px; font-weight: bold; font-size: 11px; margin-right: 6px; margin-bottom: 4px;">
                        📫 Outlook / 365
                    </a>
                </div>
                <div style="background-color: #111827; color: #ffffff; border-radius: 6px; padding: 8px 12px; margin-top: 4px; font-size: 12px; line-height: 1.5;">
                    🍏 <b>iPhone / iPad / Mac:</b> {apple_instructions}
                </div>
            </div>
            """
        else:
            date_header_suffix = f" — {date_str}" if date_str else ""

        weeks_html += f"""
        <div class="week">
            <div class="week-header">📅 {week_title}{date_header_suffix}</div>
            <ul>{items_html}</ul>
            {cal_btn_html}
        </div>
        """

    note_html = ""
    if custom_note and custom_note.strip():
        import html

        escaped_note = html.escape(custom_note.strip()).replace("\n", "<br>")
        note_html = f"""
        <div style="background-color: #f0fdf4; border-left: 4px solid #16a34a; padding: 12px 16px; margin: 16px 0; border-radius: 4px; font-size: 14px; color: #166534;">
            <strong>💬 {_('Примечание:')}</strong><br>
            {escaped_note}
        </div>
        """

    if custom_body and custom_body.strip():
        import html

        escaped_body = html.escape(custom_body.strip()).replace("\n", "<br>")
        main_content = f"""
        <div style="margin: 16px 0; line-height: 1.6; font-size: 14px;">
            {escaped_body}
        </div>
        """
    else:
        follow_up = _(
            "Если у вас есть вопросы или вы не сможете выполнить задание — "
            "пожалуйста, свяжитесь с нами заранее."
        )
        main_content = f"""
        <p>{_('Дорогой(-ая) {name},', name=first_name)}</p>
        {note_html}
        <p>{_('Ниже ваши задания на ближайшие встречи собрания:')}</p>

        {weeks_html}

        <p>{follow_up}</p>
        """

    return f"""<!DOCTYPE html>
<html lang="{language()}">
<head>
<meta charset="UTF-8">
<style>
  body {{ font-family: Arial, sans-serif; font-size: 14px; color: #333; background: #f5f5f5; margin: 0; padding: 20px; }}
  .container {{ max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; padding: 30px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
  h2 {{ color: #1565c0; margin-top: 0; }}
  .week {{ background: #f8f9fa; border-left: 4px solid #1565c0; border-radius: 4px; padding: 12px 16px; margin: 16px 0; }}
  .week-header {{ font-weight: bold; color: #1565c0; margin-bottom: 8px; font-size: 15px; }}
  ul {{ margin: 0; padding-left: 20px; }}
  li {{ margin: 4px 0; }}
  .footer {{ margin-top: 24px; color: #777; font-size: 12px; border-top: 1px solid #eee; padding-top: 16px; }}
</style>
</head>
<body>
<div class="container">
  <h2>📋 {_('Ваши задания')}</h2>
  {main_content}
  {_confirm_buttons_html(confirm_links)}
  <div class="footer">
    {_('С братской любовью,')}<br>
    <strong>{sender_name}</strong>
  </div>
</div>
</body>
</html>"""


def _build_plain_text(
    recipient_name: str,
    sender_name: str,
    assignments_by_week: List[Any],
    meeting_day: str = "",
    meeting_time: str = "19:00",
    cong_name: str = "",
    custom_note: Optional[str] = None,
    custom_body: Optional[str] = None,
    confirm_links: Optional[Tuple[str, str]] = None,
) -> str:
    """Текстовая версия письма (fallback для почтовых клиентов без HTML)."""
    first_name = _format_greeting_name(recipient_name)

    if custom_body and custom_body.strip():
        lines = [custom_body.strip(), "", _("С братской любовью,"), sender_name]
        return "\n".join(lines)

    lines = [
        _("Дорогой(-ая) {name},", name=first_name),
        "",
    ]
    if custom_note and custom_note.strip():
        lines += [
            _("💬 Примечание: {note}", note=custom_note.strip()),
            "",
        ]
    lines += [
        _("Ниже ваши задания на ближайшие встречи собрания:"),
        "",
    ]
    for item in assignments_by_week:
        week_title, date_str, items, start_date = _week_email_data(item)

        dt_start, dt_end, display_date = _calculate_meeting_datetime(
            start_date, meeting_day, meeting_time
        )
        if dt_start:
            time_display = dt_start.strftime("%H:%M")
            date_label = _(
                " — {date} (начало встречи в {time})", date=display_date, time=time_display
            )
            lines.append(f"📅 {week_title}{date_label}")
        else:
            date_label = f" — {date_str}" if date_str else ""
            lines.append(f"📅 {week_title}{date_label}")

        for it in items:
            lines.append(f"  • {it}")

        if dt_start and dt_end:
            title = _("Встреча собрания — {name}", name=first_name)
            details = _("Ваши задания на встрече собрания:\n") + "\n".join(
                f"• {it}" for it in items
            )
            gcal_url = _generate_google_calendar_url(title, dt_start, dt_end, details, cong_name)
            outlook_url = _generate_outlook_calendar_url(
                title, dt_start, dt_end, details, cong_name
            )
            lines.append(_("  [+] Добавить в Google Календарь: {url}", url=gcal_url))
            lines.append(_("  [+] Добавить в Outlook / 365: {url}", url=outlook_url))
            lines.append(
                _(
                    "  [+] iPhone / iPad / Mac: нажмите на файл assignments.ics внизу письма, "
                    "затем «Добавить»."
                )
            )
            lines.append(
                _(
                    "      Если «Добавить» нет: «Поделиться» → «Сохранить в Файлы», "
                    "откройте файл в «Файлах» → «Добавить в календарь»."
                )
            )

        lines.append("")

    if confirm_links:
        lines += [
            _("Пожалуйста, ответьте на это письмо: «Подтверждаю» или «Не смогу»."),
            "",
        ]
    lines += [
        _("Если у вас есть вопросы — свяжитесь с нами заранее."),
        "",
        _("С братской любовью,"),
        sender_name,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------

_IMAP_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _imap_date(d) -> str:
    """Дата для IMAP SEARCH («01-Oct-2026»). Не strftime("%b"): Qt включает
    системную локаль, и месяц выходит по-русски («окт») — сервер его не примет."""
    return f"{d.day:02d}-{_IMAP_MONTHS[d.month - 1]}-{d.year}"


def _utc_naive(dt: datetime) -> datetime:
    """Время в UTC без пояса — как sent_at в истории (SQLite CURRENT_TIMESTAMP).
    Дата письма без пояса считается местной."""
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _plain_body(msg) -> str:
    """Текст письма (первая text/plain часть) — для ответа без кнопки."""
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.get_content_type() == "text/plain":
            payload = part.get_payload(decode=True) or b""
            return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    return ""


class NotificationService:
    """Сервис отправки email-уведомлений участникам о заданиях."""

    GMAIL_HOST = "smtp.gmail.com"
    GMAIL_PORT_SSL = 465
    # Секунд на соединение и ответ SMTP/IMAP: без таймаута недоступный сервер
    # держит проверку и отправку несколько минут.
    NETWORK_TIMEOUT = 20
    GMAIL_PORT_TLS = 587

    def __init__(
        self,
        smtp_host: str = "smtp.gmail.com",
        smtp_port: int = 465,
        smtp_user: str = "",
        smtp_password: str = "",
        sender_name: str = "",
        meeting_day: str = "",
        meeting_time: str = "19:00",
        cong_name: str = "",
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.sender_name = sender_name or smtp_user
        self.meeting_day = meeting_day
        self.meeting_time = meeting_time
        self.cong_name = cong_name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def test_connection(self) -> Tuple[bool, str]:
        """
        Проверяет SMTP-соединение.

        Returns:
            (success: bool, message: str)
        """
        try:
            self._connect_smtp()
            return True, _("Соединение успешно установлено ✅")
        except smtplib.SMTPAuthenticationError:
            return False, _("Ошибка аутентификации — проверьте логин и пароль приложения")
        except smtplib.SMTPConnectError as e:
            return False, _("Не удалось подключиться к серверу: {e}", e=e)
        except Exception as e:
            return False, _("Ошибка: {e}", e=e)

    def send_assignment_notifications(
        self,
        week_ids: List[int],
        db_manager,
        participant_ids: List[int] = None,
        progress_callback=None,
        custom_messages: Optional[Dict[int, dict]] = None,
    ) -> NotificationResult:
        """
        Отправляет персональные уведомления участникам с заданиями
        в указанных неделях.

        Args:
            week_ids: Список ID недель для рассылки.
            db_manager: DatabaseManager для доступа к данным.
            participant_ids: Опционально — список ID участников для отправки.
                           Если None — отправляет всем.
            progress_callback: Опционально — callable(current, total, name)
                               для обновления прогресс-бара.
            custom_messages: Опционально — {participant_id: {"subject": str, "note": str, "custom_body": str}}

        Returns:
            NotificationResult со статистикой.
        """
        result = NotificationResult()

        # 1. Собираем данные из БД (фильтруем по participant_ids если указано)
        participant_assignments = self._collect_assignments(week_ids, db_manager, participant_ids)

        if not participant_assignments:
            logger.info(_("Нет назначенных участников для рассылки"))
            return result

        total = len(participant_assignments)

        # 2. Подключаемся к SMTP (одно соединение для всех писем)
        try:
            server = self._connect_smtp()
        except Exception as e:
            logger.error(_("Ошибка SMTP: {e}", e=e))
            result.failed = total
            result.failed_names = [p["name"] for p in participant_assignments.values()]
            return result

        # 3. Отправляем письма
        try:
            for idx, (p_id, p_data) in enumerate(participant_assignments.items()):
                if progress_callback:
                    progress_callback(idx + 1, total, p_data["name"])

                # История — только по неделям, где у участника есть задания,
                # а не по всем выбранным: иначе он «уведомлён» о чужих неделях.
                p_week_ids = [w["week_id"] for w in p_data.get("weeks", [])] or list(week_ids)

                email = p_data.get("email")
                if not email:
                    result.skipped_no_email += 1
                    result.skipped_names.append(p_data["name"])
                    logger.debug(_("Пропущен (нет email): {name}", name=p_data["name"]))
                    continue

                try:
                    custom = (custom_messages or {}).get(p_id, {})
                    c_subject = custom.get("subject")
                    c_note = custom.get("note")
                    c_body = custom.get("custom_body")

                    msg = self._build_message(
                        email,
                        p_data,
                        custom_subject=c_subject,
                        custom_note=c_note,
                        custom_body=c_body,
                        participant_id=p_id,
                    )
                    server.sendmail(self.smtp_user, email, msg.as_string())
                    result.sent += 1
                    logger.info(
                        _("✅ Отправлено: {name} → {email}", name=p_data["name"], email=email)
                    )
                except Exception as e:
                    result.failed += 1
                    result.failed_names.append(p_data["name"])
                    logger.error(_("❌ Ошибка отправки {name}: {e}", name=p_data["name"], e=e))

                    # Сохраняем историю ошибки (не прерываем цикл!)
                    with db_manager.get_session() as session:
                        for wid in p_week_ids:
                            session.add(
                                NotificationHistory(
                                    participant_id=p_id,
                                    week_id=wid,
                                    status="error",
                                    error_message=str(e),
                                    subject=c_subject
                                    or _("Уведомление на неделю {week}", week=wid),
                                )
                            )
                        session.commit()
                    continue

                # Письмо ушло: ошибка записи истории не делает его неотправленным
                try:
                    with db_manager.get_session() as session:
                        for wid in p_week_ids:
                            session.add(
                                NotificationHistory(
                                    participant_id=p_id,
                                    week_id=wid,
                                    status="success",
                                    subject=c_subject
                                    or _("Уведомление на неделю {week}", week=wid),
                                )
                            )
                        # новое уведомление — прежний ответ («подтвердил») уже не о нём
                        session.query(NotificationResponse).filter(
                            NotificationResponse.participant_id == p_id,
                            NotificationResponse.week_id.in_(p_week_ids),
                        ).delete(synchronize_session=False)
                        session.commit()
                except Exception as e:
                    logger.error(
                        _("Не удалось записать историю для {name}: {e}", name=p_data["name"], e=e)
                    )
        finally:
            try:
                server.quit()
            except Exception:
                pass

        return result

    IMAP_HOST = "imap.gmail.com"  # если адрес по SMTP не угадать
    # Почтовые службы, где IMAP не равен «smtp.» → «imap.»
    IMAP_BY_SMTP = {
        "smtp.office365.com": "outlook.office365.com",
        "smtp-mail.outlook.com": "outlook.office365.com",
        "smtp.mail.me.com": "imap.mail.me.com",
    }

    @property
    def imap_host(self) -> str:
        """Сервер IMAP по серверу SMTP: smtp.yandex.ru → imap.yandex.ru и т. п.
        Раньше всегда был Gmail — у других почт «Проверить ответы» не работал."""
        smtp = (self.smtp_host or "").strip().lower()
        if smtp in self.IMAP_BY_SMTP:
            return self.IMAP_BY_SMTP[smtp]
        if smtp.startswith("smtp."):
            return "imap." + smtp[len("smtp.") :]
        # mail.example.org и т. п. — обычно и SMTP, и IMAP на одном сервере
        return smtp or self.IMAP_HOST

    def fetch_replies(self, days: int = 60) -> Tuple[List[Tuple[datetime, Reply]], int]:
        """Прочитать во «Входящих» ответы на уведомления (только чтение, письма
        не помечаются прочитанными). Тот же логин и пароль приложения, что для SMTP.

        Returns:
            ([(дата письма, Reply)], сколько писем с меткой разобрать не удалось)
        """
        since = _imap_date(datetime.now() - timedelta(days=days))
        replies, unclear = [], 0
        imap = imaplib.IMAP4_SSL(
            self.imap_host, timeout=self.NETWORK_TIMEOUT, ssl_context=tls.create_default_context()
        )
        try:
            imap.login(self.smtp_user, self.smtp_password)
            imap.select("INBOX", readonly=True)
            status, data = imap.search(None, f'(SINCE {since} SUBJECT "NHJS-")')
            if status != "OK":
                return [], 0
            for num in data[0].split():
                status, parts = imap.fetch(num, "(BODY.PEEK[])")
                if status != "OK" or not parts or not isinstance(parts[0], tuple):
                    continue
                msg = email.message_from_bytes(parts[0][1])
                subject = str(make_header(decode_header(msg.get("Subject", ""))))
                reply = parse_reply(subject, _plain_body(msg))
                if reply is None:
                    unclear += 1
                    continue
                try:
                    when = _utc_naive(email.utils.parsedate_to_datetime(msg.get("Date")))
                except (TypeError, ValueError):
                    when = utc_now()
                sender = email.utils.parseaddr(msg.get("From", ""))[1]
                replies.append((when, reply._replace(sender=sender)))
        finally:
            try:
                imap.logout()
            except Exception:
                pass
        replies.sort(key=lambda item: item[0])
        return replies, unclear

    def preview_for_participant(
        self,
        participant_name: str,
        assignments_by_week: List[Any],
        custom_note: Optional[str] = None,
        custom_body: Optional[str] = None,
    ) -> str:
        """Генерирует HTML-превью письма для показа в UI."""
        return _build_html(
            participant_name,
            self.sender_name,
            assignments_by_week,
            meeting_day=self.meeting_day,
            meeting_time=self.meeting_time,
            cong_name=self.cong_name,
            custom_note=custom_note,
            custom_body=custom_body,
        )

    def collect_participant_assignments(
        self,
        week_ids: List[int],
        db_manager,
        participant_id: int,
    ) -> Optional[dict]:
        """Собирает задания для одного конкретного участника (для предпросмотра)."""
        assignments = self._collect_assignments(week_ids, db_manager, [participant_id])
        return assignments.get(participant_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _connect_smtp(self):
        """Устанавливает SMTP-соединение. Возвращает активный server объект."""
        if self.smtp_port == self.GMAIL_PORT_SSL:
            # SSL
            ctx = tls.create_default_context()
            server = smtplib.SMTP_SSL(
                self.smtp_host, self.smtp_port, context=ctx, timeout=self.NETWORK_TIMEOUT
            )
        else:
            # STARTTLS (порт 587 или другой)
            server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=self.NETWORK_TIMEOUT)
            server.ehlo()
            server.starttls(context=tls.create_default_context())
            server.ehlo()

        server.login(self.smtp_user, self.smtp_password)
        return server

    def _build_ics_for_participant(self, p_data: dict) -> str:
        """Генерирует содержимое .ics со всеми событиями и напоминаниями для участника."""
        events = []
        pid = p_data.get("id", "0")
        name = p_data.get("name", "")
        first_name = _format_greeting_name(name)

        for item in p_data.get("weeks", []):
            week_id = item.get("week_id", "0") if isinstance(item, dict) else "0"
            _title, _date_label, items, start_date = _week_email_data(item)

            if not start_date:
                continue

            dt_start, dt_end, _display_date = _calculate_meeting_datetime(
                start_date, self.meeting_day, self.meeting_time
            )
            if not dt_start or not dt_end:
                continue

            if len(items) == 1:
                summary = _("Встреча собрания: {item}", item=items[0])
            else:
                summary = _("Встреча собрания — Задания ({count})", count=len(items))

            # Формируем описание события с настоящими переносами строк \n
            # Функция _escape_ics_text сама корректно преобразует \n в \n для RFC 5545
            desc_lines = [
                _("Дорогой(-ая) {name},", name=first_name),
                _("Ваши задания на встрече собрания:"),
            ]
            for it in items:
                desc_lines.append(f"• {it}")
            description = "\n".join(desc_lines)
            uid = f"nhjs-p{pid}-w{week_id}-{dt_start.strftime('%Y%m%d')}@nhjs"

            events.append(
                {
                    "uid": uid,
                    "dt_start": dt_start,
                    "dt_end": dt_end,
                    "summary": summary,
                    "description": description,
                    "location": self.cong_name,
                }
            )

        if not events:
            return ""

        return _build_ics_content(events, self.cong_name)

    def _build_message(
        self,
        recipient_email: str,
        p_data: dict,
        custom_subject: Optional[str] = None,
        custom_note: Optional[str] = None,
        custom_body: Optional[str] = None,
        participant_id: Optional[int] = None,
    ) -> MIMEMultipart:
        """Строит MIME-сообщение для одного участника (mixed -> alternative + ics).

        С participant_id в тему добавляется метка [NHJS-…], а в письмо — кнопки
        «Подтверждаю» / «Не смогу» (ответы разбирает fetch_replies)."""
        name = p_data["name"]
        weeks = p_data["weeks"]  # [(week_title, date_str, [items]), ...] или list of dicts
        subject = (
            custom_subject.strip()
            if (custom_subject and custom_subject.strip())
            else _("Ваши задания на встрече собрания")
        )
        confirm_links = None
        week_ids = [w["week_id"] for w in weeks if isinstance(w, dict) and w.get("week_id")]
        if participant_id and week_ids and self.smtp_user:
            tag = make_tag(participant_id, week_ids)
            confirm_links = (
                mailto_url(self.smtp_user, subject, tag, CONFIRMED),
                mailto_url(self.smtp_user, subject, tag, DECLINED),
            )
            subject = f"{subject} {tag}"

        html_body = _build_html(
            name,
            self.sender_name,
            weeks,
            meeting_day=self.meeting_day,
            meeting_time=self.meeting_time,
            cong_name=self.cong_name,
            custom_note=custom_note,
            custom_body=custom_body,
            confirm_links=confirm_links,
        )
        plain_body = _build_plain_text(
            name,
            self.sender_name,
            weeks,
            meeting_day=self.meeting_day,
            meeting_time=self.meeting_time,
            cong_name=self.cong_name,
            custom_note=custom_note,
            custom_body=custom_body,
            confirm_links=confirm_links,
        )

        from_header = (
            f"{self.sender_name} <{self.smtp_user}>" if self.sender_name else self.smtp_user
        )

        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"] = from_header
        msg["To"] = recipient_email

        alt_part = MIMEMultipart("alternative")
        alt_part.attach(MIMEText(plain_body, "plain", "utf-8"))
        alt_part.attach(MIMEText(html_body, "html", "utf-8"))

        msg.attach(alt_part)

        # Календарь — одним вложением assignments.ics. Внутрь alternative его не
        # кладём: iOS Mail принимает такую часть за приглашение (iMIP), показывает
        # событие, но «Добавить» его не сохраняет; к тому же второй экземпляр с теми
        # же UID путает календарь. Параметра method в Content-Type нет: с ним
        # вложение — приглашение iMIP, и iOS Mail открывает его лишь просмотром
        # («Готово»/«Поделиться») без «Добавить» (iPhone, iOS 27.2, 30.10).
        ics_text = self._build_ics_for_participant(p_data)
        if ics_text:
            ics_part = MIMEBase("text", "calendar", charset="utf-8", name="assignments.ics")
            ics_part.set_payload(ics_text.encode("utf-8"))
            encoders.encode_base64(ics_part)
            ics_part.add_header("Content-Disposition", "attachment", filename="assignments.ics")
            msg.attach(ics_part)

        return msg

    def _collect_assignments(
        self,
        week_ids: List[int],
        db_manager,
        participant_ids: List[int] = None,
    ) -> Dict[int, dict]:
        """
        Собирает задания участников из БД для указанных недель.

        Args:
            week_ids: Список ID недель.
            db_manager: DatabaseManager для доступа к данным.
            participant_ids: Опционально — фильтр по ID участников.

        Returns:
            {participant_id: {
                "name": str,
                "email": str | None,
                "weeks": [(week_title, date_str, [task_str, ...]), ...]
            }}
        """
        from core.models import NotificationHistory

        result: Dict[int, dict] = {}

        with db_manager.get_session() as session:
            # Загружаем недели
            weeks_data: Dict[int, Week] = {}
            for wid in week_ids:
                w = session.get(Week, wid)
                if w:
                    weeks_data[wid] = w

            # Загружаем все назначения для выбранных недель
            query = (
                select(Assignment)
                .where(Assignment.week_id.in_(week_ids))
                .where(Assignment.status == "assigned")
            )

            # Фильтруем по participant_ids если указано
            if participant_ids:
                query = query.where(
                    (Assignment.participant_id.in_(participant_ids))
                    | (Assignment.assistant_id.in_(participant_ids))
                )

            assignments = session.execute(query).scalars().all()

            # Время начала каждого пункта — как в таблице расписания
            item_starts: Dict[int, int] = {}
            for wid in weeks_data:
                item_starts.update(self._assignment_start_minutes(session, wid))

            # Для каждого назначения собираем данные участника
            participant_cache: Dict[int, Participant] = {}

            def _get_participant(pid: Optional[int]) -> Optional[Participant]:
                if pid is None:
                    return None
                if pid not in participant_cache:
                    p = session.get(Participant, pid)
                    if p:
                        participant_cache[pid] = p
                return participant_cache.get(pid)

            for a in assignments:
                week = weeks_data.get(a.week_id)
                if not week:
                    continue

                week_title = week.week_title or _("Неделя {week}", week=a.week_id)
                date_str = ""
                if week.start_date:
                    date_str = week.start_date.strftime("%d.%m.%Y")

                # Учащийся и помощник: каждому — с кем он в этом пункте
                main_p = _get_participant(a.participant_id)
                assist_p = _get_participant(a.assistant_id)
                task_text = _format_assignment(
                    a.assignment_text,
                    a.duration,
                    "participant",
                    gender=main_p.gender if main_p else None,
                    partner_name=assist_p.name if assist_p else None,
                    partner_gender=assist_p.gender if assist_p else None,
                )
                assistant_task_text = _format_assignment(
                    a.assignment_text,
                    a.duration,
                    "assistant",
                    gender=assist_p.gender if assist_p else None,
                    partner_name=main_p.name if main_p else None,
                    partner_gender=main_p.gender if main_p else None,
                )
                if a.id in item_starts:
                    time_prefix = _("в {time} — ", time=format_minutes(item_starts[a.id]))
                    task_text = time_prefix + task_text
                    assistant_task_text = time_prefix + assistant_task_text

                # Основной участник
                if a.participant_id and (
                    participant_ids is None or a.participant_id in participant_ids
                ):
                    p = _get_participant(a.participant_id)
                    if p:
                        self._add_to_result(
                            result, p, a.week_id, week_title, date_str, task_text, week.start_date
                        )

                # Напарник
                if a.assistant_id and (
                    participant_ids is None or a.assistant_id in participant_ids
                ):
                    p = _get_participant(a.assistant_id)
                    if p:
                        self._add_to_result(
                            result,
                            p,
                            a.week_id,
                            week_title,
                            date_str,
                            assistant_task_text,
                            week.start_date,
                        )

        # Задания по неделям в порядке дат: номер записи недели с датой не
        # совпадает (недели добавляются из тетрадей и «Будущего года» вперемешку)
        for p_id, p_data in result.items():
            sorted_weeks = []
            raw = p_data["weeks_raw"]
            for wid in sorted(raw, key=lambda w: (raw[w][3] is None, raw[w][3] or date.min, w)):
                wt, ds, items, s_date = p_data["weeks_raw"][wid]
                sorted_weeks.append(
                    {
                        "week_id": wid,
                        "week_title": wt,
                        "date_str": ds,
                        "items": items,
                        "start_date": s_date,
                    }
                )
            p_data["weeks"] = sorted_weeks

        return result

    def _assignment_start_minutes(self, session, week_id: int) -> Dict[int, int]:
        """{id назначения: минуты от полуночи} — время пункта по core/week_layout,
        как в таблице и просмотре недели. Чтец ИБС — со временем ведущего ИБС."""
        from core.repositories.week_repository import WeekRepository

        data = WeekRepository(session=session).get_week_data(week_id)
        if not data:
            return {}
        week_items, _ = apply_circuit_overseer_week(data["week"], data["assignments"])
        ordered = [a for _, a in order_week_assignments(week_items)]
        starts = start_minutes(ordered, parse_meeting_start(self.meeting_time))

        result: Dict[int, int] = {}
        cbs_start = None
        for a, minutes in zip(ordered, starts):
            if a.get("assignment_type") == "cbs":
                cbs_start = minutes
        for a, minutes in zip(ordered, starts):
            if a.get("assignment_type") == "circuit_overseer_talk":
                continue  # подменённый пункт: его id — от бывшего ИБС
            if a.get("assignment_type") == "cbs_reader":
                if cbs_start is None:
                    continue
                minutes = cbs_start
            result[a["id"]] = minutes
        return result

    def _add_to_result(
        self,
        result: Dict,
        participant,
        week_id: int,
        week_title: str,
        date_str: str,
        task_text: str,
        start_date: Optional[date] = None,
    ) -> None:
        """Добавляет задание участника в словарь результата."""
        pid = participant.id
        if pid not in result:
            result[pid] = {
                "id": pid,
                "name": participant.name,
                "email": participant.email,
                "weeks_raw": {},  # {week_id: (title, date_str, [items], start_date)}
                "weeks": [],
            }
        weeks_raw = result[pid]["weeks_raw"]
        if week_id not in weeks_raw:
            weeks_raw[week_id] = (week_title, date_str, [], start_date)
        weeks_raw[week_id][2].append(task_text)
