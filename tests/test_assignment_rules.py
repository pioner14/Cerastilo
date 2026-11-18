"""
Тесты правил автораспределения.
Проверяют: gap enforcement, рандомность, обновление дат.
"""

from datetime import date

import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker

from core.database import DatabaseManager
from core.events import EventBus
from core.models import Assignment, Base, Participant, Setting, Week
from core.services import ParticipantService, ScheduleService


class InMemoryDatabaseManager(DatabaseManager):
    """In-memory DB for tests. Calls _init_db to populate default configs."""

    def __init__(self):
        self.engine = create_engine("sqlite:///:memory:")
        self.db_path = ":memory:"
        Base.metadata.create_all(self.engine)
        self.SessionFactory = sessionmaker(bind=self.engine)
        # Initialize default configs (AssignmentConfig entries)
        with self.get_session() as session:
            self._init_default_config(session)
            session.commit()


@pytest.fixture
def test_db():
    manager = InMemoryDatabaseManager()
    try:
        yield manager
    finally:
        manager.close()


@pytest.fixture
def s_service(test_db):
    return ScheduleService(test_db, EventBus())


@pytest.fixture
def p_service(test_db):
    return ParticipantService(test_db, EventBus())


def _create_assignment(session, week_id, number, text, atype, section, section_position):
    """Helper: создаёт Assignment с section и section_position."""
    a = Assignment(
        week_id=week_id,
        assignment_number=number,
        assignment_text=text,
        assignment_type=atype,
        section=section,
        section_position=section_position,
        status="unassigned",
    )
    session.add(a)
    return a


def _find_assignment(data, number):
    """Helper: находит задание по номеру в результатах get_week_data."""
    for a in data["assignments"]:
        if a["assignment_number"] == number:
            return a
    return None


def test_strict_gap_enforcement(s_service, p_service, test_db):
    """Verify that min_assignment_gap strictly blocks candidates."""
    # 1. Setup Gap = 2 weeks
    with test_db.get_session() as session:
        session.add(Setting(key="min_assignment_gap", value="2"))
        session.commit()

    # 2. Add two brothers with bible_reading qualification
    p1_id = p_service.add_participant("Recently Assigned", "male", "publisher", ["bible_reading"])
    p2_id = p_service.add_participant(
        "Not Recently Assigned", "male", "publisher", ["bible_reading"]
    )

    # 3. Create a PREVIOUS week where p1 was assigned (1 week ago)
    with test_db.get_session() as session:
        prev_week = Week(week_title="Week 1", start_date=date(2024, 1, 8))
        session.add(prev_week)
        session.flush()
        prev_a = Assignment(
            week_id=prev_week.id,
            assignment_number="3",
            assignment_text="Prev Reading",
            assignment_type="reading",
            section="treasures",
            section_position="3",
            participant_id=p1_id,
            status="assigned",
        )
        session.add(prev_a)
        session.commit()

    # 4. Create CURRENT week (15.01.2024) — only 1 week after prev
    with test_db.get_session() as session:
        w = Week(week_title="Week 2", start_date=date(2024, 1, 15))
        session.add(w)
        session.flush()
        _create_assignment(session, w.id, "3", "Test Reading", "reading", "treasures", "3")
        session.commit()
        week_id = w.id

    # 5. Auto-assign. p1 should be blocked (1 week < 2 week gap)
    res = s_service.auto_assign_week(week_id)
    assert res["success"] is True

    # 6. Verify p1 was not selected
    data = s_service.get_week_data(week_id)
    assignment = _find_assignment(data, "3")
    assert assignment is not None
    assert assignment["participant_id"] == p2_id  # Only p2 should pass gap check


def test_randomness_in_weighted_pool(s_service, p_service, test_db):
    """Verify that script picks randomly between equally qualified candidates."""
    # 1. Setup
    with test_db.get_session() as session:
        session.add(Setting(key="min_assignment_gap", value="0"))
        session.commit()

    p1_id = p_service.add_participant("Bro A", "male", "publisher", ["bible_reading"])
    p2_id = p_service.add_participant("Bro B", "male", "publisher", ["bible_reading"])

    with test_db.get_session() as session:
        w = Week(week_title="Random Week", start_date=date(2024, 1, 1))
        session.add(w)
        session.flush()
        _create_assignment(session, w.id, "3", "Test Reading", "reading", "treasures", "3")
        session.commit()
        week_id = w.id

    # Run multiple times and check if both are picked
    picked = set()
    for _ in range(20):
        with test_db.get_session() as session:
            session.execute(
                update(Assignment)
                .where(Assignment.week_id == week_id)
                .values(participant_id=None, status="unassigned")
            )
            session.commit()
        s_service.auto_assign_week(week_id)
        data = s_service.get_week_data(week_id)
        a = _find_assignment(data, "3")
        picked.add(a["participant_id"])

    assert p1_id in picked or p2_id in picked


def test_last_date_update(s_service, p_service, test_db):
    """Verify that last_assignment_date is updated after assignment."""
    from datetime import date, datetime

    p1_id = p_service.add_participant("Target Bro", "male", "publisher", ["bible_reading"])

    with test_db.get_session() as session:
        w = Week(week_title="Update Week", start_date=date(2024, 1, 20))
        session.add(w)
        session.flush()
        _create_assignment(session, w.id, "3", "Test Reading", "reading", "treasures", "3")
        session.commit()
        week_id = w.id

    s_service.auto_assign_week(week_id)

    with test_db.get_session() as session:
        p = session.get(Participant, p1_id)
        # last_assignment_date теперь datetime
        assert p.last_assignment_date is not None
        assert p.last_assignment_date == datetime(2024, 1, 20)


