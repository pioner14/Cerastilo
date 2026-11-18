"""Кнопка «Будущий год»: пустые недели без дублей на стыке лет."""

from datetime import date
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from core.database import DatabaseManager
from core.import_service import ImportService
from core.models import Week


@pytest.fixture
def service(tmp_path):
    db = DatabaseManager(db_path=str(tmp_path / "future_year.db"))
    try:
        yield ImportService(db, Mock())
    finally:
        db.close()


def _add_week(service, start, year, title="из тетради"):
    with service.db.get_session() as session:
        session.add(
            Week(
                week_title=title,
                start_date=start,
                month=start.month,
                year=year,
                workbook_source="mwb.epub",
            )
        )
        session.commit()


def _weeks(service):
    with service.db.get_session() as session:
        # month в старых базах — TEXT: сравниваем строкой
        return [
            (w.start_date, w.year, w.week_title, str(w.month))
            for w in session.execute(select(Week).order_by(Week.start_date)).scalars()
        ]


def test_creates_every_monday_of_year(service):
    result = service.prepare_future_year(2027)

    weeks = _weeks(service)
    assert result == {"success": True, "year": 2027, "created": 52}
    assert len(weeks) == 52
    assert weeks[0][:2] == (date(2027, 1, 4), 2027)
    assert weeks[-1] == (date(2027, 12, 27), 2027, "27 декабря – 2 января", "12")
    assert all(start.weekday() == 0 and start.year == 2027 for start, *_ in weeks)
    assert (date(2027, 3, 1), 2027, "1–7 марта", "3") in weeks
    service.event_bus.emit.assert_called_once()


def test_does_not_duplicate_week_across_new_year(service):
    # «28 декабря — 3 января» лежит в 2026 году; 2027 не должен её повторить
    _add_week(service, date(2026, 12, 28), 2026)

    service.prepare_future_year(2027)

    starts = [start for start, *_ in _weeks(service)]
    assert starts.count(date(2026, 12, 28)) == 1
    assert len(starts) == 1 + 52


def test_fills_only_missing_weeks_and_keeps_imported(service):
    _add_week(service, date(2027, 1, 4), 2027, title="4—10 ЯНВАРЯ")
    _add_week(service, date(2027, 1, 11), 2027, title="11—17 ЯНВАРЯ")

    result = service.prepare_future_year(2027)

    weeks = _weeks(service)
    assert result["created"] == 50
    assert len(weeks) == 52
    assert weeks[0][2] == "4—10 ЯНВАРЯ"


def test_repeated_call_creates_nothing(service):
    service.prepare_future_year(2027)
    service.event_bus.emit.reset_mock()

    assert service.prepare_future_year(2027)["created"] == 0
    service.event_bus.emit.assert_not_called()


def test_plan_offers_incomplete_future_year_first(service):
    # Из тетради есть только январь 2027 — предложить дозаполнить 2027
    _add_week(service, date(2027, 1, 4), 2027)

    assert service.plan_future_year(today=date(2026, 10, 29)) == {"year": 2027, "missing": 51}


def test_plan_offers_year_after_last_complete(service):
    service.prepare_future_year(2027)

    assert service.plan_future_year(today=date(2026, 10, 29)) == {"year": 2028, "missing": 52}


def test_plan_counts_from_last_year_not_current(service):
    for year in range(2027, 2032):
        service.prepare_future_year(year)

    assert service.plan_future_year(today=date(2026, 10, 29))["year"] == 2032


def test_plan_ignores_gaps_in_current_year(service):
    # Пропуск в текущем году (неделя могла быть удалена нарочно) не предлагаем
    _add_week(service, date(2026, 10, 26), 2026)

    assert service.plan_future_year(today=date(2026, 10, 29))["year"] == 2027


def test_button_offers_planned_year_and_reports_count(monkeypatch):
    from types import SimpleNamespace

    import ui.schedule_export as sv  # «Будущий год» живёт в миксине экспорта

    asked, shown, started = [], [], []
    box = SimpleNamespace(
        StandardButton=sv.QMessageBox.StandardButton,
        question=lambda _parent, _title, text, *_a: asked.append(text) or box.StandardButton.Yes,
        information=lambda _parent, _title, text: shown.append(text),
    )
    monkeypatch.setattr(sv, "QMessageBox", box)

    class FakeWorker:
        def __init__(self, func, *args, error_service=None):
            self.func, self.args = func, args
            self.finished = SimpleNamespace(connect=lambda cb: setattr(self, "cb", cb))

        def start(self):
            started.append(self.args)
            self.cb(self.func(*self.args))

    monkeypatch.setattr(sv, "TaskWorker", FakeWorker)
    facade = SimpleNamespace(
        plan_future_year=lambda: {"year": 2027, "missing": 50},
        prepare_future_year=lambda year: {"success": True, "year": year, "created": 50},
        errors=None,
    )
    view = SimpleNamespace(
        facade=facade,
        active_workers=[],
        _clean_worker=lambda: None,
        _load_tree=lambda: shown.append("tree"),
    )
    view._on_prepare_year_finished = lambda r: sv.ScheduleExportMixin._on_prepare_year_finished(
        view, r
    )

    sv.ScheduleExportMixin._on_add_future_year(view)

    assert "2027" in asked[0] and "(50)" in asked[0]
    assert started == [(2027,)]
    assert shown == ["2027 год: добавлено пустых недель — 50.", "tree"]


def test_facade_plan_future_year_real_schedule_service(tmp_path):
    """Окно вызывает facade.plan_future_year — проверка на настоящем ScheduleService,
    без заглушек (раньше метода в нём не было, кнопка падала с AttributeError)."""
    from core.base_facade import BaseApplicationFacade
    from core.services import ScheduleService

    db = DatabaseManager(db_path=str(tmp_path / "facade_year.db"))
    try:
        facade = BaseApplicationFacade(Mock(), ScheduleService(db, Mock()), Mock(), Mock())
        plan = facade.plan_future_year()
        assert set(plan) == {"year", "missing"}
        result = facade.prepare_future_year(plan["year"])
        assert result["success"] and result["created"] == plan["missing"]
        assert facade.plan_future_year()["year"] == plan["year"] + 1
    finally:
        db.close()
