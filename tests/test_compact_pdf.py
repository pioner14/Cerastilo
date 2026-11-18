"""PDF на Android: те же строки, что DOCX/PDF на ПК, и две недели на лист."""

import re
from datetime import date
from types import SimpleNamespace

from core.export.compact_layout import build_week_layout


def _week_data(start=date(2027, 2, 1), special_event=None):
    week = SimpleNamespace(
        start_date=start,
        bible_reading="ИЕЗЕКИИЛЬ 19, 20",
        songs="11,76,128",
        special_event=special_event,
        announcement=None,
    )
    a = lambda **kw: {"assistant": None, "duration": 5, "participant": None, **kw}  # noqa: E731
    return {
        "week": week,
        "settings": {
            "meeting_time": "19:00",
            "cong_name": "ДЕМО-СОБРАНИЕ",
            "module_announcement": "false",
        },
        "assignments": [
            a(
                type="chairman",
                section="fixed",
                position="chairman",
                text="Председатель",
                participant="Тарасюк Виталий",
            ),
            a(
                type="prayer",
                section="fixed",
                position="prayer_open",
                text="Молитва",
                participant="Пахомов Виталий",
            ),
            a(
                type="talk",
                section="treasures",
                position="1",
                text="1. Речь",
                participant="Афанасьев Виктор",
                duration=10,
            ),
            a(
                type="student",
                section="ministry",
                position="1",
                text="4. Что бы вы сказали?",
                participant="Зорина Елена",
                assistant="Луценко Василиса",
                duration=5,
            ),
            a(
                type="cbs",
                section="cbs",
                position="1",
                text="8. Изучение Библии",
                participant="Фомичев Филипп",
                duration=30,
            ),
            a(
                type="cbs_reader",
                section="cbs",
                position="2",
                text="Чтец",
                participant="Рыжиков Евгений",
            ),
            a(
                type="prayer",
                section="fixed",
                position="prayer_close",
                text="Молитва",
                participant="Белых Дмитрий",
            ),
        ],
    }


def test_layout_matches_desktop_structure():
    layout = build_week_layout(_week_data())
    texts = [(r["time"], r["text"], r["person"]) for r in layout["rows"]]

    assert layout["header"]["title"] == "Неделя от 1 ФЕВРАЛЯ"
    assert texts[0] == ("19:00", "Председатель", "Тарасюк Виталий")
    assert texts[1] == ("19:01", "Песня 11 и молитва", "Пахомов Виталий")
    assert ("", "СОКРОВИЩА ИЗ СЛОВА БОГА", "") in texts
    assert ("19:06", "1. Речь", "Афанасьев Виктор") in texts
    assert ("19:16", "4. Что бы вы сказали?", "Зорина Елена / Луценко Василиса") in texts
    assert any(p == "Ведущий: Фомичев Филипп\nЧтец: Рыжиков Евгений" for _, _, p in texts)
    assert texts[-1][1:] == ("Песня 128 и молитва", "Белых Дмитрий")


def test_special_event_week_has_no_rows():
    layout = build_week_layout(_week_data(special_event="circuit_assembly"))
    assert layout["special"]["title"] == "🏟️ Районный Конгресс"
    assert layout["rows"] == []


def test_two_weeks_per_page(qapp, tmp_path):
    from core.export.qt_pdf import render_compact_pdf

    weeks = [_week_data(date(2027, 2, d)) for d in (1, 8, 15, 22)]
    out = tmp_path / "s.pdf"

    assert render_compact_pdf(weeks, str(out))

    pages = len(re.findall(rb"/Type\s*/Page(?!s)", out.read_bytes()))
    assert pages == 2


def test_printer_gets_same_two_weeks_per_page_at_high_resolution(qapp, tmp_path):
    """Печать: QPrinter высокого разрешения (вывод в PDF-файл вместо принтера) —
    тоже две недели на лист, рисунок масштабируется под разрешение принтера."""
    from PySide6.QtPrintSupport import QPrinter

    from core.export.qt_pdf import paint_compact, setup_printer

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    setup_printer(printer)
    out = tmp_path / "printed.pdf"
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(out))
    assert printer.logicalDpiX() > 96

    weeks = [_week_data(date(2027, 2, d)) for d in (1, 8, 15, 22)]
    assert paint_compact(printer, weeks)

    pages = len(re.findall(rb"/Type\s*/Page(?!s)", out.read_bytes()))
    assert pages == 2


# --- Бланк: жёсткие колонки, имена по левому краю ---


def test_docx_columns_have_fixed_widths(tmp_path):
    """Ширины колонок DOCX жёсткие: иначе Word делит таблицу поровну и между
    пунктом и именами остаётся пустая полоса."""
    from docx import Document
    from docx.oxml.ns import qn

    from core.export.compact_v2_builder import CompactV2TableBuilder as B

    doc = Document()
    B().build(doc, _week_data())
    header, main = doc.tables
    for table, widths in ((header, B.HEADER_WIDTHS), (main, B.COL_WIDTHS)):
        layout = table._tbl.tblPr.find(qn("w:tblLayout"))
        assert layout is not None and layout.get(qn("w:type")) == "fixed"
        grid = [int(g.get(qn("w:w"))) for g in table._tbl.tblGrid.findall(qn("w:gridCol"))]
        assert grid == [w.twips for w in widths]
    assert round(sum(w.cm for w in B.COL_WIDTHS), 2) == 18.5  # A4 без полей 1,25 см

    texts = [[c.text for c in r.cells] for r in main.rows]
    assert ["19:01", "Песня 11 и молитва", "Пахомов Виталий"] in texts
    assert any(r[1:] == ["Песня 76", ""] for r in texts)


