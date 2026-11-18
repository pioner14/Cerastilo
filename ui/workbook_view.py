from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QTextEdit,
    QMessageBox,
)
from PySide6.QtCore import Signal

import sys
import os
from core.i18n import _

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.workers import TaskWorker
from ui.file_dialogs import get_open_file_name


class WorkbookView(QWidget):
    import_finished = Signal()

    def __init__(self, facade, embedded: bool = False):
        """embedded — раздел «Настроек» (без своего заголовка и отступов)."""
        super().__init__()
        self.facade = facade
        self.active_workers = []
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(*((0, 0, 0, 0) if embedded else (20, 20, 20, 20)))

        # Заголовок (в «Настройках» его заменяет заголовок раздела)
        if not embedded:
            header = QLabel(_("📚 Импорт рабочей тетради"))
            header.setObjectName("headerLabel")
            self.layout.addWidget(header)

        # Описание
        desc = QLabel(
            _(
                "Выберите файл EPUB с рабочей тетрадью «Наша христианская жизнь и служение».\n"
                "Программа автоматически извлечёт недели и задания."
            )
        )
        desc.setObjectName("descLabel")
        desc.setWordWrap(True)
        self.layout.addWidget(desc)

        # Кнопка выбора файла
        btn_layout = QHBoxLayout()
        self.btn_import = QPushButton(_("📁 Выбрать EPUB файл"))
        self.btn_import.setFixedWidth(200)
        self.btn_import.setObjectName("btnImport")
        self.btn_import.clicked.connect(self.select_and_import)
        btn_layout.addWidget(self.btn_import)
        btn_layout.addStretch()
        self.layout.addLayout(btn_layout)

        # Статус выбранного файла
        self.file_label = QLabel("")
        self.file_label.setObjectName("fileLabel")
        self.layout.addWidget(self.file_label)

        # Прогресс
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.layout.addWidget(self.progress)

        # Лог
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(200)
        self.log.setObjectName("logWidget")
        self.layout.addWidget(self.log)

        if not embedded:
            self.layout.addStretch()

    def _clean_worker(self):
        """Clean up finished worker from active list."""
        worker = self.sender()
        if hasattr(self, "active_workers") and worker in self.active_workers:
            self.active_workers.remove(worker)

    def select_and_import(self):
        # На Android системный диалог файл не возвращает — общий помощник
        # показывает EPUB из «Загрузки/Cerastilo»
        file_path = get_open_file_name(self, _("Открыть рабочую тетрадь"), "EPUB Files (*.epub)")

        if not file_path:
            return

        self.file_label.setText(_("📄 Файл: {v}", v=os.path.basename(file_path)))
        self.log.clear()
        self.log.append(_("🔄 Начинаю импорт..."))

        self.progress.setVisible(True)
        self.progress.setValue(20)

        self.btn_import.setEnabled(False)

        # Use background worker
        worker = TaskWorker(
            self.facade.import_workbook, file_path, error_service=self.facade.errors
        )
        worker.finished.connect(self._on_import_finished)
        # Connect finished to cleanup to prevent thread destruction issues
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        self.active_workers.append(worker)
        worker.start()

    def _cleanup_worker(self, worker):
        """Clean up worker after completion."""
        if worker in self.active_workers:
            self.active_workers.remove(worker)
        worker.deleteLater()

    def _on_import_finished(self, result):
        self.progress.setVisible(False)
        self.btn_import.setEnabled(True)

        if result.get("success"):
            self.progress.setValue(100)
            self.log.append(
                _(
                    "✅ Импортировано: {v} недель, {v2} заданий",
                    v=result.get("weeks", 0),
                    v2=result.get("assignments", 0),
                )
            )
            if result.get("filled_weeks"):
                # недели из «➕ Будущий год» уже были в базе — в «новые» не входят
                self.log.append(
                    _(
                        "📅 Заполнено пустых недель, созданных раньше: {v}",
                        v=result["filled_weeks"],
                    )
                )
            self.log.append(_("\n🎉 Импорт завершён! Теперь новые недели доступны в расписании."))
            self.import_finished.emit()
        else:
            self.log.append(_("❌ Ошибка: {v}", v=result.get("error")))
            QMessageBox.critical(
                self,
                _("Ошибка импорта"),
                _("Не удалось импортировать файл:\n{v}", v=result.get("error")),
            )

    def closeEvent(self, a0):
        """Graceful shutdown для воркеров."""
        for worker in self.active_workers[:]:
            if worker.isRunning():
                worker.quit()
                worker.wait(1000)
        self.active_workers.clear()
        super().closeEvent(a0)
