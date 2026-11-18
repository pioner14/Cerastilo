from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from core.database import DatabaseManager
from core.events import EventBus
from core.models import Assignment, AssignmentConfig, Base, ParticipantPositionConfig, Setting, Week
from core.services import ParticipantService, ScheduleService


# Mock DB Manager for testing
class InMemoryDatabaseManager(DatabaseManager):
    def __init__(self):
        # In-memory SQLite
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.SessionFactory = sessionmaker(bind=self.engine)


@pytest.fixture
def test_db():
    manager = InMemoryDatabaseManager()
    try:
        yield manager
    finally:
        manager.close()


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def p_service(test_db, event_bus):
    return ParticipantService(test_db, event_bus)


@pytest.fixture
def s_service(test_db, event_bus):
    return ScheduleService(test_db, event_bus)


def test_add_get_participant(p_service):
    p_id = p_service.add_participant(
        name="John Doe", gender="male", service_type="publisher", quals=["bible_reading"]
    )

    p = p_service.get_participant(p_id)
    assert p["name"] == "John Doe"
    assert "bible_reading" in p["qualifications"]
    assert p["gender"] == "male"


def test_auto_assign_week_simple(s_service, p_service, test_db):
    # Setup
    # 1. Add config
    with test_db.get_session() as session:
        session.add(
            AssignmentConfig(
                section="treasures",
                position="2",  # Духовные жемчужины — старейшина или служебный помощник (S-38, абз. 4)
                assignment_name="Spiritual Gems",
                required_qualification="gems",
                is_brothers_only=True,
            )
        )
        # Установим минимальный интервал в 0, чтобы тест работал корректно
        session.add(Setting(key="min_assignment_gap", value="0"))
        session.commit()

    # 2. Add participants
    p1 = p_service.add_participant("Bro A", "male", "MS", ["gems"])
    p2 = p_service.add_participant("Sis B", "female", "publisher", ["gems"])

    # 3. Create Week
    with test_db.get_session() as session:
        w = Week(week_title="Week 1", start_date=date(2024, 1, 1))
        session.add(w)
        session.commit()
        # Create Empty Assignment
        session.add(
            Assignment(
                week_id=w.id,
                assignment_number="1",
                assignment_text="Test Gems",
                assignment_type="talk",
                section="treasures",
                section_position=2,  # Духовные жемчужины — только E/MS
                status="empty",
            )
        )
        session.commit()
        week_id = w.id

    # Test
    res = s_service.auto_assign_week(week_id)
    assert res["success"] is True
    assert res["count"] == 1

    # Verify assignment
    data = s_service.get_week_data(week_id)
    # assignments is a list, find by assignment_number
    ass = next((a for a in data["assignments"] if a["assignment_number"] == "1"), None)
    assert ass is not None
    assert ass["status"] == "assigned"
    assert ass["participant_id"] in [p1, p2]


def test_conflict_detection(s_service, p_service, test_db):
    # Create week
    with test_db.get_session() as session:
        w = Week(week_title="Week 1", start_date=date(2024, 1, 1))
        session.add(w)
        session.commit()
        week_id = w.id

        # Add tasks
        session.add(
            Assignment(
                week_id=w.id, assignment_number="1", assignment_text="Task 1", status="empty"
            )
        )
        session.add(
            Assignment(
                week_id=w.id, assignment_number="2", assignment_text="Task 2", status="empty"
            )
        )
        session.commit()
        a1_id = (
            session.scalars(select(Assignment).where(Assignment.assignment_number == "1"))
            .first()
            .id
        )
        a2_id = (
            session.scalars(select(Assignment).where(Assignment.assignment_number == "2"))
            .first()
            .id
        )

    # Add participant
    p1 = p_service.add_participant("Busy Bro", "male", "elder", ["chairman"])

    # Manually assign same person to 2 tasks
    s_service.assign_participant(a1_id, p1)
    s_service.assign_participant(a2_id, p1)

    conflicts = s_service.get_week_conflicts(week_id)
    assert p1 in conflicts


def test_auto_assign_performance_no_n_plus_one(s_service, p_service, test_db):
    """Verify that auto_assign_week doesn't have N+1 query problem."""
    # Setup: create 50 participants
    for i in range(50):
        p_service.add_participant(f"Bro {i}", "male", "publisher", ["bible_reading"])

    # Add config
    with test_db.get_session() as session:
        session.add(
            AssignmentConfig(
                section="treasures",
                position="1",
                assignment_name="Bible Reading",
                required_qualification="bible_reading",
                is_brothers_only=True,
            )
        )
        # Установим минимальный интервал в 0, чтобы тест работал корректно
        session.add(Setting(key="min_assignment_gap", value="0"))
        session.commit()

    # Create week with assignment
    with test_db.get_session() as session:
        w = Week(week_title="Week 1", start_date=date(2024, 1, 1))
        session.add(w)
        session.commit()
        session.add(
            Assignment(
                week_id=w.id,
                assignment_number="1",
                assignment_text="Performance Task",
                assignment_type="student",
                section="treasures",
                section_position=1,
                status="empty",
            )
        )
        session.commit()
        week_id = w.id

    # Track queries using event listener
    from sqlalchemy import event

    query_count = {"count": 0}

    def count_queries(conn, cursor, statement, *args):
        query_count["count"] += 1

    event.listen(test_db.engine, "before_cursor_execute", count_queries)

    # Execute auto-assignment
    result = s_service.auto_assign_week(week_id)

    # With N+1 fix, query count is constant regardless of participant count
    # (previously it grew with N due to per-participant qualification lookups).
    # The threshold accounts for several constant-count bulk queries added over time:
    #   - participant_qualifications (eager load)
    #   - past_student_assignments (role alternation)
    #   - assignment dates / position dates maps
    #   - assignment_config (twice: for filtering + for is_exclusive flag)
    #   - participant_position_configs (per-participant position gap overrides)
    #   - participant_excluded_weeks (vacation/shift exclusions)
    #   - recent_pairs_map (pair rotation history)
    #   - treasures/1 program weeks left in month (MS twice a month rule)
    # All are O(1) in participant count. If this breaks, you have a real N+1.
    assert query_count["count"] <= 16, f"Too many queries: {query_count['count']}"
    assert result["success"] is True


def test_auto_assign_student_override_position_4(s_service, p_service, test_db):
    """Verify that student assignments (typed student in ministry section) override configs to require assistant and open gender."""
    # 1. Add configs
    with test_db.get_session() as session:
        # Config for position 4 is configured as a speech (brothers only, no assistant)
        session.add(
            AssignmentConfig(
                section="ministry",
                position="4",
                assignment_name="Речь (только братья)",
                required_qualification="ministry_speech",
                is_brothers_only=True,
                needs_assistant=False,
            )
        )
        session.add(Setting(key="min_assignment_gap", value="0"))
        session.commit()

    # 2. Add participants (with qualifications of both genders)
    p1 = p_service.add_participant("Bro A", "male", "publisher", ["ministry_item", "assistant"])
    p2 = p_service.add_participant("Bro C", "male", "publisher", ["ministry_item", "assistant"])
    p3 = p_service.add_participant("Sis B", "female", "publisher", ["ministry_item", "assistant"])
    p4 = p_service.add_participant("Sis D", "female", "publisher", ["ministry_item", "assistant"])

    # 3. Create Week with assignment at position 4 that is a student assignment (dialogue)
    with test_db.get_session() as session:
        w = Week(week_title="Week 1", start_date=date(2024, 1, 1))
        session.add(w)
        session.commit()
        session.add(
            Assignment(
                week_id=w.id,
                assignment_number="7",
                assignment_text="Объясняйте свои взгляды",
                assignment_type="student",
                section="ministry",
                section_position=4,
                status="empty",
            )
        )
        session.commit()
        week_id = w.id

    # Test
    res = s_service.auto_assign_week(week_id)
    assert res["success"] is True

    # Check that both student and assistant are assigned
    data = s_service.get_week_data(week_id)
    ass = next((a for a in data["assignments"] if a["assignment_number"] == "7"), None)
    assert ass is not None
    assert ass["status"] == "assigned"

    # Both student and assistant must be assigned, and they must be of the same gender
    assert ass["participant_id"] is not None
    assert ass["assistant_id"] is not None

    p_id = ass["participant_id"]
    a_id = ass["assistant_id"]

    # Get participants gender
    p_gender = next(
        p["gender"]
        for p in [
            {"id": p1, "gender": "male"},
            {"id": p2, "gender": "male"},
            {"id": p3, "gender": "female"},
            {"id": p4, "gender": "female"},
        ]
        if p["id"] == p_id
    )

    a_gender = next(
        p["gender"]
        for p in [
            {"id": p1, "gender": "male"},
            {"id": p2, "gender": "male"},
            {"id": p3, "gender": "female"},
            {"id": p4, "gender": "female"},
        ]
        if p["id"] == a_id
    )

    assert p_gender == a_gender


