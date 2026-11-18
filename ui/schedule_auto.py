"""«Авто» недели и месяца, снимок базы и откат ↶.

Вынесено из ui/schedule_view.py; ScheduleView наследует этот класс."""

from datetime import datetime

from PySide6.QtWidgets import QMessageBox

from core.db_snapshot import restore_snapshot, take_snapshot
from core.events import Event
from core.workers import TaskWorker
from ui.toast import ToastNotification
from core.i18n import _


class ScheduleAutoMixin:
    """«Авто» недели и месяца, снимок базы и откат ↶."""

    def _on_auto_assign(self):
        if self._month_mode():
            self._on_auto_assign_month()
            return
        week_id = self.current_week_id
        if not week_id:
            QMessageBox.warning(self, _("Внимание"), _("Неделя не выбрана"))
            return

        reply = QMessageBox.question(
            self,
            _("Авто-распределение"),
            _(
                "Заполнить пустые пункты недели автоматически?\n\nУже назначенные останутся на своих местах."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self._record_undo_state()
            worker = TaskWorker(
                self.facade.auto_assign_week, week_id, error_service=self.facade.errors
            )
            worker.finished.connect(self._on_auto_assign_finished)
            self.active_workers.append(worker)
            worker.start()

    def _on_auto_assign_finished(self, result):
        self._clean_worker()
        if result and result.get("success"):
            count = result.get("count", 0)
            # Тост успеха
            msg = (
                _("✅ Распределено: {count} назначений", count=count)
                if count > 0
                else _("ℹ️ Все задания уже заполнены")
            )
            ToastNotification.show_toast(self, msg, success=(count > 0))
            # Строка статуса остаётся как резервный индикатор
            sb = self.statusBar()
            if sb:
                sb.showMessage(_("Авто-назначение: {count} заданий", count=count), 5000)
            self._load_week_editor(self.current_week_id)
        else:
            err = (
                result.get("error", _("Неизвестная ошибка")) if result else _("Неизвестная ошибка")
            )
            ToastNotification.show_toast(
                self, _("❌ Ошибка: {err}", err=err), success=False, duration_ms=5000
            )
            QMessageBox.warning(
                self, _("Ошибка"), _("Не удалось распределить задания:\n{err}", err=err)
            )

    def _on_auto_assign_month(self):
        """Авто-распределение месяца: заполняются только пустые пункты всех
        недель месяца (и после форс-мажоров тоже), назначенные и особые недели
        не трогаются, алгоритм тот же."""
        if self._month_busy:
            return
        week_ids = self.month_board.weeks_with_gaps()
        if not week_ids:
            ToastNotification.show_toast(self, _("ℹ️ Пустых пунктов в месяце нет"), success=False)
            return
        titles = [c["title"] for c in self.month_board.board["columns"] if c["week_id"] in week_ids]
        reply = QMessageBox.question(
            self,
            _("Авто-распределение месяца"),
            _(
                "Заполнить пустые пункты на неделях ({n_week_ids}): {v}?\n\nУже назначенные останутся на своих местах.",
                n_week_ids=len(week_ids),
                v=", ".join(titles),
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            path = take_snapshot(self.facade.schedule.db.db_path, "month-auto")
        except Exception as e:  # без снимка откатить будет нечем — не начинаем
            QMessageBox.warning(
                self,
                _("Ошибка"),
                _("Не удалось сохранить снимок базы, распределение отменено:\n{e}", e=e),
            )
            return
        self._month_snapshot = (path, datetime.now().strftime("%H:%M"))
        # правки до распределения откатываются вместе с ним — снимком
        self.month_board.clear_history()
        self._set_month_busy(True)
        worker = TaskWorker(
            self.facade.auto_assign_weeks, week_ids, error_service=self.facade.errors
        )
        worker.finished.connect(self._on_auto_assign_month_finished)
        self.active_workers.append(worker)
        worker.start()

    def _set_month_busy(self, busy: bool) -> None:
        """Пока распределение идёт в фоне, откат к снимку и повторный запуск
        испортили бы базу и снимок — блокируем их и правки на доске."""
        self._month_busy = busy
        self.btn_auto.setEnabled(not busy)
        self.month_board.setEnabled(not busy)
        self._update_month_undo()

    def _on_auto_assign_month_finished(self, result):
        self._clean_worker()
        self._set_month_busy(False)
        result = result or {}
        if result.get("success"):
            ToastNotification.show_toast(
                self,
                _(
                    "✅ Распределено недель: {v}, назначений: {v2}",
                    v=result.get("weeks", 0),
                    v2=result.get("count", 0),
                ),
            )
        else:
            err = result.get("error") or _("Неизвестная ошибка")
            QMessageBox.warning(
                self,
                _("Ошибка"),
                _(
                    "Распределено недель: {v}, дальше ошибка:\n{err}",
                    v=result.get("weeks", 0),
                    err=err,
                ),
            )
        self.month_board.refresh()

    def _update_month_undo(self) -> None:
        board = self.month_board
        self.btn_undo.setEnabled(
            (board.can_undo() or self._month_snapshot is not None) and not self._month_busy
        )
        self.btn_redo.setEnabled(board.can_redo() and not self._month_busy)
        self.btn_undo.setToolTip(
            _("Идёт распределение месяца…")
            if self._month_busy
            else (
                _("Отменить последнюю правку на доске (Ctrl+Z)")
                if board.can_undo()
                else (
                    _("Отменить распределение месяца (снимок от {v})", v=self._month_snapshot[1])
                    if self._month_snapshot
                    else _("Нечего отменять")
                )
            )
        )
        self.btn_redo.setToolTip(_("Повторить отменённую правку на доске (Ctrl+Y)"))

    def _undo_month(self):
        """↶ в месяце: сначала правки на доске (по одной), затем — откат базы
        к снимку перед последним «Авто-распределить месяц»."""
        if self._month_busy:
            return
        if self.month_board.can_undo():
            self.month_board.undo()
            return
        if not self._month_snapshot:
            return
        path, when = self._month_snapshot
        reply = QMessageBox.question(
            self,
            _("Отменить распределение месяца"),
            _(
                "Вернуть расписание к состоянию на {when}, до авто-распределения месяца?\n\nВсе изменения, сделанные после этого, тоже пропадут.",
                when=when,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            restore_snapshot(self.facade.schedule.db, path)
        except Exception as e:
            QMessageBox.warning(self, _("Ошибка"), _("Не удалось вернуть снимок:\n{e}", e=e))
            return
        self._month_snapshot = None
        self.month_board.clear_history()
        self._undo_stack.clear()  # недельная история относится к другой базе
        self._redo_stack.clear()
        self._update_month_undo()
        # база заменена целиком: перечитать доску и открытую неделю
        self.facade.events.emit(Event.ASSIGNMENT_CHANGED)
        ToastNotification.show_toast(self, _("↶ Распределение месяца отменено"))
