import html

from core.export.compact_layout import format_week_title
from core.i18n import language, tr
from core.week_layout import (
    apply_circuit_overseer_week,
    assignment_label,
    format_minutes,
    order_week_assignments,
    parse_meeting_start,
    start_minutes,
)

_NEUTRAL = "background-color: #eceff1; color: #455a64; border-color: #cfd8dc;"
# Ключ раздела → (заголовок, CSS-класс, доп. стиль)
_SECTION_HEADERS = {
    "fixed": ("📋 ОБЩИЕ НАЗНАЧЕНИЯ", "", _NEUTRAL),
    "treasures": ("💎 СОКРОВИЩА ИЗ СЛОВА БОГА", "treasures", ""),
    "ministry": ("🌾 ОТТАЧИВАЕМ НАВЫКИ СЛУЖЕНИЯ", "ministry", ""),
    "living": ("🐑 ХРИСТИАНСКАЯ ЖИЗНЬ", "living", ""),
    "cbs": ("📖 ИЗУЧЕНИЕ БИБЛИИ В СОБРАНИИ", "living", ""),
    "other": ("ПРОЧЕЕ", "", _NEUTRAL),
}


def generate_week_html(data, meeting_time="19:00"):
    """
    Генерирует HTML-код для красивого предпросмотра расписания одной недели.
    data: словарь с ключами 'week' и 'assignments'.

    Порядок пунктов и время начала — те же, что в таблице расписания
    (core/week_layout.py): пункты, их участники и длительности берутся из базы,
    а не из жёсткого шаблона.
    """
    week = data["week"]
    assignments = [a for a in data["assignments"] if isinstance(a, dict)]
    assignments, _ = apply_circuit_overseer_week(week, assignments)
    from core.assignment_classifier import AssignmentClassifier

    classifier = AssignmentClassifier()
    ordered = order_week_assignments(assignments, classifier)
    starts = start_minutes([a for _, a in ordered], parse_meeting_start(meeting_time))

    body_rows = []
    current_section = None
    for (section_key, assignment), start in zip(ordered, starts):
        # заключительная молитва стоит в конце — без отдельного заголовка «Общие»
        closing = (
            str(assignment.get("section_position") or assignment.get("assignment_number"))
            == "prayer_close"
        )
        if section_key != current_section and not closing:
            title, css_class, style = _SECTION_HEADERS.get(section_key, _SECTION_HEADERS["other"])
            body_rows.append(
                f'<div class="section-title {css_class}" style="{style}">{html.escape(tr(title))}</div>'
            )
            current_section = section_key
        label = classifier.strip_leading_number(
            assignment_label(assignment.get("assignment_text") or tr("Назначение")),
            str(assignment.get("assignment_number") or ""),
        )
        css_class = _SECTION_HEADERS.get(section_key, _SECTION_HEADERS["other"])[1]
        # чтец ИБС — вместе с ведущим, своего времени нет
        time = "" if assignment.get("assignment_type") == "cbs_reader" else format_minutes(start)
        body_rows.append(_get_row_html(label, assignment, time, css_class))
    rows_html = "\n".join(body_rows)

    title = week["week_title"]
    if language() == "en" and week.get("start_date"):
        title = format_week_title(week["start_date"])

    html_content = f"""
    <html>
    <head>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #f9f9f9;
            padding: 20px;
            color: #333;
        }}
        .container {{
            max-width: 800px;
            margin: 0 auto;
            background: white;
            border: 1px solid #ddd;
            border-radius: 8px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            overflow: hidden;
        }}
        .header {{
            background-color: #004d40;
            color: white;
            padding: 20px;
            text-align: center;
        }}
        .header h1 {{ margin: 0; font-size: 24px; }}
        .header p {{ margin: 5px 0 0; opacity: 0.8; font-style: italic; }}
        
        .section-title {{
            background-color: #f1f8e9;
            color: #2e7d32;
            padding: 10px 15px;
            font-weight: bold;
            font-size: 16px;
            border-bottom: 2px solid #a5d6a7;
            margin-top: 15px;
        }}
        
        .row {{
            display: flex;
            padding: 10px 15px;
            border-bottom: 1px solid #eee;
            align-items: center;
        }}
        .row:last-child {{ border-bottom: none; }}
        
        .time {{
            width: 70px;
            font-weight: bold;
            color: #757575;
        }}
        .assignment-text {{
            flex: 1;
            padding-right: 15px;
        }}
        .participant {{
            width: 180px;
            font-weight: bold;
            color: #01579b;
        }}
        .assistant {{
            width: 180px;
            color: #546e7a;
            font-style: italic;
        }}
        
        .treasures {{ color: #004d40; border-left: 5px solid #004d40; }}
        .ministry {{ color: #7b1fa2; border-left: 5px solid #7b1fa2; }}
        .living {{ color: #c62828; border-left: 5px solid #c62828; }}
        
        .empty {{ color: #ccc; font-style: italic; }}
    </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>{html.escape(title)}</h1>
                <p>📚 {html.escape(week.get('bible_reading') or '')}</p>
            </div>
            
            {rows_html}
        </div>
    </body>
    </html>
    """
    return html_content


def _get_row_html(label, assignment, time, css_class=""):
    label_esc = html.escape(label)
    if not assignment:
        return f'<div class="row {css_class}"><div class="time">{time}</div><div class="assignment-text">{label_esc}</div><div class="participant empty">—</div></div>'

    # Use participant_name (loaded via ORM joins in repositories)
    # Fallback chain: participant_name -> student_name -> participant_id -> "—"
    p_name = assignment.get("participant_name") or assignment.get("student_name")
    if not p_name:
        pid = assignment.get("participant_id")
        p_name = str(pid) if isinstance(pid, int) else "—"

    p_name_esc = html.escape(p_name)
    a_name = assignment.get("assistant_name") or ""
    a_name_esc = html.escape(a_name)

    assistant_html = f'<div class="assistant">/ {a_name_esc}</div>' if a_name_esc else ""

    return f"""
    <div class="row {css_class}">
        <div class="time">{time}</div>
        <div class="assignment-text">{label_esc}</div>
        <div class="participant">{p_name_esc}</div>
        {assistant_html}
    </div>
    """
