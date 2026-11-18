"""Уведомления участников: ответы, рассылка, журнал, письмо.

Вынесено из ui/schedule_view.py; ScheduleView наследует этот класс."""

from typing import List

from PySide6.QtWidgets import QMessageBox

from core.workers import TaskWorker
from ui.toast import ToastNotification
from core.i18n import _


class ScheduleNotifyMixin:
    """Уведомления участников: ответы, рассылка, журнал, письмо."""

    def _not_notified_ids(self, assignments) -> List[int]:
        """Участники недели (и напарники), кому письмо ещё не ушло успешно."""
        statuses = getattr(self, "current_notif_statuses", {}) or {}
        ids = []
        for a in assignments:
            if a.get("status") != "assigned":
                continue
            for pid in (a.get("participant_id"), a.get("assistant_id")):
                if pid and pid not in ids and (statuses.get(pid) or {}).get("status") != "success":
                    ids.append(pid)
        return ids

    def _response_counts(self, assignments):
        """(кто уведомлён, но не ответил; кто ответил «не смогу») — имена."""
        statuses = getattr(self, "current_notif_statuses", {}) or {}
        waiting, declined, seen = [], [], set()
        for a in assignments:
            if a.get("status") != "assigned":
                continue
            for pid, name in (
                (a.get("participant_id"), a.get("participant_name")),
                (a.get("assistant_id"), a.get("assistant_name")),
            ):
                if not pid or pid in seen:
                    continue
                seen.add(pid)
                info = statuses.get(pid) or {}
                if info.get("response") == "declined":
                    declined.append(name or "")
                elif info.get("status") == "success" and not info.get("response"):
                    waiting.append(name or "")
        return waiting, declined

    def _check_replies(self) -> None:
        """Прочитать ответы на уведомления из почты (в фоне)."""
        worker = TaskWorker(
            self.facade.check_notification_replies, error_service=self.facade.errors
        )
        worker.finished.connect(self._on_check_replies_finished)
        self.active_workers.append(worker)
        worker.start()

    def _on_check_replies_finished(self, result):
        self._clean_worker()
        result = result or {}
        if not result.get("success"):
            QMessageBox.warning(
                self,
                _("Ответы на уведомления"),
                _(
                    "Не удалось прочитать почту:\n{v}",
                    v=result.get("error") or _("Неизвестная ошибка"),
                ),
            )
            return
        text = _("📥 Новых ответов: {v}", v=result.get("applied", 0))
        if result.get("unclear"):
            text += _(", непонятных: {v} — посмотрите в почте", v=result["unclear"])
        ToastNotification.show_toast(
            self, text, success=bool(result.get("applied")), duration_ms=5000
        )

    def _notify_participants(self, participant_ids: List[int]) -> None:
        from ui.notification_dialog import NotificationDialog

        if not self.current_week_id:
            return
        NotificationDialog(
            self.facade,
            [self.current_week_id],
            parent=self,
            only_participant_ids=participant_ids,
        ).exec()
        self._load_week_editor(self.current_week_id)

    def _on_notify(self):
        """Открывает диалог отправки email-уведомлений участникам."""
        from ui.export_dialog import ExportDialog
        from ui.notification_dialog import NotificationDialog

        select_dialog = ExportDialog(
            self._weeks_list_for_dialog(),
            self,
            default_week_id=self.current_week_id,
            confirm_text=_("Далее →"),
        )
        select_dialog.setWindowTitle(_("Выберите недели для уведомлений"))
        if not select_dialog.exec():
            return

        selected_ids = select_dialog.get_selected_week_ids()
        if not selected_ids:
            return

        dialog = NotificationDialog(self.facade, selected_ids, parent=self)
        dialog.exec()
        if self.current_week_id:
            self._load_week_editor(self.current_week_id)

    def _open_notification_log(self, participant_id=None):
        """Открывает диалог журнала отправки уведомлений."""
        from ui.notification_log_dialog import NotificationLogDialog

        dialog = NotificationLogDialog(
            self.facade,
            parent=self,
            initial_participant_id=participant_id,
            initial_week_id=None,
        )
        dialog.exec()
        if self.current_week_id:
            self._load_week_editor(self.current_week_id)

    def _open_participant_email(self, participant_id: int, participant_name: str):
        """Открывает диалог предпросмотра/редактирования и отправки email для одного участника."""
        from ui.email_preview_dialog import EmailPreviewEditDialog

        if not self.current_week_id:
            return

        # Берём email участника
        p = self.facade.get_participant(participant_id)
        email = None
        if p and isinstance(p, dict):
            email = p.get("email")
        elif p:
            email = getattr(p, "email", None)

        # Находим недели с назначениями для этого участника
        # (текущая неделя и ближайшие будущие с назначениями, до 4 недель)
        week_ids = self.facade.get_participant_assignment_week_ids(
            participant_id,
            current_week_id=self.current_week_id,
            limit=4,
        )
        if not week_ids:
            week_ids = [self.current_week_id]

        dialog = EmailPreviewEditDialog(
            facade=self.facade,
            participant_id=participant_id,
            participant_name=participant_name,
            participant_email=email,
            week_ids=week_ids,
            allow_send_now=True,
            parent=self,
        )
        if dialog.exec():
            # Обновляем ячейки недели (статусы, значки конвертов)
            self._load_week_editor(self.current_week_id)