def test_minor_constraints(s_service, p_service, test_db):
    # 1. Добавляем конфиг для задания с ассистентом
    with test_db.get_session() as session:
        session.add(
            AssignmentConfig(
                section="ministry",
                position="1",
                assignment_name="Ministry Item",
                required_qualification="ministry_item",
                is_brothers_only=False,
                needs_assistant=True,
            )
        )
        session.add(Setting(key="min_assignment_gap", value="0"))
        session.commit()

    # 2. Участники:
    # Евгений — взрослый, ТОЛЬКО главный (ministry_item)
    p_evgeny = p_service.add_participant(
        "Evgeny Ryzhikov", "male", "publisher", ["ministry_item"], family_id=None, is_minor=False
    )
    # Илья — несовершеннолетний член семьи Ryzhikov, ТОЛЬКО помощник (assistant)
    p_ilya = p_service.add_participant(
        "Ilya Ryzhikov", "male", "publisher", ["assistant"], family_id=p_evgeny, is_minor=True
    )
    # Посторонняя несовершеннолетняя, ТОЛЬКО помощник (assistant)
    p_stranger_minor = p_service.add_participant(
        "Stranger Minor", "male", "publisher", ["assistant"], family_id=None, is_minor=True
    )

    # Тест 1: Взрослый глава (Евгений) будет выбран главным (так как он единственный с 'ministry_item').
    # Так как среди кандидатов в ассистенты есть свободный несовершеннолетний член его семьи (Илья),
    # Илья должен быть назначен ассистентом автоматически (100% приоритет).
    # Посторонний несовершеннолетний (Stranger Minor) не может быть назначен.
    with test_db.get_session() as session:
        w = Week(week_title="Week 1", start_date=date(2026, 1, 1))
        session.add(w)
        session.commit()
        week_id = w.id

        session.add(
            Assignment(
                week_id=week_id,
                assignment_number="1",
                assignment_text="Item 1",
                assignment_type="student",
                section="ministry",
                section_position=1,
                status="empty",
            )
        )
        session.commit()
        assignment_id = (
            session.scalars(select(Assignment).where(Assignment.week_id == week_id)).first().id
        )

    # Запускаем автоназначение на эту неделю. Евгений должен стать главным, Илья — ассистентом.
    res = s_service.auto_assign_week(week_id)
    assert res["success"] is True

    # Проверяем, что главным стал Евгений, а ассистентом — именно Илья
    data = s_service.get_week_data(week_id)
    ass = next(a for a in data["assignments"] if a["id"] == assignment_id)
    assert ass["participant_id"] == p_evgeny
    assert ass["assistant_id"] == p_ilya

    # Тест 2: Если несовершеннолетний Илья — главный.
    # Для этого дадим Илье квалификацию 'ministry_item', а Евгению уберем, чтобы Илья стал единственным кандидатом в главные.
    # Евгений при этом имеет только квалификацию 'assistant', чтобы быть кандидатом в помощники.
    with test_db.get_session() as session:
        # Уберем у Евгения ministry_item, оставим assistant
        p_service.update_participant(
            p_evgeny,
            "Evgeny Ryzhikov",
            "male",
            "publisher",
            ["assistant"],
            family_id=None,
            personal_gap=0,
            is_minor=False,
        )
        # Дадим Илье ministry_item (помощником он тоже может быть, но тут он будет главным)
        p_service.update_participant(
            p_ilya,
            "Ilya Ryzhikov",
            "male",
            "publisher",
            ["ministry_item"],
            family_id=p_evgeny,
            personal_gap=0,
            is_minor=True,
        )

    with test_db.get_session() as session:
        w2 = Week(week_title="Week 2", start_date=date(2026, 1, 8))
        session.add(w2)
        session.commit()
        week_id2 = w2.id

        session.add(
            Assignment(
                week_id=week_id2,
                assignment_number="1",
                assignment_text="Item 2",
                assignment_type="student",
                section="ministry",
                section_position=1,
                status="empty",
            )
        )
        session.commit()
        assignment_id2 = (
            session.scalars(select(Assignment).where(Assignment.week_id == week_id2)).first().id
        )

    # Запускаем автоназначение на вторую неделю.
    # Главным станет Илья (единственный с 'ministry_item').
    # В качестве помощников доступны: Евгений (взрослый член семьи) и Stranger Minor (несовершеннолетний, чужая семья).
    # По правилам: "Несовершеннолетний может быть главным заданий только лишь если он назначается с другим несовершеннолетним."
    # Поскольку Евгений — взрослый, он не может быть ассистентом, когда Илья (несовершеннолетний) — главный.
    # Поэтому должен быть назначен именно Stranger Minor!
    res = s_service.auto_assign_week(week_id2)
    assert res["success"] is True

    data = s_service.get_week_data(week_id2)
    ass2 = next(a for a in data["assignments"] if a["id"] == assignment_id2)
    assert ass2["participant_id"] == p_ilya
    assert ass2["assistant_id"] == p_stranger_minor


def test_local_needs_restrictions(s_service, p_service, test_db):
    # 1. Добавляем конфиг для Living Part
    with test_db.get_session() as session:
        session.add(
            AssignmentConfig(
                section="living",
                position="1",
                assignment_name="Часть ХЖС (1-я)",
                required_qualification="living_part",
                is_brothers_only=True,
                needs_assistant=False,
            )
        )
        session.add(Setting(key="min_assignment_gap", value="0"))
        session.commit()

    # 2. Участники:
    # Elder Bro — старейшина, квалифицирован
    p_elder = p_service.add_participant(
        "Elder Bro", "male", "E", ["living_part"], family_id=None, is_minor=False
    )
    # MS Bro — служебный помощник, квалифицирован
    p_ms = p_service.add_participant(
        "MS Bro", "male", "MS", ["living_part"], family_id=None, is_minor=False
    )
    # Pub Bro — возвещатель, квалифицирован
    p_pub = p_service.add_participant(
        "Pub Bro", "male", "publisher", ["living_part"], family_id=None, is_minor=False
    )

    # 3. Неделя с заданием "Местные потребности"
    with test_db.get_session() as session:
        w = Week(week_title="Week 1", start_date=date(2026, 1, 1))
        session.add(w)
        session.commit()
        week_id = w.id

        session.add(
            Assignment(
                week_id=week_id,
                assignment_number="8",
                assignment_text="Местные потребности (15 мин.)",
                assignment_type="living",
                section="living",
                section_position=1,
                status="empty",
            )
        )
        session.commit()
        assignment_id = (
            session.scalars(select(Assignment).where(Assignment.week_id == week_id)).first().id
        )

    # Запускаем автоназначение
    res = s_service.auto_assign_week(week_id)
    assert res["success"] is True

    # Проверяем, что назначен именно старейшина (Elder Bro)
    data = s_service.get_week_data(week_id)
    ass = next(a for a in data["assignments"] if a["id"] == assignment_id)
    assert ass["participant_id"] == p_elder


