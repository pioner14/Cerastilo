"""SSL-контекст: на Android подгружаются системные корневые сертификаты."""

import ssl

from core import tls


def test_desktop_context_is_default(monkeypatch):
    monkeypatch.delenv("ANDROID_ARGUMENT", raising=False)
    context = tls.create_default_context()
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_android_loads_each_file_of_first_existing_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("ANDROID_ARGUMENT", "1")
    first, second = tmp_path / "apex", tmp_path / "system"
    first.mkdir()
    second.mkdir()
    (first / "aaaa.0").write_text("not a cert")  # мусор не ломает загрузку
    (first / "bbbb.0").write_text("x")
    (second / "cccc.0").write_text("x")
    monkeypatch.setattr(tls, "ANDROID_CA_DIRS", (str(tmp_path / "nope"), str(first), str(second)))
    loaded = []

    class Ctx(ssl.SSLContext):
        def load_verify_locations(self, cafile=None, capath=None, cadata=None):
            loaded.append(cafile)
            raise ssl.SSLError("bad")

    monkeypatch.setattr(tls.ssl, "create_default_context", lambda: Ctx(ssl.PROTOCOL_TLS_CLIENT))
    tls.create_default_context()
    assert loaded == [str(first / "aaaa.0"), str(first / "bbbb.0")]
