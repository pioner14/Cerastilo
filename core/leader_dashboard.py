"""
Пульт руководителя встречи (вкладка «Сегодня»): что не сделано и ближайшая встреча.

Руководитель встречи составляет всё расписание; председатель — только ведёт
встречу своей недели. Чистая логика без Qt и без базы: доски недель готовит
BaseApplicationFacade.get_leader_dashboard() (через get_month_board),
рисует ui/leader_dashboard_view.py.
"""

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from core.i18n import _, plural

# Сколько недель вперёд смотреть на пустые пункты и уведомления
HORIZON_WEEKS = 4
# Через сколько дней без ответа напоминать
WAITING_DAYS = 3
# За сколько дней до начала недели напоминать о неуведомлённых
NOTIFY_AHEAD_DAYS = 7


def _days_since(sent_at, today: date) -> Optional[int]:
    if isinstance(sent_at, str):
        try:
            sent_at = datetime.fromisoformat(sent_at)
        except ValueError:
            return None
    if isinstance(sent_at, datetime):
        sent_at = sent_at.date()
    if not isinstance(sent_at, date):
        return None
    return (today - sent_at).days


def _people(board: Dict):
    """(неделя, клетка, человек) по всем клеткам доски, без особых недель."""
    for row in board.get("cells", []):
        for col, cell in enumerate(row):
            column = board["columns"][col]
            if cell is None or column.get("special"):
                continue
            for person in cell["people"]:
                yield column, cell, person


def _week_label(columns: List[Dict]) -> str:
    dates = [
        c["start_date"].strftime("%d.%m")
        for c in sorted((c for c in columns if c.get("start_date")), key=lambda c: c["start_date"])
    ]
    return ", ".join(dates)


# формы слова по числу: русские три или английские две (core/i18n.py)
_plural = plural


def build_todos(
    board: Dict, today: date, next_month: Optional[Dict] = None, waiting_days: int = WAITING_DAYS
) -> List[Dict]:
    """Список дел по доске ближайших недель.

    Каждое дело: kind, text, week_ids (с чем работать), participant_ids
    (кому писать — для «not_notified» и «waiting»). Порядок — по важности;
    «not_notified» — последним из дел о людях и только для недель, что
    начинаются в ближайшие NOTIFY_AHEAD_DAYS дней.
    next_month — {"title", "week_ids", "assigned", "total"} или None,
    если в базе нет недель следующего месяца.
    """
    todos = []

    declined, declined_weeks = [], []
    not_notified, nn_weeks = [], []
    waiting, waiting_weeks = [], []
    for column, _cell, person in _people(board):
        pid = person.get("id")
        if not pid:
            continue
        notice = person.get("notice")
        if notice == "declined":
            declined.append(person["name"])
            if column not in declined_weeks:
                declined_weeks.append(column)
        elif notice in (None, "error"):
            # О заданиях сообщают листками на встрече, письмо — накануне
            # недели. Поэтому «не уведомлены» — только про ближайшие дни.
            start = column.get("start_date")
            if start is None or (start - today).days > NOTIFY_AHEAD_DAYS:
                continue
            if pid not in not_notified:
                not_notified.append(pid)
            if column not in nn_weeks:
                nn_weeks.append(column)
        elif notice == "waiting":
            days = _days_since(person.get("sent_at"), today)
            if days is not None and days >= waiting_days:
                if pid not in waiting:
                    waiting.append(pid)
                if column not in waiting_weeks:
                    waiting_weeks.append(column)

    if declined:
        n = len(declined)
        todos.append(
            {
                "kind": "declined",
                "text": _(
                    "{n} {v} без замены: {v2} ({v3})",
                    n=n,
                    v=_plural(n, "отказ", "отказа", "отказов"),
                    v2=", ".join(declined),
                    v3=_week_label(declined_weeks),
                ),
                "week_ids": [c["week_id"] for c in declined_weeks],
                "participant_ids": [],
            }
        )

    empty_weeks, empty = [], 0
    for row in board.get("cells", []):
        for col, cell in enumerate(row):
            column = board["columns"][col]
            if cell and "empty" in cell["flags"] and not column.get("special"):
                empty += 1
                if column not in empty_weeks:
                    empty_weeks.append(column)
    if empty:
        todos.append(
            {
                "kind": "empty",
                "text": _(
                    "{empty} {v} на ближайших неделях ({v2})",
                    empty=empty,
                    v=_plural(empty, "пустой пункт", "пустых пункта", "пустых пунктов"),
                    v2=_week_label(empty_weeks),
                ),
                "week_ids": [c["week_id"] for c in empty_weeks],
                "participant_ids": [],
            }
        )

    if waiting:
        n = len(waiting)
        todos.append(
            {
                "kind": "waiting",
                "text": _(
                    "{n} {v} не {v2} дольше {waiting_days} дн. ({v3})",
                    n=n,
                    v=_plural(n, "человек", "человека", "человек"),
                    v2=_plural(n, "ответил", "ответили", "ответили"),
                    waiting_days=waiting_days,
                    v3=_week_label(waiting_weeks),
                ),
                "week_ids": [c["week_id"] for c in waiting_weeks],
                "participant_ids": waiting,
            }
        )

    if not_notified:
        n = len(not_notified)
        todos.append(
            {
                "kind": "not_notified",
                "text": _(
                    "{n} {v} ({weeks})",
                    n=n,
                    weeks=_week_label(nn_weeks),
                    v=_plural(
                        n, "человек не уведомлён", "человека не уведомлены", "человек не уведомлены"
                    ),
                ),
                "week_ids": [c["week_id"] for c in nn_weeks],
                "participant_ids": not_notified,
            }
        )

    if next_month is not None:
        title = next_month["title"]
        week_ids = next_month.get("week_ids") or []
        if not week_ids or not next_month.get("total"):
            todos.append(
                {
                    "kind": "no_program",
                    "text": _("{title}: программа не импортирована", title=title),
                    "week_ids": week_ids,
                    "participant_ids": [],
                }
            )
        elif not next_month.get("assigned"):
            todos.append(
                {
                    "kind": "unassigned",
                    "text": _("{title}: не распределён", title=title),
                    "week_ids": week_ids,
                    "participant_ids": [],
                }
            )
    return todos


