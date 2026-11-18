"""Экспорт, печать, S-89 и «Будущий год» вкладки «Расписание».

Вынесено из ui/schedule_view.py; ScheduleView наследует этот класс."""

from datetime import datetime

from PySide6.QtWidgets import QDialog, QMessageBox

from ui.file_dialogs import get_save_file_name, saved_message
from core.workers import TaskWorker
from ui.toast import ToastNotification
from core.i18n import _


class ScheduleExportMixin:
    """Экспорт, печать, S-89 и «Будущий год» вкладки «Расписание»."""

    def _weeks_list_for_dialog(self):
        weeks_list = []
        for year, months in self.facade.get_weeks_tree().items():
            for month_name, weeks in months.items():
                weeks_list.append({"month": f"{_(month_name)} {year}", "weeks": weeks})
        return weeks_list

    @staticmethod
    def _can_print() -> bool:
        """На Android печать из Qt не работает (нет системного диалога) — там PDF."""
        from core.utils.android_storage import is_android

        return not is_android()

    def _on_print(self) -> None:
        """Выбрать недели (как для PDF) и напечатать: две недели на лист."""
        if not self._can_print():
            return
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter

        from core.export.qt_pdf import setup_printer
        from ui.export_dialog import ExportDialog

        dialog = ExportDialog(
            self._weeks_list_for_dialog(),
            self,
            default_week_id=self.current_week_id,
            formats=("pdf",),
        )
        dialog.setWindowTitle(_("Печать расписания"))
        if not dialog.exec():
            return
        week_ids = dialog.get_selected_week_ids()
        if not week_ids:
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        setup_printer(printer)
        if QPrintDialog(printer, self).exec() != QDialog.DialogCode.Accepted:
            return
        if self.facade.print_schedule(week_ids, printer):
            ToastNotification.show_toast(self, _("🖨️ Отправлено на печать"))
        else:
            QMessageBox.warning(
                self, _("Печать"), _("Не удалось напечатать расписание. Проверьте принтер.")
            )

    def _on_export(self, fmt="pdf"):
        from ui.export_dialog import ExportDialog

        dialog = ExportDialog(
            self._weeks_list_for_dialog(),
            self,
            default_week_id=self.current_week_id,
            formats=(fmt,),
        )
        if dialog.exec():
            selected_ids = dialog.get_selected_week_ids()
            if not selected_ids:
                return

            fmt = dialog.get_selected_format()  # 'docx', 'pdf', or 'txt'

            # --- Имя файла по умолчанию: месяц, название встречи, дата экспорта ---
            from core.export.filename import schedule_base_name

            min_date, max_date = self.facade.get_weeks_date_range(selected_ids)
            base_name = schedule_base_name(min_date, max_date)

            # Выбор фильтра и метода экспорта
            if fmt == "txt":
                file_filter = _("Текстовый файл (*.txt)")
                default_filename = f"{base_name}.txt"
                export_fn = self.facade.export_to_txt
                fn_args = (selected_ids,)
                fn_kwargs = {}
            elif fmt == "pdf":
                file_filter = _("PDF документ (*.pdf)")
                default_filename = f"{base_name}.pdf"
                export_fn = self.facade.export_to_pdf
                fn_args = (selected_ids,)
                fn_kwargs = {}
            else:  # docx
                file_filter = "Word (*.docx)"
                default_filename = f"{base_name}.docx"
                export_fn = self.facade.export_custom_docx
                fn_args = (selected_ids,)
                fn_kwargs = {"mode": dialog.get_export_mode()}

            file_path = get_save_file_name(self, _("Сохранить"), default_filename, file_filter)
            if file_path:
                self._export_path = file_path
                worker = TaskWorker(
                    export_fn,
                    *fn_args,
                    file_path,
                    **fn_kwargs,
                    error_service=self.facade.errors,
                )
                worker.finished.connect(self._on_export_finished)
                self.active_workers.append(worker)
                worker.start()

    def _on_export_finished(self, result):
        self._clean_worker()
        if result and result.get("success"):
            QMessageBox.information(
                # показываем путь, который вернул экспорт
                self,
                _("Успех"),
                saved_message(
                    result.get("path") or getattr(self, "_export_path", ""), _("Файл сохранен!")
                ),
            )

    def _on_export_s89(self):
        from ui.export_dialog import ExportDialog

        dialog = ExportDialog(
            self._weeks_list_for_dialog(),
            self,
            default_week_id=self.current_week_id,
            confirm_text=_("🎟️ Сформировать S-89"),
        )
        dialog.setWindowTitle(_("Советы S-89 — выбор недель"))
        if dialog.exec():
            self._export_s89_for_weeks(dialog.get_selected_week_ids())

    def _export_s89_for_weeks(self, selected_ids):
        """Сохраняет бланки S-89 для указанных недель (диалог сохранения + фоновая задача)."""
        if not selected_ids:
            return

        min_date, max_date = self.facade.get_weeks_date_range(selected_ids)
        default_filename = "S-89.docx"
        if min_date and max_date:
            try:
                if isinstance(min_date, str):
                    min_date = datetime.fromisoformat(min_date)
                if isinstance(max_date, str):
                    max_date = datetime.fromisoformat(max_date)
                default_filename = (
                    f"S-89_{min_date.strftime('%d.%m')}-{max_date.strftime('%d.%m')}.docx"
                )
            except Exception:
                pass

        file_path = get_save_file_name(self, _("Сохранить S-89"), default_filename, "Word (*.docx)")
        if file_path:
            self._export_path = file_path
            worker = TaskWorker(
                self.facade.export_to_s89,
                selected_ids,
                file_path,
                error_service=self.facade.errors,
            )
            worker.finished.connect(self._on_export_s89_finished)
            self.active_workers.append(worker)
            worker.start()

    def _on_export_s89_finished(self, result):
        self._clean_worker()
        if result and result.get("success"):
            QMessageBox.information(
                self,
                _("Успех"),
                saved_message(getattr(self, "_export_path", ""), _("S-89 сформирован!")),
            )

    def _on_add_future_year(self):
        # Год и число недостающих недель считает ядро: первый неполный год
        # после текущего (например, из тетради есть только январь–февраль),
        # иначе — год после последнего
        plan = self.facade.plan_future_year()
        next_year = plan["year"]
        missing = plan["missing"]

        reply = QMessageBox.question(
            self,
            _("Подтверждение"),
            _(
                "Создать пустые недели на {next_year} год ({missing})?\nУже существующие недели не изменятся.",
                next_year=next_year,
                missing=missing,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            worker = TaskWorker(
                self.facade.prepare_future_year, next_year, error_service=self.facade.errors
            )
            worker.finished.connect(self._on_prepare_year_finished)
            self.active_workers.append(worker)
            worker.start()

    def _on_prepare_year_finished(self, result):
        self._clean_worker()
        if result.get("success"):
            year = result.get("year")
            created = result.get("created", 0)
            QMessageBox.information(
                self,
                _("Готово"),
                _("{year} год: добавлено пустых недель — {created}.", year=year, created=created),
            )
            self._load_tree()