def test_personal_gap_always_respected(s_service, p_service, test_db):
    # 1. Добавляем конфиг для задания без ассистента
    with test_db.get_session() as session:
        session.add(
            AssignmentConfig(
                section="ministry",
                position="1",
                assignment_name="Ministry Item",
                required_qualification="ministry_item",
                is_brothers_only=False,
                needs_assistant=False,
            )
        )
        # Глобальный интервал равен 0!
        session.add(Setting(key="min_assignment_gap", value="0"))
        session.commit()

    # 2. Участники:
    # Татьяна — с личным интервалом 8 недель
    p_tatiana = p_service.add_participant(
        "Tatiana Skukun",
        "female",
        "publisher",
        ["ministry_item"],
        family_id=None,
        personal_gap=8,
        is_minor=False,
    )
    # Другая сестра — без личного интервала (интервал 0)
    p_other = p_service.add_participant(
        "Other Sis",
        "female",
        "publisher",
        ["ministry_item"],
        family_id=None,
        personal_gap=None,
        is_minor=False,
    )

    # 3. Две недели
    with test_db.get_session() as session:
        w1 = Week(week_title="Week 1", start_date=date(2026, 6, 1))
        w2 = Week(week_title="Week 2", start_date=date(2026, 6, 8))
        session.add_all([w1, w2])
        session.commit()

        session.add(
            Assignment(
                week_id=w1.id,
                assignment_number="1",
                assignment_text="Item Week 1",
                assignment_type="student",
                section="ministry",
                section_position=1,
                status="empty",
            )
        )
        session.add(
            Assignment(
                week_id=w2.id,
                assignment_number="1",
                assignment_text="Item Week 2",
                assignment_type="student",
                section="ministry",
                section_position=1,
                status="empty",
            )
        )
        session.commit()

        w1_id = w1.id
        w2_id = w2.id

    # Вручную назначим Татьяну на Week 1, чтобы зафиксировать её назначение на 1-й неделе
    with test_db.get_session() as session:
        a1_id = session.scalars(select(Assignment).where(Assignment.week_id == w1_id)).first().id
        a2_id = session.scalars(select(Assignment).where(Assignment.week_id == w2_id)).first().id

    s_service.assign_participant(a1_id, p_tatiana)

    # Запускаем автоназначение на Week 2
    res = s_service.auto_assign_week(w2_id)
    assert res["success"] is True

    # Проверяем, что на Week 2 была назначена Other Sis, а не Татьяна
    # (так как у Татьяны личный интервал 8 недель, а прошла только 1 неделя)
    data = s_service.get_week_data(w2_id)
    ass = next(a for a in data["assignments"] if a["id"] == a2_id)
    assert ass["participant_id"] == p_other


def test_elder_never_assigned_student_assignments(s_service, p_service, test_db):
    # 1. Configs for Bible Reading (Treasures position 3) and Ministry Item (Ministry position 1)
    with test_db.get_session() as session:
        session.add(
            AssignmentConfig(
                section="treasures",
                position="3",
                assignment_name="Bible Reading",
                required_qualification="bible_reading",
                is_brothers_only=True,
                needs_assistant=False,
            )
        )
        session.add(
            AssignmentConfig(
                section="ministry",
                position="1",
                assignment_name="Ministry Student Item",
                required_qualification="ministry_item",
                is_brothers_only=False,
                needs_assistant=False,
            )
        )
        session.add(Setting(key="min_assignment_gap", value="0"))
        session.commit()

    # 2. Elder who is qualified
    p_elder = p_service.add_participant(
        "Elder Test",
        "male",
        "E",
        ["bible_reading", "ministry_item"],
        family_id=None,
        is_minor=False,
    )
    # 3. Publisher who is qualified
    p_pub = p_service.add_participant(
        "Pub Test",
        "male",
        "publisher",
        ["bible_reading", "ministry_item"],
        family_id=None,
        is_minor=False,
    )

    # 4. Create a week with these assignments
    with test_db.get_session() as session:
        w = Week(week_title="Week 1", start_date=date(2026, 1, 1))
        session.add(w)
        session.commit()
        week_id = w.id

        session.add(
            Assignment(
                week_id=week_id,
                assignment_number="1",
                assignment_text="Bible Reading",
                assignment_type="reading",
                section="treasures",
                section_position=3,
                status="empty",
            )
        )
        session.add(
            Assignment(
                week_id=week_id,
                assignment_number="2",
                assignment_text="Student Item",
                assignment_type="student",
                section="ministry",
                section_position=1,
                status="empty",
            )
        )
        session.commit()

    # 5. Run auto-assignment
    res = s_service.auto_assign_week(week_id)
    assert res["success"] is True

    # 6. Verify that the Elder is NOT assigned to either student assignments
    data = s_service.get_week_data(week_id)
    for ass in data["assignments"]:
        if ass["section"] in ("treasures", "ministry") and ass["assignment_type"] in (
            "reading",
            "student",
        ):
            assert ass["participant_id"] != p_elder
            # The publisher should be assigned to one of them
            if ass["participant_id"] is not None:
                assert ass["participant_id"] == p_pub


def test_elder_never_assigned_as_assistant(s_service, p_service, test_db):
    # 1. Config for student assignment needing assistant
    with test_db.get_session() as session:
        session.add(
            AssignmentConfig(
                section="ministry",
                position="1",
                assignment_name="Ministry Item",
                required_qualification="ministry_item",
                is_brothers_only=False,
                needs_assistant=True,
            )
        )
        session.add(Setting(key="min_assignment_gap", value="0"))
        session.commit()

    # 2. Main participant (female publisher)
    p_main = p_service.add_participant(
        "Main Sis", "female", "publisher", ["ministry_item"], family_id=None, is_minor=False
    )
    # 3. Elder assistant candidate
    p_elder_ast = p_service.add_participant(
        "Elder Ast", "female", "E", ["assistant"], family_id=None, is_minor=False
    )
    # 4. Publisher assistant candidate
    p_pub_ast = p_service.add_participant(
        "Pub Ast", "female", "publisher", ["assistant"], family_id=None, is_minor=False
    )

    # 5. Week setup
    with test_db.get_session() as session:
        w = Week(week_title="Week 1", start_date=date(2026, 1, 1))
        session.add(w)
        session.commit()
        week_id = w.id

        session.add(
            Assignment(
                week_id=week_id,
                assignment_number="1",
                assignment_text="Student Dialogue",
                assignment_type="student",
                section="ministry",
                section_position=1,
                status="empty",
            )
        )
        session.commit()
        assignment_id = (
            session.scalars(select(Assignment).where(Assignment.week_id == week_id)).first().id
        )

    # 6. Run assignment
    res = s_service.auto_assign_week(week_id)
    assert res["success"] is True

    # 7. Check that Elder Ast was NOT assigned as assistant
    data = s_service.get_week_data(week_id)
    ass = next(a for a in data["assignments"] if a["id"] == assignment_id)
    assert ass["participant_id"] == p_main
    assert ass["assistant_id"] != p_elder_ast
    assert ass["assistant_id"] == p_pub_ast


