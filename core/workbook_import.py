"""
Импорт данных из EPUB парсера в базу данных.

Ключевые принципы:
1. Фиксированные роли (chairman, prayers) создаются ВСЕГДА
2. Переменные задания берутся из EPUB с section и section_position
3. Дата start_date формируется из start_day + month_num + year (из парсера)
4. Синхронизация: лишние задания отключаются, новые добавляются
"""

import logging
import os
import re
from datetime import date

from sqlalchemy import select

from core.models import Assignment, AssignmentStatus, Week

logger = logging.getLogger(__name__)

# Фиксированные роли, которые ВСЕГДА создаются для каждой недели
FIXED_ROLES = [
    {
        "assignment_number": "chairman",
        "assignment_text": "Председатель",
        "assignment_type": "role",
        "section": "fixed",
        "section_position": "chairman",
        "duration": 0,
    },
    {
        "assignment_number": "prayer_open",
        "assignment_text": "Молитва (открытие)",
        "assignment_type": "role",
        "section": "fixed",
        "section_position": "prayer_open",
        "duration": 0,
    },
    {
        "assignment_number": "prayer_close",
        "assignment_text": "Молитва (закрытие)",
        "assignment_type": "role",
        "section": "fixed",
        "section_position": "prayer_close",
        "duration": 0,
    },
]


def save_weeks_to_db(session, weeks_data, epub_path=None):
    """Сохраняет структуру недель из EPUB в БД через SQLAlchemy.

    Args:
        session: SQLAlchemy session
        weeks_data: список недель из WorkbookParser.parse()
        epub_path: путь к EPUB файлу (для metadata и определения года)
    """
    # Определяем год из имени файла (напр. mwb_U_202603.epub → 2026)
    year = _extract_year(epub_path)

    saved_weeks = 0
    filled_weeks = 0
    saved_assignments = 0

    # Предзагружаем существующие недели
    weeks_objs = session.execute(select(Week)).scalars().all()
    existing_weeks = {_normalize(w.week_title): w for w in weeks_objs}
    # При смене языка заголовок меняется, а дата начала остаётся прежней.
    weeks_by_date = {w.start_date: w for w in weeks_objs if w.start_date}

    for week in weeks_data:
        title = week.get("week_title", "").strip()
        if not title:
            continue

        bible_reading = week.get("bible_reading", "")
        month_num = week.get("month_num", 1)
        start_month_num = week.get("start_month_num", month_num)
        start_day = week.get("start_day", 1)

        # Корректируем год для недель, переходящих с декабря предыдущего года на январь текущего
        start_year = year
        if week.get("start_year"):
            # Год указан прямо в заголовке (неделя на стыке лет)
            start_year = week["start_year"]
        elif start_month_num == 12 and month_num == 1:
            start_year = year - 1

        # Создаём date объект вместо строки
        try:
            start_date = date(start_year, start_month_num, start_day)
        except ValueError as e:
            # Некорректная дата (например, 30 февраля)
            logger.warning(
                f"Некорректная дата {start_year}-{start_month_num}-{start_day} для недели '{title}': {e}"
            )
            start_date = None

        # --- Найти или создать Week ---
        norm_title = _normalize(title)
        week_obj = existing_weeks.get(norm_title)
        epub_assignments = week.get("assignments", [])
        match_by_position = False
        if week_obj is None and start_date is not None:
            week_obj = weeks_by_date.get(start_date)
            # Пустой импорт не заменяет неделю с назначениями из ручной истории.
            if (
                week_obj
                and week_obj.assignments
                and not epub_assignments
                and not (week_obj.workbook_source or "").lower().endswith(".epub")
            ):
                week_obj = None
            if week_obj is not None:
                match_by_position = bool(week_obj.assignments)
                if not match_by_position:
                    filled_weeks += 1
                existing_weeks.pop(_normalize(week_obj.week_title), None)
                week_obj.week_title = title
                existing_weeks[norm_title] = week_obj

        if week_obj:
            # Обновляем метаданные существующей недели
            week_obj.bible_reading = bible_reading
            old_date = week_obj.start_date
            if old_date != start_date and weeks_by_date.get(old_date) is week_obj:
                del weeks_by_date[old_date]
            week_obj.start_date = start_date
            week_obj.month = str(month_num)
            week_obj.year = year
            week_obj.workbook_source = epub_path
            # Сохраняем номера песен
            songs = week.get("songs", [])
            if songs:
                week_obj.songs = ",".join(str(s) for s in songs)
        else:
            week_obj = Week(
                week_title=title,
                start_date=start_date,
                bible_reading=bible_reading,
                month=str(month_num),
                year=year,
                workbook_source=epub_path,
                songs=",".join(str(s) for s in week.get("songs", [])),
            )
            session.add(week_obj)
            session.flush()
            existing_weeks[norm_title] = week_obj
            saved_weeks += 1

        # --- Синхронизируем задания ---
        if start_date is not None:
            weeks_by_date[start_date] = week_obj
        new_count = _sync_assignments(
            session, week_obj, epub_assignments, match_by_position=match_by_position
        )
        saved_assignments += new_count

    session.commit()
    logger.info(
        f"💾 Импорт EPUB завершён. Новых недель: {saved_weeks}, заданий: {saved_assignments}"
    )
    return {"weeks": saved_weeks, "filled_weeks": filled_weeks, "assignments": saved_assignments}


