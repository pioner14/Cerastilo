"""
Ответы участников на email-уведомления: «Подтверждаю» / «Не смогу».

Без ботов и без сервера: в теме письма метка [NHJS-<участник>-<недели>],
кнопки в письме открывают ответ (mailto:) с той же меткой и словом OK или NO.
Приложение читает входящие по IMAP (NotificationService.fetch_replies) и
разбирает ответы здесь. Чистая логика — без Qt и без базы.
"""

import re
from typing import Iterable, List, NamedTuple, Optional
from urllib.parse import quote

from core.i18n import _

CONFIRMED = "confirmed"
DECLINED = "declined"

TAG_PREFIX = "NHJS-"
_TAG_RE = re.compile(r"\[NHJS-(\d+)-([\d.]+)(?:-(OK|NO))?\]", re.IGNORECASE)

# Слова в начале ответа, если человек ответил обычным «Ответить», без кнопки
_YES_WORDS = (
    "подтверждаю",
    "да",
    "ок",
    "ok",
    "хорошо",
    "буду",
    "согласен",
    "согласна",
    "готов",
    "готова",
    "i confirm",
    "i can make it",
    "yes",
)
_NO_WORDS = (
    "не смогу",
    "нет",
    "не могу",
    "не получится",
    "не буду",
    "i can t make it",
    "i cannot make it",
    "i can not make it",
    "i decline",
    "no",
)
# Начинаются с «нет», но значат согласие: «Нет проблем, буду»
_YES_PHRASES = ("нет проблем", "нет вопросов", "без проблем", "no problem", "no worries")


class Reply(NamedTuple):
    participant_id: int
    week_ids: List[int]
    response: str  # CONFIRMED | DECLINED
    sender: str = ""  # адрес отправителя ответа (From), если известен


def normalize_email(address: str) -> str:
    """Адрес для сравнения. Gmail не различает точки в имени и часть после «+»:
    mr.alex@gmail.com и mralex+x@googlemail.com — один ящик."""
    address = (address or "").strip().lower()
    local, at, domain = address.rpartition("@")
    if at and domain in ("gmail.com", "googlemail.com"):
        return local.split("+", 1)[0].replace(".", "") + "@gmail.com"
    return address


def make_tag(participant_id: int, week_ids: Iterable[int]) -> str:
    """«[NHJS-93-63.64]» — метка письма участнику 93 о неделях 63 и 64."""
    weeks = ".".join(str(w) for w in sorted(set(week_ids)))
    return f"[{TAG_PREFIX}{participant_id}-{weeks}]"


def _kind_tag(tag: str, response: str) -> str:
    return tag[:-1] + ("-OK]" if response == CONFIRMED else "-NO]")


def mailto_url(sender_email: str, subject: str, tag: str, response: str) -> str:
    """Ссылка-кнопка: открывает ответное письмо с готовой темой и текстом."""
    word = _("Подтверждаю") if response == CONFIRMED else _("Не смогу")
    reply_subject = f"{word}: {subject} {_kind_tag(tag, response)}"
    return f"mailto:{sender_email}?subject={quote(reply_subject)}&body={quote(word)}"


def _first_line(body: str) -> str:
    for line in (body or "").splitlines():
        line = line.strip()
        if line and not line.startswith(">"):
            return line.lower()
    return ""


def _response_from_text(subject: str, body: str) -> Optional[str]:
    lowered = (subject or "").lower()
    if lowered.startswith(
        ("не смогу", "i can't make it", "i can’t make it", "i cannot make it", "i decline")
    ):
        return DECLINED
    if lowered.startswith(("подтверждаю", "i confirm:", "i confirm ")):
        return CONFIRMED
    first = re.sub(r"[^\w\s]", " ", _first_line(body)).strip()
    first = re.sub(r"\s+", " ", first)
    if any(first == w or first.startswith(w + " ") for w in _YES_PHRASES):
        return CONFIRMED
    if any(first == w or first.startswith(w + " ") for w in _NO_WORDS):
        return DECLINED  # «не смогу» проверяем раньше «да»: «нет, не смогу»
    if any(first == w or first.startswith(w + " ") for w in _YES_WORDS):
        return CONFIRMED
    return None


def parse_reply(subject: str, body: str = "") -> Optional[Reply]:
    """Разобрать ответ. None — в теме нет метки или непонятно, да это или нет."""
    match = _TAG_RE.search(subject or "")
    if not match:
        return None
    pid, weeks, kind = match.groups()
    if kind:
        response = CONFIRMED if kind.upper() == "OK" else DECLINED
    else:
        response = _response_from_text(subject, body)
        if response is None:
            return None
    week_ids = [int(w) for w in weeks.split(".") if w]
    return Reply(int(pid), week_ids, response)
