"""Проверка релизов и настройки обновлений на устройстве."""

import json
import logging
import os
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit

from core.i18n import _settings_dir
from core.version import APP_VERSION

logger = logging.getLogger(__name__)

GITHUB_LATEST_URL = "https://api.github.com/repos/pioner14/Cerastilo/releases/latest"


def parse_version(s: str) -> tuple[int, int, int] | None:
    if not isinstance(s, str):
        return None
    match = re.fullmatch(r"v?([0-9]+)\.([0-9]+)\.([0-9]+)", s.strip())
    if match is None:
        return None
    try:
        major, minor, patch = map(int, match.groups())
        return major, minor, patch
    except ValueError:
        return None


def is_newer(remote: str, local: str) -> bool:
    remote_version = parse_version(remote)
    local_version = parse_version(local)
    return (
        remote_version is not None and local_version is not None and remote_version > local_version
    )


def fetch_latest(timeout=8) -> dict | None:
    try:
        request = urllib.request.Request(
            GITHUB_LATEST_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"Cerastilo/{APP_VERSION}",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            release = json.load(response)
        version = parse_version(release["tag_name"])
        url = release["html_url"]
        if version is None or not isinstance(url, str):
            raise ValueError("Некорректные данные релиза")
        parsed_url = urlsplit(url)
        if parsed_url.scheme not in {"https", "http"} or not parsed_url.hostname:
            raise ValueError("Некорректная ссылка на релиз")
        return {"version": ".".join(map(str, version)), "url": url}
    except Exception:
        logger.debug("Не удалось получить последний релиз", exc_info=True)
        return None


def check_for_update() -> dict | None:
    release = fetch_latest()
    if release is not None and is_newer(release["version"], APP_VERSION):
        return release
    return None


def _settings_path() -> Path:
    return Path(_settings_dir()) / "update_check.json"


def _load_settings() -> dict:
    try:
        settings = json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return settings if isinstance(settings, dict) else {}


def _save_setting(key: str, value: bool | str) -> None:
    path = _settings_path()
    settings = _load_settings()
    settings[key] = value
    temp_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as temp:
            temp_path = Path(temp.name)
            json.dump(settings, temp)
        temp_path.replace(path)
    except OSError:
        logger.debug("Не удалось сохранить настройки обновлений", exc_info=True)
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                logger.debug("Не удалось удалить временный файл настроек", exc_info=True)


def auto_check_default() -> bool:
    return os.environ.get("CERASTILO_UPDATE_CHECK_DEFAULT", "").strip().lower() not in {
        "off",
        "0",
        "false",
    }


def auto_check_enabled() -> bool:
    auto = _load_settings().get("auto")
    return auto if isinstance(auto, bool) else auto_check_default()


def set_auto_check(enabled: bool) -> None:
    _save_setting("auto", enabled)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def should_auto_check(now: datetime | None = None) -> bool:
    settings = _load_settings()
    auto = settings.get("auto")
    if not (auto if isinstance(auto, bool) else auto_check_default()):
        return False
    try:
        last_check = _utc(datetime.fromisoformat(settings.get("last_check")))
    except (TypeError, ValueError, OverflowError):
        return True
    elapsed = _utc(now or datetime.now(timezone.utc)) - last_check
    return elapsed < timedelta(0) or elapsed >= timedelta(hours=24)


def mark_checked(now: datetime | None = None) -> None:
    _save_setting("last_check", _utc(now or datetime.now(timezone.utc)).isoformat())
