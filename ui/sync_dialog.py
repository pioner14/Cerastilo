"""
Синхронизация ПК ↔ планшет по Wi-Fi.

Сервер — на планшете: входящие соединения к ПК закрывает брандмауэр
(ufw, firewalld, Защитник Windows), а исходящие с ПК он пропускает.

SyncServerDialog (на планшете) запускает сервер и показывает адрес и код.
SyncClientDialog (на ПК) забирает базу планшета, объединяет её со своей
и отправляет результат обратно; планшет заменяет свою базу и закрывается.
"""

import threading

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from core.styles import palette
from core.sync_code_store import load_sync_code, save_sync_code
from core.sync_service import (
    DEFAULT_PORT,
    SyncClientError,
    SyncPushError,
    SyncServer,
    SyncServerBusyError,
    format_sync_code,
    generate_sync_code,
    get_local_ip,
    replace_database,
    sync_success_message,
    sync_with_tablet,
)
from core.i18n import _

# Сколько поток сервера ждёт замены базы в главном потоке
REPLACE_TIMEOUT_S = 60


class SyncStatusSignaler(QObject):
    """Переносит статусы HTTP-сервера в главный поток Qt."""

    status_changed = Signal(str)
    server_stopped = Signal()
    # (данные, threading.Event, dict для ошибки) — замена базы в главном потоке
    replace_requested = Signal(object, object, object)


def _plain(label: QLabel) -> QLabel:
    # QLabel наследует правило QFrame из темы (рамка и фон) — здесь рамки лишние
    label.setStyleSheet("border: none; background: transparent;")
    return label


