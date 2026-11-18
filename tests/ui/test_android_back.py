"""Кнопка «Назад» на Android: ui/android_back.py и правка Java в android/p4a_hook.py."""

import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QDialog, QMenu, QWidget

from ui.android_back import BackKeyHandler, EXIT_HINT


@pytest.fixture
def cleanup_widgets(qapp):
    """Закрывает все созданные в тесте окна и обрабатывает отложенные удаления."""
    yield
    for w in qapp.topLevelWidgets():
        w.close()
        w.deleteLater()
    qapp.processEvents()


def test_back_closes_open_menu(qapp, cleanup_widgets):
    """Открытое меню закрывается по «Назад»."""
    menu = QMenu()
    menu.addAction("Пункт")  # пустое меню Qt не показывает
    menu.popup(QPoint(0, 0))
    qapp.processEvents()
    assert menu.isVisible()

    handler = BackKeyHandler(None)
    result = handler.handle_back()
    qapp.processEvents()

    assert result == "popup"
    assert not menu.isVisible()


def test_back_closes_modal_dialog(qapp, cleanup_widgets):
    """Модальный диалог закрывается как «Отмена»."""
    dialog = QDialog()
    dialog.setModal(True)
    rejected = []
    dialog.rejected.connect(lambda: rejected.append(True))
    dialog.show()
    qapp.processEvents()

    handler = BackKeyHandler(None)
    result = handler.handle_back()
    qapp.processEvents()

    assert result == "window"
    assert rejected == [True]
    assert not dialog.isVisible()


def test_hint_then_quit_then_hint_again(qapp, cleanup_widgets, monkeypatch):
    """Двойное нажатие в интервале — выход; после интервала — снова подсказка."""
    toasts = []
    monkeypatch.setattr(
        "ui.toast.ToastNotification.show_toast",
        lambda *a, **kw: toasts.append((a, kw)),
    )
    quit_calls = []
    monkeypatch.setattr(
        "ui.android_back.QApplication.quit",
        staticmethod(lambda: quit_calls.append(True)),
    )

    main_window = QWidget()
    main_window.show()
    main_window.activateWindow()
    qapp.processEvents()
    # QApplication.activeWindow() в offscreen может вернуть None —
    # тогда главное окно не считается диалогом и логика выхода работает.
    monkeypatch.setattr(
        "ui.android_back.QApplication.activeModalWidget",
        staticmethod(lambda: None),
    )
    monkeypatch.setattr(
        "ui.android_back.QApplication.activeWindow",
        staticmethod(lambda: None),
    )
    monkeypatch.setattr(
        "ui.android_back.QApplication.activePopupWidget",
        staticmethod(lambda: None),
    )

    # Фальшивые часы: 0.0 -> 1.0 (в интервале) -> 4.0 (вне интервала)
    times = iter([0.0, 1.0, 4.0])
    handler = BackKeyHandler(main_window, clock=lambda: next(times))

    assert handler.handle_back() == "hint"
    assert len(toasts) == 1
    assert toasts[0][0][1] == EXIT_HINT

    assert handler.handle_back() == "quit"
    assert quit_calls == [True]

    # После выхода состояние сброшено — снова подсказка
    assert handler.handle_back() == "hint"
    assert len(toasts) == 2


def test_event_filter_dedup_and_release(qapp, cleanup_widgets, monkeypatch):
    """Дедупликация по метке времени, отпускание принимается, чужая клавиша — нет."""
    handler = BackKeyHandler(None)
    calls = []
    monkeypatch.setattr(handler, "handle_back", lambda: calls.append(True) or "hint")

    obj_a = QWidget()
    obj_b = QWidget()

    press = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Back, Qt.KeyboardModifier.NoModifier)
    press.setTimestamp(12345)

    # Одно и то же событие проходит через два объекта — действие одно
    assert handler.eventFilter(obj_a, press) is True
    assert handler.eventFilter(obj_b, press) is True
    assert len(calls) == 1

    # Отпускание принимается и не вызывает действие
    release = QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Back, Qt.KeyboardModifier.NoModifier)
    release.setTimestamp(12345)
    assert handler.eventFilter(obj_a, release) is True
    assert len(calls) == 1

    # Другая клавиша — не наша
    other = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier)
    assert handler.eventFilter(obj_a, other) is False
    assert len(calls) == 1


def test_patch_back_key():
    """Правка Java: убирает перехват «Назад», идемпотентна, не трогает прочее."""
    android_dir = Path(__file__).resolve().parents[2] / "android"
    if str(android_dir) not in sys.path:
        sys.path.insert(0, str(android_dir))
    import p4a_hook

    java = (
        "public boolean onKeyDown(int keyCode, KeyEvent event) {\n"
        "    if (keyCode == KeyEvent.KEYCODE_BACK) {\n"
        f"        {p4a_hook.BACK_BLOCK_START}\n"
        f"            {p4a_hook.BACK_TOAST}\n"
        "        }\n"
        "    }\n"
        "    return super.onKeyDown(keyCode, event);\n"
        "}\n"
    )

    patched = p4a_hook.patch_back_key(java)
    assert p4a_hook.BACK_BLOCK_START not in patched
    assert p4a_hook.BACK_PATCHED in patched

    # Повторный вызов ничего не меняет
    assert p4a_hook.patch_back_key(patched) == patched

    # Без тоста текст не меняется
    no_toast = java.replace(p4a_hook.BACK_TOAST, "")
    assert p4a_hook.patch_back_key(no_toast) == no_toast
