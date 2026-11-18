from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Engine,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from core.domain.entities import AssignmentStatus  # noqa: F401  (единое определение)


class Base(DeclarativeBase):
    pass


# Many-to-Many relationship for Participant <-> Qualification
participant_qualifications = Table(
    "participant_qualifications",
    Base.metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("participant_id", Integer, ForeignKey("participants.id"), nullable=False),
    Column("qualification_name", String, nullable=False),
    UniqueConstraint("participant_id", "qualification_name"),
)


class Participant(Base):
    __tablename__ = "participants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    gender = Column(String, CheckConstraint("gender IN ('male', 'female')"))
    service_type = Column(String)
    family_group_id = Column(Integer)  # Head of family ID
    is_active = Column(Boolean, default=True)
    last_assignment_date = Column(DateTime, nullable=True)
    last_main_date = Column(DateTime, nullable=True)  # Только роль ГЛАВНОГО (не напарника)
    created_at = Column(DateTime, default=datetime.utcnow)
    personal_gap = Column(Integer, nullable=True)  # NULL=авто, 0=всегда, N=раз в N нед.
    is_minor = Column(Boolean, default=False, nullable=False)  # Несовершеннолетний участник
    unavailable_from = Column(Date, nullable=True)  # Временно недоступен с (отпуск)
    unavailable_to = Column(Date, nullable=True)  # Временно недоступен по (отпуск)
    email = Column(String, nullable=True)  # Email для уведомлений о заданиях
    phone = Column(String, nullable=True)  # Номер телефона (справочно)
    # Когда менялась карточка (UTC): по нему синхронизация ПК ↔ планшет решает,
    # чья версия свежее. Ставится автоматически (см. _touch_participant), а при
    # смене одних квалификаций — явно (они в отдельной таблице).
    updated_at = Column(DateTime, nullable=True)

    # No ORM relationship for qualifications - handled via raw SQL/queries.


class Week(Base):
    __tablename__ = "weeks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    week_title = Column(String, nullable=False)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    bible_reading = Column(String)
    month = Column(Integer)
    year = Column(Integer)
    workbook_source = Column(String)
    special_event = Column(String)  # For memorial, assembly, etc.
    announcement = Column(String)  # For weekly announcements
    songs = Column(String)  # Номера песен через запятую: "23,45,67"
    created_at = Column(DateTime, default=datetime.utcnow)

    assignments = relationship("Assignment", back_populates="week", cascade="all, delete-orphan")


class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    week_id = Column(ForeignKey("weeks.id"), nullable=False)
    assignment_text = Column(String, nullable=False)
    assignment_type = Column(String)
    assignment_number = Column(String)
    section = Column(String)  # treasures, ministry, living, cbs, fixed
    section_position = Column(
        String
    )  # position within section: '1','2','3','4','chairman','reader','conductor'
    duration = Column(Integer)
    sort_order = Column(Integer, nullable=True)
    discussion_marker = Column(String)  # Captures "(N мин.) Обсуждение" from EPUB body
    participant_id = Column(ForeignKey("participants.id"))
    assistant_id = Column(ForeignKey("participants.id"))
    status = Column(String, default=AssignmentStatus.UNASSIGNED.value)
    # Когда менялось назначение (UTC). По нему синхронизация ПК ↔ планшет
    # решает, чья версия свежее. Ставится автоматически (см. ниже).
    updated_at = Column(DateTime, nullable=True)
    # Когда руководитель отметил «🧾 листок выдан» (бумажный листок с заданием).
    # Смена участника или напарника снимает отметку — новому нужен свой листок.
    slip_given_at = Column(DateTime, nullable=True)

    week = relationship("Week", back_populates="assignments")


ASSIGNMENT_TRACKED_FIELDS = ("participant_id", "assistant_id", "status")


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _touch_assignment(mapper, connection, target) -> None:
    """Отметить время изменения, если поменялись участник, напарник или статус.

    Явно заданное updated_at (например, при слиянии синхронизации) не трогаем.
    """
    from sqlalchemy import inspect as sa_inspect

    state = sa_inspect(target)
    people_changed = state.has_identity and any(
        state.attrs[field].history.has_changes() for field in ("participant_id", "assistant_id")
    )
    if people_changed and not state.attrs.slip_given_at.history.has_changes():
        target.slip_given_at = None
    if target.updated_at is not None and state.attrs.updated_at.history.has_changes():
        return
    if not state.has_identity or any(
        state.attrs[field].history.has_changes() for field in ASSIGNMENT_TRACKED_FIELDS
    ):
        target.updated_at = utc_now()


event.listen(Assignment, "before_insert", _touch_assignment)
event.listen(Assignment, "before_update", _touch_assignment)


# last_assignment_date / last_main_date меняются при каждом назначении — это не
# правка карточки, их в отметку времени не включаем.
PARTICIPANT_TRACKED_FIELDS = (
    "name",
    "gender",
    "service_type",
    "family_group_id",
    "is_active",
    "personal_gap",
    "is_minor",
    "unavailable_from",
    "unavailable_to",
    "email",
    "phone",
)


