from typing import TYPE_CHECKING, Optional

from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QSizePolicy,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import text

from .base_module import BaseModule
from core.i18n import _

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from core.facade import ApplicationFacade


class AnnouncementModule(BaseModule):
    @property
    def id(self) -> str:
        return "announcements"

    @property
    def name(self) -> str:
        return _("📢 Объявления")

    def migrate(self, session: "Session"):
        # Проверяем наличие колонки announcement в таблице weeks
        # SQLite не поддерживает IF NOT EXISTS для колонок напрямую в старых версиях,
        # но мы можем проверить pragma
        try:
            # Получаем список колонок
            result = session.execute(text("PRAGMA table_info(weeks)")).fetchall()
            columns = [row[1] for row in result]

            if "announcement" not in columns:
                session.execute(text("ALTER TABLE weeks ADD COLUMN announcement TEXT"))
                session.commit()
                import logging

                logging.getLogger(__name__).info(
                    "Applied migration: Added 'announcement' column to 'weeks'"
                )
        except Exception as e:
            import logging

            logging.getLogger(__name__).error(f"Migration error in AnnouncementModule: {e}")
            session.rollback()

    def get_week_widget(self, week_id: int, facade: "ApplicationFacade") -> Optional["QWidget"]:
        current_text = facade.get_week_announcement(week_id) or ""

        box = QGroupBox(_("📢 Объявление"))
        box.setObjectName("announcementGroup")
        # Оформление — в теме (assets/styles/*.qss): инлайн-стиль здесь
        # делал блок белым в тёмной теме.
        box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        box.setMaximumHeight(120)

        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(4)

        controls = QHBoxLayout()
        controls.addStretch()
        toggle = QToolButton()
        toggle.setObjectName("announcementExpandToggle")
        toggle.setText(_("Развернуть"))
        toggle.setCheckable(True)
        controls.addWidget(toggle)
        layout.addLayout(controls)

        editor = QTextEdit()
        editor.setObjectName("announcementEditor")
        editor.setPlaceholderText(_("Введите объявление для этой недели..."))
        editor.setFixedHeight(70)
        editor.setText(current_text)
        editor.textChanged.connect(
            lambda: facade.save_week_announcement(week_id, editor.toPlainText())
        )

        def set_expanded(expanded):
            editor.setFixedHeight(180 if expanded else 70)
            box.setMaximumHeight(240 if expanded else 120)
            toggle.setText(_("Свернуть") if expanded else _("Развернуть"))

        toggle.toggled.connect(set_expanded)
        layout.addWidget(editor)
        return box

    def get_export_content(self, week, session: "Session") -> Optional[str]:
        # week - это ORM объект Week
        # Т.к. мы добавили колонку динамически (или она есть в модели),
        # SQLAlchemy может не видеть её атрибутом, если модель не обновлена.
        # Но если мы обновим модель...

        # ВАЖНО: Python модель Week в core/models.py ТОЖЕ должна иметь это поле,
        # иначе week.announcement вызовет ошибку, даже если колонка есть в БД.
        # Поэтому мы должны обновить models.py тоже.

        if hasattr(week, "announcement") and week.announcement:
            return week.announcement.strip()
        return None
