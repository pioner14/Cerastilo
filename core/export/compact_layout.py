# core/export/compact_layout.py
"""
Содержимое компактного современного расписания (две недели на лист) без
привязки к формату файла.

Отсюда берут строки и DOCX-билдер (compact_v2_builder.py, десктоп: DOCX и PDF
через LibreOffice), и Qt-рендер PDF на Android (qt_pdf.py) — поэтому PDF на
планшете совпадает с PDF на ПК. Модуль не зависит от python-docx.
"""

from datetime import date, datetime, timedelta

from core.export.filename import month_names
from core.i18n import _, language
from core.week_layout import assignment_label, counsel_minutes

SECTION_TREASURES = "treasures"
SECTION_MINISTRY = "ministry"
SECTION_LIVING = "living"

SECTION_TITLES = {
    SECTION_TREASURES: "СОКРОВИЩА ИЗ СЛОВА БОГА",
    SECTION_MINISTRY: "ОТТАЧИВАЕМ НАВЫКИ СЛУЖЕНИЯ",
    SECTION_LIVING: "ХРИСТИАНСКАЯ ЖИЗНЬ",
}

SPECIAL_EVENT_TITLES = {
    "memorial": "🍷 Вечеря Господня",
    "circuit_assembly": "🏟️ Районный Конгресс",
    "regional_convention": "🌍 Региональный Конгресс",
}
SPECIAL_EVENT_MESSAGES = {
    "memorial": "На этой неделе обычная встреча не проводится.",
    "circuit_assembly": "Встреча-собрание не запланирована.\nВстреча отменена в связи с конгрессом.",
    "regional_convention": "Встреча-собрание не запланирована.\nВстреча отменена в связи с конгрессом.",
}

MONTHS_GENITIVE = [
    "",
    "ЯНВАРЯ",
    "ФЕВРАЛЯ",
    "МАРТА",
    "АПРЕЛЯ",
    "МАЯ",
    "ИЮНЯ",
    "ИЮЛЯ",
    "АВГУСТА",
    "СЕНТЯБРЯ",
    "ОКТЯБРЯ",
    "НОЯБРЯ",
    "ДЕКАБРЯ",
]


def parse_time(time_str: str, default: str = "19:00") -> datetime:
    try:
        return datetime.strptime((time_str or default).replace(".", ":"), "%H:%M")
    except ValueError:
        return datetime.strptime(default, "%H:%M")


