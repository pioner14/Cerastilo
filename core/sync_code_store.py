"""Хранение кода синхронизации рядом с базой."""

import os
import tempfile
from pathlib import Path

from core.sync_service import CODE_ALPHABET, CODE_LENGTH, normalize_sync_code


def load_sync_code(db_path: str) -> str:
    try:
        code = normalize_sync_code(Path(db_path).with_name("sync_code").read_text(encoding="ascii"))
    except (OSError, ValueError):
        return ""
    if len(code) == CODE_LENGTH and all(char in CODE_ALPHABET for char in code):
        return code
    return ""


def save_sync_code(db_path: str, code: str) -> bool:
    """Сохраняет код; False — записать не удалось."""
    try:
        path = Path(db_path).with_name("sync_code")
        # Временный файл создаётся с правами 0o600 и заменяет старый целиком.
        fd, temporary_path = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as tmp:
                tmp.write(normalize_sync_code(code).encode("ascii"))
            os.replace(temporary_path, path)
        finally:
            Path(temporary_path).unlink(missing_ok=True)
    except (OSError, ValueError):
        return False
    return True