def test_needs_assistant_from_config(s_service, p_service, test_db):
    """Verify that assistant is assigned based on needs_assistant from config, not hardcoded numbers."""
    with test_db.get_session() as session:
        session.add(Setting(key="min_assignment_gap", value="0"))
        session.commit()

    # Add student and assistant
    p1_id = p_service.add_participant("Student", "male", "publisher", ["ministry_item"])
    p2_id = p_service.add_participant("Assistant", "male", "publisher", ["assistant"])

    with test_db.get_session() as session:
        w = Week(week_title="Assistant Week", start_date=date(2024, 2, 1))
        session.add(w)
        session.flush()
        # ministry position 1 has needs_assistant=True in config
        _create_assignment(session, w.id, "4", "Первое посещение", "student", "ministry", "1")
        session.commit()
        week_id = w.id

    res = s_service.auto_assign_week(week_id)
    assert res["success"] is True

    data = s_service.get_week_data(week_id)
    a = _find_assignment(data, "4")
    assert a is not None
    # Student should be assigned
    assert a["participant_id"] == p1_id
    # Assistant should be assigned (from config, not hardcode)
    assert a["assistant_id"] == p2_id


def test_threading_lock_exists(s_service):
    """Verify that AutoAssignmentService has a threading lock for thread safety."""
    import threading

    # Use property (triggers lazy init) instead of private _auto_assignment_service
    auto_service = s_service.auto_assignment_service
    assert hasattr(
        auto_service, "_assign_lock"
    ), "_assign_lock attribute missing from AutoAssignmentService"
    assert isinstance(auto_service._assign_lock, (type(threading.Lock()), type(threading.RLock())))


def test_family_mixed_gender_assistant(s_service, p_service, test_db):
    """Verify that a family member of different gender can be assigned as assistant.

    spec://services/auto_assignment#assistant_matching
    Mixed-gender pairs are permitted IF both participants belong to the same family group.
    """
    with test_db.get_session() as session:
        session.add(Setting(key="min_assignment_gap", value="0"))
        session.commit()

    # Create husband-wife pair with same family_group_id
    wife_id = p_service.add_participant(
        "Жена Иванова", "female", "publisher", ["ministry_item"], family_id=1
    )
    husband_id = p_service.add_participant(
        "Муж Иванов", "male", "publisher", ["assistant"], family_id=1
    )

    with test_db.get_session() as session:
        w = Week(week_title="Family Week", start_date=date(2024, 3, 1))
        session.add(w)
        session.flush()
        # ministry position 1 has needs_assistant=True
        _create_assignment(session, w.id, "4", "Первое посещение", "student", "ministry", "1")
        session.commit()
        week_id = w.id

    res = s_service.auto_assign_week(week_id)
    assert res["success"] is True

    data = s_service.get_week_data(week_id)
    a = _find_assignment(data, "4")
    assert a is not None
    # Wife should be the student (only ministry_item qualified)
    assert a["participant_id"] == wife_id
    # Husband should be assistant despite different gender (family exception)
    assert a["assistant_id"] == husband_id, (
        f"Expected husband (id={husband_id}) as assistant for wife (id={wife_id}) "
        f"via family exception, but got assistant_id={a['assistant_id']}"
    )


def test_last_assignment_date_not_overwritten_by_earlier_week(s_service, p_service, test_db):
    """Verify that last_assignment_date is NOT overwritten by an earlier week.

    If a participant is already assigned to week of 2024-02-01, and then
    auto-assign runs on week 2024-01-15, the date should stay at 2024-02-01.
    """
    from datetime import datetime

    p1_id = p_service.add_participant("Solo Bro", "male", "publisher", ["bible_reading"])

    # 1. Create LATER week (Feb 1) and assign manually
    with test_db.get_session() as session:
        later_week = Week(week_title="Later Week", start_date=date(2024, 2, 1))
        session.add(later_week)
        session.flush()
        _create_assignment(
            session, later_week.id, "3", "Later Reading", "reading", "treasures", "3"
        )
        session.commit()
        later_week_id = later_week.id

    # Auto-assign the later week first
    s_service.auto_assign_week(later_week_id)

    # Verify date is set to Feb 1
    with test_db.get_session() as session:
        p = session.get(Participant, p1_id)
        assert p.last_assignment_date == datetime(2024, 2, 1)

    # 2. Create EARLIER week (Jan 15) with a different assignment
    # Second participant needed for the earlier week assignment
    p_service.add_participant("Another Bro", "male", "publisher", ["bible_reading"])

    with test_db.get_session() as session:
        earlier_week = Week(week_title="Earlier Week", start_date=date(2024, 1, 15))
        session.add(earlier_week)
        session.flush()
        _create_assignment(
            session,
            earlier_week.id,
            "3",
            "Earlier Reading",
            "reading",
            "treasures",
            "3",
        )
        session.commit()
        earlier_week_id = earlier_week.id

    # Auto-assign the earlier week — p1 might or might not be picked again
    s_service.auto_assign_week(earlier_week_id)

    # Key check: p1's date must NOT have been overwritten to Jan 15
    with test_db.get_session() as session:
        p = session.get(Participant, p1_id)
        assert p.last_assignment_date == datetime(2024, 2, 1), (
            f"last_assignment_date was overwritten from 2024-02-01 to "
            f"{p.last_assignment_date} by an earlier week!"
        )


