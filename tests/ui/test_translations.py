"""Перевод Qt: стандартные кнопки по-русски."""

from PySide6.QtWidgets import QDialogButtonBox

from ui.translations import install_qt_translator


def test_standard_buttons_are_russian(qapp):
    assert install_qt_translator(qapp)
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No)
    texts = {b.text().replace("&", "") for b in box.buttons()}
    assert texts == {"Да", "Нет"}
