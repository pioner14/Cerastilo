"""
Tests for:
- core/utils/pdf_utils.py (convert_docx_to_pdf)
- core/export_service.py (export_to_txt, export_to_pdf)
"""

import os
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import Assignment, Base, Participant, Week

# ──────────────────────────── fixtures ────────────────────────────


@pytest.fixture
def db_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def week_with_assignments(db_session):
    """Week with participants assigned to each section."""
    p1 = Participant(name="Иван Петров", gender="male", service_type="elder", is_active=True)
    p2 = Participant(
        name="Пётр Сидоров", gender="male", service_type="ministerial_servant", is_active=True
    )
    p3 = Participant(name="Анна Иванова", gender="female", service_type="publisher", is_active=True)
    db_session.add_all([p1, p2, p3])
    db_session.flush()

    week = Week(
        week_title="Тестовая неделя",
        start_date=date(2024, 6, 10),
        bible_reading="1 Царств 15-16",
        songs="1,2,3",
    )
    db_session.add(week)
    db_session.flush()

    assignments = [
        Assignment(
            week_id=week.id,
            participant_id=p1.id,
            section="fixed",
            section_position="chairman",
            assignment_type="chairman",
            assignment_text="Председатель",
        ),
        Assignment(
            week_id=week.id,
            participant_id=p2.id,
            section="treasures",
            section_position="1",
            assignment_type="talk",
            assignment_text="Урок из Библии (10 мин.)",
            assignment_number="1",
        ),
        Assignment(
            week_id=week.id,
            participant_id=p3.id,
            assistant_id=p1.id,
            section="ministry",
            section_position="4",
            assignment_type="demonstration",
            assignment_text="Первое посещение (2 мин.)",
            assignment_number="4",
        ),
        Assignment(
            week_id=week.id,
            participant_id=p1.id,
            section="living",
            section_position="1",
            assignment_type="needs",
            assignment_text="Местные потребности (15 мин.)",
            assignment_number="7",
        ),
    ]
    db_session.add_all(assignments)
    db_session.commit()
    return week, [p1, p2, p3]


# ──────────────────────────── pdf_utils ────────────────────────────


class TestConvertDocxToPdf:
    """Tests for core/utils/pdf_utils.convert_docx_to_pdf."""

    def test_returns_false_if_input_missing(self):
        from core.utils import convert_docx_to_pdf

        with tempfile.TemporaryDirectory() as tmpdir:
            result = convert_docx_to_pdf("/nonexistent/file.docx", os.path.join(tmpdir, "out.pdf"))
        assert result is False

    def test_calls_libreoffice_subprocess(self):
        from core.utils import convert_docx_to_pdf

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a dummy "docx" file
            docx_path = os.path.join(tmpdir, "test.docx")
            with open(docx_path, "wb") as f:
                f.write(b"dummy")
            pdf_path = os.path.join(tmpdir, "test.pdf")

            # Simulate LibreOffice creating the PDF
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
                # Pre-create the expected output file
                expected = os.path.join(tmpdir, "test.pdf")
                with open(expected, "wb") as f:
                    f.write(b"pdf")

                result = convert_docx_to_pdf(docx_path, pdf_path)

            assert mock_run.called
            cmd = mock_run.call_args[0][0]
            assert "libreoffice" in cmd[0]
            assert "--headless" in cmd
            assert "--convert-to" in cmd

    def test_uses_isolated_profile_flag(self):
        from core.utils import convert_docx_to_pdf

        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = os.path.join(tmpdir, "test.docx")
            with open(docx_path, "wb") as f:
                f.write(b"dummy")

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
                with open(os.path.join(tmpdir, "test.pdf"), "wb") as f:
                    f.write(b"pdf")
                convert_docx_to_pdf(docx_path, os.path.join(tmpdir, "test.pdf"))

            cmd = mock_run.call_args[0][0]
            assert any("-env:UserInstallation" in arg for arg in cmd)

    def test_returns_false_on_timeout(self):
        import subprocess

        from core.utils import convert_docx_to_pdf

        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = os.path.join(tmpdir, "test.docx")
            with open(docx_path, "wb") as f:
                f.write(b"dummy")

            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("lo", 30)):
                result = convert_docx_to_pdf(docx_path, os.path.join(tmpdir, "out.pdf"))

        assert result is False

    def test_returns_false_on_subprocess_error(self):
        import subprocess

        from core.utils import convert_docx_to_pdf

        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = os.path.join(tmpdir, "test.docx")
            with open(docx_path, "wb") as f:
                f.write(b"dummy")

            with patch(
                "subprocess.run",
                side_effect=subprocess.CalledProcessError(1, "libreoffice", stderr=b""),
            ):
                result = convert_docx_to_pdf(docx_path, os.path.join(tmpdir, "out.pdf"))

        assert result is False