def _sync_assignments(session, week_obj, epub_assignments, *, match_by_position=False):
    """Синхронизирует задания недели с данными из EPUB.

    1. Фиксированные роли (chairman, prayers) создаются ВСЕГДА
    2. Задания из EPUB сохраняются с section/section_position
    3. Задания, отсутствующие в EPUB, помечаются disabled
    """
    # Собираем целевой набор заданий: фиксированные + из EPUB
    target_assignments = []

    # Добавляем фиксированные роли
    for role in FIXED_ROLES:
        target_assignments.append(role.copy())

    # Добавляем задания из EPUB (с section и section_position)
    for a in epub_assignments:
        entry = {
            "assignment_number": a["number"],
            "assignment_text": a["text"],
            "assignment_type": a["type"],
            "section": a.get("section", ""),
            "section_position": a.get("section_position", ""),
            "duration": a.get("duration", 5),
        }
        # Маркер «(N мин.) Обсуждение» — только для ministry/student (один брат, без напарника)
        if a.get("discussion_marker"):
            entry["discussion_marker"] = a["discussion_marker"]
        target_assignments.append(entry)

    target_by_num = {t["assignment_number"]: t for t in target_assignments}

    # Активное задание имеет приоритет перед отключённым с тем же номером.
    current = sorted(
        week_obj.assignments, key=lambda a: a.status != AssignmentStatus.DISABLED.value
    )
    current_by_num = {a.assignment_number: a for a in current}
    current_by_position = {
        (a.section, a.section_position): a for a in current if a.section and a.section_position
    }

    matched = set()
    new_count = 0
    for num, data in target_by_num.items():
        existing = current_by_num.get(num)
        if match_by_position and data["section"] and data["section_position"]:
            # Если число пунктов в разделе изменилось, сквозной номер может сдвинуться.
            existing = current_by_position.get((data["section"], data["section_position"]))
        if existing in matched:
            existing = None
        if existing:
            matched.add(existing)
            existing.assignment_number = num
            # Обновляем текст, тип, длительность, секцию
            existing.assignment_text = data["assignment_text"]
            existing.assignment_type = data["assignment_type"]
            existing.duration = data["duration"]
            existing.section = data["section"]
            existing.section_position = data["section_position"]
            existing.discussion_marker = data.get("discussion_marker")
            if existing.status == AssignmentStatus.DISABLED.value:
                existing.status = AssignmentStatus.UNASSIGNED.value
        else:
            new_a = Assignment(
                week=week_obj,
                assignment_number=num,
                assignment_text=data["assignment_text"],
                assignment_type=data["assignment_type"],
                section=data["section"],
                section_position=data["section_position"],
                duration=data["duration"],
                status=AssignmentStatus.UNASSIGNED.value,
            )
            if data.get("discussion_marker"):
                new_a.discussion_marker = data["discussion_marker"]
            session.add(new_a)
            new_count += 1

    for assignment in current:
        if assignment not in matched and assignment.status != AssignmentStatus.DISABLED.value:
            assignment.status = AssignmentStatus.DISABLED.value

    return new_count


def _extract_year(epub_path):
    """Извлекает год из имени файла EPUB (напр. mwb_U_202603.epub → 2026)."""
    if epub_path:
        filename = os.path.basename(epub_path)
        match = re.search(r"20(\d{2})", filename)
        if match:
            return int(match.group(0))
    return 2026  # fallback


def _normalize(text):
    """Нормализует текст для сравнения заголовков недель."""
    if not text:
        return ""
    t = text.replace("—", "-").replace("–", "-").replace("−", "-")
    return t.lower().strip()
