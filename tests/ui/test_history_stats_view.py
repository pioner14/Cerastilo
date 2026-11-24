"""Вкладка «История и статистика»: обе страницы под одной вкладкой."""

from unittest.mock import Mock

from ui.history_stats_view import HistoryStatsView


def _facade():
    facade = Mock()
    facade.get_participants_list.return_value = []
    facade.get_assignment_stats.return_value = {"weeks": [], "people": []}
    return facade


def test_two_pages_and_loads_current_one(qapp):
    facade = _facade()
    view = HistoryStatsView(facade)
    assert view.pages.count() == 2
    assert view.pages.widget(0) is view.history_view
    assert view.pages.widget(1) is view.statistics_view
    assert view.help_key() == "history"

    facade.get_participants_list.reset_mock()
    view.load_data()
    facade.get_participants_list.assert_called()

    facade.get_assignment_stats.reset_mock()
    view.pages.setCurrentIndex(1)  # переход на «Статистику» сам обновляет её
    facade.get_assignment_stats.assert_called()
    assert view.help_key() == "statistics"
