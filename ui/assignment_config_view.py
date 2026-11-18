"""Assignment Configuration View.

spec://ui/views#assignment-config-view

View для настройки правил автоматического распределения заданий.
Использует ApplicationFacade для доступа к данным.
"""

from typing import TYPE_CHECKING
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QHBoxLayout,
    QMessageBox,
    QHeaderView,
    QCheckBox,
    QComboBox,
    QLabel,
)
from PySide6.QtCore import Qt
from core.i18n import _

if TYPE_CHECKING:
    from core.facade import ApplicationFacade


class AssignmentConfigView(QWidget):
    """View для конфигурации правил назначений.

    Требует обязательного внедрения ApplicationFacade через конструктор.
    """

    def __init__(self, facade: "ApplicationFacade"):
        """Инициализация view.

        Args:
            facade: ApplicationFacade для доступа к бизнес-логике.

        Raises:
            ValueError: Если facade is None.
        """
        if facade is None:
            raise ValueError("facade is required for AssignmentConfigView")

        super().__init__()
        self.facade = facade
        self.layout = QVBoxLayout(self)

        # Инфо-текст
        info = QLabel(
            _("⚙️ Настройка правил автоматического распределения для каждого типа задания.")
        )
        info.setObjectName("infoLabel")
        self.layout.addWidget(info)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            [
                _("Секция / Поз."),
                _("Название задания"),
                _("Квалификация"),
                _("Братья"),
                _("Напарник"),
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        self.layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton(_("💾 Сохранить конфигурацию"))
        self.btn_save.setObjectName("btnSaveConfig")
        self.btn_save.clicked.connect(self._save_data)
        btn_layout.addWidget(self.btn_save)

        self.layout.addLayout(btn_layout)

        self.load_data()

    def load_data(self) -> None:
        """Загружает конфигурацию назначений из фасада."""
        config = self.facade.get_assignment_config()

        # Получаем уникальный список всех квалификаций в базе
        all_quals = [
            "chairman",
            "prayer_open",
            "prayer_close",
            "treasures_talk",
            "gems",
            "bible_reading",
            "student_4",
            "student_5",
            "student_6",
            "student_7_speech",
            "living_8",
            "living_9",
            "cbs_conductor",
            "cbs_reader",
            "assistant",
        ]

        self.table.setRowCount(len(config))
        for i, row in enumerate(config):
            # ID (Section / Position)
            sec_pos = f"{row['section']} / {row['position']}"
            item_id = QTableWidgetItem(sec_pos)
            item_id.setFlags(item_id.flags() & ~Qt.ItemFlag.ItemIsEditable)
            # Store keys in UserRole for retrieval
            item_id.setData(
                Qt.ItemDataRole.UserRole, {"section": row["section"], "position": row["position"]}
            )
            self.table.setItem(i, 0, item_id)

            # Название
            self.table.setItem(i, 1, QTableWidgetItem(row["assignment_name"]))

            # Квалификация (Комбобокс)
            combo = QComboBox()
            combo.addItems(all_quals)
            combo.setCurrentText(row["required_qualification"])
            self.table.setCellWidget(i, 2, combo)

            # Братья (Чекбокс)
            check_brothers = QCheckBox()
            check_brothers.setChecked(bool(row["is_brothers_only"]))
            container_b = QWidget()
            layout_b = QHBoxLayout(container_b)
            layout_b.addWidget(check_brothers)
            layout_b.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout_b.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(i, 3, container_b)

            # Напарник (Чекбокс)
            check_assistant = QCheckBox()
            check_assistant.setChecked(bool(row["needs_assistant"]))
            container_a = QWidget()
            layout_a = QHBoxLayout(container_a)
            layout_a.addWidget(check_assistant)
            layout_a.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout_a.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(i, 4, container_a)

    def _save_data(self) -> None:
        """Сохраняет конфигурацию назначений через фасад."""
        new_config = []
        for i in range(self.table.rowCount()):
            item_id = self.table.item(i, 0)
            keys = item_id.data(Qt.ItemDataRole.UserRole)

            name = self.table.item(i, 1).text()
            qual = self.table.cellWidget(i, 2).currentText()

            # Извлекаем чекбоксы из контейнеров
            bro = self.table.cellWidget(i, 3).findChild(QCheckBox).isChecked()
            ast = self.table.cellWidget(i, 4).findChild(QCheckBox).isChecked()

            new_config.append(
                {
                    "section": keys["section"],
                    "position": keys["position"],
                    "assignment_name": name,
                    "required_qualification": qual,
                    "is_brothers_only": 1 if bro else 0,
                    "needs_assistant": 1 if ast else 0,
                }
            )

        if self.facade.save_assignment_config(new_config):
            QMessageBox.information(
                self,
                _("Успех"),
                _("Конфигурация успешно сохранена и будет применяться при автораспределении."),
            )
        else:
            QMessageBox.critical(self, _("Ошибка"), _("Не удалось сохранить конфигурацию."))