def fmt_time(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def parse_date(date_obj) -> str:
    """Дата для вывода (объект date или строка YYYY-MM-DD)."""
    date_format = "%d.%m.%Y" if language() == "ru" else "%Y-%m-%d"
    try:
        if isinstance(date_obj, date):
            return date_obj.strftime(date_format)
        if date_obj:
            return datetime.strptime(date_obj, "%Y-%m-%d").strftime(date_format)
        return ""
    except (ValueError, TypeError):
        return str(date_obj) if date_obj else ""


def parse_songs(songs_str: str) -> list:
    return [s.strip() for s in (songs_str or "").split(",") if s.strip()]


def by_position(assignments: list, position: str):
    return next((a for a in assignments if a["position"] == position), None)


def by_type(assignments: list, atype: str):
    return next((a for a in assignments if a["type"] == atype), None)


def section_items(assignments: list, section: str) -> list:
    return sorted(
        [a for a in assignments if a["section"] == section], key=lambda x: str(x["position"])
    )


# Ширина листа A4 без полей 1,25 см и колонка времени, см.
CONTENT_WIDTH_CM = 18.5
TIME_COL_CM = 1.2
NAME_COL_MIN_CM = 6.0
NAME_COL_MAX_CM = 10.4
# Средняя ширина знака жирного 12 pt (Calibri) и запас на поля ячейки, см.
NAME_CM_PER_CHAR = 0.24
NAME_PAD_CM = 0.4


def name_column_cm(layouts: list) -> float:
    """Ширина колонки имён по самому длинному имени на листе: колонка
    кончается у правого края, остальное место — названиям пунктов.
    Оценка по числу знаков (без шрифтов — работает и без Qt, и без Word)."""
    longest = max(
        (
            len(line)
            for lay in layouts
            for row in lay.get("rows", [])
            for line in (row.get("person") or "").split("\n")
        ),
        default=0,
    )
    width = longest * NAME_CM_PER_CHAR + NAME_PAD_CM
    return round(min(max(width, NAME_COL_MIN_CM), NAME_COL_MAX_CM), 2)


def week_title(week) -> str:
    return format_week_title(week.start_date)


def format_week_title(start_date) -> str:
    """«Неделя от 1 ФЕВРАЛЯ» или «Week of February 1»."""
    if not start_date:
        return ""
    try:
        d = (
            start_date
            if isinstance(start_date, date)
            else datetime.strptime(start_date, "%Y-%m-%d")
        )
    except (ValueError, TypeError):
        return str(start_date)
    month = month_names()[d.month] if language() == "en" else MONTHS_GENITIVE[d.month]
    return _("Неделя от {day} {month}", day=d.day, month=month)


def module_contents(week, settings: dict) -> list:
    """Тексты включённых модулей (объявление недели) для низа таблицы."""
    try:
        from modules.announcement import AnnouncementModule
        from modules.registry import ModuleRegistry
    except ImportError:
        return []

    registry = ModuleRegistry()
    registry.register(AnnouncementModule())
    contents = []
    for module in registry.get_all():
        if settings.get(f"module_{module.id}", "true") == "true":
            content = module.get_export_content(week, None)
            if content:
                contents.append(content)
    return contents


def build_week_layout(week_data: dict) -> dict:
    """
    Строки расписания одной недели.

    Возвращает словарь:
      - special: None или {"date", "title", "message", "event"} — неделя без встречи;
      - header: {"title", "reading", "cong_name"};
      - rows: список строк {"kind": "row"|"section"|"module", "time", "text",
        "person", "section", "song"};
      - dense: True, если пунктов много (DOCX уменьшает межстрочный интервал).
    """
    week = week_data["week"]
    asses = week_data["assignments"]
    settings = week_data["settings"]

    event = getattr(week, "special_event", None)
    if event and event != "circuit_overseer":
        return {
            "special": {
                "event": event,
                "date": parse_date(week.start_date),
                "title": _(SPECIAL_EVENT_TITLES.get(event, "Особое событие")),
                "message": _(SPECIAL_EVENT_MESSAGES.get(event, "")),
            },
            "header": None,
            "rows": [],
            "dense": False,
        }

    rows = []

    def row(t, text, person="", song=False):
        rows.append(
            {
                "kind": "row",
                "time": fmt_time(t) if t else "",
                "text": text,
                "person": person or "",
                "section": None,
                "song": song,
            }
        )

    def section(key):
        rows.append(
            {
                "kind": "section",
                "time": "",
                "text": _(SECTION_TITLES[key]),
                "person": "",
                "section": key,
                "song": False,
            }
        )

    t = parse_time(settings.get("meeting_time", "19:00"))
    songs = parse_songs(week.songs)

    total_items = (
        len([a for a in asses if a["section"] == SECTION_TREASURES])
        + len([a for a in asses if a["section"] == SECTION_MINISTRY])
        + len([a for a in asses if a["section"] in ("living", "cbs") and a["type"] != "cbs_reader"])
    )

    chairman = by_position(asses, "chairman")
    prayer_open = by_position(asses, "prayer_open")
    song1 = songs[0] if len(songs) > 0 else ""

    row(t, _("Председатель"), chairman["participant"] if chairman else "—")
    t += timedelta(minutes=1)
    row(
        t,
        _("Песня {n} и молитва", n=song1),
        prayer_open["participant"] if prayer_open else "—",
        song=True,
    )
    if language() == "en":
        row(t + timedelta(minutes=4), _("Вступительные слова (1 мин.)"))
    t += timedelta(minutes=5)  # песня и молитва + вступительные слова (1 мин)

    section(SECTION_TREASURES)
    for item in section_items(asses, SECTION_TREASURES):
        row(t, assignment_label(item["text"]), item["participant"])
        t += timedelta(minutes=item["duration"] + counsel_minutes(item))

    section(SECTION_MINISTRY)
    for item in section_items(asses, SECTION_MINISTRY):
        part = item["participant"] or ""
        if item["assistant"]:
            part += f" / {item['assistant']}"
        row(t, assignment_label(item["text"]), part)
        t += timedelta(minutes=item["duration"] + counsel_minutes(item))

    song2 = songs[1] if len(songs) > 1 else ""
    row(t, _("Песня {n}", n=song2), "", song=True)
    t += timedelta(minutes=5)

    section(SECTION_LIVING)
    cbs_reader = by_type(asses, "cbs_reader")
    is_co = event == "circuit_overseer"
    for item in sorted(
        [a for a in asses if a["section"] in ("living", "cbs") and a["type"] != "cbs_reader"],
        key=lambda x: str(x["position"]),
    ):
        if is_co and item["type"] == "cbs":
            row(t, _("Служебная речь РС (30 мин.)"), _("Районный старейшина"))
            t += timedelta(minutes=30)
            continue
        part = item["participant"] or ""
        if item["type"] == "cbs" and cbs_reader and cbs_reader["participant"]:
            part = _(
                "Ведущий: {conductor}\nЧтец: {reader}",
                conductor=part,
                reader=cbs_reader["participant"],
            )
        row(t, assignment_label(item["text"]), part)
        t += timedelta(minutes=item["duration"] + counsel_minutes(item))

    if language() == "en":
        row(t, _("Заключительные слова (3 мин.)"))
    t += timedelta(minutes=3)
    song3 = songs[2] if len(songs) > 2 else ""
    prayer_close = by_position(asses, "prayer_close")
    row(
        t,
        _("Песня {n} и молитва", n=song3),
        prayer_close["participant"] if prayer_close else "—",
        song=True,
    )

    for content in module_contents(week, settings):
        rows.append(
            {
                "kind": "module",
                "time": "",
                "text": content,
                "person": "",
                "section": None,
                "song": False,
            }
        )

    return {
        "special": None,
        "header": {
            "title": week_title(week),
            "reading": week.bible_reading or "",
            "cong_name": settings.get("cong_name", ""),
        },
        "rows": rows,
        "dense": total_items > 10,
    }
