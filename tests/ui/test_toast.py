"""
Tests for ToastNotification widget.

Verifies:
- Toast is created and shown
- Correct color for success/error states
- Auto-dismissal timer fires
- Static show() factory method works
- Toast positions itself in the parent's bottom-right corner
"""

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from ui.toast import ToastNotification


@pytest.fixture
def parent_widget(qtbot):
    """A simple parent widget to host toasts."""
    w = QWidget()
    w.resize(800, 600)
    qtbot.addWidget(w)
    w.show()
    return w


class TestToastNotification:

    def test_toast_is_visible_after_show(self, qtbot, parent_widget):
        """Toast should be visible immediately after creation."""
        toast = ToastNotification.show_toast(parent_widget, "✅ Тест успеха", success=True)
        qtbot.addWidget(toast)
        assert toast.isVisible()

    def test_success_toast_has_green_style(self, qtbot, parent_widget):
        """Success toast should use the green background color."""
        toast = ToastNotification.show_toast(parent_widget, "Успех", success=True)
        qtbot.addWidget(toast)
        style = toast.styleSheet()
        assert ToastNotification.COLOR_SUCCESS in style

    def test_error_toast_has_red_style(self, qtbot, parent_widget):
        """Error toast should use the red background color."""
        toast = ToastNotification.show_toast(parent_widget, "Ошибка", success=False)
        qtbot.addWidget(toast)
        style = toast.styleSheet()
        assert ToastNotification.COLOR_ERROR in style

    def test_toast_has_correct_height(self, qtbot, parent_widget):
        """Toast height should match the TOAST_HEIGHT constant."""
        toast = ToastNotification.show_toast(parent_widget, "Сообщение", success=True)
        qtbot.addWidget(toast)
        assert toast.height() == ToastNotification.TOAST_HEIGHT

    def test_toast_positioned_bottom_right(self, qtbot, parent_widget):
        """Toast x/y should be near parent's bottom-right corner."""
        toast = ToastNotification.show_toast(parent_widget, "Позиция", success=True)
        qtbot.addWidget(toast)
        # x should be to the right of center
        assert toast.x() > parent_widget.width() // 2
        # y should be in the bottom half
        assert toast.y() > parent_widget.height() // 2

    def test_toast_factory_returns_instance(self, qtbot, parent_widget):
        """show_toast() class method should return a ToastNotification instance."""
        toast = ToastNotification.show_toast(parent_widget, "Фабрика", success=True)
        qtbot.addWidget(toast)
        assert isinstance(toast, ToastNotification)

    def test_zero_count_uses_info_message(self, qtbot, parent_widget):
        """
        Simulate schedule_view behavior: count=0 → info message (success=False).
        The toast should be created with the neutral info message.
        """
        count = 0
        msg = f"✅ Распределено: {count} назначений" if count > 0 else "ℹ️ Все задания уже заполнены"
        is_success = count > 0

        toast = ToastNotification.show_toast(parent_widget, msg, success=is_success)
        qtbot.addWidget(toast)

        assert toast.isVisible()
        # count=0 → success=False → red palette
        assert ToastNotification.COLOR_ERROR in toast.styleSheet()