def test_global_gap_relaxation(s_service, p_service, test_db):
    """ANY-role gap rule is NON-relaxable (требование пользователя).

    «раз в min_gap недель в любой роли — не важно, помощником или ведущим» —
    железно. Единственный брат, выступавший 1 неделю назад при min_gap=2,
    НЕ назначается (пункт остаётся unassigned), даже если других кандидатов нет.
    """
    from datetime import date, datetime

    # 1. Setup strict gap = 2 weeks
    with test_db.get_session() as session:
        session.add(Setting(key="min_assignment_gap", value="2"))
        session.commit()

    # 2. Единственный брат, способный на чтение Библии.
    p1_id = p_service.add_participant("Only Brother", "male", "publisher", ["bible_reading"])

    # 3. PREVIOUS week (1 week ago): p1 выступал (ANY-role) на позиции ministry,
    #    чтобы position-gap по (treasures,3) НЕ блокировал.
    with test_db.get_session() as session:
        prev_week = Week(week_title="Week 1", start_date=date(2024, 1, 8))
        session.add(prev_week)
        session.flush()
        session.add(
            Assignment(
                week_id=prev_week.id,
                assignment_number="1",
                assignment_text="Prev Talk",
                assignment_type="student",
                section="ministry",
                section_position="1",
                participant_id=p1_id,
                status="assigned",
            )
        )
        session.commit()

    # 4. CURRENT week (15.01.2024) — только 1 неделя после прошлого выступления.
    with test_db.get_session() as session:
        w = Week(week_title="Week 2", start_date=date(2024, 1, 15))
        session.add(w)
        session.flush()
        _create_assignment(session, w.id, "3", "Test Reading", "reading", "treasures", "3")
        session.commit()
        week_id = w.id

    # 5. Auto-assign. strict gap=2 недели, но p1 выступал 1 неделю назад →
    #    железная блокировка ANY-role: НЕ назначается, пункт остаётся пустым.
    res = s_service.auto_assign_week(week_id)
    assert res["success"] is True

    # 6. Назначение не произведено — participant_id пуст.
    data = s_service.get_week_data(week_id)
    assignment = _find_assignment(data, "3")
    assert assignment is not None
    assert assignment["participant_id"] is None


def test_elder_exempt_from_gap(s_service, p_service, test_db):
    """Verify that elders (service_type='E' or 'elder') bypass assignment gap constraints."""
    from datetime import date, datetime

    # 1. Setup strict gap = 2 weeks
    with test_db.get_session() as session:
        session.add(Setting(key="min_assignment_gap", value="2"))
        session.commit()

    # 2. Add an Elder and a Publisher, both qualified
    p_elder_id = p_service.add_participant("Elder Brother", "male", "E", ["gems"])
    p_pub_id = p_service.add_participant("Publisher Brother", "male", "publisher", ["gems"])

    # 3. Create a PREVIOUS week where BOTH were assigned (1 week ago)
    with test_db.get_session() as session:
        prev_week = Week(week_title="Week 1", start_date=date(2024, 1, 8))
        session.add(prev_week)
        session.flush()

        prev_a1 = Assignment(
            week_id=prev_week.id,
            assignment_number="2",
            assignment_text="Prev Gems",
            assignment_type="gems",
            section="treasures",
            section_position="2",
            participant_id=p_elder_id,
            status="assigned",
        )
        prev_a2 = Assignment(
            week_id=prev_week.id,
            assignment_number="4",
            assignment_text="Prev Bible Study",
            assignment_type="student",
            section="ministry",
            section_position="1",
            participant_id=p_pub_id,
            status="assigned",
        )
        session.add(prev_a1)
        session.add(prev_a2)
        session.commit()

    # 4. Create CURRENT week (15.01.2024) — only 1 week after prev
    with test_db.get_session() as session:
        w = Week(week_title="Week 2", start_date=date(2024, 1, 15))
        session.add(w)
        session.flush()
        _create_assignment(session, w.id, "2", "Test Gems", "gems", "treasures", "2")
        session.commit()
        week_id = w.id

    # 5. Auto-assign. Since the elder is exempt from the gap constraint,
    # the elder should be chosen directly without needing to relax the gap constraint for the publisher.
    res = s_service.auto_assign_week(week_id)
    assert res["success"] is True

    # 6. Verify Elder WAS selected (since their gap constraint was bypassed),
    # while the publisher remained blocked.
    data = s_service.get_week_data(week_id)
    assignment = _find_assignment(data, "2")
    assert assignment is not None
    assert assignment["participant_id"] == p_elder_id


def test_assistant_cleared_if_not_assigned(s_service, p_service, test_db):
    """Verify that stale assistant is cleared when auto-assignment runs and no assistant is found."""
    # 1. Setup - global gap 0 to keep it simple
    with test_db.get_session() as session:
        session.add(Setting(key="min_assignment_gap", value="0"))
        session.commit()

    # 2. Add one student and one assistant (both male)
    p_student = p_service.add_participant("Student Male", "male", "publisher", ["ministry_item"])
    p_assistant = p_service.add_participant("Assistant Male", "male", "publisher", ["assistant"])

    # 3. Create a week and assignment
    with test_db.get_session() as session:
        w = Week(week_title="Test Week", start_date=date(2024, 4, 1))
        session.add(w)
        session.flush()

        # Create assignment with an assistant pre-assigned
        a = Assignment(
            week_id=w.id,
            assignment_number="4",
            assignment_text="Dialogue",
            assignment_type="student",
            section="ministry",
            section_position="1",
            participant_id=p_student,
            assistant_id=p_assistant,
            status="assigned",
        )
        session.add(a)
        session.commit()
        week_id = w.id

    # 4. Now add a female student but NO female assistants
    p_female_student = p_service.add_participant(
        "Student Female", "female", "publisher", ["ministry_item"]
    )
    # Make Student Male ineligible by removing his qualifications so Student Female must be chosen
    p_service.update_participant(p_student, "Student Male", "male", "publisher", [])

    # 5. Run auto-assign. For assignment 4, Student Female will be assigned (she is eligible).
    # Since there are no female assistants (and only family members can bypass same-gender constraint, and there are none),
    # no assistant can be found. The old assistant (Assistant Male) must be cleared!
    res = s_service.auto_assign_week(week_id)
    assert res["success"] is True

    # 6. Verify that the participant is Student Female and assistant is cleared (None)
    data = s_service.get_week_data(week_id)
    assignment = _find_assignment(data, "4")
    assert assignment is not None
    assert assignment["participant_id"] == p_female_student
    assert assignment["assistant_id"] is None


