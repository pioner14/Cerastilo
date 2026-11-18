# core/export/fetcher.py
"""
Загрузчик данных для экспорта расписания.

Отвечает за загрузку недель, назначений и настроек из БД.

См. spec://export/docx#fetcher
"""

import logging
import re
from typing import List, Dict, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Week, Assignment, Participant, Setting
from core.week_layout import assignment_label

logger = logging.getLogger(__name__)


class DataFetcher:
    """
    Загружает данные для экспорта расписания.

    Ответственности:
    - Загрузка недель по ID
    - Загрузка назначений для каждой недели
    - Загрузка настроек
    - Парсинг длительности из текста

    См. spec://export/docx#fetcher
    """

    def fetch_weeks(self, session: Session, week_ids: List[int]) -> List[Dict[str, Any]]:
        """
        Загрузить данные недель с назначениями.

        Args:
            session: Сессия SQLAlchemy
            week_ids: Список ID недель

        Returns:
            Список словарей с ключами:
                - 'week': объект Week
                - 'assignments': список назначений
                - 'settings': словарь настроек
        """
        # Загружаем недели
        query = select(Week).where(Week.id.in_(week_ids)).order_by(Week.id)
        weeks = session.execute(query).scalars().all()

        # Загружаем настройки
        settings_rows = session.execute(select(Setting)).scalars().all()
        settings = {s.key: s.value for s in settings_rows}

        # Алиас для помощника
        assistant_table = Participant.__table__.alias("assistant")

        result = []
        for w in weeks:
            # Загружаем назначения с участниками
            stmt = (
                select(Assignment, Participant.name, assistant_table.c.name)
                .outerjoin(Participant, Assignment.participant_id == Participant.id)
                .outerjoin(assistant_table, Assignment.assistant_id == assistant_table.c.id)
                .where(Assignment.week_id == w.id)
            )
            rows = session.execute(stmt).all()

            assignments = []
            for a, p_name, ast_name in rows:
                text = a.assignment_text or ""
                number = a.assignment_number
                label = assignment_label(text)

                # Если номер есть, добавляем его к тексту
                if number and not text.startswith(f"{number}."):
                    display_text = f"{number}. {label}"
                else:
                    display_text = label

                assignments.append(
                    {
                        "id": a.id,
                        "type": a.assignment_type,
                        "section": a.section,
                        "position": a.section_position,
                        "text": display_text,
                        "raw_text": text,
                        "discussion_marker": a.discussion_marker,
                        "participant": p_name,
                        "assistant": ast_name,
                        "duration": a.duration
                        or (10 if a.assignment_type == "cbs" or "изучение" in text.lower() else 5),
                    }
                )

            # Длительность из текста старых записей имеет приоритет.
            for a in assignments:
                match = re.search(r"\((\d+)\s*(?:мин|min)\b", a["raw_text"], re.IGNORECASE)
                if match:
                    a["duration"] = int(match.group(1))

            result.append({"week": w, "assignments": assignments, "settings": settings})

        return result

    def fetch_settings(self, session: Session) -> Dict[str, str]:
        """
        Загрузить все настройки.

        Args:
            session: Сессия SQLAlchemy

        Returns:
            Словарь настроек {key: value}
        """
        settings_rows = session.execute(select(Setting)).scalars().all()
        return {s.key: s.value for s in settings_rows}
