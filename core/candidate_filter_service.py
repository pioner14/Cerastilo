import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from core.assignment_rules import ELDER_TYPES, allowed_service_types
from core.models import AssignmentConfig


class CandidateFilterService:
    """
    Service for filtering candidate participants based on assignment criteria.
    Extracted from AutoAssignmentService to adhere to Single Responsibility Principle.

    Gap priority (highest to lowest):
    1. participant['personal_gap'] — personal override (None = use default)
    2. service_type rule: "E"/"elder" → 0, "MS" → ms_gap, else → min_gap
    3. Fallback global min_gap
    """

    # Минимальный интервал (недель) между одинаковыми позициями для тех, кто
    # освобождён от общего интервала (старейшины, personal_gap=0), если для
    # позиции не задан elder_position_gap или личная настройка.
    EXEMPT_POSITION_GAP_WEEKS = 4

    # «Вступительная речь» (treasures/1): сколько раз в календарный месяц её
    # ведёт служебный помощник (остальные недели — старейшины). Обычно это
    # 2-я и 4-я недели месяца; если там никого из MS не нашлось — следующие.
    MS_TREASURES_TALKS_PER_MONTH = 2
    MS_TREASURES_TALK_WEEKS = (2, 4)

    def __init__(self, min_gap: int, ms_gap: int = None):
        self.min_gap = min_gap
        # Учитывать назначения на более поздних неделях в интервале по позиции
        self.consider_future = False
        # ms_gap = gap для служебных помощников.
        # Если не задан — равен min_gap (обратная совместимость).
        self.ms_gap = ms_gap if ms_gap is not None else min_gap

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _effective_gap(self, participant: dict) -> int:
        """
        Compute the applicable gap for a participant.

        Priority:
        1. personal_gap (if set — overrides everything, incl. Elder exemption)
        2. service_type rule:
           - "E" / "elder" → 0 (fully exempt, can be assigned every week)
           - "MS"          → self.ms_gap
           - everything else → self.min_gap
        """
        personal = participant.get("personal_gap")
        if personal is not None:
            return personal  # 0 = always available, N = once per N weeks

        stype = participant.get("service_type", "")
        if stype in ("E", "elder"):
            return 0  # Elders: fully exempt
        if stype == "MS":
            return self.ms_gap

        return self.min_gap

    # ------------------------------------------------------------------
    # Main filter
    # ------------------------------------------------------------------

    def filter_candidates(
        self,
        participants: List[dict],
        assigned_this_week: set,
        config: Any,
        current_date_dt: datetime,
        position_dates_map: Dict[tuple, List[datetime]],
        section: str,
        position: str,
        logger: Any = None,
        assignment_text: Optional[str] = None,
        participant_position_configs: Optional[Dict[Tuple[int, str, str], int]] = None,
        relax_role_alternation: bool = False,
        allow_ms_treasures_week: bool = True,
        program_weeks_left_in_month: Optional[int] = None,
    ) -> List[dict]:
        """Filter candidates based on assignment criteria.

        Args:
            participants: Full list of participant dicts.
            assigned_this_week: IDs already assigned this week.
            config: AssignmentConfig ORM object (or None).
            current_date_dt: Current week date.
            position_dates_map: History of positions per participant.
            section: Assignment section (e.g. 'fixed', 'treasures').
            position: Assignment position string (e.g. 'chairman', '1').
            logger: Optional logger for debug output.
            assignment_text: Raw assignment text (used for «местные потребности»).
            participant_position_configs: Optional dict mapping
                ``(participant_id, section, position) -> position_gap`` for
                per-participant position gap overrides.  When a key is found
                here, it takes precedence over ``assignment_config.elder_position_gap``.
        """
        candidates = participants
        initial_count = len(candidates)
        ms_treasures_week = False

        if logger:
            logger.info(f"Initial candidates: {initial_count}")
        # 1. Filter by assignments this week
        candidates = [p for p in candidates if p["id"] not in assigned_this_week]
        if logger:
            logger.info(
                f"After WeekDupe check: {len(candidates)} (removed {initial_count - len(candidates)})"
            )

        # 1.5. Filter out elders for student assignments
        # НО не для пункта-обсуждения: он ведётся братом (в т.ч. может быть
        # старейшиной/служителем), role-alternation тоже не применима (одно
        # выступление, не учебное задание с учеником).
        is_student_assignment = (
            (section == "treasures" and position == "3") or (section == "ministry")
        ) and not (
            config is not None
            and (
                getattr(config, "is_discussion_item", False)
                or getattr(config, "is_talk_item", False)
            )
        )
        if is_student_assignment:
            prev_count = len(candidates)
            candidates = [p for p in candidates if p.get("service_type") not in ("E", "elder")]
            if logger:
                logger.info(
                    f"After Elder check for student assignment: {len(candidates)} (removed {prev_count - len(candidates)})"
                )

        # 2. Filter by qualification
        req_qual = config.required_qualification if config else None
        if req_qual:
            prev_count = len(candidates)
            candidates = [p for p in candidates if req_qual in p["qualifications"]]
            if logger:
                logger.info(
                    f"After Qual check ({req_qual}): {len(candidates)} (removed {prev_count - len(candidates)})"
                )
            if logger and len(candidates) == 0:
                logger.warning(
                    f"No candidates left after qualification filter. Required: {req_qual}"
                )

        # 2.3. Статус служения: только старейшины (председатель, ведущий ИБС,
        # «Местные потребности») или старейшины и служебные помощники
        # (core.assignment_rules.allowed_service_types)
        allowed_types = allowed_service_types(section, position, config, assignment_text)
        is_elder_only = allowed_types == ELDER_TYPES
        if allowed_types:
            prev_count = len(candidates)
            candidates = [p for p in candidates if p.get("service_type") in allowed_types]
            if logger:
                logger.info(
                    f"After service type check {allowed_types}: "
                    f"{len(candidates)} (removed {prev_count - len(candidates)})"
                )

        # 2.4. Treasures Talk (treasures / 1) — «Вступительная речь»:
        # Жёсткое правило: назначать ТОЛЬКО старейшин или служебных помощников (MS).
        # Обычные возвещатели (publisher) к этому пункту не допускаются.
        # Мягкое предпочтение: если среди допущенных есть хотя бы один старейшина —
        # в итоговый пул попадают только старейшины. Если старейшин нет — пул = все MS.
        if section == "treasures" and position == "1" and not is_elder_only:
            prev_count = len(candidates)
            # 1. Жёсткий фильтр — только E/elder и MS
            candidates = [p for p in candidates if p.get("service_type") in ("E", "elder", "MS")]
            if logger:
                logger.info(
                    f"Treasures/1: hard filter applied — only elders/MS allowed. "
                    f"{prev_count} → {len(candidates)} candidates."
                )

            ms_in_pool = [p for p in candidates if p.get("service_type") == "MS"]
            elders_in_pool = [p for p in candidates if p.get("service_type") in ("E", "elder")]

            if (
                allow_ms_treasures_week
                and ms_in_pool
                and current_date_dt
                and self._is_ms_treasures_talk_week(
                    participants, current_date_dt, position_dates_map, program_weeks_left_in_month
                )
            ):
                # 2. Неделя служебного помощника (дважды в месяц) — только MS.
                # Если их всех потом отсеют интервалы — см. повтор в конце.
                candidates = ms_in_pool
                ms_treasures_week = True
                if logger:
                    logger.info(f"Treasures/1: MS week — using {len(ms_in_pool)} MS candidate(s).")
            elif elders_in_pool:
                # 3. Мягкое предпочтение старейшин
                candidates = elders_in_pool
                if logger:
                    logger.info(
                        f"Treasures/1: soft elder preference — using {len(elders_in_pool)} elder(s)."
                    )
            elif logger:
                logger.info(
                    f"Treasures/1: no elders — falling back to {len(candidates)} MS candidate(s)."
                )

        # 2.5. Filter for student role alteration (exclude if last_student_role == "main")
        # Только для заданий с напарником: у чтения Библии напарника нет, и каждый
        # читавший навсегда оставался «main» — к чтению больше не допускался.
        needs_assistant = bool(config is not None and getattr(config, "needs_assistant", False))
        if is_student_assignment and needs_assistant and not relax_role_alternation:
            candidates_before_alteration = candidates.copy()
            prev_count = len(candidates)
            candidates = [p for p in candidates if p.get("last_student_role") != "main"]
            if logger:
                logger.info(
                    f"After Student Role Alteration check (exclude last main): {len(candidates)} (removed {prev_count - len(candidates)})"
                )

            # Relax if no candidates left
            if len(candidates) == 0:
                if logger:
                    logger.warning(
                        "No candidates left after Student Role Alteration check! Relaxing constraint."
                    )
                candidates = candidates_before_alteration

        # Сохраняем кандидатов после фильтрации по квалификации/статусам для возможного использования в relaxation
        candidates_after_qual = candidates.copy()

        # 3. Filter by gender
        if config and config.is_brothers_only:
            prev_count = len(candidates)
            candidates = [p for p in candidates if p["gender"] == "male"]
            if logger:
                logger.info(
                    f"After Gender check: {len(candidates)} (removed {prev_count - len(candidates)})"
                )
            if logger and len(candidates) == 0:
                logger.warning("No male candidates left after gender filter")

        # 4. Filter by global gap (per-participant effective gap)
        if current_date_dt:
            prev_count = len(candidates)
            # ЖЁСТКАЯ блокировка: интервал считается по ЛЮБОЙ роли (главный ИЛИ напарник).
            # Это правило нерелаксируемо — участник не может выступать чаще
            # min_gap недель ни в каком качестве (см. требование «раз в 4 недели
            # не важно, помощником или ведущим»).
            hard_valid = []
            soft_candidates = []  # кандидаты, прошедшие жёсткий фильтр — к ним
            # ниже применяется мягкий gap по гл.роли (с relaxation)
            for p in candidates:
                eff_gap = self._effective_gap(p)
                if eff_gap == 0:
                    # Полностью освобождён (Elder или personal_gap=0)
                    hard_valid.append(p)
                    soft_candidates.append((p, None))  # нет soft-ограничения
                    continue

                last_any = p.get("effective_last_date")
                if not last_any:
                    hard_valid.append(p)
                    soft_candidates.append((p, None))
                    continue

                gap_any = (current_date_dt - last_any).days / 7
                if gap_any >= eff_gap:
                    # Жёсткий фильтр по любой роли пройден.
                    # Soft-проверка — по дате главной роли (relaxable).
                    soft_candidates.append((p, p.get("effective_last_main_date")))
                # иначе: заблокирован жёстко, в relaxation не попадает.

            valid_by_gap = list(hard_valid)

            # Мягкая проверка по гл.роли + stepwise relaxation.
            if soft_candidates:
                soft_pass = [p for p, last_main in soft_candidates if last_main is None]
                soft_pending = [
                    (p, last_main) for p, last_main in soft_candidates if last_main is not None
                ]
                for p, last_main in soft_pending:
                    p_eff = self._effective_gap(p)
                    gap_main = (current_date_dt - last_main).days / 7
                    if gap_main >= p_eff:
                        soft_pass.append(p)

                if soft_pass:
                    valid_by_gap = soft_pass
                else:
                    # Stepwise relaxation ПО ГЛАВНОЙ РОЛИ (напарник не релаксируется).
                    if logger:
                        logger.warning(
                            f"No candidates left after main-role soft gap. "
                            f"Relaxing main-role gap."
                        )
                    for relaxed_ratio in [0.5, 0.0]:
                        relaxed_pool = list(hard_valid)
                        for p, last_main in soft_pending:
                            relaxed = (
                                max(1, int(self._effective_gap(p) * relaxed_ratio))
                                if relaxed_ratio > 0
                                else 0
                            )
                            gap_main = (current_date_dt - last_main).days / 7
                            if gap_main >= relaxed:
                                relaxed_pool.append(p)
                        if relaxed_pool:
                            valid_by_gap = relaxed_pool
                            if logger:
                                logger.info(
                                    f"Main-role gap relaxed (ratio={relaxed_ratio}), "
                                    f"found {len(valid_by_gap)} candidates"
                                )
                            break

            # Global gap relaxation fallback (только если жёсткий ANY-role
            # фильтр полностью выкосил всех — крайне редкий случай для малых
            # собраний). Здесь ANY-role (last_any) остаётся НЕрелаксируемым
            # (железное правило «раз в min_gap недель в любой роли»), а
            # релаксируется ТОЛЬКО дата главной роли (last_main).
            if not valid_by_gap and len(hard_valid) == 0:
                if logger:
                    logger.warning(
                        f"No candidates left after global gap filter. "
                        f"min_gap={self.min_gap}, ms_gap={self.ms_gap}. "
                        f"Hard-relaxing main-role gap only (last resort)."
                    )
                for relaxed_ratio in [0.5, 0.0]:
                    pool = []
                    for p in candidates:
                        eff_gap = self._effective_gap(p)
                        if eff_gap == 0:
                            pool.append(p)
                            continue
                        last_any = p.get("effective_last_date")
                        last_main = p.get("effective_last_main_date")
                        # ANY-role: жёстко, без релаксации.
                        if last_any:
                            gap_any = (current_date_dt - last_any).days / 7
                            if gap_any < eff_gap:
                                continue
                        # Main-role: релаксируем.
                        if not last_main:
                            pool.append(p)
                            continue
                        relaxed = max(1, int(eff_gap * relaxed_ratio)) if relaxed_ratio > 0 else 0
                        gap_main = (current_date_dt - last_main).days / 7
                        if gap_main >= relaxed:
                            pool.append(p)
                    if pool:
                        valid_by_gap = pool
                        if logger:
                            logger.info(
                                f"Global gap hard-relaxed (ratio={relaxed_ratio}, "
                                f"main-role only), found {len(valid_by_gap)} candidates"
                            )
                        break

            candidates = valid_by_gap
            if logger:
                logger.info(
                    f"After Global Gap check: {len(candidates)} (removed {prev_count - len(candidates)})"
                )
            if logger and len(candidates) == 0:
                logger.warning(
                    f"No candidates left after global gap filter. min_gap={self.min_gap}"
                )

        # Сохраняем кандидатов после всех фильтров кроме position gap для возможного использования в relaxation
        candidates_before_position_gap = candidates.copy()

        # 5. Filter by position gap (eff_gap * 2, per-participant)
        # spec://services/auto_assignment#position_gap_filter
        #
        # Gap priority (highest → lowest) for each candidate on this position:
        #  1. participant_position_configs[(id, section, position)]  — personal override
        #  2. config.elder_position_gap (if elder)                   — global elder override
        #  3. eff_gap == 0                                           — fully exempt
        #  4. eff_gap * 2                                            — standard formula
        if current_date_dt and section:
            prev_count = len(candidates)
            valid_by_pos = []
            # Track candidates with their gap for weighted selection fallback
            candidates_with_gap: List[Tuple[dict, float]] = []

            # Read elder override from config (None → no override)
            elder_pos_gap_override = getattr(config, "elder_position_gap", None) if config else None

            for p in candidates:
                eff_gap = self._effective_gap(p)
                is_elder = p.get("service_type") in ("E", "elder")
                p_id = p["id"]

                # Determine actual position gap for this candidate.
                personal_pos_gap = (
                    participant_position_configs.get((p_id, section, position))
                    if participant_position_configs
                    else None
                )

                if personal_pos_gap is not None:
                    # 1. Personal override — highest priority
                    actual_pos_gap = personal_pos_gap
                elif is_elder and elder_pos_gap_override is not None:
                    # 2. Global elder override for this position
                    actual_pos_gap = elder_pos_gap_override
                elif eff_gap == 0:
                    # 3. Освобождён от общего интервала (старейшина или personal_gap=0):
                    # может выступать каждую неделю, но не с одной и той же позицией.
                    actual_pos_gap = self.EXEMPT_POSITION_GAP_WEEKS
                else:
                    # 4. Standard formula
                    actual_pos_gap = eff_gap * 2

                pos_key = (p_id, section, position)
                pos_dates = position_dates_map.get(pos_key, [])
                if not pos_dates:
                    valid_by_pos.append(p)
                    candidates_with_gap.append((p, float("inf")))
                else:
                    # Ближайшее назначение на эту позицию — в прошлом или (если
                    # учитываем) в будущем: тот же пункт две недели подряд не
                    # должен получиться и при перераспределении ранней недели.
                    others = [
                        d
                        for d in pos_dates
                        if d < current_date_dt or (self.consider_future and d > current_date_dt)
                    ]
                    if not others:
                        valid_by_pos.append(p)
                        candidates_with_gap.append((p, float("inf")))
                    else:
                        gap_weeks = min(abs((current_date_dt - d).days) for d in others) / 7
                        candidates_with_gap.append((p, gap_weeks))
                        if gap_weeks >= actual_pos_gap:
                            valid_by_pos.append(p)

            # Relaxation logic with early returns for clarity
            # spec://services/auto_assignment#relaxation_logic
            if len(valid_by_pos) >= 2:
                candidates = valid_by_pos
                if logger:
                    logger.info(
                        f"After Position Gap check: {len(candidates)} (removed {prev_count - len(candidates)})"
                    )
            elif len(valid_by_pos) == 1:
                candidates = valid_by_pos
                if logger:
                    logger.info(
                        f"After Position Gap check: {len(candidates)} (only 1 candidate left)"
                    )
            else:
                # NO candidates pass position gap filter - use weighted selection
                candidates = self._apply_position_gap_relaxation(
                    candidates, candidates_with_gap, logger
                )

        if not candidates and ms_treasures_week:
            # Неделя MS, но всех служебных помощников отсеяли интервалы —
            # пункт не оставляем пустым: отбираем заново по обычным правилам.
            if logger:
                logger.warning("Treasures/1: no MS left after filters — falling back to elders.")
            return self.filter_candidates(
                participants,
                assigned_this_week,
                config,
                current_date_dt,
                position_dates_map,
                section,
                position,
                logger,
                assignment_text=assignment_text,
                participant_position_configs=participant_position_configs,
                relax_role_alternation=relax_role_alternation,
                allow_ms_treasures_week=False,
                program_weeks_left_in_month=program_weeks_left_in_month,
            )

        return candidates

    def _is_ms_treasures_talk_week(
        self,
        participants: List[dict],
        current_date_dt: datetime,
        position_dates_map: Dict[tuple, List[datetime]],
        program_weeks_left_in_month: Optional[int] = None,
    ) -> bool:
        """Должен ли на этой неделе «Вступительную речь» вести служебный помощник.

        program_weeks_left_in_month — сколько недель месяца (включая текущую)
        ещё содержат этот пункт; без него считаются все понедельники месяца.

        Считает, сколько раз её уже вели MS в этом календарном месяце (по истории
        и по уже распределённым неделям), и даёт очередь MS на неделях
        MS_TREASURES_TALK_WEEKS — или раньше/позже, если иначе до конца месяца
        норму не набрать.
        """
        month = (current_date_dt.year, current_date_dt.month)
        ms_ids = {p["id"] for p in participants if p.get("service_type") == "MS"}
        ms_done = sum(
            1
            for (pid, sec, pos), dates in position_dates_map.items()
            if pid in ms_ids and sec == "treasures" and pos == "1"
            for d in dates
            if (d.year, d.month) == month and d < current_date_dt
        )
        needed = self.MS_TREASURES_TALKS_PER_MONTH - ms_done
        if needed <= 0:
            return False

        week_of_month = (current_date_dt.day - 1) // 7 + 1
        if program_weeks_left_in_month is not None:
            weeks_left = program_weeks_left_in_month
        else:
            # Сколько недель (понедельников) осталось в месяце, включая текущую
            weeks_left = 0
            d = current_date_dt
            while d.month == current_date_dt.month:
                weeks_left += 1
                d += timedelta(weeks=1)

        return week_of_month in self.MS_TREASURES_TALK_WEEKS or weeks_left <= needed

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
            position_gap_value = 999 if gap == float("inf") else gap
            p["_position_gap_weeks"] = position_gap_value

        if logger:
            logger.info(
                f"Relaxation: keeping {len(candidates)} candidates with weighted selection. "
                f"Gaps: {[(p['name'], p.get('_position_gap_weeks', 0)) for p in candidates]}"
            )

        return candidates

    def _cleanup_candidate_attributes(self, candidate: dict) -> None:
        """Remove temporary attributes from candidate to prevent mutation side-effects."""
        candidate.pop("_position_gap_weeks", None)

    def _cleanup_all_candidates_attributes(self, candidates: List[dict]) -> None:
        """Remove temporary attributes from all candidates to prevent mutation side-effects."""
        for p in candidates:
            p.pop("_position_gap_weeks", None)