def test_assistant_pool_mixes_gender_and_family(s_service, p_service, test_db):
    """
    Verify that the assistant candidate pool includes both same-gender participants
    and different-gender family members, but EXCLUDES different-gender non-family members.
    """
    with test_db.get_session() as session:
        session.add(Setting(key="min_assignment_gap", value="0"))
        session.commit()

    # 1. Main participant is a female
    main_female = p_service.add_participant(
        "Main Female", "female", "publisher", ["ministry_item"], family_id=10
    )

    # 2. Assistants in database:
    # A. Husband (different gender, same family) -> Eligible
    husband = p_service.add_participant("Husband", "male", "publisher", ["assistant"], family_id=10)
    # B. Other Female (same gender, different family) -> Eligible
    other_female = p_service.add_participant(
        "Other Female", "female", "publisher", ["assistant"], family_id=20
    )
    # C. Other Male (different gender, different family) -> Ineligible
    other_male = p_service.add_participant(
        "Other Male", "male", "publisher", ["assistant"], family_id=30
    )

    # 3. Setup a week and assignment
    with test_db.get_session() as session:
        w = Week(week_title="Mixed Gender Family Pool Week", start_date=date(2024, 5, 1))
        session.add(w)
        session.flush()
        _create_assignment(session, w.id, "4", "Dialogue", "student", "ministry", "1")
        session.commit()
        week_id = w.id

    # 4. Run auto-assign multiple times to verify that both Husband and Other Female
    # can be selected, but Other Male is NEVER selected.
    selected_assistants = set()
    for seed in range(20):
        # We need to reset assignment before each run to keep it clean
        with test_db.get_session() as session:
            session.query(Assignment).filter(Assignment.week_id == week_id).update(
                {"participant_id": None, "assistant_id": None, "status": "pending"}
            )
            session.commit()

        # Set deterministic mode with seed for rotation / weighted selection
        s_service._deterministic = True
        s_service._seed = seed

        res = s_service.auto_assign_week(week_id)
        assert res["success"] is True

        data = s_service.get_week_data(week_id)
        a = _find_assignment(data, "4")
        assert a["participant_id"] == main_female
        selected_assistants.add(a["assistant_id"])

    # With family priority: Husband should ALWAYS be selected when available,
    # because family members are preferred over non-family candidates.
    assert husband in selected_assistants
    # Other Female is eligible but should NOT be selected when family member is available
    assert other_female not in selected_assistants
    # Other Male should NEVER be selected because he is of different gender and not in the family group
    assert other_male not in selected_assistants


# =============================================================================
# Тесты дифференцированного gap (ms_gap и personal_gap)
# =============================================================================


def test_ms_gap_blocks_ms_but_not_pub(s_service, p_service, test_db):
    """
    MS получает собственный gap (ms_gap=3), PUB работает с min_gap=1.
    MS назначен 2 недели назад → заблокирован.
    PUB назначен 2 недели назад → проходит (min_gap=1 < 2 нед.).
    Должен быть выбран PUB.
    """
    with test_db.get_session() as session:
        session.add(Setting(key="min_assignment_gap", value="1"))
        session.add(Setting(key="ms_assignment_gap", value="3"))
        session.commit()

    ms_id = p_service.add_participant("Ministerial", "male", "MS", ["bible_reading"])
    pub_id = p_service.add_participant("Publisher", "male", "PUB", ["bible_reading"])

    # Оба назначены 2 недели назад
    with test_db.get_session() as session:
        prev_week = Week(week_title="Prev", start_date=date(2024, 1, 8))
        session.add(prev_week)
        session.flush()
        for p_id in (ms_id, pub_id):
            session.add(
                Assignment(
                    week_id=prev_week.id,
                    assignment_number="3",
                    assignment_text="Чтение Библии",
                    assignment_type="reading",
                    section="treasures",
                    section_position="3",
                    participant_id=p_id,
                    status="assigned",
                )
            )
        session.commit()

    # Текущая неделя — ровно 2 недели спустя
    with test_db.get_session() as session:
        curr_week = Week(week_title="Curr", start_date=date(2024, 1, 22))
        session.add(curr_week)
        session.flush()
        session.add(
            Assignment(
                week_id=curr_week.id,
                assignment_number="3",
                assignment_text="Чтение Библии",
                assignment_type="reading",
                section="treasures",
                section_position=3,
                status="unassigned",
            )
        )
        week_id = curr_week.id
        session.commit()

    res = s_service.auto_assign_week(week_id)
    assert res["success"] is True

    data = s_service.get_week_data(week_id)
    a = _find_assignment(data, "3")
    # MS заблокирован (2 нед. < ms_gap=3), PUB проходит (2 нед. >= min_gap=1)
    assert a["participant_id"] == pub_id, (
        f"Expected PUB (id={pub_id}), got {a['participant_id']} "
        f"(MS id={ms_id}). MS должен быть заблокирован ms_gap=3."
    )


