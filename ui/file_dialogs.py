"""Диалог сохранения файла, который работает и на десктопе, и на Android."""

from PySide6.QtWidgets import QFileDialog

from core.utils.android_storage import export_dir, export_path, is_android
from core.i18n import tr


def get_save_file_name(parent, title: str, default_name: str, file_filter: str) -> str:
    """
    Возвращает путь для сохранения или пустую строку, если пользователь отменил.

    На Android диалога нет: файл сразу ложится в «Загрузки/Cerastilo»
    (см. core/utils/android_storage.py).
    """
    if is_android():
        return export_path(default_name)
    file_path, _ = QFileDialog.getSaveFileName(parent, title, default_name, file_filter)
    return file_path


def get_open_file_name(parent, title: str, file_filter: str) -> str:
    """
    Возвращает путь к выбранному файлу или пустую строку, если выбор отменён.

    На Android системный диалог Qt не возвращает выбранный файл (проверено
    в Waydroid 2026-10-22), поэтому там показывается список подходящих файлов
    из «Загрузки/Cerastilo» — той же папки, куда сохраняются экспорт и бэкап.
    """
    if not is_android():
        file_path, _ = QFileDialog.getOpenFileName(parent, title, "", file_filter)
        return file_path

    import os
    import re

    from PySide6.QtWidgets import QInputDialog, QMessageBox

    folder = export_dir()
    patterns = re.findall(r"\*(\.\w+)", file_filter) or [""]
    names = sorted(
        (
            name
            for name in os.listdir(folder)
            if any(name.lower().endswith(ext.lower()) for ext in patterns)
        ),
        key=lambda name: os.path.getmtime(os.path.join(folder, name)),
        reverse=True,
    )
    if not names:
        QMessageBox.information(
            parent,
            title,
            tr(
                "В папке нет подходящих файлов:\n{folder}\n\nСкопируйте файл туда.\n\nЕсли файл уже там, разрешите программе его видеть: Настройки → Приложения → Cerastilo → «Доступ ко всем файлам».",
                folder=folder,
            ),
        )
        return ""
    name, ok = QInputDialog.getItem(
        parent, title, tr("Файлы в {folder}:", folder=folder), names, 0, False
    )
    return os.path.join(folder, name) if ok and name else ""


def saved_message(file_path: str, text: str) -> str:
    """На Android дописывает к сообщению, куда лёг файл: выбрать его там нельзя."""
    if is_android():
        return f"{text}\n\n{file_path}"
    return text
