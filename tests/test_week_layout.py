"""Просмотр недели (и PDF на Android) показывает те же пункты, время и людей, что таблица."""

from core.schedule_preview import generate_week_html
from core.week_layout import format_minutes, order_week_assignments, start_minutes


def _week():
    return {
        "week": {"id": 1, "week_title": "1–7 февраля", "bible_reading": None},
        "assignments": [
            {
                "id": 1,
                "assignment_number": "chairman",
                "assignment_text": "Председатель",
                "assignment_type": "chairman",
                "section": "fixed",
                "section_position": "chairman",
                "duration": 0,
                "participant_name": "Тарасюк Виталий",
                "status": "assigned",
            },
            {
                "id": 2,
                "assignment_number": "1",
                "assignment_text": "Речь",
                "assignment_type": "talk",
                "section": "treasures",
                "section_position": "1",
                "duration": 10,
                "participant_name": "Афанасьев Виктор",
                "status": "assigned",
            },
            {
                "id": 3,
                "assignment_number": "4",
                "assignment_text": "Что бы вы сказали?",
                "assignment_type": "student",
                "section": "ministry",
                "section_position": "1",
                "duration": 5,
                "participant_name": "Зорина Елена",
                "assistant_name": "Иванова Мария",
                "status": "assigned",
            },
        ],
    }


def test_start_times_follow_durations():
    # пункты программы — после вступления (председатель, песня и молитва: 5 мин,
    # вступительные слова: 1 мин — S-38, абз. 2)
    rows = [{"duration": 0}, {"duration": 10}, {"duration": 5}]
    assert [format_minutes(m) for m in start_minutes(rows, 19 * 60)] == ["19:06", "19:06", "19:16"]


def test_chairman_and_prayers_follow_meeting_timing():
    """Как в экспорте: председатель 19:00, молитва 19:01, программа с 19:06,
    после учебного задания — минута совета, песня перед «Жизнью» 5 мин,
    заключительная молитва — через 3 мин после ИБС."""
    rows = [
        {"section_position": "chairman", "section": "fixed", "duration": 5},
        {"section_position": "prayer_open", "section": "fixed", "duration": 3},
        {"section_position": "prayer_close", "section": "fixed", "duration": 0},
        {"section_position": "1", "section": "treasures", "duration": 10},
        {"section_position": "4", "section": "ministry", "duration": 5},
        {"section_position": "7", "section": "living", "duration": 15},
        {"section_position": "8", "section": "cbs", "duration": 30},
        {
            "section_position": "cbs_reader",
            "section": "cbs",
            "assignment_type": "cbs_reader",
            "duration": 30,
        },
    ]
    times = [format_minutes(m) for m in start_minutes(rows, 19 * 60)]
    assert times == ["19:00", "19:01", "20:15", "19:06", "19:16", "19:27", "19:42", "20:12"]


def test_preview_uses_real_items_and_times():
    html = generate_week_html(_week(), meeting_time="19:30")

    for text in (
        "Тарасюк Виталий",
        "Афанасьев Виктор",
        "Зорина Елена",
        "Иванова Мария",
        "Что бы вы сказали?",
    ):
        assert text in html
    # Время считается от начала встречи по длительностям, как в таблице
    assert "19:30" in html and "19:36" in html and "19:46" in html
    # Старых жёстко зашитых пунктов и времени больше нет
    assert "Задание 9" not in html and "21:10" not in html


def test_preview_order_matches_table_order():
    data = _week()
    names = [a["participant_name"] for _, a in order_week_assignments(data["assignments"])]
    html = generate_week_html(data)
    positions = [html.index(n) for n in names]
    assert positions == sorted(positions)


def test_cbs_reader_has_no_own_time():
    """Чтец ИБС читает вместе с ведущим — в просмотре недели у него нет времени."""
    data = _week()
    data["assignments"] += [
        {
            "id": 4,
            "assignment_number": "8",
            "assignment_text": "Изучение Библии в собрании",
            "assignment_type": "cbs",
            "section": "cbs",
            "section_position": "8",
            "duration": 30,
            "participant_name": "Белых Дмитрий",
            "status": "assigned",
        },
        {
            "id": 5,
            "assignment_number": "cbs_reader",
            "assignment_text": "Чтец ИБС",
            "assignment_type": "cbs_reader",
            "section": "cbs",
            "section_position": "cbs_reader",
            "duration": 0,
            "participant_name": "Грач Сергей",
            "status": "assigned",
        },
    ]
    html = generate_week_html(data, meeting_time="19:00")
    reader_row = html[
        html.rindex('<div class="row', 0, html.index("Грач Сергей")) : html.index("Грач Сергей")
    ]
    assert '<div class="time"></div>' in reader_row


def test_cbs_reader_duration_does_not_shift_times():
    rows = [
        {"duration": 30, "assignment_type": "cbs"},
        {"duration": 30, "assignment_type": "cbs_reader"},
        {"duration": 0, "assignment_type": "prayer"},
    ]
    assert [format_minutes(m) for m in start_minutes(rows, 20 * 60)] == ["20:06", "20:36", "20:36"]


def test_closing_prayer_is_last():
    data = _week()
    data["assignments"].insert(
        1,
        {
            "id": 9,
            "assignment_number": "prayer_close",
            "assignment_text": "Молитва (закрытие)",
            "assignment_type": "prayer",
            "section": "fixed",
            "section_position": "prayer_close",
            "duration": 0,
            "participant_name": "Карпенко Виктор",
            "status": "assigned",
        },
    )
    ordered = order_week_assignments(data["assignments"])
    assert ordered[-1][1]["id"] == 9
    assert ordered[0][1]["id"] == 1  # председатель — первым