def next_meeting(board: Dict, today: date) -> Optional[Dict]:
    """Ближайшая неделя со встречей (текущая или следующая): колонка и её пункты.

    Возвращает {"column", "items": [{"label", "section", "cell"}]} или None.
    """
    for col, column in enumerate(board.get("columns", [])):
        start = column.get("start_date")
        if column.get("special") or start is None or start + timedelta(days=6) < today:
            continue
        items = [
            {"label": row["label"], "section": row["section"], "cell": board["cells"][i][col]}
            for i, row in enumerate(board["rows"])
            if board["cells"][i][col] is not None
        ]
        if items:
            return {"column": column, "items": items}
    return None


# «Первые шаги» для пустой базы: (ключ, текст, куда вести)
FIRST_STEPS = (
    ("congregation", _("Впишите название собрания, день и время встречи"), "settings"),
    (
        "participants",
        _("Добавьте возвещателей (или импортируйте из Excel в «Настройках»)"),
        "participants",
    ),
    (
        "qualifications",
        _("Отметьте возвещателям квалификации — без них «Авто» никого не назначит"),
        "participants",
    ),
    (
        "program",
        _(
            "Загрузите программу встреч: файл EPUB рабочей тетради в «Настройках» → «📚 Рабочие тетради»"
        ),
        "workbooks",
    ),
    ("assigned", _("Распределите первую неделю: «🪄 Авто» в «Расписании»"), "schedule"),
)


def first_steps(counts: Dict) -> List[Dict]:
    """Чек-лист первого запуска. counts: has_congregation, participants,
    with_qualifications, weeks, assigned. Пустой список — всё сделано,
    чек-лист больше не показывается."""
    done = {
        "congregation": bool(counts.get("has_congregation")),
        "participants": counts.get("participants", 0) > 0,
        "qualifications": counts.get("with_qualifications", 0) > 0,
        "program": counts.get("weeks", 0) > 0,
        "assigned": counts.get("assigned", 0) > 0,
    }
    if all(done.values()):
        return []
    return [
        {"key": key, "text": text, "target": target, "done": done[key]}
        for key, text, target in FIRST_STEPS
    ]
