"""
Снимок базы перед массовой правкой (авто-распределение месяца) и откат к нему.

Снимок — полная копия SQLite через backup API: безопасно при открытом
приложении. Лежит в папке snapshots/ рядом с базой, хранятся последние
KEEP_SNAPSHOTS. Откат пишет снимок обратно в ту же базу (тоже backup API),
поэтому приложение перезапускать не нужно — достаточно закрыть соединения
SQLAlchemy (engine.dispose), они откроются заново при следующем запросе.
"""

import logging
import os
import sqlite3
from datetime import datetime
from typing import List

logger = logging.getLogger(__name__)

KEEP_SNAPSHOTS = 5


def snapshot_dir(db_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), "snapshots")


def _copy(src_path: str, dst_path: str) -> None:
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def list_snapshots(db_path: str) -> List[str]:
    """Снимки этой базы, от старых к новым."""
    folder = snapshot_dir(db_path)
    if not os.path.isdir(folder):
        return []
    prefix = os.path.basename(db_path) + "."
    return sorted(
        os.path.join(folder, name)
        for name in os.listdir(folder)
        if name.startswith(prefix) and name.endswith(".snapshot")
    )


def take_snapshot(db_path: str, label: str) -> str:
    """Сохранить снимок базы; label — к чему он (попадает в имя файла).
    Возвращает путь снимка. Старые снимки сверх KEEP_SNAPSHOTS удаляются."""
    folder = snapshot_dir(db_path)
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = os.path.join(folder, f"{os.path.basename(db_path)}.{stamp}.{label}.snapshot")
    _copy(db_path, path)
    logger.info("Снимок базы перед «%s»: %s", label, path)
    for old in list_snapshots(db_path)[:-KEEP_SNAPSHOTS]:
        try:
            os.remove(old)
        except OSError as e:
            logger.warning("Не удалось удалить старый снимок %s: %s", old, e)
    return path


def restore_snapshot(db, snapshot_path: str) -> None:
    """Вернуть базу DatabaseManager `db` к снимку. Все изменения после снимка теряются."""
    if not os.path.exists(snapshot_path):
        raise FileNotFoundError(snapshot_path)
    db.close()  # иначе пул SQLAlchemy держит старые соединения
    _copy(snapshot_path, db.db_path)
    logger.info("База возвращена к снимку %s", snapshot_path)
