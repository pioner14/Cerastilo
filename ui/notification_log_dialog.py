"""
NotificationLogDialog — диалог журнала отправки email-уведомлений.

Позволяет просматривать историю всех отправленных уведомлений, фильтровать по
участнику, статусу, неделе и повторять отправку в случае ошибок.
"""

import logging
from typing import TYPE_CHECKING, Optional, List
from datetime import datetime

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor

from core.styles import palette
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QFrame,
    QWidget,
)
from core.i18n import _

if TYPE_CHECKING:
    from core.facade import ApplicationFacade

logger = logging.getLogger(__name__)


class _ResendWorker(QThread):
    finished = Signal(object)

    def __init__(self, facade: "ApplicationFacade", week_id: int, participant_id: int):
        super().__init__()
        self.facade = facade
        self.week_id = week_id
        self.participant_id = participant_id

    def run(self):
        try:
            result = self.facade.send_notifications(
                [self.week_id], participant_ids=[self.participant_id]
            )
            self.finished.emit(result)
        except Exception as e:
            logger.error(f"Error in _ResendWorker: {e}", exc_info=True)
            self.finished.emit(e)


class NotificationLogDialog(QDialog):
    """Диалог журнала отправки email-уведомлений."""

    def __init__(
        self,
        facade: "ApplicationFacade",
        parent: Optional[QWidget] = None,
        initial_participant_id: Optional[int] = None,
        initial_week_id: Optional[int] = None,
    ):
        super().__init__(parent)
        self.facade = facade
        self.current_participant_id = initial_participant_id
        self.current_week_id = initial_week_id
        self._active_workers: List[QThread] = []

        self.setWindowTitle(_("📋 Журнал отправки уведомлений"))
        self.setMinimumSize(940, 580)
        self.resize(1000, 620)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(12, 12, 12, 12)

        # --- Панель фильтров ---
        filter_frame = QFrame()
        filter_frame.setObjectName("filterFrame")
        filter_frame.setStyleSheet(
            f"QFrame#filterFrame {{ background: {palette().panel}; border-radius: 6px; padding: 6px; }}"
        )
        filter_layout = QHBoxLayout(filter_frame)
        filter_layout.setContentsMargins(8, 6, 8, 6)
        filter_layout.setSpacing(10)

        # 1. Поиск по имени / email
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(_("🔍 Поиск по имени, email или теме..."))
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._apply_filter)
        filter_layout.addWidget(self.search_input, 3)

        # 2. Фильтр по неделе
        filter_layout.addWidget(QLabel(_("Неделя:")))
        self.week_combo = QComboBox()
        self.week_combo.addItem(_("Все недели"), None)
        self.week_combo.currentIndexChanged.connect(self._apply_filter)
        filter_layout.addWidget(self.week_combo, 2)

        # 3. Фильтр по статусу
        filter_layout.addWidget(QLabel(_("Статус:")))
        self.status_combo = QComboBox()
        self.status_combo.addItem(_("Все статусы"), None)
        self.status_combo.addItem(_("✉️ Успешно"), "success")
        self.status_combo.addItem(_("⚠️ Ошибка"), "error")
        self.status_combo.currentIndexChanged.connect(self._load_data)
        filter_layout.addWidget(self.status_combo, 2)

        # Кнопка сброса фильтра по участнику (если был задан)
        self.btn_reset_participant = QPushButton(_("✕ Показать всех участников"))
        self.btn_reset_participant.setStyleSheet(
            f"QPushButton {{ color: {palette().text_error}; font-size: 11px; font-weight: bold; padding: 4px 8px; }}"
        )
        self.btn_reset_participant.clicked.connect(self._clear_participant_filter)
        self.btn_reset_participant.setVisible(bool(self.current_participant_id))
        filter_layout.addWidget(self.btn_reset_participant)

        # Кнопка Обновить
        self.btn_refresh = QPushButton(_("🔄 Обновить"))
        self.btn_refresh.clicked.connect(self._load_data)
        filter_layout.addWidget(self.btn_refresh)

        main_layout.addWidget(filter_frame)

        # Индикатор фильтра
        self.info_label = QLabel("")
        self.info_label.setStyleSheet(
            f"color: {palette().text_primary}; font-size: 12px; margin-left: 4px;"
        )
        main_layout.addWidget(self.info_label)

        # --- Таблица журнала ---
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            [
                _("Дата / Время"),
                _("Участник"),
                "Email",
                _("Неделя"),
                _("Статус"),
                _("Ошибка / Тема"),
                _("Действие"),
            ]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)

        self.table.setColumnWidth(1, 160)
        self.table.setColumnWidth(2, 170)
        self.table.setColumnWidth(3, 160)

        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        main_layout.addWidget(self.table, 1)

        # --- Нижняя панель ---
        bottom_layout = QHBoxLayout()
        self.lbl_stats = QLabel("")
        self.lbl_stats.setStyleSheet(
            f"color: {palette().text_primary}; font-weight: bold; font-size: 12px;"
        )
        bottom_layout.addWidget(self.lbl_stats)

        bottom_layout.addStretch()

        btn_close = QPushButton(_("Закрыть"))
        btn_close.setMinimumWidth(100)
        btn_close.clicked.connect(self.accept)
        bottom_layout.addWidget(btn_close)

        main_layout.addLayout(bottom_layout)

        self._all_rows: List[dict] = []
        self._load_data()

    def _clear_participant_filter(self):
        self.current_participant_id = None
        self.btn_reset_participant.setVisible(False)
        self._load_data()

    def _populate_week_combo(self):
        saved_week_id = (
            self.week_combo.currentData() if self.week_combo.count() > 0 else self.current_week_id
        )
        self.week_combo.blockSignals(True)
        self.week_combo.clear()
        self.week_combo.addItem(_("Все недели"), None)

        weeks_seen = {}
        for r in self._all_rows:
            wid = r.get("week_id")
            wtitle = r.get("week_title") or _("Неделя #{wid}", wid=wid)
            if wid and wid not in weeks_seen:
                weeks_seen[wid] = wtitle

        # Добавляем недели в список
        for wid, wtitle in sorted(weeks_seen.items(), key=lambda x: str(x[1])):
            self.week_combo.addItem(f"📅 {wtitle}", wid)

        # Если была запрошена конкретная неделя, выбираем её
        if saved_week_id is not None:
            idx = self.week_combo.findData(saved_week_id)
            if idx >= 0:
                self.week_combo.setCurrentIndex(idx)
        self.week_combo.blockSignals(False)

    def _load_data(self):
        status = self.status_combo.currentData()
        # Загружаем записи из БД без жесткого фильтра по неделе (фильтрация недели на клиенте в комбобоксе)
        self._all_rows = self.facade.get_notification_log(
            participant_id=self.current_participant_id,
            week_id=None,
            status_filter=status,
            limit=1000,
        )
        self._populate_week_combo()
        self._apply_filter()

    def _apply_filter(self):
        query = self.search_input.text().strip().lower()
        selected_week_id = self.week_combo.currentData()

        filtered = []
        for r in self._all_rows:
            # 1. Фильтр по неделе
            if selected_week_id is not None and r.get("week_id") != selected_week_id:
                continue

            # 2. Поиск по строке (имя, email, неделя, ошибка, тема)
            if query:
                name = (r.get("participant_name") or "").lower()
                email = (r.get("participant_email") or "").lower()
                week = (r.get("week_title") or "").lower()
                subj = (r.get("subject") or "").lower()
                err = (r.get("error") or "").lower()
                if not (
                    query in name
                    or query in email
                    or query in week
                    or query in subj
                    or query in err
                ):
                    continue
            filtered.append(r)

        self._render_table(filtered)

    def _render_table(self, rows: List[dict]):
        self.table.setRowCount(0)
        success_count = 0
        error_count = 0

        for i, r in enumerate(rows):
            self.table.insertRow(i)
            status = r.get("status")
            if status == "success":
                success_count += 1
            elif status == "error":
                error_count += 1

            # 0. Дата/Время
            sent_at = r.get("sent_at")
            if sent_at:
                try:
                    if hasattr(sent_at, "strftime"):
                        dt_str = sent_at.strftime("%d.%m.%Y %H:%M")
                    else:
                        dt_str = datetime.fromisoformat(str(sent_at)).strftime("%d.%m.%Y %H:%M")
                except Exception:
                    dt_str = str(sent_at)
            else:
                dt_str = "—"

            item_date = QTableWidgetItem(dt_str)
            item_date.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(i, 0, item_date)

            # 1. Участник
            item_name = QTableWidgetItem(r.get("participant_name") or "—")
            self.table.setItem(i, 1, item_name)

            # 2. Email
            item_email = QTableWidgetItem(r.get("participant_email") or "—")
            item_email.setForeground(QColor(palette().text_secondary))
            self.table.setItem(i, 2, item_email)

            # 3. Неделя
            item_week = QTableWidgetItem(r.get("week_title") or f"#{r.get('week_id')}")
            self.table.setItem(i, 3, item_week)

            # 4. Статус
            if status == "success":
                status_item = QTableWidgetItem(_("✉️ Отправлено"))
                status_item.setForeground(QColor(palette().text_success))
            elif status == "error":
                status_item = QTableWidgetItem(_("⚠️ Ошибка"))
                status_item.setForeground(QColor(palette().text_error))
            else:
                status_item = QTableWidgetItem(str(status))
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(i, 4, status_item)

            # 5. Ошибка / Тема
            err = r.get("error")
            subj = r.get("subject") or ""
            info_text = err if err else subj
            item_info = QTableWidgetItem(info_text)
            if err:
                item_info.setForeground(QColor(palette().text_error))
                item_info.setToolTip(_("Ошибка: {err}", err=err))
            else:
                item_info.setToolTip(subj)
            self.table.setItem(i, 5, item_info)

            # 6. Действие (кнопка Повторить)
            wid = r.get("week_id")
            pid = r.get("participant_id")
            pname = r.get("participant_name")

            btn_resend = QPushButton(_("🔁 Повторить"))
            btn_resend.setStyleSheet("font-size: 11px; padding: 2px 8px;")
            btn_resend.clicked.connect(lambda _, w=wid, p=pid, n=pname: self._resend(w, p, n))
            self.table.setCellWidget(i, 6, btn_resend)

        self.lbl_stats.setText(
            _(
                "Показано: {n_rows} (из {n__all_rows})  |  ✉️ Успешно: {success_count}  |  ⚠️ Ошибок: {error_count}",
                n_rows=len(rows),
                n__all_rows=len(self._all_rows),
                success_count=success_count,
                error_count=error_count,
            )
        )

        if self.current_participant_id and self._all_rows:
            pname = self._all_rows[0].get("participant_name", f"ID {self.current_participant_id}")
            self.info_label.setText(_("Фильтрация по участнику: <b>{pname}</b>", pname=pname))
        else:
            self.info_label.setText("")

    def _resend(self, week_id: int, participant_id: int, participant_name: str):
        reply = QMessageBox.question(
            self,
            _("Повторная отправка"),
            _(
                "Отправить email-уведомление участнику {participant_name} заново?",
                participant_name=participant_name,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        worker = _ResendWorker(self.facade, week_id, participant_id)
        worker.finished.connect(lambda res: self._on_resend_finished(worker, res, participant_name))
        self._active_workers.append(worker)
        worker.start()

    def _on_resend_finished(self, worker: QThread, result, participant_name: str):
        if worker in self._active_workers:
            self._active_workers.remove(worker)

        if isinstance(result, Exception):
            QMessageBox.critical(
                self,
                _("Ошибка отправки"),
                _("Не удалось отправить уведомление:\n{result}", result=result),
            )
            self._load_data()
            return

        sent_count = getattr(result, "sent", 0)
        skipped_no_email = getattr(result, "skipped_no_email", 0)
        failed_count = getattr(result, "failed", 0)

        if sent_count > 0:
            QMessageBox.information(
                self,
                _("Успех"),
                _(
                    "Уведомление для {participant_name} успешно отправлено!",
                    participant_name=participant_name,
                ),
            )
        elif skipped_no_email > 0:
            QMessageBox.warning(
                self,
                _("Email не указан"),
                _(
                    "У участника {participant_name} не указан email в карточке возвещателя.",
                    participant_name=participant_name,
                ),
            )
        elif failed_count > 0:
            # Получаем последнюю сохраненную ошибку из БД
            last_err = ""
            try:
                hist = self.facade.get_last_notification(worker.participant_id, [worker.week_id])
                if hist and hist.get("error"):
                    last_err = _("\nОшибка: {v}", v=hist["error"])
            except Exception:
                pass
            QMessageBox.warning(
                self,
                _("Ошибка отправки"),
                _(
                    "Не удалось отправить уведомление для {participant_name}.{last_err}",
                    participant_name=participant_name,
                    last_err=last_err,
                ),
            )
        else:
            QMessageBox.information(
                self,
                _("Нет назначений"),
                _(
                    "У участника {participant_name} нет назначенных заданий на эту неделю в расписании.",
                    participant_name=participant_name,
                ),
            )
        self._load_data()
