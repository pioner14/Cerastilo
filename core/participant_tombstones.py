"""Список удалённых участников — чтобы синхронизация не возвращала их.

Участник удаляется из базы насовсем, и без следа другая сторона при
синхронизации прислала бы его снова. Поэтому при удалении имя и время
(UTC) записываются в настройку ``deleted_participants`` (JSON
``{имя: ISO-время}``). Синхронизация объединяет эти списки и удаляет или
не добавляет участника, если карточка не правилась после удаления.
Новый участник с тем же именем, созданный позже, не затрагивается.
"""

import json
import logging
from datetime import datetime

from core.models import Setting

logger = logging.getLogger(__name__)

SETTING_KEY = "deleted_participants"


def load(session) -> dict:
    """{имя: datetime удаления} из настройки базы."""
    row = session.query(Setting).filter(Setting.key == SETTING_KEY).first()
    if not row or not row.value:
        return {}
    try:
        raw = json.loads(row.value)
        return {name: datetime.fromisoformat(ts) for name, ts in raw.items()}
    except (ValueError, TypeError, AttributeError) as e:
        logger.warning("Повреждён список удалённых участников: %s", e)
        return {}


def save(session, tombstones: dict) -> None:
    value = json.dumps(
        {name: ts.isoformat() for name, ts in sorted(tombstones.items())},
        ensure_ascii=False,
    )
    row = session.query(Setting).filter(Setting.key == SETTING_KEY).first()
    if row:
        row.value = value
    else:
        session.add(Setting(key=SETTING_KEY, value=value))


def record(session, name: str, when: datetime | None = None) -> None:
    """Запомнить удаление участника ``name``."""
    tombstones = load(session)
    tombstones[name] = when or datetime.utcnow()
    save(session, tombstones)


def union(a: dict, b: dict) -> dict:
    """Объединить два списка, для каждого имени — более позднее удаление."""
    merged = dict(a)
    for name, ts in b.items():
        if name not in merged or ts > merged[name]:
            merged[name] = ts
    return merged


def deleted_after_edit(participant, tombstones: dict) -> bool:
    """Удалён ли участник позже последней правки его карточки."""
    deleted_at = tombstones.get(participant.name)
    if deleted_at is None:
        return False
    stamp = participant.updated_at or participant.created_at
    return stamp is None or stamp <= deleted_at