# ──────────────────────────── ExportService.export_to_txt ────────────────────────────


class TestExportServiceTxt:
    """Tests for ExportService.export_to_txt."""

    def _make_service(self, db_session):
        from unittest.mock import MagicMock

        from core.events import EventBus
        from core.export_service import ExportService

        db = MagicMock()
        db.get_session = MagicMock(
            return_value=MagicMock(
                __enter__=lambda s, *a: db_session,
                __exit__=lambda s, *a: None,
            )
        )
        event_bus = EventBus()

        # schedule_service wraps the real week_repository
        from core.repositories.week_repository import WeekRepository

        week_repo = WeekRepository(session=db_session)
        schedule_service = MagicMock()
        schedule_service.get_week_data = lambda wid: week_repo.get_week_data(wid)

        svc = ExportService(db, event_bus, schedule_service=schedule_service)
        return svc

    def test_creates_txt_file(self, db_session, week_with_assignments):
        week, _ = week_with_assignments
        svc = self._make_service(db_session)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "schedule.txt")
            result = svc.export_to_txt([week.id], path)
            assert result is True
            assert os.path.exists(path)

    def test_txt_contains_week_title(self, db_session, week_with_assignments):
        week, _ = week_with_assignments
        svc = self._make_service(db_session)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "schedule.txt")
            svc.export_to_txt([week.id], path)
            content = Path(path).read_text(encoding="utf-8")
        assert "ТЕСТОВАЯ НЕДЕЛЯ" in content.upper()

    def test_txt_contains_bible_reading(self, db_session, week_with_assignments):
        week, _ = week_with_assignments
        svc = self._make_service(db_session)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "schedule.txt")
            svc.export_to_txt([week.id], path)
            content = Path(path).read_text(encoding="utf-8")
        assert "1 Царств 15-16" in content

    def test_txt_contains_participant_name(self, db_session, week_with_assignments):
        week, participants = week_with_assignments
        svc = self._make_service(db_session)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "schedule.txt")
            svc.export_to_txt([week.id], path)
            content = Path(path).read_text(encoding="utf-8")
        assert "Иван Петров" in content

    def test_txt_contains_assistant_name(self, db_session, week_with_assignments):
        week, _ = week_with_assignments
        svc = self._make_service(db_session)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "schedule.txt")
            svc.export_to_txt([week.id], path)
            content = Path(path).read_text(encoding="utf-8")
        # p1 is assistant for p3's assignment
        assert "Ассистент" in content

    def test_english_txt_and_preview_translate_schedule_labels(
        self, db_session, week_with_assignments, tmp_path
    ):
        from core.i18n import set_language

        week, _ = week_with_assignments
        service = self._make_service(db_session)
        service.db.get_setting.return_value = "19:00"
        path = tmp_path / "schedule.txt"
        try:
            set_language("en")
            assert service.export_to_txt([week.id], str(path))
            txt = path.read_text(encoding="utf-8")
            preview = service.generate_preview_html(week.id)
            for content in (txt, preview):
                assert "Week of June 10" in content
                assert "Chairman" in content
                assert "APPLY YOURSELF TO THE FIELD MINISTRY" in content
                assert "Первое посещение (2 min.)" in content
            assert "Assistant: Иван Петров" in txt
        finally:
            set_language("ru")

    def test_txt_multiple_weeks(self, db_session, week_with_assignments):
        week, participants = week_with_assignments
        # Add a second week
        week2 = Week(week_title="Вторая неделя", start_date=date(2024, 6, 17), songs="4,5,6")
        db_session.add(week2)
        db_session.commit()

        svc = self._make_service(db_session)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "schedule.txt")
            result = svc.export_to_txt([week.id, week2.id], path)
        assert result is True

    def test_txt_returns_false_on_write_error(self, db_session, week_with_assignments):
        week, _ = week_with_assignments
        svc = self._make_service(db_session)
        result = svc.export_to_txt([week.id], "/no/permission/here.txt")
        assert result is False

    def test_txt_encoding_is_utf8(self, db_session, week_with_assignments):
        week, _ = week_with_assignments
        svc = self._make_service(db_session)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "schedule.txt")
            svc.export_to_txt([week.id], path)
            # Should be readable as utf-8 without errors
            content = Path(path).read_text(encoding="utf-8")
        assert len(content) > 0