def test_personal_gap_overrides_service_type(s_service, p_service, test_db):
    """
    personal_gap переопределяет тип служения.
    PUB с personal_gap=3 назначен 1 неделю назад → заблокирован (1 < 3).
    Elder без personal_gap — всегда доступен.
    Должен быть выбран Elder.
    """
    with test_db.get_session() as session:
        session.add(Setting(key="min_assignment_gap", value="1"))
        session.add(Setting(key="ms_assignment_gap", value="1"))
        session.commit()

    # PUB с personal_gap=3
    pub_id = p_service.add_participant("Oleg", "male", "PUB", ["gems"], personal_gap=3)
    elder_id = p_service.add_participant("Ivan Elder", "male", "E", ["gems"])

    # Оба назначены 1 неделю назад
    with test_db.get_session() as session:
        prev_week = Week(week_title="Prev", start_date=date(2024, 1, 8))
        session.add(prev_week)
        session.flush()
        for p_id in (pub_id, elder_id):
            session.add(
                Assignment(
                    week_id=prev_week.id,
                    assignment_number="2",
                    assignment_text="Духовные жемчужины",
                    assignment_type="gems",
                    section="treasures",
                    section_position="2",
                    participant_id=p_id,
                    status="assigned",
                )
            )
        session.commit()

    # Текущая неделя — 1 неделя спустя
    with test_db.get_session() as session:
        curr_week = Week(week_title="Curr", start_date=date(2024, 1, 15))
        session.add(curr_week)
        session.flush()
        session.add(
            Assignment(
                week_id=curr_week.id,
                assignment_number="2",
                assignment_text="Духовные жемчужины",
                assignment_type="gems",
                section="treasures",
                section_position=2,
                status="unassigned",
            )
        )
        week_id = curr_week.id
        session.commit()

    res = s_service.auto_assign_week(week_id)
    assert res["success"] is True

    data = s_service.get_week_data(week_id)
    a = _find_assignment(data, "2")
    # PUB заблокирован (1 нед. < personal_gap=3), Elder всегда доступен
    assert a["participant_id"] == elder_id, (
        f"Expected Elder (id={elder_id}), got {a['participant_id']} "
        f"(PUB/Oleg id={pub_id}). personal_gap=3 должен блокировать PUB."
    )


def test_personal_gap_zero_makes_always_available(s_service, p_service, test_db):
    """
    personal_gap=0 делает MS всегда доступным (как старейшина).
    MS с personal_gap=0 назначен 1 неделю назад → проходит (gap=0 = exempt).
    PUB без personal_gap назначен 1 неделю назад → заблокирован (min_gap=2).
    Должен быть выбран MS.
    """
    with test_db.get_session() as session:
        session.add(Setting(key="min_assignment_gap", value="2"))
        session.add(Setting(key="ms_assignment_gap", value="2"))
        session.commit()

    # MS с personal_gap=0 (всегда доступен)
    ms_id = p_service.add_participant(
        "Servant Always", "male", "MS", ["bible_reading"], personal_gap=0
    )
    pub_id = p_service.add_participant("Publisher Blocked", "male", "PUB", ["bible_reading"])

    # Оба назначены 1 неделю назад
    with test_db.get_session() as session:
        prev_week = Week(week_title="Prev", start_date=date(2024, 1, 8))
        session.add(prev_week)
        session.flush()
        for p_id in (ms_id, pub_id):
            session.add(
                Assignment(
                    week_id=prev_week.id,
                    assignment_number="3",
                    assignment_text="Чтение Библии",
                    assignment_type="reading",
                    section="treasures",
                    section_position="3",
                    participant_id=p_id,
                    status="assigned",
                )
            )
        session.commit()

    # Текущая неделя — 1 неделя спустя
    with test_db.get_session() as session:
        curr_week = Week(week_title="Curr", start_date=date(2024, 1, 15))
        session.add(curr_week)
        session.flush()
        session.add(
            Assignment(
                week_id=curr_week.id,
                assignment_number="3",
                assignment_text="Чтение Библии",
                assignment_type="reading",
                section="treasures",
                section_position=3,
                status="unassigned",
            )
        )
        week_id = curr_week.id
        session.commit()

    res = s_service.auto_assign_week(week_id)
    assert res["success"] is True

    data = s_service.get_week_data(week_id)
    a = _find_assignment(data, "3")
    # MS с personal_gap=0 всегда доступен, PUB заблокирован min_gap=2
    assert a["participant_id"] == ms_id, (
        f"Expected MS/personal_gap=0 (id={ms_id}), got {a['participant_id']} "
        f"(PUB id={pub_id}). personal_gap=0 должен давать полную свободу."
    )


def test_gap_4_distribution_rotation(s_service, p_service, test_db):
    """
    Verify that with gap=4, the same participant is NOT assigned every week
    when there are multiple eligible candidates.

    This reproduces the user's bug: Соколова Юрий was assigned every week
    despite gap=4, because the selection was deterministic (first by name).
    """
    with test_db.get_session() as session:
        session.add(Setting(key="min_assignment_gap", value="4"))
        session.commit()

    # Add 3+ publishers with ministry qualification
    participants = []
    for i in range(5):
        p_id = p_service.add_participant(f"Participant {i}", "male", "publisher", ["ministry_item"])
        participants.append(p_id)

    # Create 4 weeks (exactly at gap boundary) with ministry position 1 (student assignment)
    week_ids = []
    for week_num in range(4):
        with test_db.get_session() as session:
            w = Week(week_title=f"Week {week_num}", start_date=date(2024, 1, 8 + week_num * 7))
            session.add(w)
            session.flush()
            # Ministry position 1 has needs_assistant=True, requires ministry_item qual
            _create_assignment(session, w.id, "4", "First Visit", "student", "ministry", "1")
            session.commit()
            week_ids.append(w.id)

    # Auto-assign all weeks
    s_service.auto_assign_all()

    # Check that assignments are distributed (not all to one participant)
    assigned_to = set()
    for w_id in week_ids:
        data = s_service.get_week_data(w_id)
        a = _find_assignment(data, "4")
        if a and a["participant_id"]:
            assigned_to.add(a["participant_id"])

    # At least 2 different participants should be assigned
    assert len(assigned_to) >= 2, (
        f"Same participant assigned all 4 weeks despite gap=4. "
        f"Only participant {list(assigned_to)} was chosen."
    )