def test_ms_pairing_rules(s_service, p_service, test_db):
    # 1. Config for student assignment needing assistant
    with test_db.get_session() as session:
        session.add(
            AssignmentConfig(
                section="ministry",
                position="1",
                assignment_name="Ministry Item",
                required_qualification="ministry_item",
                is_brothers_only=False,
                needs_assistant=True,
            )
        )
        session.add(Setting(key="min_assignment_gap", value="0"))
        session.commit()

    # 2. Participants
    # MS Brother (main candidate)
    p_ms = p_service.add_participant(
        "MS Bro Test", "male", "MS", ["ministry_item"], family_id=None, is_minor=False
    )
    # Sister in MS family group
    p_sis_fam = p_service.add_participant(
        "MS Sister Fam", "female", "publisher", ["assistant"], family_id=p_ms, is_minor=False
    )
    # Sister from another family
    p_sis_stranger = p_service.add_participant(
        "MS Sister Stranger", "female", "publisher", ["assistant"], family_id=None, is_minor=False
    )
    # Brother (not family)
    p_bro_pub = p_service.add_participant(
        "Pub Bro Test", "male", "publisher", ["assistant"], family_id=None, is_minor=False
    )

    # Test case A: Only stranger sister is available
    # We will disable the brother and family sister by marking them inactive temporarily, or just make a week with only the MS and stranger sister.
    # Actually, we can use the autoassigner and verify.
    # Let's create a week.
    with test_db.get_session() as session:
        w1 = Week(week_title="Week 1", start_date=date(2026, 1, 1))
        session.add(w1)
        session.commit()
        w1_id = w1.id

        session.add(
            Assignment(
                week_id=w1_id,
                assignment_number="1",
                assignment_text="Dialogue",
                assignment_type="student",
                section="ministry",
                section_position=1,
                status="empty",
            )
        )
        session.commit()
        a1_id = session.scalars(select(Assignment).where(Assignment.week_id == w1_id)).first().id

    # Disable Pub Bro and Sis Fam for Test A
    p_service.update_participant(
        p_sis_fam,
        "MS Sister Fam",
        "female",
        "publisher",
        [],
        family_id=p_ms,
        personal_gap=0,
        is_minor=False,
    )
    p_service.update_participant(
        p_bro_pub,
        "Pub Bro Test",
        "male",
        "publisher",
        [],
        family_id=None,
        personal_gap=0,
        is_minor=False,
    )

    # Auto assign. The MS will be chosen as main. The stranger sister cannot be chosen as assistant.
    # So the assistant should be empty.
    res = s_service.auto_assign_week(w1_id)
    assert res["success"] is True
    data = s_service.get_week_data(w1_id)
    ass1 = next(a for a in data["assignments"] if a["id"] == a1_id)
    assert ass1["participant_id"] == p_ms
    assert ass1["assistant_id"] is None  # Sis stranger is excluded!

    # Test case B: Family sister is available
    # Re-enable family sister, keep brother disabled
    p_service.update_participant(
        p_sis_fam,
        "MS Sister Fam",
        "female",
        "publisher",
        ["assistant"],
        family_id=p_ms,
        personal_gap=0,
        is_minor=False,
    )

    with test_db.get_session() as session:
        w2 = Week(week_title="Week 2", start_date=date(2026, 1, 8))
        session.add(w2)
        session.commit()
        w2_id = w2.id

        session.add(
            Assignment(
                week_id=w2_id,
                assignment_number="1",
                assignment_text="Dialogue 2",
                assignment_type="student",
                section="ministry",
                section_position=1,
                status="empty",
            )
        )
        session.commit()
        a2_id = session.scalars(select(Assignment).where(Assignment.week_id == w2_id)).first().id

    # Reset assignment histories for next week
    from sqlalchemy import text

    with test_db.get_session() as session:
        session.execute(text("UPDATE participants SET last_assignment_date = NULL;"))
        session.commit()

    res = s_service.auto_assign_week(w2_id)
    assert res["success"] is True
    data = s_service.get_week_data(w2_id)
    ass2 = next(a for a in data["assignments"] if a["id"] == a2_id)
    assert ass2["participant_id"] == p_ms
    assert ass2["assistant_id"] == p_sis_fam  # Sis fam is allowed and chosen!

    # Test case C: Brother is available (MS should prefer brother over stranger sister)
    p_service.update_participant(
        p_sis_fam,
        "MS Sister Fam",
        "female",
        "publisher",
        [],
        family_id=p_ms,
        personal_gap=0,
        is_minor=False,
    )
    p_service.update_participant(
        p_bro_pub,
        "Pub Bro Test",
        "male",
        "publisher",
        ["assistant"],
        family_id=None,
        personal_gap=0,
        is_minor=False,
    )

    with test_db.get_session() as session:
        w3 = Week(week_title="Week 3", start_date=date(2026, 1, 15))
        session.add(w3)
        session.commit()
        w3_id = w3.id

        session.add(
            Assignment(
                week_id=w3_id,
                assignment_number="1",
                assignment_text="Dialogue 3",
                assignment_type="student",
                section="ministry",
                section_position=1,
                status="empty",
            )
        )
        session.commit()
        a3_id = session.scalars(select(Assignment).where(Assignment.week_id == w3_id)).first().id

    res = s_service.auto_assign_week(w3_id)
    assert res["success"] is True
    data = s_service.get_week_data(w3_id)
    ass3 = next(a for a in data["assignments"] if a["id"] == a3_id)
    assert ass3["participant_id"] == p_ms
    assert ass3["assistant_id"] == p_bro_pub  # Brother is allowed and chosen!


