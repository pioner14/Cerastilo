"""
NotificationDialog — диалог отправки email-уведомлений участникам.

Позволяет просмотреть список участников с заданиями и отправить
персональные письма о их заданиях на выбранные недели.
"""

import logging
from datetime import datetime
from typing import TYPE_CHECKING, List, Dict, Optional, Any

from PySide6.QtCore import Qt, QThread, Signal

from core.styles import bind_style, palette
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
    QCheckBox,
    QRadioButton,
    QScrollArea,
    QButtonGroup,
)
from core.i18n import _

if TYPE_CHECKING:
    from core.facade import ApplicationFacade

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Worker thread for sending (keeps UI responsive)
# ---------------------------------------------------------------------------


class _SendWorker(QThread):
    """Фоновый поток отправки писем."""

    progress = Signal(int, int, str)  # current, total, name
    finished = Signal(object)  # NotificationResult

    def __init__(
        self,
        facade: "ApplicationFacade",
        week_ids: List[int],
        participant_ids: List[int],
        custom_messages: Optional[dict] = None,
    ):
        super().__init__()
        self.facade = facade
        self.week_ids = week_ids
        self.participant_ids = participant_ids
        self.custom_messages = custom_messages

    def run(self):
        def _progress(current, total, name):
            self.progress.emit(current, total, name)

        result = self.facade.send_notifications(
            self.week_ids,
            participant_ids=self.participant_ids,
            progress_callback=_progress,
            custom_messages=self.custom_messages,
        )
        self.finished.emit(result)


# ---------------------------------------------------------------------------
# Main dialog
# ---------------------------------------------------------------------------