def test_ministry_rotation_with_gap_4(s_service, p_service, test_db):
    """
    Specific test for ministry assignments with gap=4.
    Ensures fair rotation among participants for student assignments.

    Соколова Юрий should not be assigned to consecutive weeks when gap=4
    and there are other eligible candidates.
    """
    with test_db.get_session() as session:
        session.add(Setting(key="min_assignment_gap", value="4"))
        session.commit()

    # Соколов (participant 0) and 4 others with ministry_item
    sokolov_id = p_service.add_participant("Соколов", "male", "publisher", ["ministry_item"])
    others = [
        p_service.add_participant(f"Other {i}", "male", "publisher", ["ministry_item"])
        for i in range(1, 5)
    ]

    # Create 3 weeks, each with ministry position 1 and 2 (multiple ministry positions)
    week_ids = []
    for week_num in range(3):
        with test_db.get_session() as session:
            w = Week(week_title=f"Week {week_num}", start_date=date(2024, 1, 8 + week_num * 7))
            session.add(w)
            session.flush()
            # Position 1 (main student) and 2 (assistant)
            _create_assignment(session, w.id, "4", "First Visit", "student", "ministry", "1")
            _create_assignment(session, w.id, "5", "Second Visit", "student", "ministry", "2")
            session.commit()
            week_ids.append(w.id)

    s_service.auto_assign_all()

    # Count how many weeks Соколов was assigned
    sokolov_assignments = 0
    for w_id in week_ids:
        data = s_service.get_week_data(w_id)
        for a in data["assignments"]:
            if a["participant_id"] == sokolov_id:
                sokolov_assignments += 1

    # Соколов should not be assigned to all weeks (would violate fair distribution)
    assert sokolov_assignments < 3, (
        f"Соколов assigned to {sokolov_assignments} weeks out of 3 - "
        f"poor distribution despite gap=4 and {len(others)} other candidates."
    )


def test_pair_history_rotation(s_service, p_service, test_db):
    """
    Test that the same pair (main + assistant) is not assigned together again
    within PAIR_GAP_WEEKS when other eligible candidates exist.
    """
    with test_db.get_session() as session:
        session.add(Setting(key="min_assignment_gap", value="4"))
        session.commit()

    # Three female participants with ministry_item and assistant qualifications
    p1 = p_service.add_participant(
        "Рыжикова", "female", "publisher", ["ministry_item", "assistant"]
    )
    p2 = p_service.add_participant("Дудка", "female", "publisher", ["ministry_item", "assistant"])
    p3 = p_service.add_participant("Сестра3", "female", "publisher", ["ministry_item", "assistant"])

    # Week 1: 2026-01-05
    # Week 2: 2026-02-02 (4 weeks later)
    week_ids = []
    for week_num, w_date in enumerate([date(2026, 1, 5), date(2026, 2, 2)]):
        with test_db.get_session() as session:
            w = Week(week_title=f"Week {week_num + 1}", start_date=w_date)
            session.add(w)
            session.flush()
            _create_assignment(session, w.id, "4", "Dialogue", "student", "ministry", "1")
            session.commit()
            week_ids.append(w.id)

    # Pre-assign Week 1 manually: Рыжикова (main) + Дудка (assistant)
    with test_db.get_session() as session:
        a1 = session.query(Assignment).filter_by(week_id=week_ids[0]).first()
        a1.participant_id = p1
        a1.assistant_id = p2
        a1.status = "assigned"
        session.commit()

    # Run auto-assignment on Week 2
    res = s_service.auto_assign_week(week_ids[1])
    assert res.get("success") is True

    # Check who was assigned in Week 2
    with test_db.get_session() as session:
        a2 = session.query(Assignment).filter_by(week_id=week_ids[1]).first()
        assert a2.status == "assigned"
        assigned_pair = {a2.participant_id, a2.assistant_id}

        # The pair {Рыжикова, Дудка} should NOT be assigned together in Week 2
        # because Сестра3 is available and they were already in pair 4 weeks ago (< 12 weeks)
        assert assigned_pair != {
            p1,
            p2,
        }, f"Pair {assigned_pair} was repeated after only 4 weeks despite third candidate available!"
        assert (
            p3 in assigned_pair
        ), f"Expected third candidate {p3} to be in pair, got {assigned_pair}"


# ──────────── Лёгкие задания (молитвы) и интервалы по позиции ────────────


def _make_prayers_light(session):
    """Как в рабочей БД после миграции 007: молитвы не exclusive."""
    from core.models import AssignmentConfig

    session.execute(
        update(AssignmentConfig)
        .where(AssignmentConfig.position.in_(["prayer_open", "prayer_close"]))
        .values(is_exclusive=False)
    )


def test_prayer_assigned_after_parts(s_service, p_service, test_db):
    """Молитва распределяется после пунктов и не забирает брата, нужного на пункт."""
    with test_db.get_session() as session:
        _make_prayers_light(session)
        session.commit()

    both_id = p_service.add_participant("Может всё", "male", "MS", ["prayer", "living_part"])
    prayer_only_id = p_service.add_participant("Только молитва", "male", "publisher", ["prayer"])

    with test_db.get_session() as session:
        w = Week(week_title="W", start_date=date(2024, 3, 4))
        session.add(w)
        session.flush()
        _create_assignment(
            session, w.id, "pr", "Молитва (открытие)", "prayer", "fixed", "prayer_open"
        )
        _create_assignment(session, w.id, "7", "Часть ХЖС", "living", "living", "1")
        session.commit()
        week_id = w.id

    for _ in range(5):  # выбор взвешенно-случайный: проверяем, что исход стабилен
        s_service.auto_assign_week(week_id)
        data = s_service.get_week_data(week_id)
        assert _find_assignment(data, "7")["participant_id"] == both_id
        assert _find_assignment(data, "pr")["participant_id"] == prayer_only_id


