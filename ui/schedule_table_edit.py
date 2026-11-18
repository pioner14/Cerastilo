"""Правка таблицы недели: клавиши, меню, ручные пункты, очистка.

Вынесено из ui/schedule_view.py; ScheduleView наследует этот класс."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMenu, QMessageBox

from ui.schedule_widgets import ManualAssignmentDialog
from ui.toast import ToastNotification
from core.i18n import _


class ScheduleTableEditMixin:
    """Правка таблицы недели: клавиши, меню, ручные пункты, очистка."""

    def _on_assignment_rows_reordered(self, ordered_ids):
        self._record_undo_state()
        if self.facade.reorder_week_assignments(self.current_week_id, ordered_ids):
            sb = self.statusBar()
            if sb:
                sb.showMessage(_("Порядок пунктов сохранён"), 2000)
        else:
            QMessageBox.warning(self, _("Ошибка"), _("Не удалось сохранить порядок пунктов"))
            self._load_week_editor(self.current_week_id)

    def _selected_table_assignment(self):
        indexes = self.assignment_table.selectionModel().selectedIndexes()
        if not indexes:
            return None
        index = indexes[0]
        section_item = self.assignment_table.item(index.row(), 0)
        if not section_item:
            return None
        assignment_id = section_item.data(Qt.ItemDataRole.UserRole)
        return (
            index.row(),
            index.column(),
            assignment_id,
            self._table_assignments.get(assignment_id),
        )

    def _on_table_enter(self):
        if not self.assignment_table.hasFocus():
            return
        selected = self._selected_table_assignment()
        if not selected:
            return
        row, column, assignment_id, assignment = selected
        if column in (5, 6):
            cell = self.assignment_table.cellWidget(row, column)
            if cell:
                cell.click()
        elif assignment and assignment.get("assignment_type") == "custom":
            self._on_edit_manual_item(assignment_id)

    def _on_table_delete(self):
        if not self.assignment_table.hasFocus():
            return
        selected = self._selected_table_assignment()
        if selected and selected[3] and selected[3].get("assignment_type") == "custom":
            self._on_delete_manual_item(selected[2])

    def _on_table_edit(self):
        if not self.assignment_table.hasFocus():
            return
        selected = self._selected_table_assignment()
        if selected and selected[3] and selected[3].get("assignment_type") == "custom":
            self._on_edit_manual_item(selected[2])

    def _on_table_context_menu(self, position):
        index = self.assignment_table.indexAt(position)
        if not index.isValid():
            return
        row = index.row()
        section_item = self.assignment_table.item(row, 0)
        assignment_id = section_item.data(Qt.ItemDataRole.UserRole) if section_item else None
        assignment = self._table_assignments.get(assignment_id)
        if not assignment or assignment.get("assignment_type") != "custom":
            return

        menu = QMenu(self.assignment_table)
        edit_action = menu.addAction(_("Изменить"))
        duplicate_action = menu.addAction(_("Дублировать"))
        menu.addSeparator()
        delete_action = menu.addAction(_("Удалить"))
        menu.triggered.connect(
            lambda action: self._handle_table_context_action(
                action,
                assignment_id,
                edit_action,
                duplicate_action,
                delete_action,
            )
        )
        menu.popup(self.assignment_table.viewport().mapToGlobal(position))

    def _handle_table_context_action(
        self, action, assignment_id, edit_action, duplicate_action, delete_action
    ):
        try:
            if action == edit_action:
                self._on_edit_manual_item(assignment_id)
            elif action == duplicate_action:
                self._on_duplicate_manual_item(assignment_id)
            elif action == delete_action:
                self._on_delete_manual_item(assignment_id)
        except Exception as exc:
            QMessageBox.critical(self, _("Ошибка"), str(exc))

    def _on_edit_manual_item(self, assignment_id):
        try:
            assignment = self._table_assignments.get(assignment_id)
            if not assignment:
                return
            dialog = ManualAssignmentDialog(
                self.facade,
                self.current_week_id,
                self,
                assignment=assignment,
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            self._record_undo_state()
            if self.facade.update_manual_assignment(assignment_id, **dialog.get_values()):
                self._load_week_editor(self.current_week_id)
                ToastNotification.show_toast(
                    self,
                    _("✏️ Пункт обновлён"),
                    success=True,
                    duration_ms=2000,
                )
        except Exception as exc:
            QMessageBox.critical(self, _("Ошибка редактирования"), str(exc))

    def _on_duplicate_manual_item(self, assignment_id):
        self._record_undo_state()
        duplicate_id = self.facade.duplicate_manual_assignment(assignment_id)
        if duplicate_id:
            self._load_week_editor(self.current_week_id)
            ToastNotification.show_toast(
                self,
                _("📋 Пункт продублирован"),
                success=True,
                duration_ms=2000,
            )

    def _on_delete_manual_item(self, assignment_id):
        reply = QMessageBox.question(
            self,
            _("Удалить пункт"),
            _("Удалить этот внеочередной пункт из расписания?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._record_undo_state()
            self.facade.delete_manual_assignment(assignment_id)
            self._load_week_editor(self.current_week_id)
            ToastNotification.show_toast(
                self,
                _("🗑️ Пункт удалён"),
                success=False,
                duration_ms=2000,
            )

    def _on_duration_edited(self, assignment_id, editor):
        self._record_undo_state()
        if self.facade.update_assignment_duration(assignment_id, editor.value()):
            sb = self.statusBar()
            if sb:
                sb.showMessage(_("Длительность пункта обновлена"), 2000)
            return
        QMessageBox.warning(self, _("Ошибка"), _("Не удалось изменить длительность пункта"))
        self._load_week_editor(self.current_week_id)

    def _on_add_item(self):
        week_id = self.current_week_id
        if not week_id:
            QMessageBox.warning(self, _("Внимание"), _("Сначала выберите неделю"))
            return

        dialog = ManualAssignmentDialog(self.facade, week_id, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        values = dialog.get_values()
        self._record_undo_state()
        assignment_id = self.facade.add_manual_assignment(week_id=week_id, **values)
        if not assignment_id:
            QMessageBox.warning(self, _("Ошибка"), _("Не удалось добавить пункт в расписание"))
            return

        self._load_week_editor(week_id)
        ToastNotification.show_toast(
            self,
            _("➕ Пункт добавлен в расписание"),
            success=True,
            duration_ms=2500,
        )

    def _on_clear_week(self):
        week_id = self.current_week_id
        if not week_id:
            QMessageBox.warning(self, _("Внимание"), _("Неделя не выбрана"))
            return

        reply = QMessageBox.question(
            self,
            _("Очистить назначение"),
            _(
                "Вы уверены, что хотите удалить ВСЕ назначения на эту неделю?\nЭто действие нельзя отменить."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self._record_undo_state()
            self.facade.clear_week_assignments(week_id)
            self._load_week_editor(week_id)
            ToastNotification.show_toast(
                self, _("🗑️ Назначения очищены"), success=False, duration_ms=2500
            )
            sb = self.statusBar()
            if sb:
                sb.showMessage(_("Назначения удалены"), 3000)
