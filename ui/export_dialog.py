from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QCheckBox,
    QPushButton,
    QScrollArea,
    QWidget,
    QLabel,
    QFrame,
    QMessageBox,
    QComboBox,
)
from PySide6.QtCore import Qt, QTimer

from core.styles import bind_style, palette
from core.i18n import _


_FORMAT_BUTTONS = {
    # формат: (подпись, роль цвета в палитре)
    "txt": (_("📝 Текст (TXT)"), "btn_primary"),
    "pdf": ("📕 PDF", "btn_danger"),
    "docx": ("📄 Word (DOCX)", "btn_success"),
}


class ExportDialog(QDialog):
    def __init__(
        self,
        weeks_data,
        parent=None,
        default_week_id=None,
        formats=("txt", "pdf", "docx"),
        confirm_text=None,
    ):
        """Диалог выбора недель.

        formats — кнопки форматов внизу (по одной на формат).
        confirm_text — вместо кнопок форматов одна кнопка с этим текстом
        (для S-89 и уведомлений, где формат не выбирается).
        """
        super().__init__(parent)
        self.setWindowTitle(_("Выбор недель для экспорта"))
        self.setMinimumSize(420, 540)

        self.selected_weeks = []
        self._selected_format = formats[0] if formats else "docx"
        self._target_scroll_widget = None

        layout = QVBoxLayout(self)

        label = QLabel(_("Выберите недели для включения в расписание:"))
        label.setStyleSheet("font-weight: bold; margin-bottom: 5px;")
        layout.addWidget(label)

        # Область прокрутки
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)

        content_widget = QWidget()
        self.content_layout = QVBoxLayout(content_widget)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.checkboxes = []

        for month_data in weeks_data:
            month_label = QLabel(month_data["month"])
            month_label.setStyleSheet(
                f"font-weight: bold; color: {palette().text_heading}; margin-top: 10px; border-bottom: 1px solid {palette().border};"
            )
            self.content_layout.addWidget(month_label)

            for week in month_data["weeks"]:
                title = week["title"]
                if week.get("bible_reading"):
                    title += f" ({week['bible_reading']})"

                cb = QCheckBox(title)
                cb.setProperty("week_id", week["id"])

                is_default = False
                if default_week_id is not None and str(week["id"]) == str(default_week_id):
                    cb.setChecked(True)
                    is_default = True
                else:
                    cb.setChecked(False)

                self.content_layout.addWidget(cb)
                self.checkboxes.append(cb)

                if is_default and self._target_scroll_widget is None:
                    self._target_scroll_widget = cb

        self.scroll.setWidget(content_widget)
        layout.addWidget(self.scroll)

        # Кнопки выбора
        selection_layout = QHBoxLayout()
        btn_all = QPushButton(_("Выбрать все"))
        btn_none = QPushButton(_("Снять все"))
        btn_all.clicked.connect(self._select_all)
        btn_none.clicked.connect(self._select_none)
        selection_layout.addWidget(btn_all)
        selection_layout.addWidget(btn_none)
        layout.addLayout(selection_layout)

        # Линия
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        # Основные кнопки экспорта
        buttons_layout = QHBoxLayout()
        btn_cancel = QPushButton(_("Отмена"))
        btn_cancel.clicked.connect(self.reject)
        buttons_layout.addWidget(btn_cancel)
        buttons_layout.addStretch()

        if confirm_text:
            choices = [(None, confirm_text, "accent")]
        else:
            choices = [(fmt, *_FORMAT_BUTTONS[fmt]) for fmt in formats]

        for fmt, text, role in choices:
            btn = QPushButton(text)

            def build(c, fmt=fmt, role=role):
                color = getattr(c, role)
                hover = getattr(c, role + "_hover")
                text_color = "white" if fmt else c.on_accent
                return f"""
                QPushButton {{
                    background-color: {color}; color: {text_color}; font-weight: bold; padding: 8px 12px; border-radius: 4px;
                }}
                QPushButton:hover {{ background-color: {hover}; }}
            """

            bind_style(btn, build)
            btn.clicked.connect(lambda _=False, f=fmt: self._on_export(f or self._selected_format))
            buttons_layout.addWidget(btn)
            btn.setDefault(True)
        layout.addLayout(buttons_layout)

        # Авто-скролл и фокус к целевой / последней неделе
        # self — владелец: таймер отменится, если окно закроют раньше
        QTimer.singleShot(50, self, self._scroll_to_target)

    def _scroll_to_target(self):
        """Прокручивает и центрирует QScrollArea на выбранной/текущей неделе."""
        target = self._target_scroll_widget
        if not target and self.checkboxes:
            target = self.checkboxes[-1]

        if target:
            target.setFocus()
            # Прокручиваем так, чтобы целевой чекбокс оказался по центру области
            vbar = self.scroll.verticalScrollBar()
            pos = target.mapTo(self.scroll.widget(), target.rect().topLeft())
            target_y = pos.y()
            viewport_h = self.scroll.viewport().height()
            center_val = max(0, target_y - (viewport_h // 2) + (target.height() // 2))
            vbar.setValue(center_val)

    def _select_all(self):
        for cb in self.checkboxes:
            cb.setChecked(True)

    def _select_none(self):
        for cb in self.checkboxes:
            cb.setChecked(False)

    def _on_export(self, fmt: str):
        self.selected_weeks = [cb.property("week_id") for cb in self.checkboxes if cb.isChecked()]
        if not self.selected_weeks:
            QMessageBox.warning(self, _("Внимание"), _("Выберите хотя бы одну неделю!"))
            return
        self._selected_format = fmt
        self.accept()

    def get_selected_week_ids(self):
        return self.selected_weeks

    def get_selected_format(self) -> str:
        """Returns 'docx', 'pdf', or 'txt'."""
        return self._selected_format

    def get_export_mode(self):
        return "compact_modern"