class SyncServerDialog(QDialog):
    """Окно на планшете: сервер синхронизации, адрес и код для ПК."""

    def __init__(self, facade, parent=None):
        super().__init__(parent)
        self.facade = facade
        self.server_thread = None
        self.sync_server = None
        self._closing = False
        self._rotating = False
        self.db_path = self.facade.schedule.db.db_path
        self.code = load_sync_code(self.db_path)
        if not self.code:
            self.code = generate_sync_code()
            save_sync_code(self.db_path, self.code)
        self.local_ip = get_local_ip()

        self.signaler = SyncStatusSignaler()
        self.signaler.status_changed.connect(self.update_status_label)
        self.signaler.server_stopped.connect(self._restart_server)
        self.signaler.replace_requested.connect(self._replace_in_main_thread)

        self.setup_ui()
        self.start_server()

    def setup_ui(self):
        self.setWindowTitle(_("Синхронизация с ПК"))
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 24, 24, 24)

        title = _plain(QLabel(_("🔄 Синхронизация по Wi-Fi")))
        title.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {palette().text_heading}; "
            f"border: none; background: transparent;"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        hint = _plain(
            QLabel(
                _(
                    "На ПК откройте «Настройки» → «Синхронизация с планшетом» и введите "
                    "адрес и код. ПК и планшет должны быть в одной сети Wi-Fi."
                )
            )
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # Порт постоянный — ПК подставляет его сам, показываем только адрес
        self.address_label = QLabel(
            self.local_ip
            if not self.local_ip.startswith("127.")
            else _("не определён — проверьте Wi-Fi")
        )
        self._display_address = self.address_label.text()
        self.code_label = QLabel(format_sync_code(self.code))
        for label in (self.address_label, self.code_label):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setStyleSheet(
                f"font-size: 26px; font-weight: bold; letter-spacing: 2px; "
                f"color: {palette().text_primary}; padding: 6px;"
            )
        form = QFormLayout()
        form.addRow(_plain(QLabel(_("Адрес:"))), self.address_label)
        form.addRow(_plain(QLabel(_("Код:"))), self.code_label)
        layout.addLayout(form)

        self.status_label = QLabel(_("Ожидание ПК…"))
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet(
            f"font-size: 12px; color: {palette().text_warning}; font-weight: bold; padding: 10px; "
            f"background-color: {palette().warning_background}; border-radius: 4px;"
        )
        layout.addWidget(self.status_label)

        btn_layout = QHBoxLayout()
        btn_close = QPushButton(_("Закрыть"))
        btn_close.clicked.connect(self.reject)
        btn_layout.addStretch()
        self.btn_new_code = QPushButton(_("Новый код"))
        self.btn_new_code.clicked.connect(self._new_code)
        btn_layout.addWidget(self.btn_new_code)
        btn_layout.addWidget(btn_close)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def _new_code(self):
        new_code = generate_sync_code()
        # Не сохранили — при следующем открытии окна вернулся бы старый код
        if not save_sync_code(self.db_path, new_code):
            self.status_label.setText(_("Не удалось сохранить новый код. Код не изменён."))
            return
        self._rotating = True
        self.btn_new_code.setEnabled(False)
        self.code = new_code
        server, self.sync_server = self.sync_server, None
        if server is None:
            self._restart_server()
            return

        def stop_server():
            server.stop()
            self.signaler.server_stopped.emit()

        threading.Thread(target=stop_server, daemon=True).start()

    def _restart_server(self):
        if self._closing:
            return
        self._rotating = False
        self.btn_new_code.setEnabled(True)
        self.start_server()

    def start_server(self):
        self.address_label.setText(self._display_address)
        self.code_label.setText(format_sync_code(self.code))
        self.status_label.setText(_("Ожидание ПК…"))
        self.sync_server = SyncServer(
            db_path=self.db_path,
            auth_token=self.code,
            port=DEFAULT_PORT,
            on_status_change=self.signaler.status_changed.emit,
            accept_database=self._accept_from_server_thread,
        )
        try:
            self.sync_server.bind()
        except SyncServerBusyError as e:
            self.sync_server = None
            self._show_error(e.strerror)
            return
        except OSError as e:
            self.sync_server = None
            self._show_error(
                _("Не удалось запустить сервер на порту {port}: {e}", port=DEFAULT_PORT, e=e)
            )
            return
        self.server_thread = threading.Thread(target=self.sync_server.start, daemon=True)
        self.server_thread.start()

    def _show_error(self, message: str):
        self.address_label.setText("—")
        self.code_label.setText("—")
        self.status_label.setText(message)

    def _accept_from_server_thread(self, data: bytes) -> None:
        """Вызывается в потоке сервера: просит главный поток заменить базу и ждёт."""
        done, box = threading.Event(), {}
        self.signaler.replace_requested.emit(data, done, box)
        if not done.wait(REPLACE_TIMEOUT_S):
            raise RuntimeError("database replacement timed out")
        if "error" in box:
            raise box["error"]

    def _replace_in_main_thread(self, data, done, box):
        try:
            if self._closing or self._rotating:
                raise RuntimeError(_("Окно синхронизации закрывается или меняется код"))
            db = self.facade.schedule.db
            db.close()
            replace_database(db.db_path, data)
            self.btn_new_code.setEnabled(False)
        except Exception as e:  # noqa: BLE001 — ответ уйдёт ПК как ошибка 500
            box["error"] = e
        finally:
            done.set()

    def update_status_label(self, status):
        if self._rotating or self._closing:
            return
        self.status_label.setText(status)
        if status == sync_success_message():
            self._closing = True
            QMessageBox.information(
                self,
                _("Готово"),
                _(
                    "Синхронизация завершена. Приложение закроется — откройте его снова, "
                    "чтобы увидеть объединённое расписание."
                ),
            )
            self.accept()
            QApplication.quit()

    def done(self, result):
        # «Назад» на Android идёт через reject() мимо closeEvent — сервер
        # останавливаем здесь, иначе он остался бы жить со старым кодом.
        # Не ждём: обработчик может ждать главный поток.
        self._closing = True
        if self.sync_server:
            self.sync_server.stop(wait=False)
            self.sync_server = None
        super().done(result)


class _SyncWorker(QThread):
    finished_ok = Signal()
    failed = Signal(str, bool)  # текст, база ПК уже объединена

    def __init__(self, address, code, db_path):
        super().__init__()
        self.address, self.code, self.db_path = address, code, db_path

    def run(self):
        try:
            sync_with_tablet(self.address, self.code, self.db_path)
            save_sync_code(self.db_path, self.code)
            self.finished_ok.emit()
        except SyncPushError as e:
            self.failed.emit(str(e), True)
        except SyncClientError as e:
            self.failed.emit(str(e), False)
        except Exception as e:  # noqa: BLE001 — пользователю нужен ответ, а не тишина
            self.failed.emit(_("Ошибка синхронизации: {e}", e=e), False)


class SyncClientDialog(QDialog):
    """Окно на ПК: подключиться к планшету и синхронизировать базы."""

    def __init__(self, facade, parent=None):
        super().__init__(parent)
        self.facade = facade
        self.worker = None
        self.setWindowTitle(_("Синхронизация с планшетом"))
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        hint = _plain(
            QLabel(
                _(
                    "На планшете откройте «Настройки» → «Синхронизировать с ПК» и введите "
                    "адрес и код из открывшегося окна. ПК и планшет должны быть в одной сети Wi-Fi."
                )
            )
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        self.address_edit = QLineEdit(facade.get_setting("sync_last_address", "") or "")
        self.address_edit.setPlaceholderText("192.168.1.20")
        self.code_edit = QLineEdit(format_sync_code(load_sync_code(facade.schedule.db.db_path)))
        self.code_edit.setMaxLength(32)
        self.code_edit.setPlaceholderText(_("ABCD-EFGH-JKMN"))
        # Без минимальной высоты Hyprland сжимает окно, и поля обрезают текст
        for edit in (self.address_edit, self.code_edit):
            edit.setMinimumHeight(36)
            edit.setStyleSheet("font-size: 16px;")
        form.addRow(_plain(QLabel(_("Адрес планшета:"))), self.address_edit)
        form.addRow(_plain(QLabel(_("Код:"))), self.code_edit)
        layout.addLayout(form)

        self.status_label = _plain(QLabel(""))
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status_label)

        btn_layout = QHBoxLayout()
        self.btn_sync = QPushButton(_("🔄 Синхронизировать"))
        self.btn_sync.clicked.connect(self._start_sync)
        self.code_edit.returnPressed.connect(self._start_sync)
        self.btn_cancel = btn_cancel = QPushButton(_("Закрыть"))
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_sync)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
        self.setMinimumHeight(self.sizeHint().height())

    def _start_sync(self):
        if self.worker and self.worker.isRunning():
            return
        address = self.address_edit.text().strip()
        code = self.code_edit.text().strip()
        if not address or not code:
            self.status_label.setText(_("Введите адрес планшета и код."))
            return
        self.facade.save_setting("sync_last_address", address)
        self.btn_sync.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.status_label.setText(_("Забираю базу с планшета и объединяю…"))
        self.worker = _SyncWorker(address, code, self.facade.schedule.db.db_path)
        self.worker.finished_ok.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_failed(self, message, pc_merged):
        self.btn_sync.setEnabled(True)
        self.btn_cancel.setEnabled(True)
        self.status_label.setText(message)
        if pc_merged:
            self._reload_views()

    def _on_done(self):
        self.status_label.setText(sync_success_message())
        self._reload_views()
        QMessageBox.information(self, _("Готово"), _("Синхронизация с планшетом завершена."))
        self.accept()

    def _reload_views(self):
        """База на ПК объединена с планшетной — перечитать расписание без перезапуска."""
        from core.events import Event

        events = getattr(self.facade, "events", None)
        if events is None:
            return
        events.emit(Event.SCHEDULE_IMPORTED)
        events.emit(Event.ASSIGNMENT_CHANGED)

    def reject(self):
        # Пока идёт синхронизация, окно не закрываем: поток пишет в базу ПК
        if self.worker and self.worker.isRunning():
            return
        super().reject()