def test_no_consecutive_same_section_position(s_service, p_service, test_db):
    """
    Тест: один участник не назначается дважды подряд на одну и ту же позицию секции.

    Сценарий: есть 2 участника (Bro A и Bro B) с квалификацией bible_reading.
    На неделе 1 один из них получает задание (bible reading, treasures pos 3).
    На неделе 2 система ДОЛЖНА выбрать другого участника, а не того же самого,
    так как position_gap = min_gap * 2 = 2 недели, а прошла только 1 неделя.
    """
    # 1. Конфиг: Библейское чтение (treasures, position 3) — только братья
    with test_db.get_session() as session:
        session.add(
            AssignmentConfig(
                section="treasures",
                position="3",
                assignment_name="Библейское чтение",
                required_qualification="bible_reading",
                is_brothers_only=True,
                needs_assistant=False,
            )
        )
        # min_gap = 1 неделя, position_gap = 1 * 2 = 2 недели
        session.add(Setting(key="min_assignment_gap", value="1"))
        session.commit()

    # 2. Добавляем двух участников с одинаковыми квалификациями
    p_a = p_service.add_participant("Bro Alpha", "male", "publisher", ["bible_reading"])
    p_b = p_service.add_participant("Bro Beta", "male", "publisher", ["bible_reading"])

    # 3. Неделя 1: создаём и автоназначаем
    with test_db.get_session() as session:
        w1 = Week(week_title="Week 1", start_date=date(2026, 2, 2))
        session.add(w1)
        session.commit()
        session.add(
            Assignment(
                week_id=w1.id,
                assignment_number="3",
                assignment_text="Чтение Библии (1)",
                assignment_type="student",
                section="treasures",
                section_position=3,
                status="empty",
            )
        )
        session.commit()
        week1_id = w1.id

    res1 = s_service.auto_assign_week(week1_id)
    assert res1["success"] is True

    data1 = s_service.get_week_data(week1_id)
    ass1 = next((a for a in data1["assignments"] if a["assignment_number"] == "3"), None)
    assert ass1 is not None, "Назначение на неделю 1 не найдено"
    assert ass1["status"] == "assigned", "Статус должен быть 'assigned'"
    first_assigned_id = ass1["participant_id"]
    assert first_assigned_id in (p_a, p_b), "Должен быть назначен один из двух участников"

    # 4. Неделя 2 (через 1 неделю): позиционный gap ещё не истёк (нужно 2 недели)
    with test_db.get_session() as session:
        w2 = Week(week_title="Week 2", start_date=date(2026, 2, 9))
        session.add(w2)
        session.commit()
        session.add(
            Assignment(
                week_id=w2.id,
                assignment_number="3",
                assignment_text="Чтение Библии (2)",
                assignment_type="student",
                section="treasures",
                section_position=3,
                status="empty",
            )
        )
        session.commit()
        week2_id = w2.id

    res2 = s_service.auto_assign_week(week2_id)
    assert res2["success"] is True

    data2 = s_service.get_week_data(week2_id)
    ass2 = next((a for a in data2["assignments"] if a["assignment_number"] == "3"), None)
    assert ass2 is not None, "Назначение на неделю 2 не найдено"
    assert ass2["status"] == "assigned", "Статус должен быть 'assigned'"

    second_assigned_id = ass2["participant_id"]
    # Ключевая проверка: назначен ДРУГОЙ участник, не тот же самый!
    assert second_assigned_id != first_assigned_id, (
        f"Участник {first_assigned_id} был назначен дважды подряд на ту же позицию "
        f"(treasures/3), хотя position_gap = 2 недели, а прошла только 1 неделя."
    )
    assert second_assigned_id in (p_a, p_b), "Должен быть назначен один из двух участников"

    # 5. Неделя 3 (через 2 недели от первого): первый участник МОЖЕТ снова быть назначен
    with test_db.get_session() as session:
        w3 = Week(week_title="Week 3", start_date=date(2026, 2, 16))
        session.add(w3)
        session.commit()
        session.add(
            Assignment(
                week_id=w3.id,
                assignment_number="3",
                assignment_text="Чтение Библии (3)",
                assignment_type="student",
                section="treasures",
                section_position=3,
                status="empty",
            )
        )
        session.commit()
        week3_id = w3.id

    res3 = s_service.auto_assign_week(week3_id)
    assert res3["success"] is True

    data3 = s_service.get_week_data(week3_id)
    ass3 = next((a for a in data3["assignments"] if a["assignment_number"] == "3"), None)
    assert ass3 is not None, "Назначение на неделю 3 не найдено"
    assert ass3["status"] == "assigned", "Статус должен быть 'assigned'"
    # На 3-й неделе оба участника должны снова войти в пул — просто проверяем что задание выполнено
    assert ass3["participant_id"] in (p_a, p_b)


def test_treasures_talk_elder_ms_priority(s_service, p_service, test_db, monkeypatch):
    """
    Тест: первый пункт «Сокровища из Слова Бога» (treasures/1 — «Вступительная речь»).

    Правила:
    1. Обычные возвещатели (publisher) НЕ могут получить это задание.
    2. Только старейшины (E/elder) и служебные помощники (MS) допускаются.
    3. При наличии старейшин — назначается старейшина (предпочтение).
    4. Если старейшин нет — назначается MS.
    """
    # 1. Конфиг для Вступительной речи (treasures / 1)
    with test_db.get_session() as session:
        session.add(
            AssignmentConfig(
                section="treasures",
                position="1",
                assignment_name="Вступительная речь",
                required_qualification="treasures_talk",
                is_brothers_only=True,
                needs_assistant=False,
            )
        )
        session.add(Setting(key="min_assignment_gap", value="0"))
        session.commit()

    # 2. Три участника с нужной квалификацией
    p_elder = p_service.add_participant("Elder Bro", "male", "elder", ["treasures_talk"])
    p_ms = p_service.add_participant("MS Bro", "male", "MS", ["treasures_talk"])
    p_pub = p_service.add_participant("Publisher Bro", "male", "publisher", ["treasures_talk"])

    # ---- СЛУЧАЙ A: есть и старейшина, и MS, и паблишер ----
    # Ожидаем: назначается ТОЛЬКО старейшина (Elder Bro).
    # Правило «MS дважды в месяц» проверяется отдельно (test_assignment_rules) —
    # здесь неделя единственная в месяце и иначе досталась бы MS.
    from core.candidate_filter_service import CandidateFilterService

    monkeypatch.setattr(CandidateFilterService, "MS_TREASURES_TALKS_PER_MONTH", 0)
    with test_db.get_session() as session:
        w1 = Week(week_title="Week 1", start_date=date(2026, 3, 3))
        session.add(w1)
        session.commit()
        session.add(
            Assignment(
                week_id=w1.id,
                assignment_number="1",
                assignment_text="Вступительная речь (1)",
                assignment_type="talk",
                section="treasures",
                section_position=1,
                status="empty",
            )
        )
        session.commit()
        week1_id = w1.id

    res1 = s_service.auto_assign_week(week1_id)
    assert res1["success"] is True

    data1 = s_service.get_week_data(week1_id)
    ass1 = next((a for a in data1["assignments"] if a["assignment_number"] == "1"), None)
    assert ass1 is not None
    assert ass1["status"] == "assigned"
    # Назначен ТОЛЬКО старейшина — паблишер и MS не должны попасть
    assert ass1["participant_id"] == p_elder, (
        f"Ожидался старейшина (id={p_elder}), " f"но назначен участник id={ass1['participant_id']}"
    )

    # ---- СЛУЧАЙ B: старейшины нет, есть только MS и паблишер ----
    # Убираем квалификацию у старейшины, оставляем только MS и паблишера
    p_service.update_participant(
        p_elder, "Elder Bro", "male", "elder", [], family_id=None, personal_gap=0, is_minor=False
    )

    with test_db.get_session() as session:
        w2 = Week(week_title="Week 2", start_date=date(2026, 3, 10))
        session.add(w2)
        session.commit()
        session.add(
            Assignment(
                week_id=w2.id,
                assignment_number="1",
                assignment_text="Вступительная речь (2)",
                assignment_type="talk",
                section="treasures",
                section_position=1,
                status="empty",
            )
        )
        session.commit()
        week2_id = w2.id

    res2 = s_service.auto_assign_week(week2_id)
    assert res2["success"] is True

    data2 = s_service.get_week_data(week2_id)
    ass2 = next((a for a in data2["assignments"] if a["assignment_number"] == "1"), None)
    assert ass2 is not None
    assert ass2["status"] == "assigned"
    # Назначен MS — паблишер не должен попасть
    assert ass2["participant_id"] == p_ms, (
        f"Ожидался MS (id={p_ms}), "
        f"но назначен участник id={ass2['participant_id']} "
        f"(паблишер id={p_pub} не должен назначаться)"
    )

    # ---- СЛУЧАЙ C: паблишер — единственный кандидат с квалификацией ----
    # Убираем квалификацию у MS — остаётся только паблишер
    p_service.update_participant(
        p_ms, "MS Bro", "male", "MS", [], family_id=None, personal_gap=0, is_minor=False
    )

    with test_db.get_session() as session:
        w3 = Week(week_title="Week 3", start_date=date(2026, 3, 17))
        session.add(w3)
        session.commit()
        session.add(
            Assignment(
                week_id=w3.id,
                assignment_number="1",
                assignment_text="Вступительная речь (3)",
                assignment_type="talk",
                section="treasures",
                section_position=1,
                status="empty",
            )
        )
        session.commit()
        week3_id = w3.id

    res3 = s_service.auto_assign_week(week3_id)
    assert res3["success"] is True

    data3 = s_service.get_week_data(week3_id)
    ass3 = next((a for a in data3["assignments"] if a["assignment_number"] == "1"), None)
    assert ass3 is not None
    # Паблишер — единственный с квалификацией, но жёсткий фильтр его исключает.
    # Задание должно остаться без назначения (participant_id == None).
    assert ass3["participant_id"] is None, (
        f"Паблишер (id={p_pub}) не должен быть назначен на treasures/1, "
        f"но был назначен участник id={ass3['participant_id']}"
    )


