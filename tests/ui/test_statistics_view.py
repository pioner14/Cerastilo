"""Вкладка «Статистика» создаётся и рисуется."""

from datetime import date
from unittest.mock import Mock

from ui.statistics_view import StatisticsView


def test_statistics_view_renders(qapp):
    facade = Mock()
    facade.get_assignment_stats.return_value = {
        "weeks": [date(2026, 9, 7), date(2026, 9, 14)],
        "people": [
            {
                "id": 1,
                "name": "Брат",
                "weeks": {date(2026, 9, 7): ["treasures", "prayer"]},
                "counts": {"treasures": 1, "prayer": 1},
                "total": 2,
            },
            {"id": 2, "name": "Без заданий", "weeks": {}, "counts": {}, "total": 0},
        ],
    }
    view = StatisticsView(facade)
    view.resize(900, 600)
    assert not view.grab().isNull()  # paintEvent обоих графиков без ошибок
    assert view.bars.people[0]["name"] == "Брат"  # сортировка по нагрузке

    view.group_combo.setCurrentIndex(view.group_combo.findData("MS"))
    assert facade.get_assignment_stats.call_args.args[2] == "MS"
