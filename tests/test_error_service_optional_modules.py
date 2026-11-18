"""Нет модуля DOCX/EPUB (APK без WITH_DOCX=1) — понятное сообщение по-русски."""

from unittest.mock import Mock

from core.error_service import ErrorService


def _message(exc):
    bus = Mock()
    result = ErrorService(bus).handle_exception(exc, "test")
    assert bus.emit.call_args.kwargs["message"] == result["error"]
    return result["error"]


def test_missing_docx_explained():
    msg = _message(ModuleNotFoundError("No module named 'docx.shared'", name="docx.shared"))
    assert "«docx»" in msg and "S-89" in msg and "WITH_DOCX=1" in msg


def test_missing_lxml_explained():
    assert "EPUB" in _message(ModuleNotFoundError("x", name="lxml"))


def test_other_errors_unchanged():
    assert (
        _message(ModuleNotFoundError("No module named 'foo'", name="foo"))
        == "No module named 'foo'"
    )
    assert _message(ValueError("плохо")) == "плохо"
