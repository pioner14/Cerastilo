"""
Куда сохранять файлы на Android.

Системный диалог сохранения Qt на Android возвращает адрес content://, который
нельзя открыть обычным open(), поэтому экспорт и бэкап пишутся сразу в
«Загрузки/Cerastilo». Своими файлами в Download приложение на Android 11+ может
пользоваться без разрешений.
"""

import logging
import os

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = "/storage/emulated/0/Download/Cerastilo"


def is_android() -> bool:
    return "ANDROID_ARGUMENT" in os.environ


def export_dir() -> str:
    """Папка для экспорта; если в «Загрузки» писать нельзя — папка данных приложения."""
    fallback = os.path.join(os.environ.get("ANDROID_PRIVATE") or os.getcwd(), "exports")
    for path in (DOWNLOAD_DIR, fallback):
        try:
            os.makedirs(path, exist_ok=True)
            probe = os.path.join(path, ".write_test")
            with open(probe, "w"):
                pass
            os.remove(probe)
            return path
        except OSError as e:
            logger.warning(f"Папка экспорта недоступна: {path}: {e}")
    return fallback


def export_path(filename: str) -> str:
    return os.path.join(export_dir(), filename)
