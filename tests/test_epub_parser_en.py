from pathlib import Path
from zipfile import ZipFile

import pytest

from core.assignment_rules import resolve_assignment_config
from core.chairman_talk import role_talk_type
from core.epub_parser import WorkbookParser

_ROOT = Path(__file__).resolve().parents[1]


def _assignment_flags(assignment):
    config = resolve_assignment_config(
        assignment["section"],
        assignment["type"],
        assignment["text"],
        assignment.get("discussion_marker"),
        assignment["section_position"],
        None,
        lambda *_: None,
    )
    return (
        bool(getattr(config, "is_discussion_item", False)),
        assignment["type"] == "teaching" or bool(getattr(config, "is_talk_item", False)),
    )


@pytest.mark.parametrize("issue", ["202701", "202703"])
def test_english_workbook_matches_russian(issue):
    english_path = _ROOT / f"mwb_E_{issue}.epub"
    russian_path = _ROOT / f"mwb_U_{issue}.epub"
    if not english_path.is_file() or not russian_path.is_file():
        pytest.skip("Нет пары EPUB для сравнения")

    english = WorkbookParser(english_path).parse()
    russian = WorkbookParser(russian_path).parse()
    # Мартовское расписание чтения к Вечере не образует девятую неделю.
    assert len(english) == len(russian) == 8

    date_keys = ("start_day", "end_day", "month_num", "start_month_num", "start_year")
    part_keys = ("number", "section", "section_position", "type", "duration")
    for en_week, ru_week in zip(english, russian, strict=True):
        assert [en_week[key] for key in date_keys] == [ru_week[key] for key in date_keys]
        assert en_week["start_year"] is None
        assert en_week["bible_reading"].startswith("EZEKIEL")
        if en_week["week_title"] == "MARCH 8-14":
            # В этих изданиях средняя песня действительно разная.
            assert en_week["songs"] == ["8", "151", "2"]
            assert ru_week["songs"] == ["8", "133", "2"]
        else:
            assert en_week["songs"] == ru_week["songs"]

        en_parts, ru_parts = en_week["assignments"], ru_week["assignments"]
        assert len(en_parts) == len(ru_parts)
        for en_part, ru_part in zip(en_parts, ru_parts, strict=True):
            assert [en_part[key] for key in part_keys] == [ru_part[key] for key in part_keys]
            assert _assignment_flags(en_part) == _assignment_flags(ru_part)
            if en_week["week_title"] == "APRIL 12-18" and en_part["number"] == "5":
                # Русское «(5 мин.). Обсуждение» распознаётся по заголовку пункта.
                assert en_part["discussion_marker"]
                assert "discussion_marker" not in ru_part
            else:
                assert bool(en_part.get("discussion_marker")) == bool(
                    ru_part.get("discussion_marker")
                )
            if en_part["type"] == "cbs_reader":
                assert en_part["text"] == "Congregation Bible Study Reader"
                assert ru_part["text"] == "Чтец (Изучение Библии)"


@pytest.mark.parametrize(
    ("filename", "language"),
    [("mwb_U_202701.epub", "en-US"), ("mwb_E_202701.epub", None), ("workbook.epub", None)],
)
def test_workbook_language_detection(tmp_path, filename, language):
    path = tmp_path / filename
    metadata = f"<dc:language>{language}</dc:language>" if language else ""
    with ZipFile(path, "w") as epub:
        epub.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
            '<rootfile full-path="workbook.opf" media-type="application/oebps-package+xml"/>'
            "</rootfiles></container>",
        )
        epub.writestr(
            "workbook.opf",
            '<package xmlns="http://www.idpf.org/2007/opf" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f"<metadata>{metadata}</metadata>"
            '<manifest><item href="week.xhtml" media-type="application/xhtml+xml"/></manifest>'
            "</package>",
        )
        epub.writestr(
            "week.xhtml",
            "<h1>DECEMBER 28, 2026–JANUARY 3, 2027</h1>"
            "<h2>1 SAMUEL 1-2</h2><p><strong>Song 39 and Prayer</strong></p>"
            "<h2>TREASURES FROM GOD'S WORD</h2>"
            "<h3>3. Bible Reading</h3><p>(4 min. or less)</p>"
            "<h2>LIVING AS CHRISTIANS</h2>"
            "<h3>Congregation Bible Study</h3><p>(30 min.)</p>",
        )

    (week,) = WorkbookParser(path).parse()
    assert (week["start_day"], week["start_month_num"], week["start_year"]) == (28, 12, 2026)
    assert week["end_day"] == 3
    assert week["bible_reading"] == "1 SAMUEL 1-2"
    assert week["songs"] == ["39"]
    assert [(part["type"], part["duration"]) for part in week["assignments"]] == [
        ("reading", 4),
        ("cbs", 30),
        ("cbs_reader", 30),
    ]


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("chairman", "chairman_talk"),
        ("the service overseer", "service_overseer_talk"),
        ("the secretary", "secretary_talk"),
        ("coordinator of the body of elders", "coordinator_talk"),
    ],
)
def test_english_duty_talk(role, expected):
    assert role_talk_type(f"(2 min.) Talk by {role}.") == expected


def test_reimport_english_workbook_keeps_assignments(tmp_path):
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from core.models import Base, Participant, Week
    from core.workbook_import import save_weeks_to_db

    russian = _ROOT / "mwb_U_202703.epub"
    english = _ROOT / "mwb_E_202703.epub"
    if not russian.is_file() or not english.is_file():
        pytest.skip("Нет пары EPUB для повторного импорта")

    engine = create_engine(f"sqlite:///{tmp_path / 'workbook.db'}")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            save_weeks_to_db(session, WorkbookParser(russian).parse(), str(russian))
            weeks = session.scalars(select(Week).order_by(Week.start_date)).all()
            ids = [week.id for week in weeks]
            week = weeks[0]
            participant = Participant(name="Участник")
            assistant = Participant(name="Помощник")
            session.add_all([participant, assistant])
            session.flush()
            participant_id, assistant_id = participant.id, assistant.id

            selected = {("treasures", "1"), ("ministry", "1")}
            for part in week.assignments:
                if (part.section, part.section_position) in selected:
                    part.participant_id = participant_id
                    part.status = "assigned"
                    if part.section == "ministry":
                        part.assistant_id = assistant_id
            session.commit()

            english_weeks = WorkbookParser(english).parse()
            result = save_weeks_to_db(session, english_weeks, str(english))
            assert result["weeks"] == 0
            updated = session.scalars(select(Week).order_by(Week.start_date)).all()
            assert [week.id for week in updated] == ids
            for week, expected in zip(updated, english_weeks, strict=True):
                assert week.week_title == expected["week_title"]
                assert week.bible_reading == expected["bible_reading"]
                by_position = {
                    (part.section, part.section_position): part for part in week.assignments
                }
                for part in expected["assignments"]:
                    slot = (part["section"], part["section_position"])
                    assert by_position[slot].assignment_text == part["text"]
            by_position = {
                (part.section, part.section_position): part for part in updated[0].assignments
            }
            for slot in selected:
                assert by_position[slot].participant_id == participant_id
                assert by_position[slot].status == "assigned"
            assert by_position["ministry", "1"].assistant_id == assistant_id
            assert by_position["fixed", "chairman"].assignment_text == "Председатель"
    finally:
        engine.dispose()