def test_participant_position_gap_override(s_service, p_service, test_db):
    """
    Тест: PersonalPositionConfig — персональный позиционный gap для председателя.

    Проверяет, что:
    1. Старейшина с персональным gap=2 (chairman) может быть назначен председателем
       повторно уже через 2 недели, тогда как другой старейшина с глобальным gap=4
       должен ждать 4 недели.
    2. Без PersonalPositionConfig оба старейшины подчиняются global elder_position_gap=4.
    """
    ELDER_POS_GAP = 4  # глобальный gap для председателя
    PERSONAL_GAP = 2  # персональный gap для elder_a

    # Конфиг chairman: elder_position_gap=4
    with test_db.get_session() as session:
        session.add(
            AssignmentConfig(
                section="fixed",
                position="chairman",
                assignment_name="Председатель",
                required_qualification="chairman",
                is_brothers_only=True,
                needs_assistant=False,
                elder_position_gap=ELDER_POS_GAP,
            )
        )
        session.add(Setting(key="min_assignment_gap", value="0"))
        session.commit()

    # Двое старейшин с квалификацией chairman
    elder_a_id = p_service.add_participant("Elder A", "male", "elder", ["chairman"])
    elder_b_id = p_service.add_participant("Elder B", "male", "elder", ["chairman"])

    # Назначаем персональный gap=2 для Elder A
    with test_db.get_session() as session:
        session.add(
            ParticipantPositionConfig(
                participant_id=elder_a_id,
                section="fixed",
                position="chairman",
                position_gap=PERSONAL_GAP,
            )
        )
        session.commit()

    def make_week_with_chairman(week_title: str, start: date) -> int:
        """Создать неделю с одним заданием chairman и вернуть week_id."""
        with test_db.get_session() as session:
            w = Week(week_title=week_title, start_date=start)
            session.add(w)
            session.commit()
            session.add(
                Assignment(
                    week_id=w.id,
                    assignment_number="0",
                    assignment_text="Председатель",
                    assignment_type="talk",
                    section="fixed",
                    section_position=None,
                    status="empty",
                )
            )
            session.commit()
            return w.id

    # --- Неделя 1: оба свободны, назначается кто-то из двух (или Elder A, т.к. ниже total) ---
    w1_id = make_week_with_chairman("Week 1", date(2026, 1, 5))
    s_service.auto_assign_week(w1_id)
    d1 = s_service.get_week_data(w1_id)
    assigned_w1 = next(a["participant_id"] for a in d1["assignments"] if a["status"] == "assigned")
    # Первое назначение — один из старейшин
    assert assigned_w1 in (elder_a_id, elder_b_id), "Week 1: должен быть назначен один из старейшин"

    # --- Неделя 3: через 2 недели после недели 1 ---
    # Elder A (gap=2)  → ОК через 2 недели
    # Elder B (gap=4)  → НЕ ОК, нужно 4 недели
    w3_id = make_week_with_chairman("Week 3", date(2026, 1, 19))
    s_service.auto_assign_week(w3_id)
    d3 = s_service.get_week_data(w3_id)
    assigned_w3 = next(a["participant_id"] for a in d3["assignments"] if a["status"] == "assigned")

    if assigned_w1 == elder_a_id:
        # Elder A был первым → на неделе 3 Elder B (никогда не назначался) имеет приоритет (0 назначений)
        assert assigned_w3 == elder_b_id, (
            f"Неделя 3: Elder B (0 назначений) должен быть назначен, "
            f"но назначен id={assigned_w3}"
        )
        # На неделе 5: Elder B (был на неделе 3) заблокирован глобальным gap=4,
        # поэтому Elder A (был на неделе 1, gap=2 пройден) должен быть назначен.
        w5_id = make_week_with_chairman("Week 5", date(2026, 2, 2))
        s_service.auto_assign_week(w5_id)
        d5 = s_service.get_week_data(w5_id)
        assigned_w5 = next(
            a["participant_id"] for a in d5["assignments"] if a["status"] == "assigned"
        )
        assert assigned_w5 == elder_a_id, (
            f"Неделя 5: Elder A должен быть назначен, так как Elder B заблокирован, "
            f"но назначен id={assigned_w5}"
        )
    else:
        # Elder B был первым (gap=4) → на неделе 3 он НЕ доступен, назначается Elder A (gap=2, свободен)
        assert assigned_w3 == elder_a_id, (
            f"Неделя 3: Elder A (никогда не был chairman) должен быть назначен, "
            f"но назначен id={assigned_w3}"
        )
        # На неделе 5: оба доступны (Elder B: 4 недели после недели 1; Elder A: 2 недели после недели 3, personal gap=2)
        w5_id = make_week_with_chairman("Week 5", date(2026, 2, 2))
        s_service.auto_assign_week(w5_id)
        d5 = s_service.get_week_data(w5_id)
        assigned_w5 = next(
            a["participant_id"] for a in d5["assignments"] if a["status"] == "assigned"
        )
        assert assigned_w5 in (
            elder_a_id,
            elder_b_id,
        ), "Week 5: должен быть назначен один из старейшин"


def test_assistant_assignment_blocks_within_min_gap(s_service, p_service, test_db):
    """
    Интервал min_gap считается по ЛЮБОЙ роли (главный ИЛИ напарник).
    Участник с gap=3:
      Неделя 1: назначен ГЛАВНЫМ.
      Неделя 2: назначен НАПАРНИКОМ.
      Неделя 4: прошло всего 2 недели с последнего участия (Неделя 2) —
                НЕ должен назначаться, т.к. 2 < 3.
    Это закрепляет требование: возвещатель выступает не чаще раза в min_gap недель
    независимо от того, ведущий он или напарник.
    """
    from datetime import date, datetime

    from core.models import Assignment, Participant, Setting

    # 1. Глобальный интервал — 3 недели
    with test_db.get_session() as session:
        session.query(Setting).filter(Setting.key == "min_assignment_gap").delete()
        session.add(Setting(key="min_assignment_gap", value="3"))
        session.commit()

    # 2. Участники
    # X: главный (ministry_item) + напарник (assistant)
    # Y: только напарник (assistant) — напарник на неделе 1
    # Z: только главный (ministry_item) — главный на неделе 2
    # W: только главный (ministry_item) — свежий, ни в неделю 1, ни в 2
    px_id = p_service.add_participant(
        "Participant X", "male", "publisher", ["ministry_item", "assistant"]
    )
    py_id = p_service.add_participant("Participant Y", "male", "publisher", ["assistant"])
    pz_id = p_service.add_participant("Participant Z", "male", "publisher", ["ministry_item"])
    pw_id = p_service.add_participant(
        "Participant W", "male", "publisher", ["ministry_item", "assistant"]
    )

    def create_week_with_ministry(week_title: str, start: date) -> int:
        with test_db.get_session() as session:
            w = Week(week_title=week_title, start_date=start)
            session.add(w)
            session.commit()
            session.add(
                Assignment(
                    week_id=w.id,
                    assignment_number="1",
                    assignment_text="Задание 1",
                    assignment_type="student",
                    section="ministry",
                    section_position=1,
                    status="empty",
                )
            )
            session.commit()
            return w.id

    # Неделя 1: X — главный, Y — напарник
    w1_id = create_week_with_ministry("Week 1", date(2026, 3, 2))
    with test_db.get_session() as session:
        a1 = session.query(Assignment).filter(Assignment.week_id == w1_id).one()
        a1.participant_id = px_id
        a1.assistant_id = py_id
        a1.status = "assigned"
        px = session.get(Participant, px_id)
        px.last_assignment_date = datetime(2026, 3, 2)
        px.last_main_date = datetime(2026, 3, 2)
        py = session.get(Participant, py_id)
        py.last_assignment_date = datetime(2026, 3, 2)
        session.commit()

    # Неделя 2: Z — главный, X — напарник
    w2_id = create_week_with_ministry("Week 2", date(2026, 3, 9))
    with test_db.get_session() as session:
        a2 = session.query(Assignment).filter(Assignment.week_id == w2_id).one()
        a2.participant_id = pz_id
        a2.assistant_id = px_id
        a2.status = "assigned"
        pz = session.get(Participant, pz_id)
        pz.last_assignment_date = datetime(2026, 3, 9)
        pz.last_main_date = datetime(2026, 3, 9)
        px = session.get(Participant, px_id)
        px.last_assignment_date = datetime(2026, 3, 9)
        # last_main_date остаётся 2026-03-02 (роль напарника не сдвигает очередь на главную)
        session.commit()

    # Неделя 4: 2026-03-23 — 2 недели с последнего участия X (напарник на неделе 2).
    # X НЕ должен назначаться: 2 < min_gap=3.
    # W — свежий кандидат, Z — прошёл как main на неделе 2 (тоже блокирован по любой роли).
    w4_id = create_week_with_ministry("Week 4", date(2026, 3, 23))

    s_service.auto_assign_week(w4_id)

    with test_db.get_session() as session:
        a4 = session.query(Assignment).filter(Assignment.week_id == w4_id).one()
        assert a4.participant_id != px_id, (
            "Participant X не должен назначаться: всего 2 недели с роли напарника (Неделя 2), "
            "что меньше min_gap=3. Интервал считается по любой роли."
        )