# ──────────────────────────── ExportService.export_to_pdf ────────────────────────────


class TestExportServicePdf:
    """Tests for ExportService.export_to_pdf."""

    def _make_service(self, db_session):
        from core.events import EventBus
        from core.export_service import ExportService

        db = MagicMock()
        db.get_session = MagicMock(
            return_value=MagicMock(
                __enter__=lambda s, *a: db_session,
                __exit__=lambda s, *a: None,
            )
        )
        svc = ExportService(db, EventBus())
        return svc

    def test_calls_convert_docx_to_pdf(self, db_session, week_with_assignments):
        week, _ = week_with_assignments
        svc = self._make_service(db_session)

        with (
            patch.object(svc, "export_custom_docx", return_value=True) as mock_docx,
            patch("core.utils.convert_docx_to_pdf", return_value=True) as mock_pdf,
        ):
            # Need to import convert_docx_to_pdf in the right namespace
            with tempfile.TemporaryDirectory() as tmpdir:
                path = os.path.join(tmpdir, "out.pdf")
                # Patch at the module level used inside export_to_pdf
                with patch("core.utils.convert_docx_to_pdf", return_value=True):
                    result = svc.export_to_pdf([week.id], path)

        # export_custom_docx must have been called to generate temp DOCX
        assert mock_docx.called

    def test_cleans_up_temp_docx_on_success(self, db_session, week_with_assignments):
        week, _ = week_with_assignments
        svc = self._make_service(db_session)
        created_tmps = []

        original_mkstemp = tempfile.mkstemp

        def tracking_mkstemp(**kwargs):
            fd, path = original_mkstemp(**kwargs)
            created_tmps.append(path)
            return fd, path

        with (
            patch("tempfile.mkstemp", side_effect=tracking_mkstemp),
            patch.object(svc, "export_custom_docx", return_value=True),
            patch("core.utils.convert_docx_to_pdf", return_value=True),
        ):
            with tempfile.TemporaryDirectory() as tmpdir:
                svc.export_to_pdf([week.id], os.path.join(tmpdir, "out.pdf"))

        # All temporary files should be removed
        for tmp in created_tmps:
            assert not os.path.exists(tmp), f"Temp file not cleaned up: {tmp}"

    def test_returns_false_if_docx_generation_fails(self, db_session):
        svc = self._make_service(db_session)
        with patch.object(svc, "export_custom_docx", return_value=False):
            with tempfile.TemporaryDirectory() as tmpdir:
                result = svc.export_to_pdf([999], os.path.join(tmpdir, "out.pdf"))
        assert result is False