def _touch_participant(mapper, connection, target) -> None:
    """Отметить время правки карточки участника (как _touch_assignment)."""
    from sqlalchemy import inspect as sa_inspect

    state = sa_inspect(target)
    if target.updated_at is not None and state.attrs.updated_at.history.has_changes():
        return
    if not state.has_identity or any(
        state.attrs[field].history.has_changes() for field in PARTICIPANT_TRACKED_FIELDS
    ):
        target.updated_at = utc_now()


event.listen(Participant, "before_insert", _touch_participant)
event.listen(Participant, "before_update", _touch_participant)


class AssignmentConfig(Base):
    """Конфигурация квалификаций по (section, position).

    section — раздел встречи: fixed, treasures, ministry, living, cbs
    position — позиция внутри раздела (str): '1','2','3' или 'chairman','reader'

    Это позволяет корректно обрабатывать плавающую нумерацию:
    пункт 7 в EPUB может быть (ministry, 4) или (living, 1).
    """

    __tablename__ = "assignment_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    section = Column(String, nullable=False)
    position = Column(String, nullable=False)
    assignment_name = Column(String)
    required_qualification = Column(String)
    is_brothers_only = Column(Boolean, default=False)
    needs_assistant = Column(Boolean, default=False)
    elder_position_gap = Column(Integer, nullable=True)
    # NULL = нет особого ограничения для старейшин.
    # N   = старейшины назначаются на эту позицию не чаще раза в N недель,
    #        даже несмотря на их глобальное освобождение от gap-фильтра.
    is_exclusive = Column(Boolean, nullable=False, default=True)
    # True  (1) = назначение на эту позицию полностью блокирует участника
    #             от других заданий в той же неделе (поведение по умолчанию).
    # False (0) = «лёгкое» задание: участник остаётся доступен для ministry.
    #             Пример: молитва (prayer_open/close), чтение Библии (treasures/3).

    __table_args__ = (UniqueConstraint("section", "position"),)


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String, primary_key=True)
    value = Column(String)


class NotificationHistory(Base):
    """История отправки уведомлений участникам."""

    __tablename__ = "notification_history"

    id = Column(Integer, primary_key=True)
    participant_id = Column(Integer, nullable=False)
    week_id = Column(Integer, nullable=False)
    sent_at = Column(DateTime, default=func.now(), nullable=False)
    status = Column(String(20), nullable=False)  # "success" | "error"
    error_message = Column(Text, nullable=True)
    subject = Column(String(200), nullable=True)


class NotificationResponse(Base):
    """Ответ участника на уведомление о неделе: подтвердил / не сможет.

    Ставится из ответа на письмо (core/notification_replies.py) или вручную;
    одна строка на участника и неделю. Новое уведомление о неделе её снимает.
    """

    __tablename__ = "notification_responses"
    __table_args__ = (
        UniqueConstraint("participant_id", "week_id", name="uq_notification_response"),
    )

    id = Column(Integer, primary_key=True)
    participant_id = Column(Integer, nullable=False, index=True)
    week_id = Column(Integer, nullable=False, index=True)
    response = Column(String(20), nullable=False)  # "confirmed" | "declined"
    source = Column(String(20), nullable=False, default="manual")  # "email" | "manual"
    responded_at = Column(DateTime, default=utc_now, nullable=False)  # UTC, как sent_at


# =============================================================================
# Модели для новых графиков (уборка, распорядители, микрофоны, звук, ZOOM)
# =============================================================================


class Group(Base):
    """Группы для уборки зала."""

    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)  # "Группа 1", "Группа 2", ...
    order = Column(Integer, default=0)  # Порядок групп (1, 2, 3...)
    is_active = Column(Boolean, default=True)  # Активна ли группа

    # Relationships
    cleaning_schedules = relationship("CleaningSchedule", back_populates="group")


class CleaningSchedule(Base):
    """График уборки зала."""

    __tablename__ = "cleaning_schedule"

    id = Column(Integer, primary_key=True, autoincrement=True)
    week_start = Column(Date, nullable=False)  # Начало недели
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False)

    # Relationships
    group = relationship("Group", back_populates="cleaning_schedules")

    __table_args__ = (UniqueConstraint("week_start", name="uix_cleaning_week"),)


class AttendantSchedule(Base):
    """График распорядителей (встречи в Зале Царства)."""

    __tablename__ = "attendant_schedule"

    id = Column(Integer, primary_key=True, autoincrement=True)
    week_start = Column(Date, nullable=False)
    meeting_type = Column(String(20), nullable=False)  # 'midweek' или 'weekend'
    participant_id = Column(Integer, ForeignKey("participants.id"))
    position = Column(Integer, default=1)  # 1 или 2 (два человека на встречу)

    # Relationships
    participant = relationship("Participant")

    __table_args__ = (
        UniqueConstraint(
            "week_start", "meeting_type", "position", name="uix_attendant_week_meeting_pos"
        ),
    )


