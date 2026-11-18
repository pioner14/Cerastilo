"""
Auto Assignment Service - Business logic for automatic assignment distribution.

This service handles the automatic assignment of participants to schedule tasks,
implementing fair rotation and qualification-based filtering.

Reference: spec://services/auto_assignment
"""

import logging
import random
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, case, func, or_, select, update

from core.mappers import ParticipantMapper
from core.models import (
    Assignment,
    AssignmentConfig,
    AssignmentStatus,
    Participant,
    ParticipantPositionConfig,
    Setting,
    Week,
)
from core.assignment_rules import family_assistant_allowed, resolve_assignment_config
from core.chairman_talk import (
    counted_assignment,
    is_chairman_talk,
    is_role_talk,
    role_holders,
    role_setting,
)
from core.chairman_talk import sync_rows as sync_chairman_talks
from core.utils import date_to_datetime
from core.candidate_filter_service import CandidateFilterService


class AutoAssignmentService:
    """
    Service for automatic assignment distribution.

    Responsibilities:
    - Filter candidates based on qualifications and constraints
    - Select best candidate using rotation algorithm
    - Assign assistants for applicable assignments
    - Coordinate the entire assignment process

    Reference: spec://services/auto_assignment
    """

    # Section priority for assignment order
    SECTION_PRIORITY = {"fixed": 0, "cbs": 1, "treasures": 2, "living": 3, "ministry": 4}

    # Weight constants for selection algorithm
    NEVER_ASSIGNED_DAYS_WEIGHT = 365  # Days weight for never-assigned participants
    NEVER_ASSIGNED_GAP_MARKER = 999  # Position gap marker for never-assigned
    POSITION_GAP_WEIGHT_FACTOR = 0.1  # Factor for position gap in weighted selection
    MIN_POOL_SIZE_FOR_ROTATION = 3  # Minimum candidates for rotation pool
    PAIR_GAP_WEEKS = 12  # Minimum weeks before the same pair can be assigned together again
    # Окно (недель до текущей), за которое считается нагрузка для очереди.
    # Счёт «за всё время» заставлял нового брата получать почти всё, пока он
    # не догонит остальных по их многолетней истории; будущие недели не считаем.
    LOAD_WINDOW_WEEKS = 26

    def __init__(
        self,
        session_factory,
        week_repository=None,
        assignment_repository=None,
        participant_repository=None,
        deterministic=False,
        seed=None,
    ):
        self.session_factory = session_factory
        self.week_repo = week_repository
        self.assignment_repo = assignment_repository
        self.participant_repo = participant_repository
        self.logger = logging.getLogger(__name__)
        self._assign_lock = threading.RLock()
        self._deterministic = deterministic
        self._seed = seed
        self._selection_counter = 0  # For deterministic seed rotation

        # candidate_filter is (re-)created in _do_auto_assign_week with DB values
        self.candidate_filter = CandidateFilterService(min_gap=2)

    def auto_assign_week(
        self, week_id: int, session=None, only_empty: bool = False
    ) -> Dict[str, Any]:
        """
        Automatically assign participants to all assignments in a week.

        Args:
            week_id: ID of the week to process
            session: Optional SQLAlchemy session (if None, creates new)
            only_empty: заполнять только пустые пункты (и недостающих напарников);
                уже назначенных не трогать и не ставить их второй раз за неделю

        Returns:
            Dict with 'success', 'count', and optional 'message' keys
        """
        with self._assign_lock:
            should_close_session = session is None
            if session is None:
                session = self.session_factory()

            try:
                return self._do_auto_assign_week(session, week_id, only_empty=only_empty)
            finally:
                if should_close_session:
                    session.close()

    def _do_auto_assign_week(
        self,
        session,
        week_id: int,
        truncate_log: bool = True,
        consider_future: bool = True,
        only_empty: bool = False,
    ) -> Dict[str, Any]:
        """consider_future — учитывать назначения на более поздних неделях
        (интервалы в обе стороны). При «распределить всё» они всё равно будут
        перезаписаны, поэтому там False."""
        """Internal implementation of auto_assign_week."""
        debug_logger = self._setup_debug_logger(truncate_log=truncate_log)
        debug_logger.info(f"=== START AUTO-ASSIGN WEEK {week_id} ===")

        # 1. Load settings
        gap_setting = session.execute(
            select(Setting.value).where(Setting.key == "min_assignment_gap")
        ).scalar()
        min_gap = int(gap_setting) if gap_setting else 0
        debug_logger.info(f"Min Gap: {min_gap}")

        ms_gap_setting = session.execute(
            select(Setting.value).where(Setting.key == "ms_assignment_gap")
        ).scalar()
        ms_gap = int(ms_gap_setting) if ms_gap_setting else min_gap
        debug_logger.info(f"MS Gap: {ms_gap}")

        # Re-create filter with up-to-date DB values (avoids stale in-memory gap)
        self.candidate_filter = CandidateFilterService(min_gap=min_gap, ms_gap=ms_gap)
        self.candidate_filter.consider_future = consider_future

        # 2. Get week assignments
        assignments = (
            session.execute(
                select(Assignment).where(
                    and_(
                        Assignment.week_id == week_id,
                        Assignment.status != AssignmentStatus.DISABLED.value,
                    )
                )
            )
            .scalars()
            .all()
        )

        if not assignments:
            debug_logger.info("No assignments found.")
            self._close_debug_logger(debug_logger)
            return {"success": True, "count": 0, "message": "Нет заданий для распределения"}

        # 3. Get week info
        week_obj = session.get(Week, week_id)
        current_date_dt = (
            date_to_datetime(week_obj.start_date)
            if week_obj and week_obj.start_date
            else datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        )
        debug_logger.info(f"Week Date (Target): {current_date_dt}")

        # При посещении районного старейшины (РС) Изучение Библии в собрании (CBS) не проводится,
        # вместо него — служебная речь районного старейшины, поэтому CBS не распределяется среди возвещателей.
        if week_obj and getattr(week_obj, "special_event", None) == "circuit_overseer":
            assignments = [
                a
                for a in assignments
                if a.section != "cbs" and a.assignment_type not in ("cbs", "cbs_reader")
            ]
            debug_logger.info(
                "Circuit overseer week: excluded CBS and CBS reader from auto-assignment."
            )

        # 4. Load assignment configurations (needed before history: light positions)
        configs_raw = session.execute(select(AssignmentConfig)).scalars().all()
        configs_by_key = {(c.section, c.position): c for c in configs_raw}
        # Лёгкие задания (is_exclusive=False: молитвы, чтение Библии) не должны
        # отодвигать очередь на пункты программы. NULL считается exclusive.
        light_keys = {
            (c.section, c.position)
            for c in configs_raw
            if c.is_exclusive is not None and not c.is_exclusive
        }

        # 4a. Load participants with history
        history_data = self._load_participants_with_history(
            session,
            week_id,
            current_date_dt,
            light_keys=light_keys,
            consider_future=consider_future,
        )
        participants_data = history_data["participants_data"]
        position_dates_map = history_data["position_dates_map"]
        pairs_map = history_data.get("pairs_map", {})

        debug_logger.info(f"Loaded {len(participants_data)} participants.")

        assigned_this_week = set()
        # Participants assigned to a non-exclusive position (is_exclusive=False in
        # assignment_config, e.g. prayer, Bible reading) are NOT blocked from also
        # receiving a ministry assignment in the same week.
        non_blocking_assigned: set = set()
        assigned_count = 0

        # 5a. Load per-participant position gap overrides.
        # Maps (participant_id, section, position) -> position_gap.
        # Entries here take priority over assignment_config.elder_position_gap.
        ppc_raw = session.execute(select(ParticipantPositionConfig)).scalars().all()
        participant_position_configs: Dict[Tuple[int, str, str], int] = {
            (r.participant_id, r.section, r.position): r.position_gap for r in ppc_raw
        }
        if participant_position_configs:
            debug_logger.info(
                f"Loaded {len(participant_position_configs)} participant position override(s): "
                f"{[(k, v) for k, v in participant_position_configs.items()]}"
            )

        # 6. Sort assignments by priority. Лёгкие задания — в самом конце:
        # иначе молитва первой забирает брата, дольше всех ждущего пункт,
        # и блокирует его на неделю.
        # В конец — только лёгкие задания раздела «fixed» (молитвы): они
        # конкурируют с пунктами за тех же братьев. Чтение Библии остаётся на
        # своём месте в «Сокровищах» — в конце очереди его некому было отдать.
        def _goes_last(a: Assignment) -> bool:
            key = (a.section or "", self._position_key(a.section_position, a.assignment_text))
            return key in light_keys and key[0] == "fixed"

        assignments.sort(key=lambda a: (_goes_last(a),) + self._assignment_priority(a))
        participants_by_id = {p["id"]: p for p in participants_data}

        # «Только пустые»: уже назначенные заняты на этой неделе до начала
        # распределения — иначе пустой пункт раньше по очереди мог бы достаться
        # человеку, который уже стоит на другом пункте этой недели.
        if only_empty:
            for a in assignments:
                if not a.participant_id:
                    # главного сняли (отказ, отпуск), напарник остаётся на месте
                    if a.assistant_id:
                        assigned_this_week.add(a.assistant_id)
                        non_blocking_assigned.discard(a.assistant_id)
                    continue
                cfg = configs_by_key.get(
                    (a.section or "", self._position_key(a.section_position, a.assignment_text))
                )
                exclusive = getattr(cfg, "is_exclusive", True)
                for pid in (a.participant_id, a.assistant_id):
                    if not pid:
                        continue
                    assigned_this_week.add(pid)
                    if exclusive is False and pid == a.participant_id:
                        non_blocking_assigned.add(pid)
                    else:
                        non_blocking_assigned.discard(pid)

        # Речи по обязанности (кроме председателя) — брату из настроек;
        # настройки читаем, только если такие пункты на неделе есть
        holders = (
            role_holders(session)
            if any(is_role_talk(a) and not is_chairman_talk(a) for a in assignments)
            else {}
        )

        # 7. Process each assignment
        for a in assignments:
            if is_chairman_talk(a) or holders.get(role_setting(a)):
                # Речь председателя / брата из «Обязанностей в собрании» не
                # распределяется: её получает он сам (sync_chairman_talks ниже)
                continue
            a_num = str(a.assignment_number)
            debug_logger.info(f"--- Processing {a_num}: {a.assignment_text} ---")

            # Get assignment config
            # config_key: (section, position). Для fresh-импорта section_position
            # уже канонический строковый ключ. Для legacy-данных с section_position
            # IS NULL выводим позицию из assignment_text (W-7: ранее обрабатывался
            # только «Председатель», prayer_* оставались без config → терялся
            # is_brothers_only и женщины могли назначаться на молитву).
            _pos_key = self._position_key(a.section_position, a.assignment_text)
            config_key = (a.section or "", _pos_key)
            is_light = config_key in light_keys
            config = configs_by_key.get(config_key)

            # Поправки по типу пункта («Что бы вы сказали», обсуждение, ученическое
            # задание, речь) — общие с ручным выбором участника, см. core/assignment_rules.
            config = resolve_assignment_config(
                a.section,
                a.assignment_type,
                a.assignment_text,
                a.discussion_marker,
                a.section_position,
                config,
                lambda sec, pos: configs_by_key.get((sec, pos)),
            )
            if getattr(config, "kind", None):
                debug_logger.info(f"Overriding config by assignment kind: {config.kind}")

            # Filter candidates
            a_sec = a.section or ""
            # Use the canonical position string from config (e.g. 'chairman', 'reader', '1').
            # This ensures consistent keys across position_dates_map and participant_position_configs.
            # Fall back to str(section_position) only when config is unavailable.
            if config and getattr(config, "position", None):
                a_pos = str(config.position)
            else:
                a_pos = str(a.section_position) if a.section_position is not None else ""

            # For ministry assignments: participants who only have prayer or
            # Bible reading this week are still eligible.
            effective_assigned = (
                assigned_this_week - non_blocking_assigned
                if a_sec == "ministry"
                else assigned_this_week
            )

            if only_empty and a.participant_id:
                # Пункт уже назначен: дополняем только недостающего напарника.
                main = participants_by_id.get(a.participant_id)
                if a.assistant_id or not (config and config.needs_assistant) or main is None:
                    continue
                assistant = self._assign_assistant(
                    participants_data,
                    effective_assigned,
                    main,
                    min_gap,
                    current_date_dt,
                    position_dates_map,
                    a_sec,
                    a_pos,
                    debug_logger,
                    config=config,
                    participant_position_configs=participant_position_configs,
                    pairs_map=pairs_map,
                    assignment_text=a.assignment_text,
                )
                if assistant:
                    a.assistant_id = assistant["id"]
                    assigned_this_week.add(assistant["id"])
                    non_blocking_assigned.discard(assistant["id"])
                    assistant["total_assignments"] += 1
                    assistant["effective_last_date"] = current_date_dt
                    assistant["all_total"] += 1
                    assistant["all_last_date"] = current_date_dt
                    if a_sec:
                        position_dates_map.setdefault((assistant["id"], a_sec, a_pos), []).append(
                            current_date_dt
                        )
                    pair_key = (min(main["id"], assistant["id"]), max(main["id"], assistant["id"]))
                    pairs_map.setdefault(pair_key, []).append(current_date_dt)
                    assigned_count += 1
                continue

            # Для лёгких заданий интервалы и очередь считаются по ПОЛНОЙ истории
            # (чтобы один брат не молился каждую неделю), для пунктов — только
            # по полноценным заданиям.
            pool = self._light_views(participants_data) if is_light else participants_data

            program_weeks_left = (
                self._treasures_talk_weeks_left(session, current_date_dt)
                if (a_sec, a_pos) == ("treasures", "1")
                else None
            )
            candidates = self.candidate_filter.filter_candidates(
                pool,
                effective_assigned,
                config,
                current_date_dt,
                position_dates_map,
                a_sec,
                a_pos,
                debug_logger,
                assignment_text=a.assignment_text,
                participant_position_configs=participant_position_configs,
                program_weeks_left_in_month=program_weeks_left,
            )

            if not candidates:
                # Чередование ролей (main/assistant) — мягкое правило: если из-за
                # него и интервалов не осталось никого, отбираем без него.
                candidates = self.candidate_filter.filter_candidates(
                    pool,
                    effective_assigned,
                    config,
                    current_date_dt,
                    position_dates_map,
                    a_sec,
                    a_pos,
                    debug_logger,
                    assignment_text=a.assignment_text,
                    participant_position_configs=participant_position_configs,
                    relax_role_alternation=True,
                    program_weeks_left_in_month=program_weeks_left,
                )
                if candidates:
                    debug_logger.warning("Role alternation relaxed: no candidates otherwise.")

            if not candidates:
                debug_logger.warning("NO CANDIDATES LEFT!")
                continue

            # Select best candidate
            # Очередь по самой позиции: кто реже всех получал ИМЕННО этот пункт.
            # Без неё человек, у которого меньше квалификаций (например, старейшина
            # без председательства и ИБС), по общей нагрузке «недогружен» и
            # получал свой единственный доступный пункт заметно чаще остальных.
            # Если все кандидаты освобождены от общего интервала (пункты для
            # старейшин) — позиционная очередь главная. В смешанном пуле она лишь
            # уточняет выбор среди одинаково загруженных: главной она отдавала бы
            # пункты старейшинам в ущерб служебным помощникам.
            self._annotate_position_counts(
                candidates, a_sec, a_pos, current_date_dt, position_dates_map
            )
            position_first = all(self.candidate_filter._effective_gap(p) == 0 for p in candidates)
            selected = self._select_best_candidate(
                candidates,
                current_date_dt,
                debug_logger,
                use_main_date=True,
                position_first=position_first,
            )
            self._cleanup_all_candidates_attributes(candidates)

            if not selected:
                debug_logger.warning("Selection failed!")
                continue
            if is_light:
                selected = participants_by_id[selected["id"]]

            debug_logger.info(
                f"Assigned: {selected['name']} (total: {selected['total_assignments']})"
            )

            # Assign participant
            a.participant_id = selected["id"]
            a.status = AssignmentStatus.ASSIGNED.value
            assigned_this_week.add(selected["id"])

            # Track non-exclusive assignments (is_exclusive=False in assignment_config).
            # These participants remain available for ministry assignments in the same week.
            # Determined by DB config — no hardcoded qualification names needed.
            config_is_exclusive = getattr(config, "is_exclusive", True)
            if config_is_exclusive is None:
                config_is_exclusive = True  # treat NULL as exclusive (safe default)
            if not config_is_exclusive:
                non_blocking_assigned.add(selected["id"])
            else:
                # Heavy assignment: remove from non-blocking if previously light-assigned.
                non_blocking_assigned.discard(selected["id"])

            assigned_count += 1

            # Update in-memory counters
            selected["all_total"] += 1
            selected["all_last_date"] = current_date_dt
            selected["all_last_main_date"] = current_date_dt
            if not is_light:
                selected["total_assignments"] += 1
                selected["effective_last_date"] = current_date_dt
                # Роль ГЛАВНОГО: обновляем отдельный счётчик для справедливого gap-фильтра.
                # Напарник (assistant) обновляет effective_last_date, но НЕ effective_last_main_date.
                selected["effective_last_main_date"] = current_date_dt

            # Update position history
            if a_sec:
                pos_key = (selected["id"], a_sec, a_pos)
                position_dates_map.setdefault(pos_key, []).append(current_date_dt)
                position_dates_map[pos_key].sort()

            # FIX (Баг 1): update last_student_role in-memory for sequential weeks.
            # Without this, auto_assign_all doesn't see the role change between weeks
            # and the same person gets the same role repeatedly (M→M→M or A→A→A).
            is_student = (a_sec == "ministry") or (a_sec == "treasures" and a_pos == "3")
            if is_student:
                selected["last_student_role"] = "main"

            # Handle assistant
            if only_empty and a.assistant_id:
                continue  # напарник уже есть — не меняем
            a.assistant_id = None
            assistant = None
            if config and config.needs_assistant:
                assistant = self._assign_assistant(
                    participants_data,
                    effective_assigned,  # same effective set (prayer/bible_reading unblocked for ministry)
                    selected,
                    min_gap,
                    current_date_dt,
                    position_dates_map,
                    a_sec,
                    a_pos,
                    debug_logger,
                    config=config,
                    participant_position_configs=participant_position_configs,
                    pairs_map=pairs_map,
                    assignment_text=a.assignment_text,
                )

            if assistant:
                a.assistant_id = assistant["id"]
                assigned_this_week.add(assistant["id"])
                # Ministry assistant → fully booked now (remove from non-blocking if present)
                non_blocking_assigned.discard(assistant["id"])
                assistant["total_assignments"] += 1
                assistant["effective_last_date"] = current_date_dt
                assistant["all_total"] += 1
                assistant["all_last_date"] = current_date_dt
                # Напарник НЕ обновляет effective_last_main_date —
                # очередь на главную роль остаётся на прежнем месте.

                if a_sec:
                    ast_pos_key = (assistant["id"], a_sec, a_pos)
                    position_dates_map.setdefault(ast_pos_key, []).append(current_date_dt)
                    position_dates_map[ast_pos_key].sort()

                # Update pairs_map in-memory for sequential assignments/weeks
                pair_key = (
                    min(selected["id"], assistant["id"]),
                    max(selected["id"], assistant["id"]),
                )
                pairs_map.setdefault(pair_key, []).append(current_date_dt)
                pairs_map[pair_key].sort()

                # FIX (Баг 1): update last_student_role for assistant too
                if is_student:
                    assistant["last_student_role"] = "assistant"

        # Bulk-update both last_assignment_date and last_main_date in ONE query.
        week_date_dt = (
            date_to_datetime(week_obj.start_date) if week_obj and week_obj.start_date else None
        )
        if week_date_dt and assigned_this_week:
            # main_assigned_this_week — ID участников, получивших роль ГЛАВНОГО на этой неделе.
            # Напарник обновляет только last_assignment_date; его очередь на главную роль
            # (last_main_date) остаётся прежней.
            main_assigned_this_week = {
                p["id"] for p in participants_data if p.get("all_last_main_date") == current_date_dt
            }
            # Один UPDATE для всех назначенных: last_assignment_date — всем,
            # last_main_date — только роли ГЛАВНОГО и только если дата свежее.
            main_ids_param = list(main_assigned_this_week) if main_assigned_this_week else [None]
            session.execute(
                update(Participant)
                .where(Participant.id.in_(assigned_this_week))
                .values(
                    last_assignment_date=case(
                        (
                            or_(
                                Participant.last_assignment_date == None,
                                Participant.last_assignment_date < week_date_dt,
                            ),
                            week_date_dt,
                        ),
                        else_=Participant.last_assignment_date,
                    ),
                    last_main_date=case(
                        (
                            and_(
                                Participant.id.in_(main_ids_param),
                                or_(
                                    Participant.last_main_date == None,
                                    Participant.last_main_date < week_date_dt,
                                ),
                            ),
                            week_date_dt,
                        ),
                        else_=Participant.last_main_date,
                    ),
                )
            )

        # Председатель недели — на «Речь председателя программы»
        sync_chairman_talks(assignments, holders, only_empty=only_empty)

        session.commit()
        self._close_debug_logger(debug_logger)

        return {"success": True, "count": assigned_count}

    def auto_assign_all(self, session=None) -> Dict[str, Any]:
        """
        Automatically assign participants for all weeks.

        Args:
            session: Optional SQLAlchemy session

        Returns:
            Dict with 'success' and 'count' keys
        """
        with self._assign_lock:
            should_close_session = session is None
            if session is None:
                session = self.session_factory()

            try:
                weeks = session.execute(select(Week.id).order_by(Week.start_date)).scalars().all()

                total = 0
                for idx, w_id in enumerate(weeks):
                    # Первая неделя обрезает лог (truncate), остальные дописывают —
                    # иначе в auto_assign_all сохранится только лог последней недели.
                    result = self._do_auto_assign_week(
                        session, w_id, truncate_log=(idx == 0), consider_future=False
                    )
                    if result.get("success"):
                        total += result["count"]

                return {"success": True, "count": total}
            finally:
                if should_close_session:
                    session.close()

    # ==================== Private Methods ====================

    # Removed _filter_candidates - moved to CandidateFilterService

    def _apply_position_gap_relaxation(
        self,
        candidates: List[dict],
        candidates_with_gap: List[Tuple[dict, float]],
        logger: Any = None,
    ) -> List[dict]:
        """
        Apply position gap relaxation using weighted selection.

        Instead of completely removing the filter, candidates with larger gaps
        get higher probability in weighted selection.

        Args:
            candidates: Original candidates list
            candidates_with_gap: List of (candidate, gap_weeks) tuples
            logger: Optional logger

        Returns:
            Candidates list with _position_gap_weeks attribute for weighted selection
        """
        if logger:
            logger.warning(
                f"Position Gap would leave 0 candidates. "
                f"Using weighted selection from {len(candidates)} candidates."
            )

        # First, clean up any existing _position_gap_weeks from previous runs
        self._cleanup_all_candidates_attributes(candidates)

        # Add position_gap_weeks to candidates for weighted selection
        for p, gap in candidates_with_gap:
            position_gap_value = self.NEVER_ASSIGNED_GAP_MARKER if gap == float("inf") else gap
            p["_position_gap_weeks"] = position_gap_value

        if logger:
            logger.info(
                f"Relaxation: keeping {len(candidates)} candidates with weighted selection. "
                f"Gaps: {[(p['name'], p.get('_position_gap_weeks', 0)) for p in candidates]}"
            )

        return candidates

    def _select_best_candidate(
        self,
        candidates: List[dict],
        current_date_dt: datetime,
        logger: Any = None,
        use_main_date: bool = False,
        position_first: bool = False,
    ) -> Optional[dict]:
        """
        Select the best candidate using weighted rotation algorithm.

        spec://services/auto_assignment#candidate_selection

        The algorithm:
        1. Create wide pool (min_total + 2) for rotation
        2. Sort by (total_assignments, last_assignment_date)
        3. Take top-N candidates
        4. Weighted random selection - more days since last assignment = higher weight
        Also considers position_gap_weeks if available (from relaxation)

        This ensures fair rotation while preferring candidates who haven't been assigned recently.
        """
        if not candidates:
            return None

        def _rarest_on_position(pool: List[dict]) -> List[dict]:
            """Оставить тех, кто реже всех получал эту позицию (если посчитано)."""
            if not all("_pos_count" in p for p in pool):
                return pool
            min_pos = min(p["_pos_count"] for p in pool)
            return [p for p in pool if p["_pos_count"] == min_pos]

        if position_first:
            candidates = _rarest_on_position(candidates)

        # Extended pool: min + 2 for rotation
        min_total = min(p["total_assignments"] for p in candidates)
        wide_pool = [p for p in candidates if p["total_assignments"] <= min_total + 2]
        if not position_first:
            wide_pool = _rarest_on_position(wide_pool)

        # Sort by (total_assignments, last assignment date, name) to ensure stable rotation
        if use_main_date:
            wide_pool.sort(
                key=lambda p: (
                    p["total_assignments"],
                    (
                        p.get("effective_last_main_date")
                        if "effective_last_main_date" in p
                        else p.get("effective_last_date")
                    )
                    or datetime.min,
                    p["name"],
                )
            )
        else:
            wide_pool.sort(
                key=lambda p: (
                    p["total_assignments"],
                    p.get("effective_last_date") or datetime.min,
                    p["name"],
                )
            )

        # Use weighted selection for ALL candidates (including small pools)
        weights = self._calculate_selection_weights(wide_pool, current_date_dt, use_main_date)
        total_weight = sum(weights)
        if self._deterministic and self._seed is not None:
            # Use seed + counter for reproducible but varied selection
            rng = random.Random(self._seed + self._selection_counter)
            r = rng.uniform(0, total_weight) if total_weight > 0 else 0
            self._selection_counter += 1
        else:
            r = random.uniform(0, total_weight) if total_weight > 0 else 0
        if total_weight > 0 and weights:
            cumulative = 0
            for p, w in zip(wide_pool, weights):
                cumulative += w
                if r <= cumulative:
                    selected = p
                    break
            else:
                selected = wide_pool[-1]  # Fallback to last
        else:
            selected = wide_pool[0]

        if logger:
            logger.info(
                f"Selected (rotation): {selected['name']} (total: {selected['total_assignments']})"
            )

        # Clean up temporary attributes to prevent mutation side-effects
        self._cleanup_candidate_attributes(selected)

        return selected

    def _calculate_selection_weights(
        self, candidates: List[dict], current_date_dt: datetime, use_main_date: bool = False
    ) -> List[float]:
        """
        Calculate selection weights for candidates.

        Weight formula:
        - Base: days since last assignment (or NEVER_ASSIGNED_DAYS_WEIGHT for never-assigned)
        - If _position_gap_weeks set (relaxation): multiply by (1 + gap * POSITION_GAP_WEIGHT_FACTOR)

        Args:
            candidates: List of candidate dicts
            current_date_dt: Current date for gap calculation
            use_main_date: If True, uses effective_last_main_date for calculating gap

        Returns:
            List of weights corresponding to candidates
        """
        weights = []
        for p in candidates:
            if use_main_date:
                last_date = (
                    p.get("effective_last_main_date")
                    if "effective_last_main_date" in p
                    else p.get("effective_last_date")
                )
            else:
                last_date = p.get("effective_last_date")

            if last_date:
                days_since = (current_date_dt - last_date).days
            else:
                # Never assigned - give maximum weight
                days_since = self.NEVER_ASSIGNED_DAYS_WEIGHT

            # If position_gap_weeks is set (from relaxation), use it as additional factor
            position_gap = p.get("_position_gap_weeks")
            if position_gap is not None:
                # Combine global gap weight with position gap weight
                # Position gap is more important in relaxation scenario
                weight = max(1, days_since) * (1 + position_gap * self.POSITION_GAP_WEIGHT_FACTOR)
            else:
                weight = max(1, days_since)

            weights.append(weight)

        return weights

    def _cleanup_candidate_attributes(self, candidate: dict) -> None:
        """
        Remove temporary attributes from candidate to prevent mutation side-effects.

        Args:
            candidate: Candidate dict to clean up
        """
        candidate.pop("_position_gap_weeks", None)
        candidate.pop("_pos_count", None)

    def _cleanup_all_candidates_attributes(self, candidates: List[dict]) -> None:
        """
        Remove temporary attributes from all candidates to prevent mutation side-effects.

        Args:
            candidates: List of candidate dicts to clean up
        """
        for p in candidates:
            p.pop("_position_gap_weeks", None)
            p.pop("_pos_count", None)

    @staticmethod
    def _same_family(p1: dict, p2: dict) -> bool:
        """True if two participants belong to the same family group.

        Family membership rules:
          - If p1 is the head (family_group_id is None): members have family_group_id == p1.id
          - If p1 is a member: others in the same family share the same family_group_id,
            OR the head has id == p1.family_group_id
        """
        fid1 = p1.get("family_group_id")
        fid2 = p2.get("family_group_id")
        id1, id2 = p1["id"], p2["id"]

        if fid1 is None and fid2 is None:
            return False  # Оба — главы разных семей
        if fid1 is None:
            return fid2 == id1  # p1 — глава, p2 — член его семьи
        if fid2 is None:
            return fid1 == id2  # p2 — глава, p1 — член его семьи
        return fid1 == fid2  # Оба — члены одной семьи

    def _assign_assistant(
        self,
        participants_data: List[dict],
        assigned_this_week: set,
        selected_participant: dict,
        min_gap: int,
        current_date_dt: datetime,
        position_dates_map: Dict[tuple, List[datetime]],
        section: str,
        position: str,
        logger: Any = None,
        config: Any = None,
        participant_position_configs: Optional[Dict[Tuple[int, str, str], int]] = None,
        pairs_map: Optional[Dict[Tuple[int, int], List[datetime]]] = None,
        assignment_text: Optional[str] = None,
    ) -> Optional[dict]:
        """Find and assign an assistant for the participant."""
        # Filter assistant candidates (base — without gender filter)
        # spec://services/auto_assignment#assistant_matching
        base_candidates = [
            p
            for p in participants_data
            if p["id"] not in assigned_this_week
            and p["id"] != selected_participant["id"]
            and "assistant" in p["qualifications"]
        ]

        # Standard path: same gender only + family exception
        # Family members bypass gender restriction (только там, где S-38 это
        # разрешает), other candidates must be of the same gender.
        family_ok = family_assistant_allowed(assignment_text)
        ast_candidates = [
            p
            for p in base_candidates
            if p["gender"] == selected_participant["gender"]
            or (family_ok and self._same_family(selected_participant, p))
        ]

        # Apply minor/adult assistant rules
        main_is_minor = selected_participant.get("is_minor", False)
        if main_is_minor:
            # If main is a MINOR: assistant MUST also be a minor.
            # Rule: "A minor can only do a student assignment when paired with another minor."
            # Adult family members are NOT allowed as assistants for a minor main.
            ast_candidates = [p for p in ast_candidates if p.get("is_minor", False)]

        else:
            # If main is an ADULT: minor candidates who are NOT family members are excluded.
            ast_candidates = [
                p
                for p in ast_candidates
                if not p.get("is_minor", False) or self._same_family(selected_participant, p)
            ]

        # Exclude elders from being assistants in student assignments.
        # Elders never receive student assignments (neither as main nor as assistant).
        is_student_assignment = (section == "treasures" and position == "3") or (
            section == "ministry"
        )
        if is_student_assignment:
            ast_candidates = [
                p for p in ast_candidates if p.get("service_type") not in ("E", "elder")
            ]

        # Gap check for assistant
        # Uses _effective_gap() to respect personal_gap per participant,
        # instead of applying only the global min_gap to everyone.

        if ast_candidates and current_date_dt:
            ast_valid = []
            for p in ast_candidates:
                if p.get("service_type") in ("E", "elder"):
                    ast_valid.append(p)
                    continue
                eff_gap = self.candidate_filter._effective_gap(p)  # учитывает personal_gap
                if eff_gap == 0:
                    ast_valid.append(p)
                    continue
                l_date = p.get("effective_last_date")
                if not l_date or (current_date_dt - l_date).days / 7 >= eff_gap:
                    ast_valid.append(p)
                else:
                    if logger:
                        gap_weeks = (current_date_dt - l_date).days / 7
                        logger.info(
                            f"Assistant gap-blocked: {p.get('name')} "
                            f"(last_any={l_date.date() if l_date else None}, "
                            f"gap_weeks={gap_weeks:.1f}, eff_gap={eff_gap})"
                        )
            ast_candidates = ast_valid

        if not ast_candidates:
            return None

        # Position-gap filter for assistant (аналогично главному фильтру).
        # Запрещает повторное назначение на ТОЙ ЖЕ позиции (section, position)
        # чаще, чем eff_gap*2 недель. Assistant тоже пишется в position_dates_map,
        # поэтому фильтр симметричен главному. Relaxation — через взвешенный
        # выбор (если никто не прошёл) — не блокирует назначение полностью.
        # spec://services/auto_assignment#position_gap_filter
        if current_date_dt and ast_candidates and section and position:
            valid_by_pos = []
            candidates_with_gap: List[Tuple[dict, float]] = []
            elder_pos_gap_override = getattr(config, "elder_position_gap", None) if config else None
            for p in ast_candidates:
                eff_gap = self.candidate_filter._effective_gap(p)
                is_elder = p.get("service_type") in ("E", "elder")
                p_id = p["id"]
                personal_pos_gap = (
                    participant_position_configs.get((p_id, section, position))
                    if participant_position_configs
                    else None
                )
                if personal_pos_gap is not None:
                    actual_pos_gap = personal_pos_gap
                elif is_elder and elder_pos_gap_override is not None:
                    actual_pos_gap = elder_pos_gap_override
                elif eff_gap == 0:
                    valid_by_pos.append(p)
                    candidates_with_gap.append((p, float("inf")))
                    continue
                else:
                    actual_pos_gap = eff_gap * 2

                pos_key = (p_id, section, position)
                pos_dates = position_dates_map.get(pos_key, [])
                if not pos_dates:
                    valid_by_pos.append(p)
                    candidates_with_gap.append((p, float("inf")))
                else:
                    past = [d for d in pos_dates if d < current_date_dt]
                    if not past:
                        valid_by_pos.append(p)
                        candidates_with_gap.append((p, float("inf")))
                    else:
                        gap_weeks = (current_date_dt - past[-1]).days / 7
                        candidates_with_gap.append((p, gap_weeks))
                        if gap_weeks >= actual_pos_gap:
                            valid_by_pos.append(p)

            if valid_by_pos:
                ast_candidates = valid_by_pos
                if logger:
                    logger.info(
                        f"Assistant position-gap check: {len(ast_candidates)} "
                        f"candidate(s) pass on ({section},{position})"
                    )
            else:
                # Relaxation: никто не прошёл — оставляем весь пул с весами.
                ast_candidates = self.candidate_filter._apply_position_gap_relaxation(
                    ast_candidates, candidates_with_gap, logger
                )

        # Sort/Filter for student role rotation
        # If this is a student assignment, prioritize those who were main last time to be assistant now.
        # (is_student_assignment is defined above)

        # FIX (Баг 2): Hard filter for role alternation in student assignments.
        # If this is a student assignment, prefer (with hard filter + relaxation)
        # those whose last role was "main" — so they now take the assistant role.
        # This enforces M→A→M→A alternation instead of the previous soft sort.
        if is_student_assignment:
            # Hard filter: only those whose last_student_role == "main" (should be asst now)
            # OR those who have never had a student assignment (last_student_role is None)
            # Кто не может быть основным (нет ministry_item — «только помощник»),
            # чередоваться не может: иначе после первого раза помощником такой
            # человек больше никогда не проходит фильтр и выпадает навсегда.
            ideal_ast = [
                p
                for p in ast_candidates
                if p.get("last_student_role") == "main"
                or p.get("last_student_role") is None
                or "ministry_item" not in p["qualifications"]
            ]
            if ideal_ast:
                ast_candidates = ideal_ast
                if logger:
                    logger.info(
                        f"Assistant role alternation (hard filter): {len(ideal_ast)} candidate(s) "
                        f"whose last student role was 'main' or new."
                    )
            else:
                # Relaxation: no ideal candidates, use full pool
                if logger:
                    logger.warning(
                        "Assistant role alternation: no candidates with last_role='main'. "
                        "Relaxing to full assistant pool."
                    )

        # Family priority: if a family member (e.g. spouse) is among the
        # filtered candidates, prefer them over non-family candidates.
        # This only applies to candidates who already passed all filters
        # (qualification, gap, gender/family, role alternation).
        family_candidates = [
            p for p in ast_candidates if self._same_family(selected_participant, p)
        ]
        if family_candidates:
            if logger:
                logger.info(
                    f"Family priority: {len(family_candidates)} family member(s) "
                    f"found — {[p['name'] for p in family_candidates]}. "
                    f"Selecting family member."
                )
            # If multiple family members, pick the one with fewest assignments
            family_candidates.sort(
                key=lambda p: (p["total_assignments"], p.get("effective_last_date") or datetime.min)
            )
            assistant = family_candidates[0]
            if logger:
                logger.info(f"Assigned Assistant (family): {assistant['name']}")
            # Очистка _position_gap_weeks для предотвращения утечки состояния
            # между неделями в auto_assign_all (W-6).
            for p in ast_candidates + family_candidates:
                p.pop("_position_gap_weeks", None)
            return assistant

        # Pair History Filter: avoid repeating the same (main, assistant) pair too frequently.
        # Does not apply to family members (handled above).
        if pairs_map is not None and current_date_dt and ast_candidates:
            sel_id = selected_participant["id"]
            pair_filtered = []
            for p in ast_candidates:
                pair_key = (min(sel_id, p["id"]), max(sel_id, p["id"]))
                past_pair_dates = [d for d in pairs_map.get(pair_key, []) if d < current_date_dt]
                if not past_pair_dates:
                    pair_filtered.append(p)
                else:
                    gap_weeks = (current_date_dt - past_pair_dates[-1]).days / 7
                    if gap_weeks >= self.PAIR_GAP_WEEKS:
                        pair_filtered.append(p)
                    elif logger:
                        logger.info(
                            f"Pair-blocked: {p['name']} was in pair with {selected_participant['name']} "
                            f"{gap_weeks:.1f} weeks ago (< {self.PAIR_GAP_WEEKS}w limit)"
                        )

            if pair_filtered:
                if logger:
                    logger.info(
                        f"Pair history filter: {len(pair_filtered)}/{len(ast_candidates)} "
                        f"candidate(s) pass (no pair in last {self.PAIR_GAP_WEEKS} weeks)."
                    )
                ast_candidates = pair_filtered
            else:
                # Relaxation: nobody passes the pair gap limit.
                # Keep all candidates, but prioritize those who haven't been in pair the longest.
                if logger:
                    logger.warning(
                        f"Pair history filter: all candidates were in pair with {selected_participant['name']} "
                        f"recently! Relaxing pair filter and prioritizing older pairs."
                    )

                def _pair_recency_key(p):
                    pair_key = (min(sel_id, p["id"]), max(sel_id, p["id"]))
                    past_d = [d for d in pairs_map.get(pair_key, []) if d < current_date_dt]
                    return past_d[-1] if past_d else datetime.min

                ast_candidates.sort(key=_pair_recency_key)

        # Use unified selection logic with weighted random
        min_ast_total = min(p["total_assignments"] for p in ast_candidates)
        ast_wide = [p for p in ast_candidates if p["total_assignments"] <= min_ast_total + 2]

        # Sort by (total_assignments, last assignment date, name) for consistency
        ast_wide.sort(
            key=lambda p: (
                p["total_assignments"],
                p.get("effective_last_date") or datetime.min,
                p["name"],
            )
        )

        # Use weighted selection for ALL candidates (including small pools)
        weights = self._calculate_selection_weights(ast_wide, current_date_dt, use_main_date=False)
        total_weight = sum(weights)
        if self._deterministic and self._seed is not None:
            rng = random.Random(self._seed + self._selection_counter)
            r = rng.uniform(0, total_weight) if total_weight > 0 else 0
            self._selection_counter += 1
        else:
            r = random.uniform(0, total_weight) if total_weight > 0 else 0
        if total_weight > 0 and weights:
            cumulative = 0
            for p, w in zip(ast_wide, weights):
                cumulative += w
                if r <= cumulative:
                    assistant = p
                    break
            else:
                assistant = ast_wide[-1]
        else:
            assistant = ast_wide[0]

        if logger:
            logger.info(f"Assigned Assistant (rotation): {assistant['name']}")

        # Очистка _position_gap_weeks для предотвращения утечки состояния
        # между неделями в auto_assign_all (W-6). Без этого stale-маркер 999
        # для never-assigned искажает веса главного выбора на следующей неделе.
        for p in ast_wide:
            p.pop("_position_gap_weeks", None)
        for p in ast_candidates:
            p.pop("_position_gap_weeks", None)

        return assistant

    def _load_participants_with_history(
        self,
        session,
        week_id: int,
        current_date_dt: datetime,
        light_keys=frozenset(),
        consider_future: bool = False,
    ) -> Dict[str, Any]:
        """
        Load participants with their assignment history.

        Uses ParticipantRepository ORM methods instead of text() SQL queries.
        Reference: spec://services/auto_assignment#load_participants_with_history
        """
        # Get active participants via ParticipantMapper
        participants_dto = ParticipantMapper.bulk_load_with_stats(session, active_only=True)

        # Use repository methods instead of text() SQL
        if self.participant_repo:
            dates_map = self.participant_repo.get_assignment_dates_map(session)
            main_dates_map = self.participant_repo.get_main_assignment_dates_map(session)
            position_dates_map = self.participant_repo.get_position_dates_map(session)
            pairs_map = self.participant_repo.get_recent_pairs_map(session)
        else:
            # Fallback: create temporary repository from session factory
            from core.database import DatabaseManager
            from core.repositories.participant_repository import ParticipantRepository

            # Get db_manager from session if possible, or use session_factory
            if hasattr(self.session_factory, "__self__") and isinstance(
                self.session_factory.__self__, DatabaseManager
            ):
                temp_repo = ParticipantRepository(self.session_factory.__self__)
            else:
                # Create a minimal wrapper for session
                temp_repo = _SessionBasedRepository(session)

            dates_map = temp_repo.get_assignment_dates_map(session)
            main_dates_map = temp_repo.get_main_assignment_dates_map(session)
            position_dates_map = temp_repo.get_position_dates_map(session)
            pairs_map = temp_repo.get_recent_pairs_map(session)

        # Query all past student assignments to compute last student role for each participant
        # Student assignments are treasures position 3 (Bible reading) and ministry section items
        from core.models import Assignment, AssignmentStatus, Week
        from sqlalchemy import and_, or_

        past_student_assignments = session.execute(
            select(Assignment.participant_id, Assignment.assistant_id, Week.start_date)
            .join(Week, Assignment.week_id == Week.id)
            .where(
                and_(
                    counted_assignment(Assignment),
                    Week.start_date < current_date_dt.date(),
                    or_(
                        and_(Assignment.section == "treasures", Assignment.section_position == 3),
                        Assignment.section == "ministry",
                    ),
                )
            )
        ).all()

        last_student_assignment = {}
        for pid, aid, start_date in past_student_assignments:
            if pid:
                if (
                    pid not in last_student_assignment
                    or last_student_assignment[pid][0] < start_date
                ):
                    last_student_assignment[pid] = (start_date, "main")
            if aid:
                if (
                    aid not in last_student_assignment
                    or last_student_assignment[aid][0] < start_date
                ):
                    last_student_assignment[aid] = (start_date, "assistant")

        # Даты лёгких заданий (молитвы и т.п.) по участнику — их вычитаем из
        # истории для пунктов программы. У лёгких заданий нет напарника.
        light_dates: Dict[int, List[datetime]] = {}
        if light_keys:
            light_rows = session.execute(
                select(
                    Assignment.participant_id,
                    Assignment.section,
                    Assignment.section_position,
                    Assignment.assignment_text,
                    Week.start_date,
                )
                .join(Week, Assignment.week_id == Week.id)
                .where(
                    and_(
                        counted_assignment(Assignment),
                        Assignment.participant_id.isnot(None),
                    )
                )
            ).all()
            for pid, sec, sec_pos, text, start_date in light_rows:
                if (sec or "", self._position_key(sec_pos, text)) in light_keys:
                    dt = date_to_datetime(start_date)
                    if dt:
                        light_dates.setdefault(pid, []).append(dt)

        def _without(dates: List[datetime], remove: List[datetime]) -> List[datetime]:
            """Вычесть даты как мультимножество (в одну неделю может быть два задания)."""
            rest = list(dates)
            for d in remove:
                if d in rest:
                    rest.remove(d)
            return rest

        from datetime import timedelta

        window_start = current_date_dt - timedelta(weeks=self.LOAD_WINDOW_WEEKS)

        def _load_in_window(dates: List[datetime]) -> int:
            return sum(1 for d in dates if window_start <= d < current_date_dt)

        def _nearest(dates: List[datetime]) -> Optional[datetime]:
            """Ближайшее назначение, выраженное как «прошлая» дата.

            Фильтр и выбор считают интервалы от «последней» даты. Чтобы они
            работали в обе стороны, будущее назначение через N недель
            подставляется как дата N недель назад: при перераспределении
            более ранней недели человек, уже стоящий на следующей, не
            получит пункт неделей раньше (тот же пункт две недели подряд).
            """
            last = _last_before(dates)
            if not consider_future:
                return last
            future = [d for d in dates if d > current_date_dt]
            if not future:
                return last
            mirrored = current_date_dt - (min(future) - current_date_dt)
            return mirrored if last is None or mirrored > last else last

        def _last_before(dates: List[datetime]) -> Optional[datetime]:
            past = [d for d in dates if d < current_date_dt]
            return max(past) if past else None

        # Convert DTOs to dict format
        from datetime import timedelta
        from core.models import ParticipantExcludedWeek

        week_start = current_date_dt.date()
        week_end = week_start + timedelta(days=6)

        # Load all excluded-week records for this specific week in a single query (no N+1)
        excluded_this_week_ids = set(
            session.execute(
                select(ParticipantExcludedWeek.participant_id).where(
                    ParticipantExcludedWeek.week_start == week_start
                )
            )
            .scalars()
            .all()
        )

        participants_data = []
        for dto in participants_dto:
            # 1. Filter out participants who are temporarily unavailable (on vacation)
            if dto.unavailable_from and dto.unavailable_to:
                if dto.unavailable_from <= week_end and week_start <= dto.unavailable_to:
                    continue
            elif dto.unavailable_from:
                if week_end >= dto.unavailable_from:
                    continue
            elif dto.unavailable_to:
                if week_start <= dto.unavailable_to:
                    continue

            # 2. Filter out participants excluded for this specific week (shift schedule / one-off skip)
            if dto.id in excluded_this_week_ids:
                continue

            last_date_dt = dto.last_assignment_date
            last_role_info = last_student_assignment.get(dto.id)
            last_student_role = last_role_info[1] if last_role_info else None

            p_data = {
                "id": dto.id,
                "name": dto.name,
                "gender": dto.gender,
                "service_type": dto.service_type,
                "family_group_id": dto.family_group_id,
                "last_assignment_date": last_date_dt,
                "last_main_date": dto.last_main_date,
                "total_assignments": dto.total_assignments,
                "qualifications": dto.qualifications,
                "personal_gap": dto.personal_gap,  # Per-participant gap override
                "is_minor": dto.is_minor,  # Несовершеннолетний участник
                "last_student_role": last_student_role,
            }

            # Полная история (все задания) — для лёгких заданий.
            all_dates = dates_map.get(dto.id, [])
            all_main_dates = main_dates_map.get(dto.id, [])
            p_light = light_dates.get(dto.id, [])
            p_data["all_total"] = _load_in_window(all_dates)
            p_data["all_last_date"] = _nearest(all_dates)
            p_data["all_last_main_date"] = _nearest(all_main_dates)

            # История только полноценных заданий — для пунктов программы:
            # лёгкие задания не сдвигают очередь и не блокируют интервалом.
            p_data["total_assignments"] = _load_in_window(_without(all_dates, p_light))
            p_data["effective_last_date"] = _nearest(_without(all_dates, p_light))
            p_data["effective_last_main_date"] = _nearest(_without(all_main_dates, p_light))
            participants_data.append(p_data)

        return {
            "participants_data": participants_data,
            "dates_map": dates_map,
            "position_dates_map": position_dates_map,
            "pairs_map": pairs_map,
        }

    @staticmethod
    def _position_key(section_position, assignment_text) -> str:
        """Канонический ключ позиции для assignment_config.

        Для fresh-импорта section_position уже строковый ключ. Для legacy-данных
        с section_position IS NULL позиция выводится из assignment_text (W-7:
        иначе prayer_* оставались без config и терялся is_brothers_only).
        """
        if section_position is not None:
            return str(section_position)
        text = (assignment_text or "").strip().lower()
        return {
            "председатель": "chairman",
            "молитва (открытие)": "prayer_open",
            "молитва (закрытие)": "prayer_close",
        }.get(text, "")

    @staticmethod
    def _treasures_talk_weeks_left(session, current_date_dt: datetime) -> int:
        """Сколько недель месяца, начиная с текущей, содержат «Вступительную речь»
        (недели без программы — конгресс, Вечеря, пустые — не считаются)."""
        start = current_date_dt.date()
        if start.month == 12:
            month_end = start.replace(year=start.year + 1, month=1, day=1)
        else:
            month_end = start.replace(month=start.month + 1, day=1)
        return (
            session.execute(
                select(func.count(func.distinct(Week.id)))
                .join(Assignment, Assignment.week_id == Week.id)
                .where(
                    and_(
                        Week.start_date >= start,
                        Week.start_date < month_end,
                        Assignment.section == "treasures",
                        Assignment.section_position == "1",
                        Assignment.status != AssignmentStatus.DISABLED.value,
                    )
                )
            ).scalar()
            or 0
        )

    def _annotate_position_counts(
        self,
        candidates: List[dict],
        section: str,
        position: str,
        current_date_dt: datetime,
        position_dates_map: Dict[tuple, List[datetime]],
    ) -> None:
        """Записать в кандидатов _pos_count — сколько раз за LOAD_WINDOW_WEEKS
        каждый получал позицию (section, position) до текущей недели."""
        window_start = current_date_dt - timedelta(weeks=self.LOAD_WINDOW_WEEKS)
        for p in candidates:
            dates = position_dates_map.get((p["id"], section, position), [])
            p["_pos_count"] = sum(1 for d in dates if window_start <= d < current_date_dt)

    @staticmethod
    def _light_views(participants: List[dict]) -> List[dict]:
        """Копии участников, где история для фильтра/выбора — полная.

        Фильтр и выбор читают total_assignments / effective_last_*; для лёгких
        заданий подставляем all_*. Выбранный по id маппится обратно на оригинал.
        """
        return [
            {
                **p,
                "total_assignments": p["all_total"],
                "effective_last_date": p["all_last_date"],
                "effective_last_main_date": p["all_last_main_date"],
            }
            for p in participants
        ]

    def _assignment_priority(self, a: Assignment) -> Tuple[int, int]:
        """Calculate assignment priority for sorting."""
        sec = a.section or ""
        pos = a.section_position or ""
        sec_order = self.SECTION_PRIORITY.get(sec, 5)

        try:
            pos_order = int(pos)
        except (ValueError, TypeError):
            pos_order = 99 if pos != "chairman" else 0

        return (sec_order, pos_order)

    def _setup_debug_logger(self, truncate_log: bool = True) -> logging.Logger:
        """Setup debug logger for assignment process.

        Args:
            truncate_log: если True — открыть файл в режиме "w" (обрезать).
                Если False — режим "a" (допись). Используется auto_assign_all,
                чтобы лог всех недель сохранялся, а не перетирался последней.
        """
        debug_logger = logging.getLogger("auto_assign_debug")
        debug_logger.setLevel(logging.DEBUG)
        # Предотвращаем накопление утечённых handlers от предыдущих вызовов,
        # прерванных исключением до `_close_debug_logger`.
        for h in list(debug_logger.handlers):
            try:
                h.close()
            except Exception:
                pass
            debug_logger.removeHandler(h)
        fh = logging.FileHandler(
            "auto_assign_debug.log",
            mode="w" if truncate_log else "a",
            encoding="utf-8",
        )
        fh.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
        debug_logger.addHandler(fh)
        return debug_logger

    def _close_debug_logger(self, logger: logging.Logger):
        """Close debug logger handler."""
        if logger.handlers:
            logger.handlers[0].close()
            logger.removeHandler(logger.handlers[0])


