"""
BaseApplicationFacade - Abstract base class for application facades.

This module defines the common interface for the application UI (PySide6 desktop and Android).
See spec://core/base_facade for specification.
"""

import logging
from abc import ABC
from typing import Any, Dict, List, Optional
from core.i18n import _, tr


class BaseApplicationFacade(ABC):
    """
    Abstract base class for application facades.

    Provides a unified interface for the UI layer, hiding the complexity
    of multiple services and underlying data layers.

    Subclasses:
    - ApplicationFacade (core/facade.py) - Desktop version with PySide6
    """

    def __init__(self, participant_service, schedule_service, error_service, event_bus):
        """
        Initialize the facade with required services.

        Args:
            participant_service: Service for participant management
            schedule_service: Service for schedule management
            error_service: Service for error handling
            event_bus: Event bus for publishing/subscribing to events
        """
        self.participants = participant_service
        self.schedule = schedule_service
        self.errors = error_service
        self.events = event_bus

    # === Week Management ===

    def get_week_data(self, week_id: int) -> Optional[Dict[str, Any]]:
        """Get data for a specific week."""
        return self.schedule.get_week_data(week_id)

    def get_week_conflicts(self, week_id: int) -> List[Dict[str, Any]]:
        """Get conflicts for a specific week."""
        return self.schedule.get_week_conflicts(week_id)

    def generate_preview_html(self, week_id: int) -> str:
        """Generate HTML preview for a week."""
        return self.schedule.generate_preview_html(week_id)

    def get_weeks_tree(self) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
        """Get weeks organized in a tree: {год: {месяц: [недели]}}.

        Форма совпадает с core/repositories/week_repository.py.
        """
        return self.schedule.get_weeks_tree()

    def get_week_special_event(self, week_id: int) -> Optional[str]:
        """Get special event type for a week."""
        return self.schedule.get_week_special_event(week_id)

    def set_special_event(self, week_id: int, event_type: str) -> bool:
        """Set special event for a week."""
        return self.schedule.set_special_event(week_id, event_type)

    def get_weeks_date_range(self, week_ids: List[int]) -> Dict[str, Any]:
        """Get date range for specified weeks."""
        return self.schedule.get_weeks_date_range(week_ids)

    def get_week_announcement(self, week_id: int) -> str:
        """Get announcement for a week."""
        return self.schedule.get_week_announcement(week_id)

    def save_week_announcement(self, week_id: int, text: str) -> bool:
        """Save announcement for a week."""
        return self.schedule.save_week_announcement(week_id, text)

    # === Assignment Management ===

    def auto_assign_week(self, week_id: int, only_empty: bool = True) -> Dict[str, Any]:
        """Авто-распределение недели. По умолчанию — только пустые пункты:
        ручные назначения и уже сделанные замены не перезаписываются."""
        return self.schedule.auto_assign_week(week_id, only_empty=only_empty)

    def auto_assign_weeks(self, week_ids: List[int]) -> Dict[str, Any]:
        """Авто-распределение нескольких недель по очереди (по порядку week_ids —
        от ранней к поздней, чтобы каждая следующая учитывала предыдущие).
        Заполняются только пустые пункты, назначенные остаются.

        Returns:
            {"success", "count": назначено всего, "weeks": сколько недель
             распределено, "error": текст первой ошибки или None}
        """
        total, done = 0, 0
        for week_id in week_ids:
            result = self.auto_assign_week(week_id) or {}  # only_empty=True по умолчанию
            if not result.get("success"):
                return {
                    "success": False,
                    "count": total,
                    "weeks": done,
                    "error": result.get("error") or _("Неизвестная ошибка"),
                }
            total += result.get("count", 0)
            done += 1
        return {"success": True, "count": total, "weeks": done, "error": None}

    def auto_assign_all(self) -> Dict[str, Any]:
        """Auto-assign participants to all weeks."""
        return self.schedule.auto_assign_all()

    def assign_participant(
        self, assignment_id: int, participant_id: Optional[int], role: str = "participant"
    ) -> bool:
        """Assign a participant to an assignment."""
        return self.schedule.assign_participant(assignment_id, participant_id, role)

    def set_slip_given(self, assignment_ids, given: bool = True) -> bool:
        """Отметить «🧾 листок выдан» у пунктов (given=False — снять отметку)."""
        return self.schedule.set_slip_given(assignment_ids, given)

    def restore_people(self, entries) -> bool:
        """Вернуть людей пунктов к записанному состоянию (отмена на доске месяца)."""
        return self.schedule.restore_people(entries)

    def swap_people(self, first_id: int, first_role: str, second_id: int, second_role: str) -> bool:
        """Поменять местами людей двух пунктов одной операцией."""
        return self.schedule.swap_people(first_id, first_role, second_id, second_role)

    def add_manual_assignment(
        self,
        week_id: int,
        text: str,
        section: str,
        duration: int,
        participant_id: Optional[int] = None,
    ) -> Optional[int]:
        """Add a custom assignment to a week."""
        return self.schedule.add_manual_assignment(
            week_id,
            text,
            section,
            duration,
            participant_id,
        )

    def update_assignment_duration(self, assignment_id: int, duration: int) -> bool:
        """Update the duration of an assignment in minutes."""
        return self.schedule.update_assignment_duration(assignment_id, duration)

    def update_manual_assignment(
        self,
        assignment_id: int,
        text: str,
        section: str,
        duration: int,
        participant_id: Optional[int] = None,
    ) -> bool:
        """Update a custom assignment."""
        return self.schedule.update_manual_assignment(
            assignment_id,
            text,
            section,
            duration,
            participant_id,
        )

    def delete_manual_assignment(self, assignment_id: int) -> bool:
        """Delete a custom assignment."""
        return self.schedule.delete_manual_assignment(assignment_id)

    def duplicate_manual_assignment(self, assignment_id: int) -> Optional[int]:
        """Duplicate a custom assignment."""
        return self.schedule.duplicate_manual_assignment(assignment_id)

    def reorder_week_assignments(self, week_id: int, ordered_ids: List[int]) -> bool:
        """Persist the manual order of assignments for a week."""
        return self.schedule.reorder_week_assignments(week_id, ordered_ids)

    def replace_week_assignments(self, week_id: int, assignments: List[Dict[str, Any]]) -> bool:
        """Restore a complete assignment snapshot for a week."""
        return self.schedule.replace_week_assignments(week_id, assignments)

    def clear_week_assignments(self, week_id: int) -> bool:
        """Clear all assignments for a week."""
        return self.schedule.clear_week_assignments(week_id)

    def has_assignments(self, week_id: int) -> bool:
        """Check if a week has any assignments."""
        return self.schedule.has_assignments(week_id)

    def get_assignment(self, assignment_id: int) -> Optional[Dict[str, Any]]:
        """Get assignment data by ID."""
        return self.schedule.get_assignment(assignment_id)

    def get_assignment_stats(self, start, end, group: str = "all") -> Dict[str, Any]:
        """Выступления за период для вкладки «Статистика»."""
        return self.schedule.get_assignment_stats(start, end, group)

    def get_assignment_config(self, section: Optional[str] = None, position: Optional[str] = None):
        """Get assignment configuration."""
        return self.schedule.get_assignment_config(section, position)

    def save_assignment_config(self, config_list: List[Dict[str, Any]]) -> bool:
        """Save assignment configuration."""
        return self.schedule.save_assignment_config(config_list)

    # === Participant Management ===

    def get_participants_list(self) -> List[Dict[str, Any]]:
        """Get list of all participants (alias for get_all_participants)."""
        return self.participants.get_all_participants()

    def set_unavailable(self, p_id: int, unavailable_from, unavailable_to) -> bool:
        """Отпуск «с … по …» участника без открытия карточки (None — снять)."""
        return self.participants.set_unavailable(p_id, unavailable_from, unavailable_to)

    def get_all_participants(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """Get all participants with their statistics."""
        return self.participants.get_all_participants(active_only=active_only)

    def get_participant(self, p_id: int) -> Optional[Dict[str, Any]]:
        """Get a specific participant by ID."""
        return self.participants.get_participant(p_id)

    def get_participant_history(self, p_id: int) -> List[Dict[str, Any]]:
        """Get assignment history for a participant."""
        return self.participants.get_participant_history(p_id)

    def add_participant(
        self,
        name: str,
        gender: str,
        service_type: str,
        quals: List[str],
        family_id: Optional[int] = None,
        personal_gap: Optional[int] = None,
        is_minor: bool = False,
        unavailable_from: Optional[Any] = None,
        unavailable_to: Optional[Any] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> Optional[int]:
        """Add a new participant."""
        return self.participants.add_participant(
            name,
            gender,
            service_type,
            quals,
            family_id,
            personal_gap,
            is_minor,
            unavailable_from,
            unavailable_to,
            email=email,
            phone=phone,
        )

    def update_participant(
        self,
        p_id: int,
        name: str,
        gender: str,
        service_type: str,
        quals: List[str],
        family_id: Optional[int] = None,
        personal_gap: Optional[int] = None,
        is_minor: bool = False,
        unavailable_from: Optional[Any] = None,
        unavailable_to: Optional[Any] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> bool:
        """Update an existing participant."""
        return self.participants.update_participant(
            p_id,
            name,
            gender,
            service_type,
            quals,
            family_id,
            personal_gap,
            is_minor,
            unavailable_from,
            unavailable_to,
            email=email,
            phone=phone,
        )

    def delete_participant(self, p_id: int) -> bool:
        """Delete a participant."""
        return self.participants.delete_participant(p_id)

    # === Import/Export ===

    def import_workbook(self, file_path: str) -> bool:
        """Import workbook data from EPUB file."""
        return self.schedule.import_workbook(file_path)

    def export_custom_docx(
        self, week_ids: List[int], output_path: str, mode: str = "compact"
    ) -> bool:
        """Export weeks to custom DOCX format."""
        return self.schedule.export_custom_docx(week_ids, output_path, mode)

    def export_to_s89(self, week_ids: List[int], output_path: str) -> bool:
        """Export weeks to S-89 form."""
        return self.schedule.export_to_s89(week_ids, output_path)

    def export_to_txt(self, week_ids: List[int], output_path: str) -> bool:
        """Export weeks to plain text format."""
        return self.schedule.export_to_txt(week_ids, output_path)

    def export_to_pdf(self, week_ids: List[int], output_path: str) -> bool:
        """Export weeks to PDF format."""
        return self.schedule.export_to_pdf(week_ids, output_path)

    def print_schedule(self, week_ids: List[int], printer) -> bool:
        """Напечатать расписание на принтер (QPrinter) — как PDF, две недели на лист."""
        return self.schedule.print_schedule(week_ids, printer)

    # === Settings ===

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a setting value."""
        return self.schedule.get_setting(key, default)

    def save_setting(self, key: str, value: Any) -> bool:
        """Save a setting value."""
        return self.schedule.save_setting(key, value)

    # === Year Management ===

    def prepare_future_year(self, year: int) -> Dict[str, Any]:
        """Create missing empty weeks for a future year."""
        return self.schedule.prepare_future_year(year)

    def plan_future_year(self) -> Dict[str, int]:
        """Year to offer for «Будущий год» and how many weeks are missing."""
        return self.schedule.plan_future_year()

    # === Error Handling ===

    def handle_error(self, exception: Exception, context: str = "") -> None:
        """Handle an exception."""
        return self.errors.handle_exception(exception, context)

    def report_error(self, message: str, context: str = "") -> None:
        """Report an error message."""
        return self.errors.report_error(message, context)

    # === Notifications ===

    def send_notifications(
        self,
        week_ids: List[int],
        participant_ids: List[int] = None,
        progress_callback=None,
        custom_messages: Optional[dict] = None,
    ):
        """
        Отправляет email-уведомления участникам с заданиями в указанных неделях.

        Args:
            week_ids: Список ID недель для рассылки.
            participant_ids: Опционально — список IDparticipants, которым отправлять письма.
                            Если не указано — отправляет всем участникам с заданиями.
            progress_callback: Опционально — callable(current, total, name)
                               для обновления прогресс-бара.
            custom_messages: Опционально — {participant_id: {"subject": str, "note": str, "custom_body": str}}

        Returns:
            NotificationResult со статистикой отправки.
        """
        from core.notification_service import NotificationService

        smtp_host = self.get_setting("smtp_host", "smtp.gmail.com")
        try:
            smtp_port = int(self.get_setting("smtp_port", 465))
        except (ValueError, TypeError):
            smtp_port = 465
        smtp_user = self.get_setting("smtp_user", "")
        smtp_password = self.get_setting("smtp_password", "")
        sender_name = self.get_setting("smtp_sender_name", "")
        meeting_day = self.get_setting("meeting_day", "")
        meeting_time = self.get_setting("meeting_time", "19:00")
        cong_name = self.get_setting("cong_name", "")

        service = NotificationService(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            sender_name=sender_name,
            meeting_day=meeting_day,
            meeting_time=meeting_time,
            cong_name=cong_name,
        )
        return service.send_assignment_notifications(
            week_ids=week_ids,
            participant_ids=participant_ids,
            db_manager=self.schedule.db,
            progress_callback=progress_callback,
            custom_messages=custom_messages,
        )

    def send_single_notification(
        self,
        participant_id: int,
        week_ids: List[int],
        custom_subject: Optional[str] = None,
        custom_note: Optional[str] = None,
        custom_body: Optional[str] = None,
    ) -> bool:
        """
        Отправляет уведомление конкретному участнику на выбранные недели.

        Returns:
            True при успешной отправке, False при ошибке.
        """
        custom_messages = None
        if custom_subject or custom_note or custom_body:
            custom_messages = {
                participant_id: {
                    "subject": custom_subject,
                    "note": custom_note,
                    "custom_body": custom_body,
                }
            }

        res = self.send_notifications(
            week_ids=week_ids,
            participant_ids=[participant_id],
            custom_messages=custom_messages,
        )
        return res.sent > 0

    CANDIDATE_STATS_WEEKS = 26

    def get_candidate_stats(
        self, week_id: int, exclude_assignment_id: Optional[int] = None
    ) -> Dict[int, Dict[str, Any]]:
        """
        Подсказки для выбора участника на неделю week_id — одним запросом.

        Returns:
            {participant_id: {"count": заданий за 26 недель до этой недели,
                              "last_date": date | None, "last_text": str,
                              "next_date": date | None, "next_text": str — ближайшее
                                  задание после этой недели,
                              "busy": уже назначен на эту неделю,
                              "away": неделя у него исключена или в отпуске (с … по …)}}
        Считаются и основные задания, и роль напарника. Пункт, для которого
        выбирают участника (exclude_assignment_id), занятость не создаёт.
        """
        from datetime import date, timedelta

        from sqlalchemy import select

        from core.models import Assignment, AssignmentStatus, Week

        def _as_date(value):
            if isinstance(value, str):
                return date.fromisoformat(value[:10])
            return value

        def empty():
            return {
                "count": 0,
                "last_date": None,
                "last_text": "",
                "busy": False,
                "next_date": None,
                "next_text": "",
            }

        stats: Dict[int, Dict[str, Any]] = {}
        with self.schedule.db.get_session() as session:
            week = session.get(Week, week_id)
            ref = _as_date(week.start_date) if week else None
            if ref is None:
                return stats
            window_start = ref - timedelta(weeks=self.CANDIDATE_STATS_WEEKS)
            rows = session.execute(
                select(
                    Assignment.id,
                    Assignment.participant_id,
                    Assignment.assistant_id,
                    Assignment.week_id,
                    Assignment.assignment_text,
                    Week.start_date,
                )
                .join(Week, Week.id == Assignment.week_id)
                .where(Assignment.status == AssignmentStatus.ASSIGNED.value)
            ).all()
            # как в автоназначении: исключённая неделя (понедельник её начала) или отпуск
            away_ids = self._away_by_week(session, {week_id: ref})[week_id]

        for a_id, main_id, assistant_id, a_week_id, text, start in rows:
            start = _as_date(start)
            for pid, suffix in ((main_id, ""), (assistant_id, " (напарник)")):
                if not pid:
                    continue
                st = stats.setdefault(pid, empty())
                if a_week_id == week_id:
                    st["busy"] = st["busy"] or a_id != exclude_assignment_id
                elif start and start < ref:
                    if start >= window_start:
                        st["count"] += 1
                    if st["last_date"] is None or start > st["last_date"]:
                        st["last_date"] = start
                        st["last_text"] = f"{text or ''}{suffix}"
                elif start and start > ref:
                    if st["next_date"] is None or start < st["next_date"]:
                        st["next_date"] = start
                        st["next_text"] = f"{text or ''}{suffix}"
        for pid in away_ids:
            stats.setdefault(pid, empty())["away"] = True
        return stats

    def get_month_board(self, week_ids: List[int]) -> Dict[str, Any]:
        """Доска месяца по неделям week_ids (по порядку колонок).

        См. core/month_board.build_month_board — там описан результат.
        История назначений и старейшины берутся одной выборкой на всю доску.
        """
        from sqlalchemy import select

        from core.models import Assignment, AssignmentStatus, Participant, Week
        from core.month_board import ELDER, _as_date, build_month_board

        weeks = [data for data in (self.get_week_data(wid) for wid in week_ids) if data]
        conflicts = {}
        for data in weeks:
            week_id = data["week"].get("id")
            try:
                conflicts[week_id] = self.get_week_conflicts(week_id) or []
            except Exception:
                logging.getLogger(__name__).exception("Доска месяца: конфликты недели %s", week_id)
                conflicts[week_id] = []

        with self.schedule.db.get_session() as session:
            rows = session.execute(
                select(Assignment.participant_id, Assignment.assistant_id, Week.start_date)
                .join(Week, Week.id == Assignment.week_id)
                .where(Assignment.status == AssignmentStatus.ASSIGNED.value)
            ).all()
            elder_ids = (
                session.execute(select(Participant.id).where(Participant.service_type == ELDER))
                .scalars()
                .all()
            )
            away = self._away_by_week(
                session,
                {
                    data["week"].get("id"): _as_date(data["week"].get("start_date"))
                    for data in weeks
                },
            )

        history = []
        for main_id, assistant_id, start in rows:
            for pid in (main_id, assistant_id):
                if pid:
                    history.append((pid, start))
        notifications = {}
        for data in weeks:
            week_id = data["week"].get("id")
            try:
                notifications[week_id] = self.get_week_notification_statuses(week_id)
            except Exception:
                logging.getLogger(__name__).exception(
                    "Доска месяца: уведомления недели %s", week_id
                )
                notifications[week_id] = {}
        return build_month_board(weeks, history, elder_ids, conflicts, notifications, away)

    def get_away_assignments(self, participant_id: int, today=None) -> List[Dict[str, Any]]:
        """Задания участника на неделях, когда его не будет (отпуск «с … по …»
        или исключённая неделя), начиная с текущей недели.

        [{"assignment_id", "week_id", "start_date", "text", "role"}] по дате;
        role — "participant" (главный) или "assistant".
        """
        from datetime import date, timedelta

        from sqlalchemy import or_, select

        from core.models import Assignment, AssignmentStatus, Week

        today = today or date.today()
        with self.schedule.db.get_session() as session:
            rows = session.execute(
                select(
                    Assignment.id,
                    Assignment.week_id,
                    Week.start_date,
                    Assignment.assignment_text,
                    Assignment.participant_id,
                )
                .join(Week, Week.id == Assignment.week_id)
                .where(
                    Assignment.status == AssignmentStatus.ASSIGNED.value,
                    Week.start_date >= today - timedelta(days=6),
                    or_(
                        Assignment.participant_id == participant_id,
                        Assignment.assistant_id == participant_id,
                    ),
                )
                .order_by(Week.start_date)
            ).all()
            away = self._away_by_week(session, {row.week_id: row.start_date for row in rows})
        return [
            {
                "assignment_id": row.id,
                "week_id": row.week_id,
                "start_date": row.start_date,
                "text": row.assignment_text,
                "role": "participant" if row.participant_id == participant_id else "assistant",
            }
            for row in rows
            if participant_id in away.get(row.week_id, ())
        ]

    def replace_away_assignments(
        self, items: List[Dict[str, Any]], auto: bool = True
    ) -> Dict[str, Any]:
        """Снять участника с заданий (items из get_away_assignments) и, если
        auto, заполнить освободившиеся места «Авто» (только пустые пункты).

        Возвращает {"released": N, "replacements": [{"start_date", "text", "name"}]}
        — кто встал на освободившееся место (name=None — замены не нашлось).
        """
        from core.models import Assignment, Participant

        for item in items:
            self.assign_participant(item["assignment_id"], None, item["role"])
        if auto and items:
            week_ids = sorted(
                {i["week_id"] for i in items},
                key=lambda w: next(i["start_date"] for i in items if i["week_id"] == w),
            )
            self.auto_assign_weeks(week_ids)
        replacements = []
        with self.schedule.db.get_session() as session:
            for item in items:
                a = session.get(Assignment, item["assignment_id"])
                pid = None
                if a is not None:
                    pid = a.assistant_id if item["role"] == "assistant" else a.participant_id
                p = session.get(Participant, pid) if pid else None
                replacements.append(
                    {
                        "start_date": item["start_date"],
                        "text": item["text"],
                        "name": p.name if p else None,
                    }
                )
        return {"released": len(items), "replacements": replacements}

    @staticmethod
    def _away_by_week(session, starts: Dict[int, Any]) -> Dict[int, set]:
        """{week_id: участники, недоступные на неделе}: отпуск «с … по …»
        из карточки или исключённая неделя («Сменный график»), как в автоназначении.
        starts — {week_id: дата начала недели}."""
        from sqlalchemy import select

        from core.models import Participant, ParticipantExcludedWeek
        from core.month_board import on_leave

        starts = {wid: start for wid, start in starts.items() if wid and start}
        away: Dict[int, set] = {wid: set() for wid in starts}
        if not starts:
            return away
        week_by_start = {}
        for wid, start in starts.items():
            week_by_start.setdefault(start, []).append(wid)
        for pid, week_start in session.execute(
            select(
                ParticipantExcludedWeek.participant_id, ParticipantExcludedWeek.week_start
            ).where(ParticipantExcludedWeek.week_start.in_(list(week_by_start)))
        ).all():
            for wid in week_by_start.get(week_start, ()):
                away[wid].add(pid)
        for pid, u_from, u_to in session.execute(
            select(Participant.id, Participant.unavailable_from, Participant.unavailable_to).where(
                (Participant.unavailable_from.isnot(None))
                | (Participant.unavailable_to.isnot(None))
            )
        ).all():
            for wid, start in starts.items():
                if on_leave(u_from, u_to, start):
                    away[wid].add(pid)
        return away

    def get_leader_dashboard(self, today=None) -> Dict[str, Any]:
        """Пульт руководителя встречи: дела и ближайшая встреча.

        Смотрит HORIZON_WEEKS недель начиная с текущей и весь следующий
        месяц (есть ли программа, распределён ли). См. core/leader_dashboard.
        Возвращает {"todos", "meeting", "board"}.
        """
        from datetime import date, timedelta

        from core.leader_dashboard import HORIZON_WEEKS, build_todos, first_steps, next_meeting
        from core.month_board import _as_date

        today = today or date.today()
        weeks = []  # (start, week_id, «Месяц год»)
        for year, months in self.get_weeks_tree().items():
            for month_name, month_weeks in months.items():
                for week in month_weeks:
                    start = _as_date(week.get("start_date"))
                    if start:
                        weeks.append((start, week["id"], f"{month_name} {year}"))
        weeks.sort()

        upcoming = [wid for start, wid, _ in weeks if start + timedelta(days=6) >= today][
            :HORIZON_WEEKS
        ]
        board = self.get_month_board(upcoming)

        first = date(today.year, today.month, 1)
        nm = (first + timedelta(days=32)).replace(day=1)
        nm_weeks = [
            (wid, title)
            for start, wid, title in weeks
            if (start.year, start.month) == (nm.year, nm.month)
        ]
        months_ru = tuple(
            tr(m)
            for m in (
                "Январь",
                "Февраль",
                "Март",
                "Апрель",
                "Май",
                "Июнь",
                "Июль",
                "Август",
                "Сентябрь",
                "Октябрь",
                "Ноябрь",
                "Декабрь",
            )
        )
        next_month = {
            "title": nm_weeks[0][1] if nm_weeks else f"{months_ru[nm.month - 1]} {nm.year}",
            "week_ids": [wid for wid, _ in nm_weeks],
            "assigned": 0,
            "total": 0,
        }
        if nm_weeks:
            summary = self.get_month_board(next_month["week_ids"])["summary"]
            next_month.update(assigned=summary["assigned"], total=summary["total"])

        return {
            "todos": build_todos(board, today, next_month),
            "meeting": next_meeting(board, today),
            "board": board,
            "first_steps": first_steps(self._first_steps_counts()),
        }

    def _first_steps_counts(self) -> Dict[str, Any]:
        """Сколько уже заполнено — для «Первых шагов» на пустой базе."""
        from sqlalchemy import func, select

        from core.models import Assignment, Participant, Setting, Week, participant_qualifications

        with self.schedule.db.get_session() as session:

            def count(query):
                return session.execute(query).scalar() or 0

            cong = session.get(Setting, "cong_name")
            return {
                "has_congregation": bool(cong and (cong.value or "").strip()),
                "participants": count(select(func.count(Participant.id))),
                "with_qualifications": count(
                    select(func.count(func.distinct(participant_qualifications.c.participant_id)))
                ),
                "weeks": count(select(func.count(Week.id))),
                "assigned": count(
                    select(func.count(Assignment.id)).where(Assignment.participant_id.is_not(None))
                ),
            }

    def get_participant_assignment_week_ids(
        self,
        participant_id: int,
        current_week_id: Optional[int] = None,
        limit: int = 4,
    ) -> List[int]:
        """
        Возвращает список ID недель с назначениями для участника.

        Если передан current_week_id — сначала проверяет его, затем ищет
        ближайшие недели (будущие, затем прошлые), где участник назначен.
        Возвращает не более `limit` недель.
        """
        from sqlalchemy import or_, select

        from datetime import date as _date

        from core.models import Assignment, AssignmentStatus, Week

        with self.schedule.db.get_session() as session:
            query = (
                select(Assignment.week_id, Week.start_date)
                .join(Week, Week.id == Assignment.week_id)
                .where(
                    or_(
                        Assignment.participant_id == participant_id,
                        Assignment.assistant_id == participant_id,
                    )
                )
                .where(Assignment.status == AssignmentStatus.ASSIGNED.value)
                .distinct()
            )
            # Порядок — по датам недель: номер записи с датой не совпадает
            dates = {wid: start or _date.min for wid, start in session.execute(query).all()}
            current_date = None
            if current_week_id is not None:
                current_date = session.execute(
                    select(Week.start_date).where(Week.id == current_week_id)
                ).scalar()

        if not dates:
            # Нет назначений вообще — возвращаем текущую неделю
            return [current_week_id] if current_week_id else []

        def key(wid):
            return (dates[wid], wid)

        if current_week_id is not None:
            # Сначала текущая и будущие (по возрастанию дат), затем прошлые (по убыванию)
            pivot = (current_date or _date.min, current_week_id) if current_date else None
            if pivot is None:
                ordered = sorted(dates, key=key)
            else:
                future = sorted([w for w in dates if key(w) >= pivot], key=key)
                past = sorted([w for w in dates if key(w) < pivot], key=key, reverse=True)
                ordered = future + past
        else:
            ordered = sorted(dates, key=key)

        return ordered[:limit]

    def preview_participant_email(
        self,
        participant_id: int,
        week_ids: List[int],
        custom_note: Optional[str] = None,
        custom_body: Optional[str] = None,
    ) -> str:
        """
        Возвращает HTML-превью письма для конкретного участника.
        """
        from core.notification_service import NotificationService

        smtp_host = self.get_setting("smtp_host", "smtp.gmail.com")
        try:
            smtp_port = int(self.get_setting("smtp_port", 465))
        except (ValueError, TypeError):
            smtp_port = 465
        smtp_user = self.get_setting("smtp_user", "")
        smtp_password = self.get_setting("smtp_password", "")
        sender_name = self.get_setting("smtp_sender_name", "")
        meeting_day = self.get_setting("meeting_day", "")
        meeting_time = self.get_setting("meeting_time", "19:00")
        cong_name = self.get_setting("cong_name", "")

        service = NotificationService(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            sender_name=sender_name,
            meeting_day=meeting_day,
            meeting_time=meeting_time,
            cong_name=cong_name,
        )
        p_data = service.collect_participant_assignments(week_ids, self.schedule.db, participant_id)
        if not p_data:
            return (
                "<p style='color: #777; font-style: italic;'>"
                + _("Нет заданий на выбранные недели")
                + "</p>"
            )

        return service.preview_for_participant(
            p_data["name"],
            p_data["weeks"],
            custom_note=custom_note,
            custom_body=custom_body,
        )

    def participant_calendar_ics(self, participant_id: int, week_ids: List[int]) -> str:
        """Файл календаря (.ics) с заданиями участника на недели week_ids.

        Тот же файл, что прикладывается к письму, — для тех, у кого нет почты:
        его можно переслать в мессенджере. Пустая строка — заданий нет.
        """
        from core.notification_service import NotificationService

        service = NotificationService(
            meeting_day=self.get_setting("meeting_day", ""),
            meeting_time=self.get_setting("meeting_time", "19:00"),
            cong_name=self.get_setting("cong_name", ""),
        )
        p_data = service.collect_participant_assignments(week_ids, self.schedule.db, participant_id)
        if not p_data:
            return ""
        return service._build_ics_for_participant(p_data)

    def get_pair_history(self, participant_id: int, week_id: int) -> Dict[int, Dict[str, Any]]:
        """С кем участник уже выступал парой до недели week_id.

        Returns:
            {id другого участника: {"count": сколько раз в паре, "last_date": date}}
            Пара — основной участник и напарник одного задания, в любом порядке.
        """
        from datetime import date

        from sqlalchemy import or_, select

        from core.models import Assignment, AssignmentStatus, Week

        def _as_date(value):
            if isinstance(value, str):
                return date.fromisoformat(value[:10])
            return value

        pairs: Dict[int, Dict[str, Any]] = {}
        if not participant_id:
            return pairs
        with self.schedule.db.get_session() as session:
            week = session.get(Week, week_id)
            ref = _as_date(week.start_date) if week else None
            if ref is None:
                return pairs
            rows = session.execute(
                select(Assignment.participant_id, Assignment.assistant_id, Week.start_date)
                .join(Week, Week.id == Assignment.week_id)
                .where(Assignment.status == AssignmentStatus.ASSIGNED.value)
                .where(Assignment.assistant_id.is_not(None))
                .where(
                    or_(
                        Assignment.participant_id == participant_id,
                        Assignment.assistant_id == participant_id,
                    )
                )
            ).all()
        for main_id, assistant_id, start in rows:
            start = _as_date(start)
            if not start or start >= ref:
                continue
            other = assistant_id if main_id == participant_id else main_id
            if not other or other == participant_id:
                continue
            st = pairs.setdefault(other, {"count": 0, "last_date": None})
            st["count"] += 1
            if st["last_date"] is None or start > st["last_date"]:
                st["last_date"] = start
        return pairs

    def test_smtp_connection(self):
        """
        Проверяет SMTP-соединение с текущими настройками.

        Returns:
            (success: bool, message: str)
        """
        from core.notification_service import NotificationService

        smtp_host = self.get_setting("smtp_host", "smtp.gmail.com")
        smtp_port_raw = str(self.get_setting("smtp_port", "465")).strip()
        smtp_port = int(smtp_port_raw) if smtp_port_raw.isdigit() else 465
        smtp_user = self.get_setting("smtp_user", "")
        smtp_password = self.get_setting("smtp_password", "")
        sender_name = self.get_setting("smtp_sender_name", "")

        service = NotificationService(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            sender_name=sender_name,
        )
        return service.test_connection()

    def get_last_notification(self, participant_id: int, week_ids: List[int]) -> Optional[dict]:
        """
        Получает статус последней отправки уведомления дляparticipant.

        Returns:
            dict with keys: sent_at, status, error (or None if no history)
        """
        from sqlalchemy import select

        from core.models import NotificationHistory

        with self.schedule.db.get_session() as session:
            stmt = (
                select(NotificationHistory)
                .filter(
                    NotificationHistory.participant_id == participant_id,
                    NotificationHistory.week_id.in_(week_ids),
                )
                .order_by(NotificationHistory.sent_at.desc())
                .limit(1)
            )

            item = session.execute(stmt).scalars().first()
            if item:
                return {
                    "sent_at": item.sent_at,
                    "status": item.status,
                    "error": item.error_message,
                }
        return None

    def get_week_notification_statuses(self, week_id: int) -> dict:
        """
        Возвращает статусы последнего уведомления для каждого участника недели
        за ОДИН запрос к БД (для отображения индикаторов в расписании).

        Returns:
            {participant_id: {"sent_at": datetime, "status": str, "error": str|None}}
        """
        from sqlalchemy import func, select

        from core.models import NotificationHistory

        result = {}
        with self.schedule.db.get_session() as session:
            # Подзапрос: MAX(sent_at) для каждого participant_id на данную неделю
            subq = (
                select(
                    NotificationHistory.participant_id,
                    func.max(NotificationHistory.sent_at).label("max_sent_at"),
                )
                .where(NotificationHistory.week_id == week_id)
                .group_by(NotificationHistory.participant_id)
                .subquery()
            )
            # Основной запрос: объединяем с таблицей для получения status/error
            stmt = (
                select(NotificationHistory)
                .join(
                    subq,
                    (NotificationHistory.participant_id == subq.c.participant_id)
                    & (NotificationHistory.sent_at == subq.c.max_sent_at),
                )
                .where(NotificationHistory.week_id == week_id)
            )

            rows = session.execute(stmt).scalars().all()
            for row in rows:
                result[row.participant_id] = {
                    "sent_at": row.sent_at,
                    "status": row.status,
                    "error": row.error_message,
                    "subject": row.subject,
                    "response": None,
                }
            # ответ участника: "confirmed" | "declined" (core/notification_replies.py)
            for pid, response in self._week_responses(session, week_id).items():
                result.setdefault(
                    pid, {"sent_at": None, "status": None, "error": None, "subject": None}
                )
                result[pid]["response"] = response
        return result

    @staticmethod
    def _week_responses(session, week_id: int) -> Dict[int, str]:
        from sqlalchemy import select

        from core.models import NotificationResponse

        rows = session.execute(
            select(NotificationResponse.participant_id, NotificationResponse.response).where(
                NotificationResponse.week_id == week_id
            )
        ).all()
        return {pid: response for pid, response in rows}

    def set_notification_response(
        self,
        participant_id: int,
        week_id: int,
        response: Optional[str],
        source: str = "manual",
        responded_at=None,
    ) -> None:
        """Отметить ответ участника о неделе («confirmed» / «declined»), None — снять."""
        from core.events import Event
        from core.models import NotificationResponse, utc_now

        with self.schedule.db.get_session() as session:
            row = (
                session.query(NotificationResponse)
                .filter_by(participant_id=participant_id, week_id=week_id)
                .one_or_none()
            )
            if response is None:
                if row is not None:
                    session.delete(row)
            else:
                if row is None:
                    row = NotificationResponse(participant_id=participant_id, week_id=week_id)
                    session.add(row)
                row.response = response
                row.source = source
                row.responded_at = responded_at or utc_now()  # в UTC, как sent_at
            session.commit()
        self.events.emit(Event.ASSIGNMENT_CHANGED, week_id=week_id)

    def apply_notification_replies(self, replies) -> int:
        """Записать разобранные ответы [(дата письма, Reply)]. Ответ учитывается,
        только если он пришёл после последнего отправленного уведомления об этой
        неделе (старый ответ не «подтверждает» повторное письмо) и он новее уже
        записанного. Ответ с чужого адреса (не из email участника) не
        учитывается: метку в теме видит любой, кому переслали письмо.
        Возвращает, сколько отметок поставлено или изменено."""
        import logging
        import re

        from sqlalchemy import func, select

        from core.events import Event
        from core.models import NotificationHistory, NotificationResponse, Participant
        from core.notification_replies import normalize_email

        applied = 0
        with self.schedule.db.get_session() as session:
            for when, reply in replies:
                if reply.sender:
                    participant = session.get(Participant, reply.participant_id)
                    allowed = {
                        normalize_email(a)
                        for a in re.split(
                            r"[,;\s]+", (participant.email or "") if participant else ""
                        )
                        if a.strip()
                    }
                    if normalize_email(reply.sender) not in allowed:
                        logging.getLogger(__name__).warning(
                            "Ответ на уведомление с чужого адреса %s (участник %s) пропущен",
                            reply.sender,
                            reply.participant_id,
                        )
                        continue
                for week_id in reply.week_ids:
                    last_sent = session.execute(
                        select(func.max(NotificationHistory.sent_at)).where(
                            NotificationHistory.participant_id == reply.participant_id,
                            NotificationHistory.week_id == week_id,
                            NotificationHistory.status == "success",
                        )
                    ).scalar()
                    if last_sent is None or when < last_sent:
                        continue
                    row = (
                        session.query(NotificationResponse)
                        .filter_by(participant_id=reply.participant_id, week_id=week_id)
                        .one_or_none()
                    )
                    if row is not None and row.responded_at and row.responded_at >= when:
                        continue
                    if row is None:
                        row = NotificationResponse(
                            participant_id=reply.participant_id, week_id=week_id
                        )
                        session.add(row)
                    row.response, row.source, row.responded_at = reply.response, "email", when
                    applied += 1
            session.commit()
        if applied:
            self.events.emit(Event.ASSIGNMENT_CHANGED)
        return applied

    def check_notification_replies(self) -> Dict[str, Any]:
        """Прочитать ответы на уведомления из почты (IMAP) и отметить их.

        Returns: {"success", "applied", "unclear", "error"}
        """
        from core.notification_service import NotificationService

        user = self.get_setting("smtp_user", "")
        password = self.get_setting("smtp_password", "")
        if not user or not password:
            return {
                "success": False,
                "applied": 0,
                "unclear": 0,
                "error": _("Не настроена почта: укажите логин и пароль приложения в «Настройках»"),
            }
        service = NotificationService(smtp_user=user, smtp_password=password)
        try:
            replies, unclear = service.fetch_replies()
        except Exception as e:
            return {"success": False, "applied": 0, "unclear": 0, "error": str(e)}
        return {
            "success": True,
            "applied": self.apply_notification_replies(replies),
            "unclear": unclear,
            "error": None,
        }

    def get_notification_log(
        self,
        participant_id: Optional[int] = None,
        week_id: Optional[int] = None,
        status_filter: Optional[str] = None,
        limit: int = 300,
    ) -> List[dict]:
        """
        Возвращает полный журнал уведомлений для отображения в диалоге.

        Args:
            participant_id: Если задан — только для этого участника.
            week_id: Если задан — только для этой недели.
            status_filter: 'success' | 'error' | None (все).
            limit: Максимальное количество записей.

        Returns:
            [{
                "id": int,
                "participant_id": int,
                "participant_name": str,
                "participant_email": str|None,
                "week_id": int,
                "week_title": str,
                "sent_at": datetime,
                "status": str,
                "error": str|None,
                "subject": str|None,
            }, ...]  — отсортированы по sent_at DESC
        """
        from sqlalchemy import select

        from core.models import NotificationHistory, Participant, Week

        rows = []
        with self.schedule.db.get_session() as session:
            stmt = (
                select(NotificationHistory)
                .order_by(NotificationHistory.sent_at.desc())
                .limit(limit)
            )

            if participant_id is not None:
                stmt = stmt.where(NotificationHistory.participant_id == participant_id)
            if week_id is not None:
                stmt = stmt.where(NotificationHistory.week_id == week_id)
            if status_filter:
                stmt = stmt.where(NotificationHistory.status == status_filter)

            items = session.execute(stmt).scalars().all()

            # Кешируем участников и недели
            p_cache: dict = {}
            w_cache: dict = {}

            for item in items:
                pid = item.participant_id
                wid = item.week_id

                if pid not in p_cache:
                    p = session.get(Participant, pid)
                    p_cache[pid] = (p.name, p.email) if p else (f"Участник #{pid}", None)
                if wid not in w_cache:
                    w = session.get(Week, wid)
                    w_cache[wid] = w.week_title if w else f"Неделя #{wid}"

                p_name, p_email = p_cache[pid]
                rows.append(
                    {
                        "id": item.id,
                        "participant_id": pid,
                        "participant_name": p_name,
                        "participant_email": p_email,
                        "week_id": wid,
                        "week_title": w_cache[wid],
                        "sent_at": item.sent_at,
                        "status": item.status,
                        "error": item.error_message,
                        "subject": item.subject,
                    }
                )
        return rows

    def get_notification_preview(self, week_ids: List[int]) -> List[dict]:
        """
        Возвращает список участников с их заданиями для предпросмотра в диалоге.

        Returns:
            [{"id": int, "name": str, "email": str|None, "tasks": [str, ...]}, ...]
        """
        from sqlalchemy import select

        from core.models import Assignment, Participant, Week
        from core.notification_service import NotificationService

        result = []
        seen: dict = {}

        with self.schedule.db.get_session() as session:
            weeks_map = {}
            for wid in week_ids:
                w = session.get(Week, wid)
                if w:
                    weeks_map[wid] = w

            assignments = (
                session.execute(
                    select(Assignment)
                    .where(Assignment.week_id.in_(week_ids))
                    .where(Assignment.status == "assigned")
                )
                .scalars()
                .all()
            )

            for a in assignments:
                week = weeks_map.get(a.week_id)
                task_text = a.assignment_text
                if a.duration:
                    task_text += f" ({a.duration} мин.)"

                for pid, role_suffix in [
                    (a.participant_id, ""),
                    (a.assistant_id, " (напарник)"),
                ]:
                    if not pid:
                        continue
                    if pid not in seen:
                        p = session.get(Participant, pid)
                        if not p:
                            continue
                        seen[pid] = {
                            "id": pid,
                            "name": p.name,
                            "email": p.email,
                            "tasks": [],
                        }
                    seen[pid]["tasks"].append(task_text + role_suffix)

        return sorted(seen.values(), key=lambda x: x["name"])

    def import_emails_from_xlsx(self, xlsx_path: str) -> dict:
        """
        Импортирует email и телефоны из Excel-файла в БД.

        Args:
            xlsx_path: Путь к XLSX-файлу «Список возвещателей.xlsx».

        Returns:
            Словарь со статистикой (см. scripts/import_emails_from_xlsx.py).
        """
        import os

        from core.settings import Settings

        settings = Settings.load()
        db_path = settings.db_path

        # Import function from scripts
        import sys

        scripts_dir = os.path.join(os.path.dirname(__file__), "..", "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)

        from import_emails_from_xlsx import import_emails_from_xlsx as _import

        return _import(xlsx_path, db_path)