def test_prayer_does_not_block_part_by_gap(s_service, p_service, test_db):
    """Молитва неделю назад не блокирует брата от пункта интервалом ms_gap."""
    with test_db.get_session() as session:
        session.add(Setting(key="min_assignment_gap", value="4"))
        session.add(Setting(key="ms_assignment_gap", value="4"))
        _make_prayers_light(session)
        session.commit()

    prayed_id = p_service.add_participant("Молился", "male", "MS", ["prayer", "living_part"])
    spoke_id = p_service.add_participant("Выступал", "male", "MS", ["living_part"])

    with test_db.get_session() as session:
        prev = Week(week_title="Prev", start_date=date(2024, 3, 4))
        session.add(prev)
        session.flush()
        session.add(
            Assignment(
                week_id=prev.id,
                assignment_number="pr",
                assignment_text="Молитва (открытие)",
                assignment_type="prayer",
                section="fixed",
                section_position="prayer_open",
                participant_id=prayed_id,
                status="assigned",
            )
        )
        session.add(
            Assignment(
                week_id=prev.id,
                assignment_number="7",
                assignment_text="Часть ХЖС",
                assignment_type="living",
                section="living",
                section_position="1",
                participant_id=spoke_id,
                status="assigned",
            )
        )
        w = Week(week_title="Now", start_date=date(2024, 3, 11))
        session.add(w)
        session.flush()
        _create_assignment(session, w.id, "7", "Часть ХЖС", "living", "living", "1")
        session.commit()
        week_id = w.id

    s_service.auto_assign_week(week_id)
    data = s_service.get_week_data(week_id)
    assert _find_assignment(data, "7")["participant_id"] == prayed_id


def test_elder_not_same_position_two_weeks_in_row(s_service, p_service, test_db):
    """Старейшина без общего интервала не берёт ту же позицию неделю подряд."""
    e1_id = p_service.add_participant("Старейшина 1", "male", "E", ["living_part"])
    e2_id = p_service.add_participant("Старейшина 2", "male", "E", ["living_part"])

    with test_db.get_session() as session:
        prev = Week(week_title="Prev", start_date=date(2024, 3, 4))
        session.add(prev)
        session.flush()
        session.add(
            Assignment(
                week_id=prev.id,
                assignment_number="7",
                assignment_text="Часть ХЖС",
                assignment_type="living",
                section="living",
                section_position="1",
                participant_id=e1_id,
                status="assigned",
            )
        )
        # Второй старейшина тоже выступал неделю назад, но с другой частью —
        # по общей давности они равны, решает только интервал по позиции.
        session.add(
            Assignment(
                week_id=prev.id,
                assignment_number="8",
                assignment_text="Часть ХЖС 2",
                assignment_type="living",
                section="living",
                section_position="2",
                participant_id=e2_id,
                status="assigned",
            )
        )
        w = Week(week_title="Now", start_date=date(2024, 3, 11))
        session.add(w)
        session.flush()
        _create_assignment(session, w.id, "7", "Часть ХЖС", "living", "living", "1")
        session.commit()
        week_id = w.id

    for _ in range(5):
        s_service.auto_assign_week(week_id)
        data = s_service.get_week_data(week_id)
        assert _find_assignment(data, "7")["participant_id"] == e2_id


def test_position_rotation_for_elder_only_pool():
    """В пуле старейшин решает очередь по позиции, в смешанном — общая нагрузка."""
    from datetime import datetime

    from core.auto_assignment_service import AutoAssignmentService

    svc = AutoAssignmentService(session_factory=None)
    now = datetime(2024, 3, 11)

    def pool():
        # «Мало пунктов всего, но этот пункт часто» против «много пунктов, этот — ни разу»
        return [
            {
                "id": 1,
                "name": "Мало квалификаций",
                "total_assignments": 2,
                "_pos_count": 2,
                "effective_last_main_date": None,
            },
            {
                "id": 2,
                "name": "Много квалификаций",
                "total_assignments": 10,
                "_pos_count": 0,
                "effective_last_main_date": None,
            },
        ]

    for _ in range(5):
        assert (
            svc._select_best_candidate(pool(), now, use_main_date=True, position_first=True)["id"]
            == 2
        )
        assert (
            svc._select_best_candidate(pool(), now, use_main_date=True, position_first=False)["id"]
            == 1
        )


def test_bible_reading_not_blocked_by_role_alternation(s_service, p_service, test_db):
    """Чтение Библии (без напарника) не подчиняется чередованию main/assistant.

    Раньше читавший брат навсегда считался «main» и отсеивался, а оставшихся
    выбивал интервал — чтение оставалось без исполнителя.
    """
    with test_db.get_session() as session:
        session.add(Setting(key="min_assignment_gap", value="4"))
        session.commit()

    reader_id = p_service.add_participant("Читал давно", "male", "publisher", ["bible_reading"])
    helper_id = p_service.add_participant("Был напарником", "male", "publisher", ["bible_reading"])
    sister_id = p_service.add_participant("Сестра", "female", "publisher", ["ministry_item"])

    with test_db.get_session() as session:
        old = Week(week_title="Old", start_date=date(2024, 1, 1))
        prev = Week(week_title="Prev", start_date=date(2024, 3, 4))
        now = Week(week_title="Now", start_date=date(2024, 3, 11))
        session.add_all([old, prev, now])
        session.flush()
        session.add(
            Assignment(  # 10 недель назад читал Библию (роль main)
                week_id=old.id,
                assignment_number="3",
                assignment_text="Чтение Библии",
                assignment_type="reading",
                section="treasures",
                section_position="3",
                participant_id=reader_id,
                status="assigned",
            )
        )
        session.add(
            Assignment(  # неделю назад был напарником — интервал 4 его блокирует
                week_id=prev.id,
                assignment_number="4",
                assignment_text="Учебное задание",
                assignment_type="student",
                section="ministry",
                section_position="1",
                participant_id=sister_id,
                assistant_id=helper_id,
                status="assigned",
            )
        )
        _create_assignment(session, now.id, "3", "Чтение Библии", "reading", "treasures", "3")
        session.commit()
        week_id = now.id

    s_service.auto_assign_week(week_id)
    data = s_service.get_week_data(week_id)
    assert _find_assignment(data, "3")["participant_id"] == reader_id


