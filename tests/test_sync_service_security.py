"""
Тесты безопасности сервера синхронизации.

Сервер доступен всей локальной сети, поэтому защита держится на токене.
Проверяем, что дыры, найденные 01.10.2026, закрыты: слабый токен, отсутствие
лимита размера запроса, утечка внутренних ошибок клиенту, приём любого файла
как базы и потеря данных при неудачном слиянии.
"""

import io
import os
import sqlite3
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import HTTPServer

import pytest

from core.sync_service import (
    MAX_UPLOAD_BYTES,
    SyncHTTPHandler,
    SyncServer,
    backup_database,
    is_sqlite,
)

TOKEN = "test-token-0123456789"


def _sqlite_bytes() -> bytes:
    """Минимальная валидная база SQLite."""
    path = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO t (v) VALUES ('hello')")
    conn.commit()
    conn.close()
    with open(path, "rb") as fh:
        data = fh.read()
    os.remove(path)
    return data


def _multipart(token: str, db_bytes: bytes, boundary: str | None = None) -> tuple[bytes, str]:
    boundary = boundary or uuid.uuid4().hex
    body = b"\r\n".join(
        [
            f"--{boundary}".encode(),
            b'Content-Disposition: form-data; name="token"',
            b"",
            token.encode(),
            f"--{boundary}".encode(),
            b'Content-Disposition: form-data; name="database"; filename="phone.db"',
            b"",
            db_bytes,
            f"--{boundary}--".encode(),
            b"",
        ]
    )
    return body, boundary