class MicrophoneSchedule(Base):
    """График работы с микрофонами."""

    __tablename__ = "microphone_schedule"

    id = Column(Integer, primary_key=True, autoincrement=True)
    week_start = Column(Date, nullable=False)
    meeting_type = Column(String(20), nullable=False)  # 'midweek' или 'weekend'
    participant_id = Column(Integer, ForeignKey("participants.id"))
    position = Column(Integer, default=1)  # 1 или 2

    # Relationships
    participant = relationship("Participant")

    __table_args__ = (
        UniqueConstraint(
            "week_start", "meeting_type", "position", name="uix_microphone_week_meeting_pos"
        ),
    )


class SoundSchedule(Base):
    """График звукооператоров."""

    __tablename__ = "sound_schedule"

    id = Column(Integer, primary_key=True, autoincrement=True)
    week_start = Column(Date, nullable=False)
    meeting_type = Column(String(20), nullable=False)  # 'midweek' или 'weekend'
    participant_id = Column(Integer, ForeignKey("participants.id"))
    position = Column(Integer, default=1)  # 1 или 2

    # Relationships
    participant = relationship("Participant")

    __table_args__ = (
        UniqueConstraint(
            "week_start", "meeting_type", "position", name="uix_sound_week_meeting_pos"
        ),
    )


class ZoomAttendantSchedule(Base):
    """График распорядителей в ZOOM."""

    __tablename__ = "zoom_attendant_schedule"

    id = Column(Integer, primary_key=True, autoincrement=True)
    week_start = Column(Date, nullable=False)
    meeting_type = Column(String(20), nullable=False)  # 'midweek' или 'weekend'
    participant_id = Column(Integer, ForeignKey("participants.id"))

    # Relationships
    participant = relationship("Participant")

    @property
    def position(self) -> int:
        """Для Zoom всегда одна позиция (один человек на встречу)."""
        return 1

    __table_args__ = (UniqueConstraint("week_start", "meeting_type", name="uix_zoom_week_meeting"),)


class StageSchedule(Base):
    """График работы на сцене."""

    __tablename__ = "stage_schedule"

    id = Column(Integer, primary_key=True, autoincrement=True)
    week_start = Column(Date, nullable=False)
    meeting_type = Column(String(20), nullable=False)  # 'midweek' или 'weekend'
    participant_id = Column(Integer, ForeignKey("participants.id"))
    position = Column(Integer, default=1)  # Всегда 1 (один человек на встречу)

    # Relationships
    participant = relationship("Participant")

    __table_args__ = (
        UniqueConstraint(
            "week_start", "meeting_type", "position", name="uix_stage_week_meeting_pos"
        ),
    )


class ParticipantExcludedWeek(Base):
    """Конкретные недели, когда участник недоступен.

    Используется для двух сценариев:
    1. Разовые пропуски (участника не будет на встрече в конкретную неделю).
    2. Периодические пропуски (сменный график) — хранятся как набор конкретных дат.

    Поле week_start содержит дату начала недели (понедельник или дата начала встречи).
    Выбор: одна запись = одна неделя-исключение.
    """

    __tablename__ = "participant_excluded_weeks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    participant_id = Column(
        Integer, ForeignKey("participants.id", ondelete="CASCADE"), nullable=False
    )
    week_start = Column(Date, nullable=False)  # Дата начала недели (начало встречи)

    __table_args__ = (
        UniqueConstraint("participant_id", "week_start", name="uix_excluded_week_participant"),
    )


class ParticipantPositionConfig(Base):
    """Персональный позиционный интервал участника для конкретной позиции встречи.

    Переопределяет ``elder_position_gap`` из ``assignment_config`` для конкретного
    участника. Используется, когда нужно разрешить отдельному старейшине занимать
    ту или иную позицию чаще (или реже), чем остальным.

    Примеры применения:
    - руководитель встречи — Председатель: position_gap=2 (раз в 2 недели вместо 4).
    - Любой другой участник — любая позиция с индивидуальным ограничением.

    Приоритет в алгоритме (от высшего к низшему):
    1. ``ParticipantPositionConfig.position_gap``  ← эта таблица
    2. ``AssignmentConfig.elder_position_gap``     ← глобальный для всех старейшин
    3. ``eff_gap == 0`` → участник полностью освобождён
    4. ``eff_gap * 2``  → стандартная формула
    """

    __tablename__ = "participant_position_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    participant_id = Column(
        Integer,
        ForeignKey("participants.id", ondelete="CASCADE"),
        nullable=False,
    )
    section = Column(String, nullable=False)  # Раздел: 'fixed', 'cbs', 'treasures', ...
    position = Column(String, nullable=False)  # Позиция: 'chairman', 'conductor', '1', ...
    position_gap = Column(Integer, nullable=False)
    # Минимальный интервал в неделях между назначениями этого участника на данную позицию.

    __table_args__ = (
        UniqueConstraint(
            "participant_id",
            "section",
            "position",
            name="uix_participant_position_config",
        ),
    )


# «Речь председателя» следует за председателем недели (хук before_flush).
import core.chairman_talk  # noqa: E402,F401
