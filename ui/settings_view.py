"""Settings View.

spec://ui/views#settings-view

View для настройки параметров собрания, модулей и резервного копирования.
Использует ApplicationFacade для доступа к бизнес-логике.
"""

from typing import TYPE_CHECKING
from core.chairman_talk import ROLE_SETTINGS
from core.styles import Theme, apply_theme, bind_style, get_system_theme
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QFormLayout,
    QPushButton,
    QGroupBox,
    QComboBox,
    QCheckBox,
    QMessageBox,
    QFileDialog,
    QScrollArea,
    QFrame,
    QListWidget,
)
import datetime

from core.utils.android_storage import is_android
from ui.file_dialogs import get_open_file_name, get_save_file_name
from core import donate
from core.i18n import _, tr
from core.notification_service import meeting_day_display
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

if TYPE_CHECKING:
    from core.facade import ApplicationFacade


class SettingsView(QWidget):
    """View для настроек приложения.

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
            raise ValueError("facade is required for SettingsView")

        super().__init__()
        self.facade = facade
        # Содержимое — в области прокрутки: на низком экране (планшет) группы
        # иначе сжимаются по высоте и поля налезают друг на друга
        # Слева — оглавление разделов: страница длинная, нужное (почту,
        # синхронизацию) иначе приходится искать прокруткой
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.section_nav = QListWidget()
        self.section_nav.setObjectName("settingsSections")
        self.section_nav.setMaximumWidth(220)
        self.section_nav.setFrameShape(QFrame.Shape.NoFrame)
        self.section_nav.currentRowChanged.connect(self._go_to_section)
        outer.addWidget(self.section_nav)
        self.scroll = scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        self.layout = QVBoxLayout(content)

        group = QGroupBox(_("Настройки собрания"))
        group_layout = QFormLayout()

        self.cong_name = QLineEdit()
        self.cong_name.setPlaceholderText(_("Введите название собрания"))
        group_layout.addRow(_("Название собрания:"), self.cong_name)

        self.meeting_day = QLineEdit()
        self.meeting_day.setPlaceholderText(_("например, Четверг"))
        group_layout.addRow(_("День встречи:"), self.meeting_day)

        self.meeting_time = QLineEdit()
        self.meeting_time.setPlaceholderText(_("например, 18:30"))
        group_layout.addRow(_("Время начала встречи:"), self.meeting_time)

        self.min_gap = QComboBox()
        self.min_gap.addItems([_("1 неделя"), _("2 недели"), _("3 недели"), _("4 недели")])
        group_layout.addRow(_("Минимальный перерыв между заданиями:"), self.min_gap)

        self.ms_gap = QComboBox()
        self.ms_gap.addItems([_("1 неделя"), _("2 недели"), _("3 недели"), _("4 недели")])
        self.ms_gap.setToolTip(
            _(
                "Интервал для служебных помощников.\n"
                "Переопределяет общий перерыв для участников с типом 'Помощник'.\n"
                "Отдельные братья могут иметь свой интервал (в карточке участника)."
            )
        )
        group_layout.addRow(_("Перерыв для служебных помощников:"), self.ms_gap)

        group.setLayout(group_layout)
        self.layout.addWidget(group)

        # === Обязанности в собрании ===
        # Если тетрадь пишет «Речь ответственного за служение» и т.п., этот
        # пункт сразу получает выбранного брата (core/chairman_talk.py)
        roles_group = QGroupBox(_("👥 Обязанности в собрании"))
        roles_layout = QFormLayout()
        roles_hint = QLabel(
            _(
                "Если в рабочей тетради написано, например, «Речь ответственного за "
                "служение», этот пункт сразу получает выбранного брата."
            )
        )
        roles_hint.setWordWrap(True)
        bind_style(roles_hint, lambda c: f"color: {c.text_secondary}; font-size: 11px;")
        roles_layout.addRow(roles_hint)
        self.role_combos = {}
        for key, label in ROLE_SETTINGS.items():
            combo = QComboBox()
            self.role_combos[key] = combo
            roles_layout.addRow(_(label) + ":", combo)
        roles_group.setLayout(roles_layout)
        self.layout.addWidget(roles_group)

        btn_save = QPushButton(_("💾 Сохранить параметры"))
        btn_save.setObjectName("btnSaveSettings")
        btn_save.clicked.connect(self._save_settings)
        self.layout.addWidget(btn_save)

        # === Оформление ===
        theme_group = QGroupBox(_("🎨 Оформление"))
        theme_layout = QFormLayout()
        self.theme_combo = QComboBox()
        self.theme_combo.addItem(_("Как в системе"), "system")
        self.theme_combo.addItem(_("Светлая"), Theme.LIGHT.value)
        self.theme_combo.addItem(_("Тёмная"), Theme.DARK.value)
        idx = self.theme_combo.findData(self.facade.get_setting("theme", "system"))
        self.theme_combo.setCurrentIndex(max(idx, 0))
        self.theme_combo.currentIndexChanged.connect(self._on_theme_selected)
        theme_layout.addRow(_("Тема:"), self.theme_combo)
        # Язык хранится на этом устройстве (не в базе: база синхронизируется)
        from core.i18n import LANGUAGES, language

        self.language_combo = QComboBox()
        for code, title in LANGUAGES.items():
            self.language_combo.addItem(title, code)
        self.language_combo.setCurrentIndex(max(self.language_combo.findData(language()), 0))
        self.language_combo.currentIndexChanged.connect(self._on_language_selected)
        theme_layout.addRow("Язык / Language:", self.language_combo)
        theme_group.setLayout(theme_layout)
        self.layout.addWidget(theme_group)

        # === Модули ===
        modules_group = QGroupBox(_("🧩 Модули"))
        modules_layout = QVBoxLayout()

        # Checkboxes for each module
        self.module_checks = {}
        # Get all modules from registry
        for module in self.facade.registry.get_all():
            chk = QCheckBox(module.name)
            # Check if enabled (default true)
            is_enabled = self.facade.get_setting(f"module_{module.id}", "true") == "true"
            chk.setChecked(is_enabled)
            # Save immediately on change
            chk.toggled.connect(
                lambda checked, m_id=module.id: self._on_module_toggled(m_id, checked)
            )
            modules_layout.addWidget(chk)
            self.module_checks[module.id] = chk

        modules_group.setLayout(modules_layout)
        self.layout.addWidget(modules_group)

        # === Миграция данных ===
        import_group = QGroupBox(_("💾 Миграция данных"))
        import_layout = QVBoxLayout()

        import_desc = QLabel(_("Импорт истории прошлых назначений из CSV-файла NW Scheduler."))
        bind_style(import_desc, lambda c: f"color: {c.text_secondary}; font-size: 11px;")
        import_desc.setWordWrap(True)
        import_layout.addWidget(import_desc)

        self.btn_import_nws = QPushButton(_("🕒 Импортировать историю из NW Scheduler"))
        bind_style(
            self.btn_import_nws,
            lambda c: f"""
            QPushButton {{
                background-color: {c.btn_neutral};
                color: white;
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {c.btn_neutral_hover};
            }}
        """,
        )
        self.btn_import_nws.clicked.connect(self._import_history)
        import_layout.addWidget(self.btn_import_nws)

        import_group.setLayout(import_layout)
        self.layout.addWidget(import_group)

        # === Резервное копирование ===
        backup_group = QGroupBox(_("🛡️ Безопасность данных"))
        backup_layout = QHBoxLayout()

        self.btn_backup = QPushButton(_("📦 Создать бэкап"))
        self.btn_backup.setStyleSheet("padding: 8px; font-weight: bold;")
        self.btn_backup.clicked.connect(self._create_backup)

        self.btn_restore = QPushButton(_("📂 Восстановить"))
        self.btn_restore.setStyleSheet("padding: 8px; font-weight: bold;")
        self.btn_restore.clicked.connect(self._restore_backup)

        backup_layout.addWidget(self.btn_backup)
        backup_layout.addWidget(self.btn_restore)

        backup_group.setLayout(backup_layout)
        self.layout.addWidget(backup_group)

        # === Синхронизация ПК ↔ планшет по Wi-Fi ===
        sync_group = QGroupBox(_("🔄 Синхронизация ПК ↔ планшет"))
        sync_layout = QVBoxLayout()
        if is_android():
            sync_hint = _("Показать адрес и код для ПК: ПК заберёт расписание, объединит и вернёт (по Wi-Fi).")
            sync_text = _("🔄 Синхронизировать с ПК")
        else:
            sync_hint = _("Забрать расписание с планшета, объединить с этим и вернуть на планшет (по Wi-Fi).")
            sync_text = _("🔄 Синхронизация с планшетом")
        sync_label = QLabel(sync_hint)
        sync_label.setWordWrap(True)
        sync_layout.addWidget(sync_label)
        self.btn_sync = QPushButton(sync_text)
        self.btn_sync.setStyleSheet("padding: 8px; font-weight: bold;")
        self.btn_sync.clicked.connect(self._open_sync)
        sync_layout.addWidget(self.btn_sync)
        sync_group.setLayout(sync_layout)
        self.layout.addWidget(sync_group)

        # === Рабочие тетради (раньше — отдельная вкладка «📚 Тетради») ===
        from ui.workbook_view import WorkbookView

        workbook_group = QGroupBox(_("📚 Рабочие тетради"))
        workbook_layout = QVBoxLayout(workbook_group)
        self.workbook_view = WorkbookView(facade=self.facade, embedded=True)
        workbook_layout.addWidget(self.workbook_view)
        self.workbook_group = workbook_group
        self.layout.addWidget(workbook_group)

        # === Email-уведомления ===
        email_group = QGroupBox(_("📧 Email-уведомления"))
        email_layout = QVBoxLayout()

        email_desc = QLabel(
            _(
                "Настройки SMTP для отправки персональных уведомлений участникам о заданиях.\n"
                "Для Gmail: включите 2FA и создайте «Пароль приложения» в настройках Google-аккаунта."
            )
        )
        bind_style(email_desc, lambda c: f"color: {c.text_secondary}; font-size: 11px;")
        email_desc.setWordWrap(True)
        email_layout.addWidget(email_desc)

        email_form = QFormLayout()

        self.smtp_sender_name = QLineEdit()
        self.smtp_sender_name.setPlaceholderText(_("Имя Фамилия"))
        email_form.addRow(_("Имя отправителя:"), self.smtp_sender_name)

        self.smtp_user = QLineEdit()
        self.smtp_user.setPlaceholderText("name@gmail.com")
        email_form.addRow(_("Email (логин SMTP):"), self.smtp_user)

        self.smtp_password = QLineEdit()
        self.smtp_password.setPlaceholderText(_("Пароль приложения (App Password)"))
        self.smtp_password.setEchoMode(QLineEdit.EchoMode.Password)
        email_form.addRow(_("Пароль приложения:"), self.smtp_password)

        self.smtp_host = QLineEdit()
        self.smtp_host.setPlaceholderText("smtp.gmail.com")
        email_form.addRow(_("SMTP-сервер:"), self.smtp_host)

        self.smtp_port = QLineEdit()
        self.smtp_port.setPlaceholderText("465")
        email_form.addRow(_("SMTP-порт:"), self.smtp_port)

        email_layout.addLayout(email_form)

        email_btn_layout = QHBoxLayout()

        btn_save_smtp = QPushButton(_("💾 Сохранить настройки email"))
        btn_save_smtp.clicked.connect(self._save_smtp_settings)
        btn_save_smtp.setStyleSheet("padding: 6px 12px;")

        btn_test_smtp = QPushButton(_("🔌 Проверить соединение"))
        self.btn_test_smtp = btn_test_smtp
        btn_test_smtp.clicked.connect(self._test_smtp)
        btn_test_smtp.setStyleSheet("padding: 6px 12px;")

        btn_import_emails = QPushButton(_("📋 Импорт email из Excel"))
        btn_import_emails.clicked.connect(self._import_emails)
        btn_import_emails.setStyleSheet("padding: 6px 12px;")
        btn_import_emails.setToolTip(
            _("Импортировать email и телефоны из «Список возвещателей.xlsx»")
        )

        email_btn_layout.addWidget(btn_save_smtp)
        email_btn_layout.addWidget(btn_test_smtp)
        email_btn_layout.addWidget(btn_import_emails)
        email_layout.addLayout(email_btn_layout)

        email_group.setLayout(email_layout)
        self.layout.addWidget(email_group)

        # === Поддержать проект ===
        donate_group = QGroupBox(_("❤️ Поддержать проект"))
        donate_layout = QVBoxLayout()
        donate_label = QLabel(
            _(
                "Cerastilo делает один человек в свободное время, без команды и спонсоров. "
                "Если программа помогает вашему собранию, можно поддержать её развитие."
            )
        )
        donate_label.setWordWrap(True)
        donate_layout.addWidget(donate_label)
        # Кнопки строятся из списка платформ core.donate.PLATFORMS
        self.donate_buttons = []
        several = len(donate.PLATFORMS) > 1
        for platform in donate.PLATFORMS:
            row = QHBoxLayout()
            if several:
                row.addWidget(QLabel(platform.title))
            buttons = []
            if platform.fixed_url is not None:
                buttons.append(
                    (
                        QPushButton(f"☕ {platform.fixed_amount} {platform.currency}"),
                        platform.fixed_link(),
                    )
                )
            buttons.append((QPushButton(_("💝 Своя сумма")), platform.free_url))
            for btn, url in buttons:
                btn.clicked.connect(lambda _checked=False, u=url: self._open_donate(u))
                if not platform.configured:
                    btn.setEnabled(False)
                    btn.setToolTip(_("Ссылка для пожертвований ещё не настроена"))
                self.donate_buttons.append(btn)
                row.addWidget(btn)
            row.addStretch()
            donate_layout.addLayout(row)
        donate_group.setLayout(donate_layout)
        self.layout.addWidget(donate_group)

        self.layout.addStretch()
        self._build_section_nav()

        self._load_settings()

    def _load_settings(self) -> None:
        """Загружает настройки из фасада."""
        self.cong_name.setText(self.facade.get_setting("cong_name", ""))
        self.meeting_day.setText(meeting_day_display(self.facade.get_setting("meeting_day", "")))
        self.meeting_time.setText(self.facade.get_setting("meeting_time", ""))

        gap = self.facade.get_setting("min_assignment_gap", "2")
        self.min_gap.setCurrentIndex(int(gap) - 1 if gap.isdigit() else 1)

        ms_gap = self.facade.get_setting("ms_assignment_gap", "2")
        self.ms_gap.setCurrentIndex(int(ms_gap) - 1 if ms_gap.isdigit() else 1)

        self._load_role_settings()
        self._load_smtp_settings()

    def _load_role_settings(self) -> None:
        """Списки «Обязанностей в собрании»: братья-старейшины, выбранный — по настройке."""
        elders = sorted(
            (
                p
                for p in self.facade.get_all_participants()
                if p.get("gender") == "male" and p.get("service_type") in ("E", "elder")
            ),
            key=lambda p: p.get("name") or "",
        )
        for key, combo in self.role_combos.items():
            current = str(self.facade.get_setting(key, "") or "")
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(_("— не выбран —"), "")
            for p in elders:
                combo.addItem(p.get("name") or "", str(p["id"]))
            index = combo.findData(current)
            if current and index < 0:
                # выбранный брат больше не старейшина или удалён — оставим видимым
                person = self.facade.get_participant(int(current)) if current.isdigit() else None
                combo.addItem((person or {}).get("name") or f"#{current}", current)
                index = combo.count() - 1
            combo.setCurrentIndex(max(index, 0))
            combo.blockSignals(False)

    def _load_smtp_settings(self) -> None:
        """Загружает SMTP-настройки из фасада."""
        self.smtp_sender_name.setText(self.facade.get_setting("smtp_sender_name", ""))
        self.smtp_user.setText(self.facade.get_setting("smtp_user", ""))
        self.smtp_password.setText(self.facade.get_setting("smtp_password", ""))
        self.smtp_host.setText(self.facade.get_setting("smtp_host", "smtp.gmail.com"))
        self.smtp_port.setText(self.facade.get_setting("smtp_port", "465"))

    def _save_settings(self) -> None:
        """Сохраняет настройки через фасад."""
        self.facade.save_setting("cong_name", self.cong_name.text())
        saved_day = self.facade.get_setting("meeting_day", "")
        if self.meeting_day.text() != meeting_day_display(saved_day):
            self.facade.save_setting("meeting_day", self.meeting_day.text())
        self.facade.save_setting("meeting_time", self.meeting_time.text())
        self.facade.save_setting("min_assignment_gap", str(self.min_gap.currentIndex() + 1))
        self.facade.save_setting("ms_assignment_gap", str(self.ms_gap.currentIndex() + 1))
        for key, combo in self.role_combos.items():
            self.facade.save_setting(key, combo.currentData() or "")

        QMessageBox.information(self, _("Успех"), _("Настройки успешно сохранены!"))

    def _import_history(self) -> None:
        """Импортирует историю из CSV-файла NW Scheduler."""
        from core.history_import import import_history_from_csv

        file_path, _ = QFileDialog.getOpenFileName(
            self, tr("Выбрать экспорт NW Scheduler (CSV)"), "", "CSV Files (*.csv)"
        )

        if not file_path:
            return

        result = import_history_from_csv(file_path)

        if result["success"]:
            stats = result["stats"]
            msg = tr(
                "Импорт успешно завершён!\n\n📅 Добавлено недель: {v}\n📝 Импортировано заданий: {v2}\n⚠️ Пропущено (не найдены в базе): {v3}",
                v=stats["weeks"],
                v2=stats["assignments"],
                v3=stats["skipped"],
            )
            QMessageBox.information(self, tr("Успех"), msg)
        else:
            QMessageBox.critical(
                self, tr("Ошибка"), tr("Не удалось выполнить импорт:\n{v}", v=result["error"])
            )

    def _open_sync(self) -> None:
        """Синхронизация: на планшете — сервер с адресом и кодом, на ПК — подключение к нему."""
        from ui.sync_dialog import SyncClientDialog, SyncServerDialog

        dialog_cls = SyncServerDialog if is_android() else SyncClientDialog
        dialog_cls(self.facade, self).exec()

    def _create_backup(self) -> None:
        """Создаёт резервную копию базы данных."""
        from core.backup_logic import create_backup

        default_name = f"NHJS_Backup_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M')}.zip"
        file_path = get_save_file_name(
            self, _("Сохранить бэкап"), default_name, "ZIP Files (*.zip)"
        )

        if file_path:
            res = create_backup(file_path)
            if res["success"]:
                QMessageBox.information(
                    self,
                    _("Успех"),
                    _("Резервная копия создана:\n{file_path}", file_path=file_path),
                )
            else:
                QMessageBox.critical(
                    self, _("Ошибка"), _("Не удалось создать бэкап:\n{v}", v=res["error"])
                )

    def _restore_backup(self) -> None:
        """Восстанавливает базу данных из резервной копии."""
        from core.backup_logic import restore_backup

        reply = QMessageBox.warning(
            self,
            _("Внимание"),
            _("Восстановление заменит ТЕКУЩУЮ базу данных.\nВы уверены?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            file_path = get_open_file_name(self, _("Выбрать файл бэкапа"), "ZIP Files (*.zip)")
        except OSError as e:
            QMessageBox.critical(self, _("Ошибка"), str(e))
            return

        if file_path:
            res = restore_backup(file_path)
            if res["success"]:
                QMessageBox.information(
                    self,
                    _("Успех"),
                    _(
                        "База данных успешно восстановлена!\nПерезагрузите программу для применения изменений."
                    ),
                )
            else:
                QMessageBox.critical(
                    self, _("Ошибка"), _("Не удалось восстановить:\n{v}", v=res["error"])
                )

    def _on_theme_selected(self, _index: int) -> None:
        """Применяет выбранную тему сразу и сохраняет выбор."""
        from PySide6.QtWidgets import QApplication

        value = self.theme_combo.currentData()
        self.facade.save_setting("theme", value)
        theme = get_system_theme() if value == "system" else Theme(value)
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, theme)

    def _on_language_selected(self) -> None:
        """Запомнить язык интерфейса; включится после перезапуска программы."""
        from core.i18n import save_language

        try:
            save_language(self.language_combo.currentData())
        except OSError as e:
            QMessageBox.warning(self, _("Ошибка"), _("Не удалось сохранить язык: {e}", e=e))
            return
        # на обоих языках: текущий интерфейс ещё на старом
        QMessageBox.information(
            self,
            "Язык / Language",
            "Язык изменится после перезапуска программы.\n"  # i18n: не переводить (на двух языках)
            "The language will change after you restart the app.",
        )

    def _on_module_toggled(self, module_id: str, checked: bool) -> None:
        """Обрабатывает переключение модуля.

        Args:
            module_id: Идентификатор модуля.
            checked: Включён или выключен.
        """
        self.facade.save_setting(f"module_{module_id}", "true" if checked else "false")

    def _open_donate(self, url: str) -> None:
        """Открыть ссылку для пожертвования в браузере."""
        QDesktopServices.openUrl(QUrl(url))

    def _build_section_nav(self) -> None:
        """Оглавление: по одному пункту на каждую группу настроек (заголовок группы)."""
        self._sections = []
        for i in range(self.layout.count()):
            widget = self.layout.itemAt(i).widget()
            if isinstance(widget, QGroupBox):
                self._sections.append(widget)
                self.section_nav.addItem(widget.title())

    def show_workbooks(self) -> None:
        """Перейти к разделу «📚 Рабочие тетради»."""
        if self.workbook_group in self._sections:
            self.section_nav.setCurrentRow(self._sections.index(self.workbook_group))

    def _go_to_section(self, row: int) -> None:
        if 0 <= row < len(self._sections):
            group = self._sections[row]
            self.scroll.verticalScrollBar().setValue(group.y())

    def _save_smtp_settings(self, quiet: bool = False) -> None:
        """Сохраняет SMTP-настройки email-уведомлений."""
        self.facade.save_setting("smtp_sender_name", self.smtp_sender_name.text().strip())
        self.facade.save_setting("smtp_user", self.smtp_user.text().strip())
        self.facade.save_setting("smtp_password", self.smtp_password.text())
        self.facade.save_setting("smtp_host", self.smtp_host.text().strip() or "smtp.gmail.com")
        self.facade.save_setting("smtp_port", self.smtp_port.text().strip() or "465")
        if not quiet:
            QMessageBox.information(self, _("Успех"), _("Настройки email сохранены!"))

    def _test_smtp(self) -> None:
        """Проверяет SMTP-соединение с текущими настройками — в фоне, чтобы окно
        не зависало, пока сервер не отвечает (до таймаута в NotificationService)."""
        from core.workers import TaskWorker

        if getattr(self, "_smtp_worker", None) and self._smtp_worker.isRunning():
            return
        # Сначала сохраняем (без отдельного окна «сохранено»), потом проверяем
        self._save_smtp_settings(quiet=True)
        self.btn_test_smtp.setEnabled(False)
        self.btn_test_smtp.setText(_("⏳ Проверяю…"))
        self._smtp_worker = TaskWorker(self.facade.test_smtp_connection)
        self._smtp_worker.finished.connect(self._on_test_smtp_finished)
        self._smtp_worker.start()

    def _on_test_smtp_finished(self, result: dict) -> None:
        self.btn_test_smtp.setEnabled(True)
        self.btn_test_smtp.setText(_("🔌 Проверить соединение"))
        if not result.get("success"):
            QMessageBox.critical(
                self, _("Ошибка"), str(result.get("error") or _("Неизвестная ошибка"))
            )
            return
        ok, msg = result.get("data") or (False, _("Неизвестная ошибка"))
        if ok:
            QMessageBox.information(self, _("✅ Соединение"), msg)
        else:
            QMessageBox.warning(self, _("❌ Ошибка"), msg)

    def _import_emails(self) -> None:
        """Импортирует email и телефоны из Excel-файла в БД."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Выбрать файл со списком возвещателей"),
            "",
            "Excel Files (*.xlsx *.xls)",
        )
        if not file_path:
            return

        result = self.facade.import_emails_from_xlsx(file_path)

        if not result.get("success"):
            QMessageBox.critical(
                self, tr("Ошибка"), tr("Не удалось импортировать:\n{v}", v=result.get("error"))
            )
            return

        s = result["stats"]
        msg = tr(
            "Импорт завершён!\n\n✅ Обновлено участников: {v}\n⚠️  Без email в файле: {v2}\n❓ Не найдены в БД: {v3}\n❓ Нет в файле: {v4}",
            v=s["updated"],
            v2=s["no_email"],
            v3=s["not_found_in_db"],
            v4=s["not_found_in_xlsx"],
        )
        QMessageBox.information(self, tr("Успех"), msg)
