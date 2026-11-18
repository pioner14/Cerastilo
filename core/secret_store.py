"""
Секреты приложения (пароль SMTP) — отдельно от базы.

Таблица settings целиком попадает в бэкапы и в синхронизацию с планшетом,
поэтому пароль там хранить нельзя. Секреты лежат в JSON-файле рядом с базой
(.<имя базы>.secrets.json, права 600): в бэкап и синхронизацию уходит только
сам файл базы.
"""

import json
import logging
import os
from typing import Dict, Optional

logger = logging.getLogger(__name__)

SECRET_KEYS = frozenset({"smtp_password"})


class SecretStore:
    def __init__(self, db_path: str):
        if db_path == ":memory:":
            self.path: Optional[str] = None
        else:
            folder, name = os.path.split(os.path.abspath(db_path))
            self.path = os.path.join(folder, f".{name}.secrets.json")
        self._memory: Dict[str, str] = {}

    def _read(self) -> Dict[str, str]:
        if self.path is None:
            return self._memory
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            logger.error(f"Не удалось прочитать файл секретов {self.path}: {e}")
            return {}

    def has(self, key: str) -> bool:
        return key in self._read()

    def get(self, key: str, default=None):
        return self._read().get(key, default)

    def set(self, key: str, value: str) -> None:
        data = dict(self._read())
        data[key] = value
        if self.path is None:
            self._memory = data
            return
        tmp = self.path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, self.path)
