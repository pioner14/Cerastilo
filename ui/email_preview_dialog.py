"""
EmailPreviewEditDialog — диалог предпросмотра и ручного редактирования email-уведомления.

Позволяет изменить тему письма, добавить персональное примечание к стандартному
шаблону или написать произвольный текст письма перед отправкой.
"""

import html
from typing import TYPE_CHECKING, List, Optional

from PySide6.QtCore import Qt, QThread, QTimer, Signal

from core.styles import bind_style, palette
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSplitter,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from core.i18n import _

if TYPE_CHECKING:
    from core.facade import ApplicationFacade


def save_participant_calendar(
    parent, facade, participant_id: int, participant_name: str, week_ids: List[int]
) -> Optional[str]:
    """Сохранить файл календаря (.ics) с заданиями участника на недели week_ids.

    Тот же файл, что прикладывается к письму: его можно переслать участнику
    без почты в мессенджере. Возвращает путь к файлу или None (отмена, нет заданий).
    """
    from ui.file_dialogs import get_save_file_name, saved_message

    ics_text = facade.participant_calendar_ics(participant_id, week_ids)
    if not ics_text:
        QMessageBox.information(parent, _("Календарь"), _("На выбранные недели заданий нет."))
        return None
    safe_name = "".join(ch for ch in participant_name if ch.isalnum() or ch in " -_").strip()
    file_path = get_save_file_name(
        parent,
        _("Сохранить календарь"),
        _("Задания {v}.ics", v=safe_name or participant_id),
        _("Календарь (*.ics)"),
    )
    if not file_path:
        return None
    if not file_path.lower().endswith(".ics"):
        file_path += ".ics"
    # newline="" — в .ics строки уже разделены CRLF (RFC 5545)
    with open(file_path, "w", encoding="utf-8", newline="") as f:
        f.write(ics_text)
    QMessageBox.information(
        parent,
        _("Календарь"),
        saved_message(
            file_path,
            _(
                "Файл календаря сохранён. Его можно переслать участнику — "
                "задания добавятся в календарь телефона."
            ),
        ),
    )
    return file_path


class _SingleSendWorker(QThread):
    """Фоновый поток для отправки уведомления одному участнику."""

    finished = Signal(bool, str)

    def __init__(
        self,
        facade,
        participant_id: int,
        week_ids: List[int],
        subject: str,
        note: str,
        custom_body: Optional[str],
    ):
        super().__init__()
        self.facade = facade
        self.participant_id = participant_id
        self.week_ids = week_ids
        self.subject = subject
        self.note = note
        self.custom_body = custom_body

    def run(self):
        try:
            ok = self.facade.send_single_notification(
                participant_id=self.participant_id,
                week_ids=self.week_ids,
                custom_subject=self.subject,
                custom_note=self.note,
                custom_body=self.custom_body,
            )
            self.finished.emit(ok, "" if ok else _("Ошибка отправки через SMTP"))
        except Exception as e:
            self.finished.emit(False, str(e))