class _SessionBasedRepository:
    """
    Helper class for repository operations when only session is available.
    Provides same interface as ParticipantRepository for date mapping methods.
    """

    def __init__(self, session):
        self._session = session

    def get_assignment_dates_map(self, session=None) -> Dict[int, List[datetime]]:
        """Get mapping of participant_id to list of assignment dates."""
        from sqlalchemy import select

        from core.models import Week

        # Use provided session or internal session
        sess = session or self._session

        query = (
            select(Assignment.participant_id, Assignment.assistant_id, Week.start_date)
            .join(Week, Assignment.week_id == Week.id)
            .where(counted_assignment(Assignment))
        )
        results = sess.execute(query).all()

        dates_map: Dict[int, List[datetime]] = {}
        for participant_id, assistant_id, start_date in results:
            dt = date_to_datetime(start_date)
            if not dt:
                continue

            if participant_id:
                dates_map.setdefault(participant_id, []).append(dt)
            if assistant_id:
                dates_map.setdefault(assistant_id, []).append(dt)

        for pid in dates_map:
            dates_map[pid].sort()

        return dates_map

    def get_main_assignment_dates_map(self, session=None) -> Dict[int, List[datetime]]:
        """Get mapping of participant_id to list of main assignment dates."""
        from sqlalchemy import select

        from core.models import Week

        sess = session or self._session

        query = (
            select(Assignment.participant_id, Week.start_date)
            .join(Week, Assignment.week_id == Week.id)
            .where(counted_assignment(Assignment))
            .where(Assignment.participant_id.isnot(None))
        )
        results = sess.execute(query).all()

        dates_map: Dict[int, List[datetime]] = {}
        for participant_id, start_date in results:
            dt = date_to_datetime(start_date)
            if not dt:
                continue

            dates_map.setdefault(participant_id, []).append(dt)

        for pid in dates_map:
            dates_map[pid].sort()

        return dates_map

    def get_position_dates_map(self, session=None) -> Dict[Tuple[int, str, str], List[datetime]]:
        """Get mapping of (participant_id, section, position) to list of dates."""
        from sqlalchemy import select

        from core.models import Week

        sess = session or self._session

        query = (
            select(
                Assignment.participant_id,
                Assignment.assistant_id,
                Assignment.section,
                Assignment.section_position,
                Week.start_date,
            )
            .join(Week, Assignment.week_id == Week.id)
            .where(counted_assignment(Assignment))
        )
        results = sess.execute(query).all()

        position_dates_map: Dict[Tuple[int, str, str], List[datetime]] = {}
        for participant_id, assistant_id, section, position, start_date in results:
            dt = date_to_datetime(start_date)
            if not dt or not section:
                continue

            key_sec_pos = (section, str(position or ""))

            if participant_id:
                key = (participant_id, *key_sec_pos)
                position_dates_map.setdefault(key, []).append(dt)
            if assistant_id:
                key = (assistant_id, *key_sec_pos)
                position_dates_map.setdefault(key, []).append(dt)

        for key in position_dates_map:
            position_dates_map[key].sort()

        return position_dates_map

    def get_recent_pairs_map(self, session=None) -> Dict[Tuple[int, int], List[datetime]]:
        """Get mapping of unordered participant pairs (p1, p2) to assignment dates."""
        from sqlalchemy import select
        from core.models import Week

        sess = session or self._session

        query = (
            select(Assignment.participant_id, Assignment.assistant_id, Week.start_date)
            .join(Week, Assignment.week_id == Week.id)
            .where(counted_assignment(Assignment))
            .where(Assignment.participant_id.isnot(None))
            .where(Assignment.assistant_id.isnot(None))
        )
        results = sess.execute(query).all()

        pairs_map: Dict[Tuple[int, int], List[datetime]] = {}
        for p1_id, p2_id, start_date in results:
            dt = date_to_datetime(start_date)
            if not dt or not p1_id or not p2_id:
                continue
            pair_key = (min(p1_id, p2_id), max(p1_id, p2_id))
            pairs_map.setdefault(pair_key, []).append(dt)

        for key in pairs_map:
            pairs_map[key].sort()

        return pairs_map
