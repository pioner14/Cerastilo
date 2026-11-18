"""
Toast Notification Widget for NHJS_N.

A lightweight, non-blocking overlay notification that appears in the
bottom-right corner of the parent window and fades out automatically.

Usage:
    ToastNotification.show(parent_widget, "✅ Распределено 8 назначений", success=True)
    ToastNotification.show(parent_widget, "⚠️ Ошибка при распределении", success=False)
"""

from PySide6.QtCore import QPropertyAnimation, QPoint, QTimer, Qt, QEasingCurve, Property
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QWidget, QHBoxLayout, QGraphicsOpacityEffect


class ToastNotification(QWidget):
    """
    Animated toast notification that overlays the parent window.

    - Slides in from the bottom-right.
    - Stays visible for `duration_ms` milliseconds.
    - Fades out smoothly.
    - Self-destructs after animation completes.
    """

    TOAST_MARGIN = 20  # Distance from window edge (px)
    TOAST_HEIGHT = 52  # Fixed height (px)
    FADE_IN_MS = 200  # Fade-in duration
    FADE_OUT_MS = 350  # Fade-out duration

    # Palette
    COLOR_SUCCESS = "#1e8449"  # Deep green
    COLOR_ERROR = "#c0392b"  # Deep red
    COLOR_INFO = "#1a5276"  # Deep blue
    TEXT_COLOR = "#ffffff"

    def __init__(
        self, parent: QWidget, message: str, success: bool = True, duration_ms: int = 3500
    ):
        super().__init__(parent)

        self._duration_ms = duration_ms
        bg_color = self.COLOR_SUCCESS if success else self.COLOR_ERROR

        # --- Layout ---
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 0, 18, 0)
        layout.setSpacing(10)

        label = QLabel(message)
        # Фон и рамку подписи задаёт тема приложения (светлая плашка) — убираем
        label.setStyleSheet(
            f"color: {self.TEXT_COLOR}; font-size: 13px; font-weight: 500;"
            " background: transparent; border: none;"
        )
        label.setWordWrap(False)
        layout.addWidget(label)

        # --- Style ---
        # Без WA_StyledBackground подкласс QWidget не рисует фон из своего QSS:
        # под темой приложения белый текст оказывался на светлом фоне
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"""
            ToastNotification {{
                background-color: {bg_color};
                border-radius: 8px;
            }}
        """
        )

        # Size: dynamic width based on text, fixed height
        fm = label.fontMetrics()
        text_w = fm.horizontalAdvance(message)
        toast_w = min(max(text_w + 60, 220), 500)
        self.setFixedSize(toast_w, self.TOAST_HEIGHT)

        # --- Opacity effect (for fade) ---
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

        # Keep on top, no window frame, transparent background
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.SubWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        # --- Position ---
        self._update_position()
        self.show()
        self.raise_()

        # --- Fade IN ---
        self._fade_in = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_in.setDuration(self.FADE_IN_MS)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_in.start()

        # --- Auto-dismiss timer ---
        QTimer.singleShot(self._duration_ms, self._start_fade_out)

    def _update_position(self):
        """Position toast in bottom-right corner of parent."""
        parent = self.parent()
        if parent is None:
            return
        pw = parent.width()
        ph = parent.height()
        x = pw - self.width() - self.TOAST_MARGIN
        y = ph - self.height() - self.TOAST_MARGIN
        self.move(x, y)

    def _start_fade_out(self):
        """Start the fade-out animation, then destroy self."""
        self._fade_out = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_out.setDuration(self.FADE_OUT_MS)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade_out.finished.connect(self.deleteLater)
        self._fade_out.start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def show_toast(
        cls, parent: QWidget, message: str, success: bool = True, duration_ms: int = 3500
    ) -> "ToastNotification":
        """
        Show a toast notification on the given parent widget.

        Args:
            parent:      Parent QWidget (toast overlays it)
            message:     Text to display (can include emoji)
            success:     True = green, False = red
            duration_ms: How long to show before fading out

        Returns:
            The ToastNotification instance (usually not needed).
        """
        toast = cls(parent, message, success=success, duration_ms=duration_ms)
        return toast