def test_discussion_override_single_brother_no_assistant(s_service, p_service, test_db):
    """Пункт «Обсуждение» (ministry/student с discussion_marker) назначается
    ОДНОМУ мужчине без напарника, независимо от конфига позиции."""
    from core.models import Assignment, AssignmentConfig, Setting

    # 1. Конфиг позиции «минistry/3» — как обычный student (с напарником, любой пол),
    #    чтобы override был осмысленным: override должен его перебить.
    with test_db.get_session() as session:
        session.add(
            AssignmentConfig(
                section="ministry",
                position="3",
                assignment_name="Обычное задание",
                required_qualification="ministry_item",
                is_brothers_only=False,
                needs_assistant=True,
            )
        )
        session.add(Setting(key="min_assignment_gap", value="0"))
        session.commit()

    # 2. Участники обоих полов, все квалифицированы (bro1 - MS)
    bro1 = p_service.add_participant("Bro A", "male", "MS", ["ministry_item", "assistant"])
    bro2 = p_service.add_participant("Bro B", "male", "publisher", ["ministry_item", "assistant"])
    sis1 = p_service.add_participant("Sis C", "female", "publisher", ["ministry_item", "assistant"])
    sis2 = p_service.add_participant("Sis D", "female", "publisher", ["ministry_item", "assistant"])

    # 3. Неделя с пунктом-обсуждением (есть discussion_marker)
    with test_db.get_session() as session:
        w = Week(week_title="Week Diss", start_date=date(2024, 1, 1))
        session.add(w)
        session.commit()
        session.add(
            Assignment(
                week_id=w.id,
                assignment_number="6",
                assignment_text="Что бы вы сказали?",
                assignment_type="student",
                section="ministry",
                section_position=3,
                discussion_marker="(6 мин.) Обсуждение",
                status="empty",
            )
        )
        session.commit()
        week_id = w.id

    res = s_service.auto_assign_week(week_id)
    assert res["success"] is True

    with test_db.get_session() as session:
        a = session.query(Assignment).filter(Assignment.week_id == week_id).one()
        assert a.status == "assigned"
        # Назначен ровно ОДИН мужчина (старейшина/MS - bro1)
        assert a.participant_id == bro1
        # Напарника НЕТ
        assert a.assistant_id is None


def test_discussion_override_triggers_only_with_marker(s_service, p_service, test_db):
    """Без discussion_marker обычный student-пункт остаётся с напарником (не override)."""
    from core.models import Assignment, AssignmentConfig, Setting

    with test_db.get_session() as session:
        session.add(
            AssignmentConfig(
                section="ministry",
                position="3",
                assignment_name="Обычное задание",
                required_qualification="ministry_item",
                is_brothers_only=False,
                needs_assistant=True,
            )
        )
        session.add(Setting(key="min_assignment_gap", value="0"))
        session.commit()

    bro1 = p_service.add_participant("Bro A", "male", "publisher", ["ministry_item", "assistant"])
    bro2 = p_service.add_participant("Bro E", "male", "publisher", ["ministry_item", "assistant"])
    sis1 = p_service.add_participant("Sis C", "female", "publisher", ["ministry_item", "assistant"])
    sis2 = p_service.add_participant("Sis D", "female", "publisher", ["ministry_item", "assistant"])

    with test_db.get_session() as session:
        w = Week(week_title="Week NoMarker", start_date=date(2024, 1, 1))
        session.add(w)
        session.commit()
        session.add(
            Assignment(
                week_id=w.id,
                assignment_number="6",
                assignment_text="Развивайте интерес",
                assignment_type="student",
                section="ministry",
                section_position=3,
                discussion_marker=None,
                status="empty",
            )
        )
        session.commit()
        week_id = w.id

    res = s_service.auto_assign_week(week_id)
    assert res["success"] is True

    with test_db.get_session() as session:
        a = session.query(Assignment).filter(Assignment.week_id == week_id).one()
        assert a.status == "assigned"
        # Без override должен быть напарник (главный мужчина → напарник мужчина)
        assert a.assistant_id is not None


def test_discussion_override_allows_elders_saturated_pool(s_service, p_service, test_db):
    """Discussion-override НЕ исключает старейшин и НЕ применяет role-alternation.

    Сценарий: все братья-нестарейшины имеют last_student_role == "main"
    (role-alternation их заблокирует), остаётся только старейшина.
    Override Discussion должен назначить старейшину одному пункту без напарника
    (что воспроизводит проблему с неделей 21–27 сентября на реальных данных).
    """
    from datetime import datetime

    from core.models import Assignment, AssignmentConfig, Participant, Setting

    with test_db.get_session() as session:
        session.add(
            AssignmentConfig(
                section="ministry",
                position="3",
                assignment_name="Обычное задание",
                required_qualification="ministry_item",
                is_brothers_only=False,
                needs_assistant=True,
            )
        )
        session.add(Setting(key="min_assignment_gap", value="4"))
        session.commit()

    # Братья-нестарейшины: квалифицированы, у всех last_student_role == "main"
    bro_pub = p_service.add_participant(
        "Bro Pub", "male", "publisher", ["ministry_item", "assistant"]
    )
    bro_ms = p_service.add_participant("Bro MS", "male", "MS", ["ministry_item", "assistant"])
    # Старейшина: квалифицирован ministry_item
    elder = p_service.add_participant("Elder X", "male", "E", ["ministry_item"])

    # Братья назначались "main" на прошлой неделе — role-alternation их отсеет
    with test_db.get_session() as session:
        prev = Week(week_title="Prev", start_date=date(2024, 1, 1) - timedelta(days=7))
        session.add(prev)
        session.commit()
        for bro in (bro_pub, bro_ms):
            session.add(
                Assignment(
                    week_id=prev.id,
                    assignment_number="4",
                    assignment_text="Начинайте разговор",
                    assignment_type="student",
                    section="ministry",
                    section_position=1,
                    participant_id=bro,
                    status="assigned",
                )
            )
            p = session.get(Participant, bro)
            p.last_assignment_date = datetime(2024, 1, 1) - timedelta(days=7)
            p.last_main_date = datetime(2024, 1, 1) - timedelta(days=7)
        session.commit()

    # Текущая неделя с пунктом обсуждения (старейшина не назначен нигде)
    with test_db.get_session() as session:
        w = Week(week_title="Week Diss", start_date=date(2024, 1, 1))
        session.add(w)
        session.commit()
        session.add(
            Assignment(
                week_id=w.id,
                assignment_number="6",
                assignment_text="Что бы вы сказали?",
                assignment_type="student",
                section="ministry",
                section_position=3,
                discussion_marker="(6 мин.) Обсуждение",
                status="empty",
            )
        )
        session.commit()
        week_id = w.id

    res = s_service.auto_assign_week(week_id)
    assert res["success"] is True

    with test_db.get_session() as session:
        a = session.query(Assignment).filter(Assignment.week_id == week_id).one()
        assert a.status == "assigned", "Discussion item must be assigned"
        # Назначен ОДИН мужчина — старейшина (т.к. не-старейшины заблокированы
        # role-alternation). Без отключения senior-фильтра осталось бы 0 кандидатов.
        assert a.participant_id == elder
        assert a.assistant_id is None