class NotificationDialog(QDialog):
    """Диалог отправки email-уведомлений участникам о заданиях."""

    def __init__(
        self,
        facade: "ApplicationFacade",
        week_ids: List[int],
        parent=None,
        only_participant_ids: Optional[List[int]] = None,
        default_subject: Optional[str] = None,
    ):
        super().__init__(parent)
        # Тема письма для всех, у кого не задана своя (например, «Ваши задания на ноябрь»)
        self.default_subject = default_subject
        self.facade = facade
        self.week_ids = week_ids
        # Если задано — отмечены только эти участники («Уведомить оставшихся»)
        self.only_participant_ids = (
            set(only_participant_ids) if only_participant_ids is not None else None
        )
        self._worker = None
        self._sending = False  # идёт рассылка — окно не закрывается (done)
        self._selected_participant_ids: List[int] = []
        self.custom_messages: dict = {}  # pid -> {subject, note, custom_body}

        self.setWindowTitle(_("📨 Уведомить участников"))
        self.setMinimumWidth(560)
        self.setMinimumHeight(440)

        layout = QVBoxLayout(self)

        # --- Info block ---
        info_group = QGroupBox(_("ℹ️ Информация"))
        info_layout = QVBoxLayout()

        # SMTP status
        smtp_user = self.facade.get_setting("smtp_user", "")
        smtp_password = self.facade.get_setting("smtp_password", "")
        sender_name = self.facade.get_setting("smtp_sender_name", "")
        has_smtp = bool(smtp_user and smtp_password)

        if has_smtp:
            smtp_label = QLabel(
                _(
                    "<b>Отправитель:</b> {v} <{smtp_user}>",
                    v=sender_name or smtp_user,
                    smtp_user=smtp_user,
                )
            )
        else:
            smtp_label = QLabel(
                _("⚠️ <b>Email не настроен!</b> Перейдите в Настройки → Email-уведомления.")
            )
            smtp_label.setStyleSheet(f"color: {palette().text_warning};")

        smtp_label.setWordWrap(True)
        info_layout.addWidget(smtp_label)

        # Week list
        weeks_info = self._build_weeks_info()
        weeks_label = QLabel(_("<b>Недели:</b> {weeks_info}", weeks_info=weeks_info))
        weeks_label.setWordWrap(True)
        info_layout.addWidget(weeks_label)

        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        # --- Participant selection ---
        selection_group = QGroupBox(_("👥 Получатели уведомлений"))
        selection_layout = QVBoxLayout()

        top_ctrl_layout = QHBoxLayout()
        self.cb_select_all = QCheckBox(_("Выбрать всех (с email)"))
        self.cb_select_all.setChecked(True)
        self.cb_select_all.toggled.connect(self._toggle_select_all)
        top_ctrl_layout.addWidget(self.cb_select_all)
        top_ctrl_layout.addStretch()
        selection_layout.addLayout(top_ctrl_layout)

        self.participant_checks: Dict[int, QCheckBox] = {}  # pid -> checkbox

        # Scroll area for participants
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.participant_widget = QWidget()
        self.participant_layout = QVBoxLayout(self.participant_widget)
        self.participant_layout.setSpacing(4)
        scroll.setWidget(self.participant_widget)

        selection_layout.addWidget(scroll)
        selection_group.setLayout(selection_layout)
        layout.addWidget(selection_group)

        # --- Progress bar ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.progress_label = QLabel("")
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_label.setVisible(False)
        layout.addWidget(self.progress_label)

        # --- Buttons ---
        btn_layout = QHBoxLayout()

        self.btn_test = QPushButton(_("🔌 Проверить соединение"))
        self.btn_test.setStyleSheet("padding: 7px 14px;")
        self.btn_test.clicked.connect(self._test_connection)

        self.btn_send = QPushButton(_("📨 Отправить"))
        bind_style(
            self.btn_send,
            lambda c: (
                f"padding: 7px 14px; background-color: {c.btn_primary}; color: white; "
                "font-weight: bold; border-radius: 4px;"
            ),
        )
        self.btn_send.clicked.connect(self._start_send)

        self.btn_close = QPushButton(_("Закрыть"))
        self.btn_close.setStyleSheet("padding: 7px 14px;")
        self.btn_close.clicked.connect(self.reject)

        btn_layout.addWidget(self.btn_test)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_send)
        btn_layout.addWidget(self.btn_close)
        layout.addLayout(btn_layout)

        # Disable send if no SMTP configured
        if not has_smtp:
            self.btn_send.setEnabled(False)
            self.btn_send.setToolTip(_("Настройте email в разделе Настройки → Email-уведомления"))

        self._load_preview()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _toggle_select_all(self, checked: bool):
        for cb in self.participant_checks.values():
            if cb.isEnabled():
                cb.blockSignals(True)
                cb.setChecked(checked)
                cb.blockSignals(False)
        self._update_send_button_state()

    def _update_send_button_state(self):
        selected_count = sum(1 for cb in self.participant_checks.values() if cb.isChecked())
        total_enabled = sum(1 for cb in self.participant_checks.values() if cb.isEnabled())

        self.btn_send.setText(_("📨 Отправить ({selected_count})", selected_count=selected_count))
        has_smtp = bool(self.facade.get_setting("smtp_user", ""))
        self.btn_send.setEnabled(selected_count > 0 and has_smtp)

        self.cb_select_all.blockSignals(True)
        if total_enabled > 0 and selected_count == total_enabled:
            self.cb_select_all.setCheckState(Qt.CheckState.Checked)
        elif selected_count > 0:
            self.cb_select_all.setCheckState(Qt.CheckState.PartiallyChecked)
        else:
            self.cb_select_all.setCheckState(Qt.CheckState.Unchecked)
        self.cb_select_all.blockSignals(False)

    def _build_weeks_info(self) -> str:
        """Формирует строку со списком выбранных недель."""
        parts = []
        for wid in self.week_ids:
            data = self.facade.get_week_data(wid)
            if data:
                parts.append(data.get("week_title", _("Неделя {wid}", wid=wid)))
        return ", ".join(parts) if parts else "—"

    def _load_preview(self) -> None:
        """Загружает и показывает список участников со статусами и чекбоксами."""
        # Очищаем предыдущие виджеты
        while self.participant_layout.count():
            item = self.participant_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.participant_checks = {}

        try:
            summary = self.facade.get_notification_preview(self.week_ids)
        except Exception as e:
            QMessageBox.warning(
                self, _("Ошибка"), _("Не удалось загрузить список участников: {e}", e=e)
            )
            return

        if not summary:
            empty_lbl = QLabel(_("Нет назначенных участников на выбранные недели"))
            empty_lbl.setStyleSheet(
                f"color: {palette().text_secondary}; font-style: italic; margin: 10px;"
            )
            self.participant_layout.addWidget(empty_lbl)
            self._update_send_button_state()
            return

        for item in summary:
            name = item["name"]
            email = item.get("email")
            pid = item.get("id")
            tasks = item.get("tasks", [])

            if not pid:
                continue

            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(4, 2, 4, 2)

            cb = QCheckBox(name)
            cb.setChecked(
                bool(email)
                and (self.only_participant_ids is None or pid in self.only_participant_ids)
            )
            cb.setEnabled(bool(email))
            cb.toggled.connect(self._update_send_button_state)

            tasks_text = "\n".join(f"• {t}" for t in tasks)
            tooltip = f"Email: {email or _('нет email')}"
            if tasks_text:
                tooltip += _("\n\nЗадания:\n{tasks_text}", tasks_text=tasks_text)

            # Показываем статус отправки
            status_info = self.facade.get_last_notification(pid, self.week_ids)
            status_lbl = QLabel()
            if status_info:
                dt = status_info.get("sent_at")
                if dt:
                    if hasattr(dt, "strftime"):
                        date_str = dt.strftime(_("%d.%m в %H:%M"))
                    else:
                        try:
                            date_str = datetime.fromisoformat(str(dt)).strftime(_("%d.%m в %H:%M"))
                        except Exception:
                            date_str = str(dt)
                else:
                    date_str = "—"
                if status_info.get("status") == "success":
                    status_lbl.setText(_("✅ Отправлено {date_str}", date_str=date_str))
                    status_lbl.setStyleSheet(
                        f"color: {palette().text_success}; font-size: 11px; font-weight: bold;"
                    )
                else:
                    err = status_info.get("error") or ""
                    status_lbl.setText(_("❌ Ошибка"))
                    status_lbl.setStyleSheet(
                        f"color: {palette().text_error}; font-size: 11px; font-weight: bold;"
                    )
                    if err:
                        tooltip += _("\n\nОшибка последней отправки: {err}", err=err)
            elif not email:
                status_lbl.setText(_("⚠️ Без email"))
                status_lbl.setStyleSheet(f"color: {palette().text_warning}; font-size: 11px;")

            cb.setToolTip(tooltip)
            row_layout.addWidget(cb)
            row_layout.addStretch()

            # Кнопка настройки / предпросмотра письма
            if email:
                is_custom = pid in self.custom_messages
                btn_edit = QPushButton(_("✏️ Изменено") if is_custom else _("✏️ Письмо"))
                if is_custom:
                    btn_edit.setStyleSheet(
                        f"QPushButton {{ font-size: 11px; padding: 2px 8px; background: {palette().surface_subtle}; color: {palette().accent}; border: 1px solid {palette().border}; border-radius: 3px; font-weight: bold; }}"
                    )
                else:
                    btn_edit.setStyleSheet(
                        f"QPushButton {{ font-size: 11px; padding: 2px 8px; color: {palette().text_secondary}; }}"
                    )
                btn_edit.setToolTip(_("Предпросмотр и ручное редактирование текста письма"))
                btn_edit.clicked.connect(
                    lambda _, p=pid, n=name, em=email: self._open_edit_email(p, n, em)
                )
                row_layout.addWidget(btn_edit)
            else:
                # Без почты — файл календаря, чтобы переслать в мессенджере
                btn_ics = QPushButton(_("📅 Календарь"))
                btn_ics.setStyleSheet(
                    f"QPushButton {{ font-size: 11px; padding: 2px 8px; color: {palette().text_secondary}; }}"
                )
                btn_ics.setToolTip(
                    _("Сохранить файл календаря (.ics) с заданиями — переслать участнику")
                )
                btn_ics.clicked.connect(lambda _, p=pid, n=name: self._save_calendar(p, n))
                row_layout.addWidget(btn_ics)

            row_layout.addWidget(status_lbl)

            self.participant_layout.addWidget(row_widget)
            self.participant_checks[pid] = cb

        self._update_send_button_state()

    def _messages_for(self, participant_ids: List[int]) -> dict:
        """Свои правки письма + общая тема (default_subject), где своей темы нет."""
        if not self.default_subject:
            return self.custom_messages
        messages = {}
        for pid in participant_ids:
            custom = dict(self.custom_messages.get(pid) or {})
            if not (custom.get("subject") or "").strip():
                custom["subject"] = self.default_subject
            messages[pid] = custom
        return messages

    def _save_calendar(self, participant_id: int, name: str):
        from ui.email_preview_dialog import save_participant_calendar

        save_participant_calendar(self, self.facade, participant_id, name, self.week_ids)

    def _open_edit_email(self, participant_id: int, name: str, email: Optional[str]):
        """Открывает диалог редактирования темы и текста письма участнику."""
        from ui.email_preview_dialog import EmailPreviewEditDialog

        initial = self.custom_messages.get(participant_id)
        dialog = EmailPreviewEditDialog(
            self.facade,
            participant_id,
            name,
            email,
            self.week_ids,
            initial_data=initial,
            parent=self,
        )
        if dialog.exec():
            data = dialog.get_custom_data()
            if data:
                self.custom_messages[participant_id] = data
            else:
                self.custom_messages.pop(participant_id, None)
            self._load_preview()

    def _test_connection(self) -> None:
        """Проверяет SMTP-соединение."""
        self.btn_test.setEnabled(False)
        self.btn_test.setText(_("Проверка..."))
        try:
            ok, msg = self.facade.test_smtp_connection()
            if ok:
                QMessageBox.information(self, _("✅ Соединение"), msg)
            else:
                QMessageBox.warning(self, _("❌ Ошибка соединения"), msg)
        except Exception as e:
            QMessageBox.critical(self, _("Ошибка"), str(e))
        finally:
            self.btn_test.setEnabled(True)
            self.btn_test.setText(_("🔌 Проверить соединение"))

    def _start_send(self) -> None:
        """Запускает фоновую отправку писем выбранным участникам."""
        selected_ids = [
            pid for pid, cb in self.participant_checks.items() if cb.isChecked() and cb.isEnabled()
        ]

        if not selected_ids:
            QMessageBox.warning(
                self, _("Ошибка"), _("Не выбрано ни одного участника для отправки!")
            )
            return

        reply = QMessageBox.question(
            self,
            _("Подтверждение"),
            _(
                "Отправить письма {n_selected_ids} выбранным участникам?",
                n_selected_ids=len(selected_ids),
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # UI: прогресс
        self.btn_send.setEnabled(False)
        self.btn_test.setEnabled(False)
        self.btn_close.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.progress_label.setText(_("Подготовка..."))
        self.progress_label.setVisible(True)

        # Запускаем поток с выбранными participants и кастомными сообщениями
        self._worker = _SendWorker(
            self.facade,
            self.week_ids,
            selected_ids,
            custom_messages=self._messages_for(selected_ids),
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._sending = True
        self._worker.start()

    def done(self, result: int) -> None:
        """Закрытие (крестик, Esc, «Закрыть») во время отправки: поток QThread
        уничтожился бы на ходу вместе с окном — не закрываем, просим подождать."""
        worker = self._worker
        if worker is not None and worker.isRunning():
            if self._sending:
                QMessageBox.information(
                    self, _("Идёт отправка"), _("Письма ещё отправляются — дождитесь окончания.")
                )
                return
            worker.wait()  # результат уже получен, поток завершается
        super().done(result)

    def _on_progress(self, current: int, total: int, name: str) -> None:
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.progress_label.setText(
            _("Отправка {current}/{total}: {name}...", current=current, total=total, name=name)
        )

    def _on_finished(self, result) -> None:
        """Обрабатывает завершение отправки."""
        self._sending = False
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        self.btn_test.setEnabled(True)
        self.btn_close.setEnabled(True)

        # Обновляем статусы в списке
        self._load_preview()

        summary = result.summary()
        if result.failed == 0:
            QMessageBox.information(self, _("✅ Рассылка завершена"), summary)
        else:
            QMessageBox.warning(self, _("⚠️ Рассылка завершена с ошибками"), summary)