class TestSpecialEventExport:
    """Тесты экспорта недель со специальным событием (конгресс, вечеря)."""

    def test_export_txt_special_event(self, db_session):
        from unittest.mock import MagicMock
        from core.export_service import ExportService
        from core.events import EventBus

        week = Week(
            week_title="Неделя 30 ноября - 6 декабря",
            start_date=date(2026, 11, 30),
            special_event="circuit_assembly",
        )
        db_session.add(week)
        db_session.commit()

        schedule_service = MagicMock()
        schedule_service.get_week_data.return_value = {
            "week": {
                "week_title": week.week_title,
                "start_date": week.start_date,
                "special_event": week.special_event,
                "bible_reading": None,
            },
            "assignments": [],
        }
        export_service = ExportService(MagicMock(), EventBus(), schedule_service=schedule_service)

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, "schedule.txt")
            res = export_service.export_to_txt([week.id], out_file)
            assert res is True
            content = Path(out_file).read_text(encoding="utf-8")

            assert "Районный Конгресс" in content
            assert "Встреча отменена в связи с конгрессом" in content

    def test_export_docx_special_event(self, db_session):
        from core.export_schedule_docx import CustomScheduleExporter
        from docx import Document

        week = Week(
            week_title="Неделя 30 ноября - 6 декабря",
            start_date=date(2026, 11, 30),
            special_event="circuit_assembly",
        )
        db_session.add(week)
        db_session.commit()

        exporter = CustomScheduleExporter()

        with tempfile.TemporaryDirectory() as tmpdir:
            for mode in ("compact", "compact_modern", "modern", "full_modern"):
                out_docx = os.path.join(tmpdir, f"schedule_{mode}.docx")
                res = exporter.export([week.id], out_docx, db_session, mode=mode)
                assert res["success"] is True
                doc = Document(res["path"])
                full_text = " ".join(
                    [p.text for p in doc.paragraphs]
                    + [c.text for t in doc.tables for r in t.rows for c in r.cells]
                )
                assert "Районный Конгресс" in full_text
                assert "Встреча отменена в связи с конгрессом" in full_text

    def test_export_circuit_overseer_replaces_cbs(self, db_session):
        from core.export_schedule_docx import CustomScheduleExporter
        from core.export_service import ExportService
        from unittest.mock import MagicMock
        from core.events import EventBus
        from docx import Document

        week = Week(
            week_title="Неделя визита РС",
            start_date=date(2026, 11, 23),
            special_event="circuit_overseer",
            songs="12,34,56",
        )
        db_session.add(week)
        db_session.commit()

        # Добавим CBS и чтеца CBS
        db_session.add_all(
            [
                Assignment(
                    week_id=week.id,
                    section="living",
                    section_position="1",
                    assignment_text="Живите по вере",
                    assignment_type="living",
                    duration=15,
                ),
                Assignment(
                    week_id=week.id,
                    section="cbs",
                    section_position="1",
                    assignment_text="Изучение Библии в собрании",
                    assignment_type="cbs",
                    duration=30,
                ),
                Assignment(
                    week_id=week.id,
                    section="cbs",
                    section_position="2",
                    assignment_text="Чтец CBS",
                    assignment_type="cbs_reader",
                    duration=30,
                ),
            ]
        )
        db_session.commit()

        exporter = CustomScheduleExporter()

        with tempfile.TemporaryDirectory() as tmpdir:
            for mode in ("compact", "compact_modern", "modern", "full_modern"):
                out_docx = os.path.join(tmpdir, f"co_schedule_{mode}.docx")
                res = exporter.export([week.id], out_docx, db_session, mode=mode)
                assert res["success"] is True
                doc = Document(res["path"])
                full_text = " ".join(
                    [p.text for p in doc.paragraphs]
                    + [c.text for t in doc.tables for r in t.rows for c in r.cells]
                )
                assert "Служебная речь РС" in full_text
                assert "Районный старейшина" in full_text
                assert "Изучение Библии в собрании" not in full_text
