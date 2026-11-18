"""
Backfill service for syncing assignment metadata from EPUB parser
to existing database records WITHOUT resetting assignments.

Use case: after changing parser logic (e.g. new _find_talk_marker),
existing weeks may have stale assignment_type / discussion_marker.
Full re-import resets participant_id / assistant_id / status.
Backfill updates only semantic fields and preserves assignments.
"""

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from core.epub_parser import WorkbookParser
from core.models import Assignment, Week

logger = logging.getLogger(__name__)


def backfill_epub(session, epub_path: str) -> Dict[str, int]:
    """Re-parse an EPUB and sync semantic fields into existing assignments.

    Updated fields: assignment_text, assignment_type, section,
                    section_position, duration, discussion_marker.
    Preserved fields: participant_id, assistant_id, status.

    Args:
        session: SQLAlchemy session
        epub_path: Path to EPUB file

    Returns:
        Dict with counts: {'weeks': N, 'assignments': N, 'updated': N}
    """
    weeks_data = WorkbookParser(epub_path).parse()
    weeks_objs = session.execute(select(Week)).scalars().all()
    existing_by_title = {_normalize(w.week_title): w for w in weeks_objs}

    updated = 0
    touched_weeks = 0

    for week in weeks_data:
        title = week.get("week_title", "").strip()
        if not title:
            continue

        week_obj = existing_by_title.get(_normalize(title))
        if not week_obj:
            continue

        current_by_num = {a.assignment_number: a for a in week_obj.assignments}

        for a in week.get("assignments", []):
            num = a.get("number")
            existing = current_by_num.get(num)
            if not existing:
                continue

            changed = False
            if existing.assignment_text != a.get("text", existing.assignment_text):
                existing.assignment_text = a.get("text", existing.assignment_text)
                changed = True
            if existing.assignment_type != a.get("type", existing.assignment_type):
                existing.assignment_type = a.get("type", existing.assignment_type)
                changed = True
            if existing.section != a.get("section", existing.section):
                existing.section = a.get("section", existing.section)
                changed = True
            if existing.section_position != a.get("section_position", existing.section_position):
                existing.section_position = a.get("section_position", existing.section_position)
                changed = True
            if existing.duration != a.get("duration", existing.duration):
                existing.duration = a.get("duration", existing.duration)
                changed = True
            # discussion_marker присутствует в словаре парсера ТОЛЬКО когда
            # он не None (см. epub_parser). Поэтому обновляем строго при
            # наличии ключа — иначе сотрём существующий маркер у задания,
            # для которого парсер не нашёл маркер (например не-ministry).
            if "discussion_marker" in a:
                marker = a.get("discussion_marker")
                if existing.discussion_marker != marker:
                    existing.discussion_marker = marker
                    changed = True

            if changed:
                updated += 1

        touched_weeks += 1

    session.commit()
    logger.info(
        "Backfill complete: weeks=%d, assignments_updated=%d (epub=%s)",
        touched_weeks,
        updated,
        epub_path,
    )
    return {"weeks": touched_weeks, "assignments": updated}


def _normalize(text: str) -> str:
    if not text:
        return ""
    return text.replace("—", "-").replace("–", "-").replace("−", "-").lower().strip()