def test_talk_override_allows_elders_no_assistant(s_service, p_service, test_db):
    """Talk-override НЕ исключает старейшин и НЕ применяет role-alternation.

    Сценарий: министерское задание с assignment_type='teaching' (маркер «Речь»).
    Обычная student-логика отсеяла бы старейшину и заменила бы на партнёра.
    Override для Talk должен назначить одного брата (в т.ч. старейшину) без напарника.
    """
    from datetime import datetime

    from core.models import Assignment, AssignmentConfig, Participant, Setting

    with test_db.get_session() as session:
        session.add(
            AssignmentConfig(
                section="ministry",
                position="3",
                assignment_name="Обычное задание",
                required_qualification="ministry_item",
                is_brothers_only=False,
                needs_assistant=True,
            )
        )
        session.add(
            AssignmentConfig(
                section="ministry",
                position="4",
                assignment_name="Речь (только братья)",
                required_qualification="ministry_speech",
                is_brothers_only=True,
                needs_assistant=False,
            )
        )
        session.add(Setting(key="min_assignment_gap", value="4"))
        session.commit()

    elder = p_service.add_participant("Elder Talk", "male", "E", ["ministry_speech"])
    bro_pub = p_service.add_participant("Bro Pub", "male", "publisher", ["ministry_speech"])
    bro_ms = p_service.add_participant("Bro MS", "male", "MS", ["ministry_speech"])

    with test_db.get_session() as session:
        prev = Week(week_title="Prev Talk", start_date=date(2024, 1, 1) - timedelta(days=7))
        session.add(prev)
        session.commit()
        for bro in (bro_pub, bro_ms):
            session.add(
                Assignment(
                    week_id=prev.id,
                    assignment_number="4",
                    assignment_text="Начинайте разговор",
                    assignment_type="student",
                    section="ministry",
                    section_position=1,
                    participant_id=bro,
                    status="assigned",
                )
            )
            p = session.get(Participant, bro)
            p.last_assignment_date = datetime(2024, 1, 1) - timedelta(days=7)
            p.last_main_date = datetime(2024, 1, 1) - timedelta(days=7)
        session.commit()

    with test_db.get_session() as session:
        w = Week(week_title="Week Talk", start_date=date(2024, 1, 1))
        session.add(w)
        session.commit()
        session.add(
            Assignment(
                week_id=w.id,
                assignment_number="6",
                assignment_text="Объясняйте свои взгляды",
                assignment_type="teaching",
                section="ministry",
                section_position=3,
                status="empty",
            )
        )
        session.commit()
        week_id = w.id

    res = s_service.auto_assign_week(week_id)
    assert res["success"] is True

    with test_db.get_session() as session:
        a = session.query(Assignment).filter(Assignment.week_id == week_id).one()
        assert a.status == "assigned", "Talk item must be assigned"
        # Talk не исключает старейшин и не требует напарника.
        assert a.participant_id == elder
        assert a.assistant_id is None


def test_what_would_you_say_goes_to_elder_without_ministry_item(s_service, p_service, test_db):
    """«Что бы вы сказали?» ведёт старейшина или помощник — квалификация учеников
    («Учебные задания») не нужна. Раньше её требовали, у старейшин её нет,
    и пункт оставался пустым (февраль 2027)."""
    from core.models import Assignment, AssignmentConfig, Setting

    with test_db.get_session() as session:
        session.add(
            AssignmentConfig(
                section="ministry",
                position="1",
                assignment_name="Учебное задание",
                required_qualification="ministry_item",
                is_brothers_only=False,
                needs_assistant=True,
            )
        )
        session.add(Setting(key="min_assignment_gap", value="0"))
        session.commit()

    elder = p_service.add_participant("Elder NoStudent", "male", "E", ["gems", "living_part"])
    p_service.add_participant("Bro Pub", "male", "publisher", ["ministry_item"])

    with test_db.get_session() as session:
        w = Week(week_title="Week What Would You Say Elder", start_date=date(2027, 2, 1))
        session.add(w)
        session.commit()
        session.add(
            Assignment(
                week_id=w.id,
                assignment_number="4",
                assignment_text="Что бы вы сказали?",
                assignment_type="student",
                section="ministry",
                section_position=1,
                discussion_marker="(5 мин.) Обсуждение",
                status="empty",
            )
        )
        session.commit()
        week_id = w.id

    res = s_service.auto_assign_week(week_id)
    assert res["success"] is True

    with test_db.get_session() as session:
        a = session.query(Assignment).filter(Assignment.week_id == week_id).one()
        assert a.status == "assigned"
        assert a.participant_id == elder
        assert a.assistant_id is None


def test_what_would_you_say_only_elders_or_ms(s_service, p_service, test_db):
    """Пункт «Что бы вы сказали» в служении назначается ТОЛЬКО старейшинам или служебным помощникам (MS)."""
    from core.models import Assignment, AssignmentConfig, Setting

    with test_db.get_session() as session:
        session.add(
            AssignmentConfig(
                section="ministry",
                position="3",
                assignment_name="Учебное задание",
                required_qualification="ministry_item",
                is_brothers_only=False,
                needs_assistant=True,
            )
        )
        session.add(Setting(key="min_assignment_gap", value="0"))
        session.commit()

    # Добавляем обычного брата, сестру, и служебного помощника
    bro_pub = p_service.add_participant(
        "Bro Pub", "male", "publisher", ["ministry_item", "assistant"]
    )
    sis = p_service.add_participant(
        "Sister A", "female", "publisher", ["ministry_item", "assistant"]
    )
    bro_ms = p_service.add_participant("Bro MS", "male", "MS", ["ministry_item", "assistant"])

    with test_db.get_session() as session:
        w = Week(week_title="Week What Would You Say", start_date=date(2024, 1, 1))
        session.add(w)
        session.commit()
        session.add(
            Assignment(
                week_id=w.id,
                assignment_number="5",
                assignment_text="Что бы вы сказали: Разговор о Боге",
                assignment_type="student",
                section="ministry",
                section_position=2,
                status="empty",
            )
        )
        session.commit()
        week_id = w.id

    res = s_service.auto_assign_week(week_id)
    assert res["success"] is True

    with test_db.get_session() as session:
        a = session.query(Assignment).filter(Assignment.week_id == week_id).one()
        assert a.status == "assigned"
        # Должен быть назначен только MS (или старейшина), ни в коем случае не pub и не сестра
        assert a.participant_id == bro_ms
        assert a.assistant_id is None