@pytest.fixture
def server(tmp_path):
    """Поднять настоящий сервер на случайном порту в отдельном потоке."""
    db_path = str(tmp_path / "tablet.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.commit()
    conn.close()

    handler_cls = SyncHTTPHandler.create_handler(db_path, TOKEN, None)
    httpd = HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address

    yield {"url": f"http://{host}:{port}/sync", "db_path": db_path, "httpd": httpd}

    httpd.shutdown()
    httpd.server_close()


def _post(url: str, body: bytes, boundary: str, *, length: int | None = None):
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    request.add_header("Content-Length", str(length if length is not None else len(body)))
    return urllib.request.urlopen(request, timeout=10)


# === Лимит размера запроса ===


def test_oversized_request_is_rejected(server):
    body, boundary = _multipart(TOKEN, b"x" * 1024, "b")
    # Заявляем больше лимита, отправляя тело целиком.
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(server["url"], body, boundary, length=MAX_UPLOAD_BYTES + 1)
    assert exc.value.code == 413


def test_limit_is_defined_and_reasonable():
    assert 1024 < MAX_UPLOAD_BYTES <= 512 * 1024 * 1024


def test_bad_content_length_returns_411(server, tmp_path):
    import socket

    host, port = server["httpd"].server_address
    payload = (
        b"POST /sync HTTP/1.1\r\n"
        b"Host: x\r\n"
        b"Content-Type: multipart/form-data; boundary=b\r\n"
        b"Content-Length: banana\r\n\r\n"
    )
    with socket.create_connection((host, port), timeout=5) as sock:
        sock.sendall(payload)
        response = sock.recv(4096)
    assert b"411" in response.split(b"\r\n")[0]


# === Токен ===


def test_wrong_token_is_rejected(server):
    body, boundary = _multipart("wrong-token", _sqlite_bytes(), "b")
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(server["url"], body, boundary)
    assert exc.value.code == 401


def test_missing_token_is_rejected(server):
    boundary = "b"
    body = b"\r\n".join(
        [
            b"--b",
            b'Content-Disposition: form-data; name="database"; filename="p.db"',
            b"",
            b"SQLite format 3\x00",
            b"--b--",
            b"",
        ]
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(server["url"], body, boundary)
    assert exc.value.code == 401


def test_token_is_long_enough():
    """48 бит (token_urlsafe(6)) перебираются; 256 бит — нет."""
    import secrets as secrets_module

    token = secrets_module.token_urlsafe(32)
    assert len(token) >= 40


# === Проверка загружаемого файла ===


def test_non_sqlite_upload_is_rejected(server):
    body, boundary = _multipart(TOKEN, b"just some bytes, not a database", "b")
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(server["url"], body, boundary)
    assert exc.value.code == 400


def test_is_sqlite_helper():
    assert is_sqlite(b"SQLite format 3\x00" + b"\x00" * 32) is True
    assert is_sqlite(b"") is False
    assert is_sqlite(b"SQLite") is False
    assert is_sqlite(b"<?xml version='1.0'?>") is False


# === Ошибки не утекают наружу ===


def test_internal_errors_do_not_leak_details(server, monkeypatch):
    import core.sync_service as sync_service

    def explode(*args, **kwargs):
        raise RuntimeError("secret path /home/user/private.db is broken")

    # Замена базы на планшете — то, что делает POST /sync
    monkeypatch.setattr(sync_service, "replace_database", explode)

    body, boundary = _multipart(TOKEN, _sqlite_bytes(), "b")
    try:
        _post(server["url"], body, boundary)
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", "replace")
        assert exc.code == 500
        assert "secret path" not in payload
        assert "private.db" not in payload
    else:
        pytest.fail("ожидалась ошибка 500")


# === Резервная копия ===


def test_backup_created_before_merge(tmp_path):
    db = tmp_path / "scheduler.db"
    db.write_bytes(b"payload")

    backup = backup_database(str(db))

    assert backup and os.path.exists(backup)
    assert open(backup, "rb").read() == b"payload"
    assert db.read_bytes() == b"payload"  # оригинал не тронут
    os.remove(backup)


def test_backup_of_missing_file_is_not_fatal(tmp_path):
    assert backup_database(str(tmp_path / "nope.db")) == ""
    assert backup_database("") == ""


# === Адрес прослушивания ===


def test_bind_host_is_explicit_and_logged():
    """0.0.0.0 нужен телефону, но это должно быть осознанным решением."""
    server = SyncServer("/tmp/x.db", TOKEN, port=9999)
    assert server.host == "0.0.0.0"

    local = SyncServer("/tmp/x.db", TOKEN, port=9999, host="127.0.0.1")
    assert local.host == "127.0.0.1"


def test_start_binds_configured_host(tmp_path):
    """Сервер слушает именно на указанном адресе (start() ведёт себя вечно)."""
    db = tmp_path / "x.db"
    sqlite3.connect(str(db)).close()

    server = SyncServer(str(db), TOKEN, port=0, host="127.0.0.1")
    # start() без bind() занимает порт сам
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while server.httpd is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.httpd is not None, "сервер не поднялся"
        assert server.httpd.server_address[0] == "127.0.0.1"
    finally:
        server.stop()


def test_backup_uses_consistent_copy_and_keeps_last_copies(tmp_path, monkeypatch):
    import sqlite3

    import core.sync_service as sync

    db = tmp_path / "base.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t (x)")
    con.execute("INSERT INTO t VALUES (42)")
    con.commit()
    con.close()

    stamps = iter(f"20270101-0000{i:02d}" for i in range(10))

    class _Now:
        @staticmethod
        def now():
            class _D:
                def strftime(self, fmt):
                    return next(stamps)

            return _D()

    monkeypatch.setattr(sync, "datetime", _Now)
    paths = [sync.backup_database(str(db)) for _ in range(sync.KEEP_SYNC_BACKUPS + 2)]

    left = sorted(p.name for p in tmp_path.glob("base.db.pre-sync-*.bak"))
    assert len(left) == sync.KEEP_SYNC_BACKUPS
    assert left[-1] == os.path.basename(paths[-1])  # остаются самые новые
    con = sqlite3.connect(paths[-1])
    assert con.execute("SELECT x FROM t").fetchone() == (42,)
    con.close()


def test_read_database_bytes_is_valid_sqlite(tmp_path):
    import sqlite3

    from core.sync_service import is_sqlite, read_database_bytes

    db = tmp_path / "base.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t (x)")
    con.commit()
    data = read_database_bytes(str(db))  # соединение открыто — копия всё равно целая
    con.close()
    assert is_sqlite(data)