class EmailPreviewEditDialog(QDialog):
    """Диалог предпросмотра и редактирования текста письма участнику."""

    DEFAULT_SUBJECT = _("Ваши задания на встрече собрания")

    @staticmethod
    def _resolve_email(facade, participant_id, participant_email):
        email = str(participant_email or "").strip()
        if email:
            return email
        try:
            participant = facade.get_participant(participant_id)
        except Exception:
            return ""
        if isinstance(participant, dict):
            return str(participant.get("email") or "").strip()
        return str(getattr(participant, "email", "") or "").strip()

    def __init__(
        self,
        facade: "ApplicationFacade",
        participant_id: int,
        participant_name: str,
        participant_email: Optional[str],
        week_ids: List[int],
        initial_data: Optional[dict] = None,
        parent: Optional[QWidget] = None,
        allow_send_now: bool = False,
    ):
        super().__init__(parent)
        self.facade = facade
        self.participant_id = participant_id
        self.participant_name = participant_name
        self.participant_email = self._resolve_email(
            facade,
            participant_id,
            participant_email,
        )
        self.week_ids = week_ids
        self.result_data: Optional[dict] = None
        self.allow_send_now = allow_send_now
        self._send_worker = None
        self._sending = False  # идёт отправка — окно не закрывается (done)

        title_prefix = _("✉️ Отправка уведомления") if allow_send_now else _("✏️ Настройка письма")
        self.setWindowTitle(f"{title_prefix} — {self.participant_name}")
        self.setMinimumSize(850, 600)
        self.resize(920, 650)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(12, 12, 12, 12)

        # --- Верхняя информационная панель ---
        header_frame = QFrame()
        header_frame.setStyleSheet(
            f"QFrame {{ background: {palette().panel}; border-radius: 6px; padding: 8px 12px; }}"
        )
        header_layout = QVBoxLayout(header_frame)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)

        safe_name = html.escape(str(self.participant_name or "—"))
        safe_email = html.escape(self.participant_email or _("не указан"))
        lbl_to = QLabel(
            _(
                "<b>Получатель:</b> {safe_name} &nbsp;&nbsp;|&nbsp;&nbsp; <b>Email:</b> <span style='color: {accent};'>{safe_email}</span>",
                safe_name=safe_name,
                accent=palette().accent,
                safe_email=safe_email,
            )
        )
        lbl_to.setObjectName("emailRecipientLabel")
        lbl_to.setWordWrap(True)
        header_layout.addWidget(lbl_to)

        # Недели, о которых пишем. При отправке из меню участника можно
        # выбрать каждую; по умолчанию — только первая (текущая/ближайшая).
        # В письмо и в историю уведомлений идут только отмеченные недели.
        self.week_checkboxes: List[QCheckBox] = []
        if allow_send_now and len(week_ids) > 1:
            weeks_row = QHBoxLayout()
            weeks_row.addWidget(QLabel(_("📅 <b>Какие недели войдут в письмо:</b>")))
            for i, wid in enumerate(week_ids):
                cb = QCheckBox(self._week_title(wid))
                cb.setProperty("week_id", wid)
                cb.setChecked(i == 0)
                cb.toggled.connect(self._on_weeks_changed)
                self.week_checkboxes.append(cb)
                weeks_row.addWidget(cb)
            weeks_row.addStretch()
            header_layout.addLayout(weeks_row)
        else:
            weeks_hint_text = (
                _(
                    "📅 В письмо войдут задания из <b>{n_week_ids} недель</b> с назначениями для этого участника",
                    n_week_ids=len(week_ids),
                )
                if len(week_ids) > 1
                else _("📅 В письмо войдут задания из текущей недели")
            )
            lbl_weeks = QLabel(weeks_hint_text)
            lbl_weeks.setStyleSheet(f"font-size: 11px; color: {palette().text_secondary};")
            header_layout.addWidget(lbl_weeks)

        # Поле редактирования темы письма
        subj_layout = QHBoxLayout()
        subj_layout.addWidget(QLabel(_("<b>Тема письма:</b>")))
        self.subject_edit = QLineEdit()
        self.subject_edit.setText((initial_data or {}).get("subject") or self.DEFAULT_SUBJECT)
        self.subject_edit.textChanged.connect(self._schedule_preview_update)
        subj_layout.addWidget(self.subject_edit)
        header_layout.addLayout(subj_layout)

        main_layout.addWidget(header_frame)

        # --- Основная рабочая область (Splitter: редактор слева, превью справа) ---
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # === ЛЕВАЯ ПАНЕЛЬ: РЕДАКТОР ===
        editor_widget = QWidget()
        editor_layout = QVBoxLayout(editor_widget)
        editor_layout.setContentsMargins(0, 0, 8, 0)
        editor_layout.setSpacing(8)

        lbl_mode = QLabel(_("<b>Режим текста:</b>"))
        editor_layout.addWidget(lbl_mode)

        self.btn_group = QButtonGroup(self)
        self.radio_template = QRadioButton(_("Стандартный шаблон + примечание"))
        self.radio_custom = QRadioButton(_("Полностью свой текст письма"))
        self.btn_group.addButton(self.radio_template, 1)
        self.btn_group.addButton(self.radio_custom, 2)

        editor_layout.addWidget(self.radio_template)
        editor_layout.addWidget(self.radio_custom)

        # Блок 1: Личное примечание
        self.note_container = QWidget()
        note_layout = QVBoxLayout(self.note_container)
        note_layout.setContentsMargins(0, 4, 0, 0)
        self.lbl_note_hint = QLabel(_("💬 <b>Личное примечание к письму:</b>"))
        self.lbl_note_hint.setStyleSheet(f"font-size: 12px; color: {palette().text_secondary};")
        self.note_edit = QTextEdit()
        self.note_edit.setPlaceholderText(
            _("Например:\nБрат Андрей, пожалуйста, обрати внимание, что у тебя также микрофон 1...")
        )
        self.note_edit.setText((initial_data or {}).get("note") or "")
        self.note_edit.textChanged.connect(self._schedule_preview_update)
        note_layout.addWidget(self.lbl_note_hint)
        note_layout.addWidget(self.note_edit)
        editor_layout.addWidget(self.note_container)

        # Блок 2: Произвольный текст
        self.body_container = QWidget()
        body_layout = QVBoxLayout(self.body_container)
        body_layout.setContentsMargins(0, 4, 0, 0)
        self.lbl_body_hint = QLabel(_("📝 <b>Полный текст письма:</b>"))
        self.lbl_body_hint.setStyleSheet(f"font-size: 12px; color: {palette().text_secondary};")
        self.body_edit = QTextEdit()
        self.body_edit.setPlaceholderText(_("Введите произвольный текст сообщения..."))
        self.body_edit.setText((initial_data or {}).get("custom_body") or "")
        self.body_edit.textChanged.connect(self._schedule_preview_update)
        body_layout.addWidget(self.lbl_body_hint)
        body_layout.addWidget(self.body_edit)
        editor_layout.addWidget(self.body_container)

        # Переключение режимов
        has_custom_body = bool((initial_data or {}).get("custom_body"))
        if has_custom_body:
            self.radio_custom.setChecked(True)
            self.note_container.setVisible(False)
            self.body_container.setVisible(True)
        else:
            self.radio_template.setChecked(True)
            self.note_container.setVisible(True)
            self.body_container.setVisible(False)

        self.radio_template.toggled.connect(self._on_mode_changed)
        self.radio_custom.toggled.connect(self._on_mode_changed)

        splitter.addWidget(editor_widget)

        # === ПРАВАЯ ПАНЕЛЬ: ПРЕДПРОСМОТР ===
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(8, 0, 0, 0)
        preview_layout.setSpacing(6)

        lbl_preview = QLabel(_("👁️ <b>Предпросмотр (как увидит получатель):</b>"))
        preview_layout.addWidget(lbl_preview)

        self.preview_browser = QTextBrowser()
        self.preview_browser.setOpenExternalLinks(False)
        self.preview_browser.setMinimumSize(360, 360)
        preview_layout.addWidget(self.preview_browser)

        splitter.addWidget(preview_widget)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([380, 500])

        main_layout.addWidget(splitter, 1)

        # --- Нижняя панель с кнопками ---
        bottom_layout = QHBoxLayout()
        self.btn_reset = QPushButton(_("Сбросить к стандартному"))
        self.btn_reset.setStyleSheet(f"color: {palette().text_error};")
        self.btn_reset.clicked.connect(self._reset_to_default)
        bottom_layout.addWidget(self.btn_reset)

        self.btn_calendar = QPushButton(_("📅 Календарь (.ics)"))
        self.btn_calendar.setToolTip(
            _(
                "Сохранить файл календаря с заданиями на отмеченные недели —\n"
                "например, чтобы переслать участнику без почты"
            )
        )
        self.btn_calendar.clicked.connect(
            lambda: save_participant_calendar(
                self,
                self.facade,
                self.participant_id,
                self.participant_name,
                self.selected_week_ids(),
            )
        )
        bottom_layout.addWidget(self.btn_calendar)

        bottom_layout.addStretch()

        if self.allow_send_now:
            self.btn_send_now = QPushButton(_("📨 Отправить сейчас"))
            bind_style(
                self.btn_send_now,
                lambda c: (
                    f"background-color: {c.btn_success}; color: white; font-weight: bold; "
                    "padding: 7px 18px; border-radius: 4px;"
                ),
            )
            has_email = bool(self.participant_email)
            has_smtp = bool(self.facade.get_setting("smtp_user", ""))
            if not has_email:
                self.btn_send_now.setEnabled(False)
                self.btn_send_now.setToolTip(_("У участника не указан email"))
            elif not has_smtp:
                self.btn_send_now.setEnabled(False)
                self.btn_send_now.setToolTip(_("Настройте email в Настройки → Email-уведомления"))
            self._send_block_reason = (
                self.btn_send_now.toolTip() if not self.btn_send_now.isEnabled() else ""
            )
            self.btn_send_now.clicked.connect(self._send_now)
            bottom_layout.addWidget(self.btn_send_now)

            self.btn_cancel = QPushButton(_("Закрыть"))
            self.btn_cancel.clicked.connect(self.reject)
            bottom_layout.addWidget(self.btn_cancel)
        else:
            self.btn_save = QPushButton(_("💾 Применить изменения"))
            bind_style(
                self.btn_save,
                lambda c: (
                    f"background-color: {c.btn_primary}; color: white; font-weight: bold; "
                    "padding: 6px 16px; border-radius: 4px;"
                ),
            )
            self.btn_save.clicked.connect(self._save_and_close)
            bottom_layout.addWidget(self.btn_save)

            self.btn_cancel = QPushButton(_("Отмена"))
            self.btn_cancel.clicked.connect(self.reject)
            bottom_layout.addWidget(self.btn_cancel)

        main_layout.addLayout(bottom_layout)

        # Таймер для отложенного рендеринга предпросмотра при наборе текста
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(200)
        self._preview_timer.timeout.connect(self._update_preview)

        self._update_preview()

    def _week_title(self, week_id: int) -> str:
        try:
            data = self.facade.get_week_data(week_id) or {}
        except Exception:
            data = {}
        return (data.get("week") or {}).get("week_title") or _("Неделя {week_id}", week_id=week_id)

    def selected_week_ids(self) -> List[int]:
        """Недели, которые войдут в письмо."""
        if not self.week_checkboxes:
            return list(self.week_ids)
        return [cb.property("week_id") for cb in self.week_checkboxes if cb.isChecked()]

    def _on_weeks_changed(self):
        if self.allow_send_now and not self._send_block_reason:
            has_weeks = bool(self.selected_week_ids())
            self.btn_send_now.setEnabled(has_weeks)
            self.btn_send_now.setToolTip("" if has_weeks else _("Отметьте хотя бы одну неделю"))
        self._update_preview()

    def _on_mode_changed(self):
        is_custom = self.radio_custom.isChecked()
        self.note_container.setVisible(not is_custom)
        self.body_container.setVisible(is_custom)
        self._update_preview()

    def _schedule_preview_update(self):
        self._preview_timer.start()

    def _update_preview(self):
        custom_note = (
            self.note_edit.toPlainText().strip() if self.radio_template.isChecked() else None
        )
        custom_body = (
            self.body_edit.toPlainText().strip() if self.radio_custom.isChecked() else None
        )

        try:
            html_content = self.facade.preview_participant_email(
                self.participant_id,
                self.selected_week_ids(),
                custom_note=custom_note,
                custom_body=custom_body,
            )
            if not html_content or not html_content.strip():
                # ключ перевода содержит исходный цвет — подменяем его цветом темы
                html_content = _(
                    "<p style='color: #64748b; font-style: italic;'>"
                    "Предпросмотр пуст: для получателя нет заданий на выбранные недели."
                    "</p>"
                ).replace("#64748b", palette().preview_muted)
        except Exception as exc:
            html_content = _(
                "<p style='color: #b91c1c;'>Не удалось построить предпросмотр: {v}</p>",
                v=html.escape(str(exc)),
            ).replace("#b91c1c", palette().preview_error)
        self.preview_browser.setHtml(html_content)
        self.preview_browser.ensureCursorVisible()

    def _reset_to_default(self):
        reply = QMessageBox.question(
            self,
            _("Сброс"),
            _("Сбросить тему и текст письма к стандартному шаблону?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.subject_edit.setText(self.DEFAULT_SUBJECT)
            self.note_edit.clear()
            self.body_edit.clear()
            self.radio_template.setChecked(True)
            self.result_data = None
            self._update_preview()

    def _save_and_close(self):
        subject = self.subject_edit.text().strip()
        note = self.note_edit.toPlainText().strip()
        custom_body = (
            self.body_edit.toPlainText().strip() if self.radio_custom.isChecked() else None
        )

        is_default_subject = subject == self.DEFAULT_SUBJECT or not subject
        is_empty_note = not note
        is_empty_body = not custom_body

        if is_default_subject and is_empty_note and is_empty_body:
            # Изменений нет — считаем сброшенным
            self.result_data = None
        else:
            self.result_data = {
                "subject": subject or self.DEFAULT_SUBJECT,
                "note": note if self.radio_template.isChecked() else "",
                "custom_body": custom_body if self.radio_custom.isChecked() else None,
            }

        self.accept()

    def get_custom_data(self) -> Optional[dict]:
        """Возвращает словарь настроек письма или None если используется стандартный."""
        return self.result_data

    def _send_now(self):
        if not self.participant_email:
            QMessageBox.warning(self, _("Ошибка"), _("У участника не указан email-адрес!"))
            return

        subject = self.subject_edit.text().strip() or self.DEFAULT_SUBJECT
        note = self.note_edit.toPlainText().strip() if self.radio_template.isChecked() else ""
        custom_body = (
            self.body_edit.toPlainText().strip() if self.radio_custom.isChecked() else None
        )

        self.btn_send_now.setEnabled(False)
        self.btn_send_now.setText(_("⏳ Отправка..."))

        week_ids = self.selected_week_ids()
        if not week_ids:
            QMessageBox.warning(self, _("Ошибка"), _("Отметьте хотя бы одну неделю."))
            return

        self._send_worker = _SingleSendWorker(
            self.facade,
            self.participant_id,
            week_ids,
            subject,
            note,
            custom_body,
        )
        self._send_worker.finished.connect(self._on_send_finished)
        self._sending = True
        self._send_worker.start()

    def done(self, result: int) -> None:
        """Закрытие (крестик, Esc, «Закрыть») во время отправки: поток QThread
        уничтожился бы на ходу вместе с окном — не закрываем, просим подождать."""
        worker = self._send_worker
        if worker is not None and worker.isRunning():
            if self._sending:
                QMessageBox.information(
                    self, _("Идёт отправка"), _("Письма ещё отправляются — дождитесь окончания.")
                )
                return
            worker.wait()  # результат уже получен, поток завершается
        super().done(result)

    def _on_send_finished(self, success: bool, error: str):
        self._sending = False
        self.btn_send_now.setEnabled(True)
        self.btn_send_now.setText(_("📨 Отправить сейчас"))
        if success:
            QMessageBox.information(
                self,
                _("Успешно"),
                _(
                    "Уведомление успешно отправлено для:\n{participant_name} ({participant_email})",
                    participant_name=self.participant_name,
                    participant_email=self.participant_email,
                ),
            )
            self.accept()
        else:
            QMessageBox.critical(
                self,
                _("Ошибка отправки"),
                _(
                    "Не удалось отправить уведомление для {participant_name}:\n{error}",
                    participant_name=self.participant_name,
                    error=error,
                ),
            )
