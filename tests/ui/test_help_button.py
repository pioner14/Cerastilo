"""Кнопка «❓ Справка» в главном окне открывает руководство на главе текущей вкладки."""

from main import MainWindow


def test_help_button_opens_section_of_current_tab(qapp, facade):
    window = MainWindow(facade)
    try:
        assert window.tabs.cornerWidget() is window.help_button
        assert "Справка" in window.help_button.text()

        window.tabs.setCurrentWidget(window.schedule_view)
        window.help_button.click()
        dialog = window._help_dialog
        assert dialog.current_doc == "guide"
        assert dialog.toc.currentItem().text(0).startswith("6. ")

        # Повторное открытие — то же окно, уже на другой главе
        window.tabs.setCurrentWidget(window.settings_view)
        window.show_help()
        assert window._help_dialog is dialog
        assert dialog.toc.currentItem().text(0).startswith("11. ")
        dialog.close()
    finally:
        window.close()
        window.deleteLater()
