import ssl
import io
import json
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import URLError

import pytest

from core import update_check
from core.version import APP_VERSION


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "x.db"))
    monkeypatch.delenv("CERASTILO_UPDATE_CHECK_DEFAULT", raising=False)
    return tmp_path / "update_check.json"


def test_version_matches_pyproject():
    path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with path.open("rb") as file:
        assert APP_VERSION == tomllib.load(file)["project"]["version"]


def test_parse_and_compare_versions():
    assert update_check.parse_version("v0.1.10") == (0, 1, 10)
    assert update_check.parse_version("0.1.9") == (0, 1, 9)
    assert update_check.parse_version("garbage") is None
    assert update_check.is_newer("v0.1.10", "0.1.9")
    assert not update_check.is_newer("0.1.9", "0.1.10")
    assert not update_check.is_newer("v0.1.10", "0.1.10")
    assert not update_check.is_newer("garbage", "0.1.9")
    assert not update_check.is_newer("0.1.9", "garbage")


def test_fetch_latest(monkeypatch):
    url = "https://github.com/pioner14/Cerastilo/releases/tag/v0.1.1"

    def urlopen(request, timeout, context):
        assert isinstance(context, ssl.SSLContext)  # свой контекст: на Android — CA системы
        assert request.full_url == update_check.GITHUB_LATEST_URL
        assert request.get_header("Accept") == "application/vnd.github+json"
        assert request.get_header("User-agent") == f"Cerastilo/{APP_VERSION}"
        assert timeout == 8
        return io.BytesIO(json.dumps({"tag_name": "v0.1.1", "html_url": url}).encode())

    monkeypatch.setattr(update_check.urllib.request, "urlopen", urlopen)
    assert update_check.fetch_latest() == {"version": "0.1.1", "url": url}


def test_fetch_latest_network_error(monkeypatch):
    def urlopen(*args, **kwargs):
        raise URLError("offline")

    monkeypatch.setattr(update_check.urllib.request, "urlopen", urlopen)
    assert update_check.fetch_latest() is None


@pytest.mark.parametrize("body", [b"not json", b'{"html_url":"https://github.com"}'])
def test_fetch_latest_invalid_response(monkeypatch, body):
    monkeypatch.setattr(
        update_check.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(body)
    )
    assert update_check.fetch_latest() is None


@pytest.mark.parametrize("version, is_update", [("99.0.0", True), (APP_VERSION, False)])
def test_check_for_update(monkeypatch, version, is_update):
    release = {"version": version, "url": "https://github.com/pioner14/Cerastilo/releases"}
    monkeypatch.setattr(update_check, "fetch_latest", lambda: release)
    assert update_check.check_for_update() == (release if is_update else None)


@pytest.mark.parametrize("value", ["off", "0", "false"])
def test_auto_check_default(settings_file, monkeypatch, value):
    assert update_check.auto_check_enabled()
    monkeypatch.setenv("CERASTILO_UPDATE_CHECK_DEFAULT", value)
    assert not update_check.auto_check_default()
    assert not update_check.auto_check_enabled()
    update_check.set_auto_check(True)
    assert update_check.auto_check_enabled()


@pytest.mark.parametrize("content", ["{", "[]", '{"auto": "false", "last_check": "wrong"}'])
def test_damaged_settings(settings_file, content):
    settings_file.write_text(content, encoding="utf-8")
    assert update_check.auto_check_enabled()
    assert update_check.should_auto_check()
    update_check.set_auto_check(False)
    assert not update_check.auto_check_enabled()


def test_should_auto_check(settings_file):
    now = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)
    assert update_check.should_auto_check(now)
    update_check.mark_checked(now)
    assert not update_check.should_auto_check(now + timedelta(hours=23, minutes=59))
    assert update_check.should_auto_check(now + timedelta(hours=24))
    assert update_check.should_auto_check(now - timedelta(seconds=1))

    update_check.set_auto_check(False)
    assert not update_check.should_auto_check(now + timedelta(days=2))
    assert json.loads(settings_file.read_text(encoding="utf-8")) == {
        "auto": False,
        "last_check": now.isoformat(),
    }
    update_check.mark_checked(now)
    assert not update_check.auto_check_enabled()