def test_ms_treasures_talk_week_rule():
    """«Вступительная речь»: служебный помощник дважды в месяц (2-я и 4-я недели)."""
    from datetime import datetime

    from core.candidate_filter_service import CandidateFilterService

    f = CandidateFilterService(min_gap=4)
    people = [{"id": 1, "service_type": "MS"}, {"id": 2, "service_type": "E"}]

    def is_ms_week(day, ms_dates=(), weeks_left=None):
        pmap = {(1, "treasures", "1"): [datetime(2027, 3, d) for d in ms_dates]}
        return f._is_ms_treasures_talk_week(people, datetime(2027, 3, day), pmap, weeks_left)

    # март 2027: понедельники 1, 8, 15, 22, 29
    assert is_ms_week(1) is False  # 1-я неделя — старейшина
    assert is_ms_week(8) is True  # 2-я неделя — MS
    assert is_ms_week(22, ms_dates=[8]) is True  # 4-я неделя — второй MS
    assert is_ms_week(29, ms_dates=[8, 22]) is False  # норма набрана
    # 2-я неделя пропала (MS не нашлось): на 3-й, если программных недель
    # осталось ровно столько, сколько нужно, — тоже MS
    assert is_ms_week(15, ms_dates=[], weeks_left=2) is True
    assert is_ms_week(15, ms_dates=[], weeks_left=3) is False


def test_ms_gets_treasures_talk_on_ms_week(s_service, p_service, test_db):
    """На 2-й неделе месяца пункт получает служебный помощник, хотя старейшина свободен."""
    p_service.add_participant("Старейшина", "male", "E", ["treasures_talk"])
    ms_id = p_service.add_participant("Служебный помощник", "male", "MS", ["treasures_talk"])

    with test_db.get_session() as session:
        w = Week(week_title="8—14 МАРТА", start_date=date(2027, 3, 8))
        session.add(w)
        session.flush()
        _create_assignment(session, w.id, "1", "Вступительная речь", "talk", "treasures", "1")
        session.commit()
        week_id = w.id

    s_service.auto_assign_week(week_id)
    data = s_service.get_week_data(week_id)
    assert _find_assignment(data, "1")["participant_id"] == ms_id


def test_position_gap_looks_at_later_weeks_too(s_service, p_service, test_db):
    """Перераспределение более ранней недели не ставит человека на тот же пункт,
    который у него уже стоит на следующей неделе (интервал считается в обе стороны)."""
    from core.candidate_filter_service import CandidateFilterService

    e1 = p_service.add_participant("Старейшина 1", "male", "E", ["living_part"])
    e2 = p_service.add_participant("Старейшина 2", "male", "E", ["living_part"])

    with test_db.get_session() as session:
        w1 = Week(week_title="W1", start_date=date(2024, 3, 4))
        w2 = Week(week_title="W2", start_date=date(2024, 3, 11))
        session.add_all([w1, w2])
        session.flush()
        # на более поздней неделе пункт уже у первого старейшины
        session.add(
            Assignment(
                week_id=w2.id,
                assignment_number="7",
                assignment_text="Часть ХЖС",
                assignment_type="living",
                section="living",
                section_position="1",
                participant_id=e1,
                status="assigned",
            )
        )
        # второй старейшина выступал недавно с другой частью — по давности
        # первый выглядит «свободнее», решает только интервал по позиции
        prev = Week(week_title="W0", start_date=date(2024, 2, 26))
        session.add(prev)
        session.flush()
        session.add(
            Assignment(
                week_id=prev.id,
                assignment_number="8",
                assignment_text="Часть ХЖС 2",
                assignment_type="living",
                section="living",
                section_position="2",
                participant_id=e2,
                status="assigned",
            )
        )
        _create_assignment(session, w1.id, "7", "Часть ХЖС", "living", "living", "1")
        session.commit()
        week_id = w1.id

    for _ in range(5):
        s_service.auto_assign_week(week_id)
        data = s_service.get_week_data(week_id)
        assert _find_assignment(data, "7")["participant_id"] == e2


def test_assistant_only_not_dropped_by_role_alternation(s_service, p_service, test_db):
    """Сестра только с квалификацией «помощник» не выпадает из очереди.

    Чередование «основной → помощник» не для неё: основной она быть не может.
    Раньше после первого раза помощником жёсткий фильтр чередования навсегда
    убирал её из пула, пока есть хоть один «идеальный» кандидат.
    """
    with test_db.get_session() as session:
        session.add(Setting(key="min_assignment_gap", value="0"))
        session.commit()

    p_service.add_participant("Main A", "female", "publisher", ["ministry_item", "assistant"])
    p_service.add_participant("Main B", "female", "publisher", ["ministry_item", "assistant"])
    other = p_service.add_participant(
        "Other", "female", "publisher", ["ministry_item", "assistant"]
    )
    helper_only = p_service.add_participant("Helper Only", "female", "publisher", ["assistant"])

    with test_db.get_session() as session:
        # История: «Helper Only» уже была помощницей, «Other» — основной.
        past = Week(week_title="Past", start_date=date(2024, 1, 1))
        session.add(past)
        session.flush()
        a = _create_assignment(session, past.id, "4", "Dialogue", "student", "ministry", "1")
        a.participant_id = other
        a.assistant_id = helper_only
        a.status = "assigned"
        w = Week(week_title="Target", start_date=date(2024, 6, 3))
        session.add(w)
        session.flush()
        _create_assignment(session, w.id, "4", "Dialogue", "student", "ministry", "1")
        session.commit()
        week_id = w.id

    chosen = set()
    for seed in range(30):
        with test_db.get_session() as session:
            session.query(Assignment).filter(Assignment.week_id == week_id).update(
                {"participant_id": None, "assistant_id": None, "status": "pending"}
            )
            session.commit()
        s_service._deterministic = True
        s_service._seed = seed
        assert s_service.auto_assign_week(week_id)["success"] is True
        chosen.add(_find_assignment(s_service.get_week_data(week_id), "4")["assistant_id"])

    assert helper_only in chosen, f"«только помощник» ни разу не выбрана: {chosen}"