def test_export_file_name_has_month_meeting_and_export_date():
    from core.export.filename import schedule_base_name

    today = date(2026, 11, 13)
    title = "Встреча «Христианская жизнь и служение»"
    assert (
        schedule_base_name(date(2026, 12, 7), date(2026, 12, 28), today)
        == f"Декабрь 2026 {title} 13.11.2026"
    )
    assert (
        schedule_base_name("2026-11-30", "2026-12-21", today)
        == f"Ноябрь–Декабрь 2026 {title} 13.11.2026"
    )
    assert (
        schedule_base_name(date(2026, 12, 28), date(2027, 1, 4), today)
        == f"Декабрь 2026–Январь 2027 {title} 13.11.2026"
    )
    assert schedule_base_name(None, None, today) == f"{title} 13.11.2026"


def test_name_column_fits_longest_name_on_sheet():
    """Колонка имён — по самому длинному имени листа, в пределах 6…10,4 см;
    обе недели листа получают одинаковые ширины."""
    from core.export.compact_layout import (
        NAME_COL_MAX_CM,
        NAME_COL_MIN_CM,
        name_column_cm,
    )
    from core.export.compact_v2_builder import CompactV2TableBuilder

    def lay(*persons):
        return {"rows": [{"person": p} for p in persons]}

    short = name_column_cm([lay("Ив Ан")])
    pair = name_column_cm([lay("Ив Ан"), lay("Николаева Юлия / Медведева Людмила")])
    huge = name_column_cm([lay("Я" * 80)])
    assert short == NAME_COL_MIN_CM
    assert NAME_COL_MIN_CM < pair < NAME_COL_MAX_CM
    assert huge == NAME_COL_MAX_CM
    # «Ведущий: …\nЧтец: …» меряется по самой длинной строке
    assert name_column_cm([lay("Ведущий: Ив Ан\nЧтец: Ив Ан")]) == NAME_COL_MIN_CM

    b = CompactV2TableBuilder()
    b.fit_columns([_week_data(), _week_data(date(2027, 2, 8))])
    assert round(sum(w.cm for w in b.COL_WIDTHS), 2) == 18.5
    assert NAME_COL_MIN_CM <= round(b.COL_WIDTHS[2].cm, 2) <= NAME_COL_MAX_CM


def test_compact_layout_in_russian_and_english():
    from core.i18n import set_language

    data = _week_data(date(2027, 1, 4))
    data["week"].songs = "12,76,128"
    try:
        set_language("ru")
        russian = build_week_layout(data)
        assert russian["header"]["title"] == "Неделя от 4 ЯНВАРЯ"
        assert [(r["time"], r["text"], r["person"]) for r in russian["rows"]] == [
            ("19:00", "Председатель", "Тарасюк Виталий"),
            ("19:01", "Песня 12 и молитва", "Пахомов Виталий"),
            ("", "СОКРОВИЩА ИЗ СЛОВА БОГА", ""),
            ("19:06", "1. Речь", "Афанасьев Виктор"),
            ("", "ОТТАЧИВАЕМ НАВЫКИ СЛУЖЕНИЯ", ""),
            ("19:16", "4. Что бы вы сказали?", "Зорина Елена / Луценко Василиса"),
            ("19:21", "Песня 76", ""),
            ("", "ХРИСТИАНСКАЯ ЖИЗНЬ", ""),
            ("19:26", "8. Изучение Библии", "Ведущий: Фомичев Филипп\nЧтец: Рыжиков Евгений"),
            ("19:59", "Песня 128 и молитва", "Белых Дмитрий"),
        ]

        set_language("en")
        english = build_week_layout(data)
        assert english["header"]["title"] == "Week of January 4"
        assert [r["text"] for r in english["rows"]] == [
            "Chairman",
            "Song 12 and Prayer",
            "Opening Comments (1 min.)",
            "TREASURES FROM GOD'S WORD",
            "1. Речь",
            "APPLY YOURSELF TO THE FIELD MINISTRY",
            "4. Что бы вы сказали?",
            "Song 76",
            "LIVING AS CHRISTIANS",
            "8. Изучение Библии",
            "Concluding Comments (3 min.)",
            "Song 128 and Prayer",
        ]
        assert english["rows"][9]["person"] == "Conductor: Фомичев Филипп\nReader: Рыжиков Евгений"
        cyrillic = re.compile(r"[А-Яа-яЁё]")
        assignments = {a["text"] for a in data["assignments"] if a["section"] != "fixed"}
        assert all(
            not cyrillic.search(r["text"]) for r in english["rows"] if r["text"] not in assignments
        )

        data["week"].special_event = "circuit_overseer"
        assert any(
            r["text"] == "Service Talk by Circuit Overseer (30 min.)"
            and r["person"] == "Circuit Overseer"
            for r in build_week_layout(data)["rows"]
        )

        for event, title in (
            ("memorial", "🍷 Memorial"),
            ("circuit_assembly", "🏟️ Circuit Assembly"),
            ("regional_convention", "🌍 Regional Convention"),
        ):
            data["week"].special_event = event
            special = build_week_layout(data)["special"]
            assert special["title"] == title
            assert special["date"] == "2027-01-04"
            assert special["message"].startswith("No regular meeting this week.")
    finally:
        set_language("ru")
