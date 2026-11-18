"""
Database synchronization service.
Handles merging two SQLite databases (e.g. desktop master and the Android tablet).
Сервер — на планшете (входящие к ПК закрывает брандмауэр), ПК подключается к нему.
"""

import os
import logging
import secrets
import shutil
import sqlite3
import tempfile
from datetime import datetime
from typing import Dict, Any, List
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import sessionmaker

from core import participant_tombstones
from core.secret_store import SECRET_KEYS
from core.models import (
    Base,
    Participant,
    ParticipantExcludedWeek,
    Week,
    Assignment,
    AssignmentConfig,
    AssignmentStatus,
    NotificationHistory,
    NotificationResponse,
    Setting,
    participant_qualifications,
)
from core.i18n import _, tr

logger = logging.getLogger(__name__)

# The server is reachable from the local network, so the request body is capped:
# a real schedule database is a few megabytes, tens of megabytes is plenty.
MAX_UPLOAD_BYTES = 64 * 1024 * 1024

SQLITE_MAGIC = b"SQLite format 3\x00"

# A phone on the same Wi-Fi cannot reach 127.0.0.1, so the server has to listen
# on every interface. Making it an explicit, named choice keeps it visible.
ALL_INTERFACES_HOST = "0.0.0.0"
DEFAULT_BIND_HOST = ALL_INTERFACES_HOST
# Один постоянный порт: планшет показывает адрес, ПК подставляет порт сам.
# Занятый порт — почти всегда уже открытое окно синхронизации, и об этом
# честно говорим (раньше сервер молча перескакивал на 8766 и дальше).
DEFAULT_PORT = 8765


class SyncServerBusyError(OSError):
    """Порт синхронизации занят — окно синхронизации уже открыто."""


# Код подключения вводят руками на планшете, поэтому он короткий. Перебор
# короткого кода по сети останавливает лимит неверных попыток: после него
# сервер до перезапуска отвечает отказом на всё.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # без похожих 0/O, 1/I
CODE_LENGTH = 6
MAX_FAILED_ATTEMPTS = 5


def generate_sync_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalize_sync_code(code: str) -> str:
    return "".join(code.split()).upper()


def is_sqlite(data: bytes) -> bool:
    """Cheap check that an upload really is a SQLite database.

    The merge would fail on garbage anyway, but rejecting it up front keeps a
    junk file out of the temp folder and gives the client a clear answer.
    """
    return bool(data) and data[: len(SQLITE_MAGIC)] == SQLITE_MAGIC


# Сколько копий «.pre-sync-*.bak» держать рядом с базой: каждая — полная база
KEEP_SYNC_BACKUPS = 5


def _sqlite_copy(src_path: str, dst_path: str) -> None:
    """Целостная копия SQLite через backup API: в отличие от чтения файла
    подряд, не захватит базу посреди записи (см. core/db_snapshot)."""

    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def read_database_bytes(db_path: str) -> bytes:
    """Содержимое базы для отправки по сети — через целостную копию."""
    fd, tmp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _sqlite_copy(db_path, tmp_path)
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        os.remove(tmp_path)


def sync_success_message() -> str:
    """Текст «готово» сервера синхронизации — по нему окно на ПК понимает успех."""
    return _("Синхронизация успешно завершена!")


def backup_database(db_path: str) -> str:
    """Copy the database next to itself before a risky merge.

    Returns the backup path. A failure here must not stop synchronization, so
    errors are logged and an empty string is returned. Keeps the last
    KEEP_SYNC_BACKUPS copies.
    """
    if not db_path or not os.path.exists(db_path):
        return ""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = f"{db_path}.pre-sync-{stamp}.bak"
    try:
        try:
            _sqlite_copy(db_path, backup_path)
        except sqlite3.DatabaseError:
            # Не открылась как SQLite (повреждена?) — копия файла как есть
            # всё равно лучше, чем никакой.
            if os.path.exists(backup_path):
                os.remove(backup_path)
            shutil.copy2(db_path, backup_path)
        logger.info("SyncServer: database backed up to %s", backup_path)
    except Exception as e:
        logger.warning("SyncServer: could not back up database: %s", e)
        return ""
    folder, name = os.path.split(os.path.abspath(db_path))
    old = sorted(
        f for f in os.listdir(folder) if f.startswith(name + ".pre-sync-") and f.endswith(".bak")
    )
    for stale in old[:-KEEP_SYNC_BACKUPS]:
        try:
            os.remove(os.path.join(folder, stale))
        except OSError as e:
            logger.warning("SyncServer: could not remove old backup %s: %s", stale, e)
    return backup_path


def _source_is_newer(source, target) -> bool:
    """Нужно ли переносить назначение с планшета (source) на ПК (target)."""
    if source.updated_at is not None:
        return target.updated_at is None or source.updated_at > target.updated_at
    if target.updated_at is not None:
        return False
    # Обе базы без отметок времени (до миграции 017) — прежнее правило:
    # заполненное назначение с планшета переносится.
    return source.status == AssignmentStatus.ASSIGNED.value


def _participant_source_is_newer(source, target) -> bool:
    """Переносить ли ручные поля карточки участника с планшета (source) на ПК."""
    if source.updated_at is not None:
        return target.updated_at is None or source.updated_at > target.updated_at
    # С планшета без отметки (старая версия) — прежнее правило «планшет
    # побеждает», но только если и на ПК карточку не правили после обновления.
    return target.updated_at is None


class DatabaseMerger:
    """
    Merges a source database (e.g. uploaded from the tablet) into a target database (e.g. desktop master).
    Uses business rules to match records and resolve conflicts.
    """

    def __init__(self, target_db_path: str, source_db_path: str):
        self.target_engine = create_engine(f"sqlite:///{target_db_path}")
        self.source_engine = create_engine(f"sqlite:///{source_db_path}")
        # База со старой версии приложения может не иметь новых колонок
        from core.database import ensure_required_columns

        ensure_required_columns(self.target_engine)
        ensure_required_columns(self.source_engine)

        self.TargetSession = sessionmaker(bind=self.target_engine)
        self.SourceSession = sessionmaker(bind=self.source_engine)

        # ID Mappings from Source -> Target
        self.participant_id_map = {}  # {source_id: target_id}
        self.week_id_map = {}  # {source_id: target_id}
        # Участники, чья карточка взята с планшета (новые или свежее, чем на ПК)
        self._participants_from_source = set()
        self.tombstones = {}

    def merge(self) -> bool:
        """Execute the merge process."""
        target_session = self.TargetSession()
        source_session = self.SourceSession()

        try:
            logger.info("Starting database merge...")

            # 0. Списки удалённых участников с обеих сторон
            self.tombstones = participant_tombstones.union(
                participant_tombstones.load(target_session),
                participant_tombstones.load(source_session),
            )
            if self.tombstones:
                participant_tombstones.save(target_session, self.tombstones)

            # 1. Merge Participants & Qualifications
            self._merge_participants(target_session, source_session)
            self._drop_deleted_participants(target_session)

            # 1a. Отдельные недели, когда участника не будет (объединение)
            self._merge_excluded_weeks(target_session, source_session)

            # 2. Merge Weeks
            self._merge_weeks(target_session, source_session)

            # 3. Merge Assignments
            self._merge_assignments(target_session, source_session)

            # 4. Merge Settings
            self._merge_settings(target_session, source_session)

            # 5. Ответы участников на уведомления (✅ / ❌)
            self._merge_notification_responses(target_session, source_session)

            target_session.commit()
            logger.info("Database merge completed successfully.")
            return True

        except Exception as e:
            target_session.rollback()
            logger.error(f"Error during database merge: {e}", exc_info=True)
            return False
        finally:
            target_session.close()
            source_session.close()
            # Иначе пул держит файлы открытыми (временный файл с планшета
            # потом удаляется)
            self.target_engine.dispose()
            self.source_engine.dispose()

    def _merge_participants(self, target_sess, source_sess):
        """Merge Participant entities by name."""
        source_participants = [
            sp
            for sp in source_sess.query(Participant).all()
            # Удалён на ПК после последней правки на планшете — не возвращаем
            if not participant_tombstones.deleted_after_edit(sp, self.tombstones)
        ]
        for sp in source_participants:
            tp = target_sess.query(Participant).filter(Participant.name == sp.name).first()

            # Get qualifications from source
            sq_rows = (
                source_sess.execute(
                    select(participant_qualifications.c.qualification_name).where(
                        participant_qualifications.c.participant_id == sp.id
                    )
                )
                .scalars()
                .all()
            )

            if tp:
                # Ручные поля карточки переносятся, только если правка на
                # планшете свежее (как у назначений): иначе старая копия
                # планшета затёрла бы отпуск или статус, заданные на ПК.
                source_wins = _participant_source_is_newer(sp, tp)
                if source_wins:
                    self._participants_from_source.add(sp.id)
                    tp.gender = sp.gender or tp.gender
                    tp.service_type = sp.service_type
                    tp.is_active = sp.is_active
                    tp.personal_gap = sp.personal_gap
                    tp.is_minor = sp.is_minor
                    tp.unavailable_from = sp.unavailable_from
                    tp.unavailable_to = sp.unavailable_to
                    # family_group_id ссылается на participant.id главы семьи —
                    # отображаем через participant_id_map (CR-5).
                    if sp.family_group_id is not None:
                        tp.family_group_id = self.participant_id_map.get(
                            sp.family_group_id, sp.family_group_id
                        )
                    else:
                        tp.family_group_id = None
                    if sp.updated_at is not None:
                        tp.updated_at = sp.updated_at
                # Контакты: пустое поле на одной стороне не стирает адрес на
                # другой; заполненные на обеих — берём с более свежей.
                if sp.email and (source_wins or not tp.email):
                    tp.email = sp.email
                if sp.phone and (source_wins or not tp.phone):
                    tp.phone = sp.phone
                # last_assignment_date / last_main_date — LWW (последняя запись wins),
                # т.к. обе БД могут накапливать собственную историю назначений.
                if sp.last_assignment_date:
                    if (
                        not tp.last_assignment_date
                        or sp.last_assignment_date > tp.last_assignment_date
                    ):
                        tp.last_assignment_date = sp.last_assignment_date
                if sp.last_main_date:
                    if not tp.last_main_date or sp.last_main_date > tp.last_main_date:
                        tp.last_main_date = sp.last_main_date
                # Квалификации: свежая карточка с планшета заменяет набор
                # (иначе снятая на ПК квалификация возвращалась бы); у старых
                # баз без отметок времени — прежнее объединение.
                tq_rows = (
                    target_sess.execute(
                        select(participant_qualifications.c.qualification_name).where(
                            participant_qualifications.c.participant_id == tp.id
                        )
                    )
                    .scalars()
                    .all()
                )
                legacy = sp.updated_at is None and tp.updated_at is None
                if source_wins and not legacy:
                    for qual in set(tq_rows) - set(sq_rows):
                        target_sess.execute(
                            participant_qualifications.delete().where(
                                participant_qualifications.c.participant_id == tp.id,
                                participant_qualifications.c.qualification_name == qual,
                            )
                        )
                if source_wins or legacy:
                    for qual in sq_rows:
                        if qual not in tq_rows:
                            target_sess.execute(
                                participant_qualifications.insert().values(
                                    participant_id=tp.id, qualification_name=qual
                                )
                            )
                self.participant_id_map[sp.id] = tp.id
            else:
                # Insert new participant. Все значимые для бизнес-логики поля
                # копируются с учётом маппинга ссылочных ID (CR-4/CR-5).
                # family_group_id — через participant_id_map (глава мог быть
                # смержен ранее). Если глава ещё не встретился — оставляем raw ID
                # с последующим допатчем (см. ниже двухпроходной подход).
                mapped_family_id = (
                    self.participant_id_map.get(sp.family_group_id, sp.family_group_id)
                    if sp.family_group_id is not None
                    else None
                )
                new_p = Participant(
                    name=sp.name,
                    gender=sp.gender,
                    service_type=sp.service_type,
                    family_group_id=mapped_family_id,
                    is_active=sp.is_active,
                    last_assignment_date=sp.last_assignment_date,
                    last_main_date=sp.last_main_date,
                    created_at=sp.created_at,
                    personal_gap=sp.personal_gap,
                    is_minor=sp.is_minor,
                    unavailable_from=sp.unavailable_from,
                    unavailable_to=sp.unavailable_to,
                    email=sp.email,
                    phone=sp.phone,
                    updated_at=sp.updated_at,
                )
                target_sess.add(new_p)
                target_sess.flush()
                self._participants_from_source.add(sp.id)

                for qual in sq_rows:
                    target_sess.execute(
                        participant_qualifications.insert().values(
                            participant_id=new_p.id, qualification_name=qual
                        )
                    )

                self.participant_id_map[sp.id] = new_p.id

        # Второй проход: починить family_group_id для участников, чей глава
        # ещё не был в participant_id_map при первом проходе (главы и члены
        # обрабатываются независимо по name). Перерисуем все target-ссылки
        # через окончательный participant_id_map.
        for sp in source_participants:
            if sp.family_group_id is None or sp.id not in self._participants_from_source:
                continue
            target_pid = self.participant_id_map.get(sp.id)
            if target_pid is None:
                continue
            tp = target_sess.get(Participant, target_pid)
            if tp is None:
                continue
            mapped_head = self.participant_id_map.get(sp.family_group_id)
            if mapped_head is not None and tp.family_group_id != mapped_head:
                tp.family_group_id = mapped_head

    def _drop_deleted_participants(self, target_sess):
        """Удалить на ПК тех, кого удалили на планшете после правки на ПК."""
        for tp in target_sess.query(Participant).all():
            if not participant_tombstones.deleted_after_edit(tp, self.tombstones):
                continue
            logger.info("Sync: участник «%s» удалён на другом устройстве", tp.name)
            target_sess.execute(
                participant_qualifications.delete().where(
                    participant_qualifications.c.participant_id == tp.id
                )
            )
            target_sess.query(ParticipantExcludedWeek).filter(
                ParticipantExcludedWeek.participant_id == tp.id
            ).delete()
            target_sess.delete(tp)
        target_sess.flush()

    def _merge_excluded_weeks(self, target_sess, source_sess):
        """Недели-исключения участников: объединение по (участник, неделя).

        Удаление исключения на одном устройстве не переносится — запись
        с другого устройства вернётся. Это безопаснее, чем потерять пропуск.
        """
        existing = {
            (row.participant_id, row.week_start)
            for row in target_sess.query(ParticipantExcludedWeek).all()
        }
        for row in source_sess.query(ParticipantExcludedWeek).all():
            pid = self.participant_id_map.get(row.participant_id)
            if pid is None or row.week_start is None:
                continue
            key = (pid, row.week_start)
            if key in existing:
                continue
            target_sess.add(ParticipantExcludedWeek(participant_id=pid, week_start=row.week_start))
            existing.add(key)

    def _merge_weeks(self, target_sess, source_sess):
        """Merge Week entities by start_date."""
        source_weeks = source_sess.query(Week).all()
        for sw in source_weeks:
            tw = target_sess.query(Week).filter(Week.start_date == sw.start_date).first()
            if tw:
                # Update attributes if source announcement or special event is newer/exists
                tw.special_event = sw.special_event or tw.special_event
                tw.announcement = sw.announcement or tw.announcement
                tw.songs = sw.songs or tw.songs
                self.week_id_map[sw.id] = tw.id
            else:
                # Insert new week
                new_w = Week(
                    week_title=sw.week_title,
                    start_date=sw.start_date,
                    bible_reading=sw.bible_reading,
                    month=sw.month,
                    year=sw.year,
                    workbook_source=sw.workbook_source,
                    special_event=sw.special_event,
                    announcement=sw.announcement,
                    songs=sw.songs,
                    created_at=sw.created_at,
                )
                target_sess.add(new_w)
                target_sess.flush()
                self.week_id_map[sw.id] = new_w.id

    def _merge_assignments(self, target_sess, source_sess):
        """Merge main midweek meeting assignments."""
        source_assignments = source_sess.query(Assignment).all()
        for sa in source_assignments:
            # Map week ID
            target_week_id = self.week_id_map.get(sa.week_id)
            if not target_week_id:
                continue

            # Find matching assignment on target week.
            # PRIMARY key: assignment_number (стабилен при перефразировке текста
            # в новых EPUB-версиях — совпадает с ключом workbook_import._sync_assignments).
            # FALLBACK: (section, section_position, assignment_text) для legacy-данных
            # без assignment_number.
            ta = None
            if sa.assignment_number:
                ta = (
                    target_sess.query(Assignment)
                    .filter(
                        Assignment.week_id == target_week_id,
                        Assignment.assignment_number == sa.assignment_number,
                    )
                    .first()
                )
            if not ta:
                ta = (
                    target_sess.query(Assignment)
                    .filter(
                        Assignment.week_id == target_week_id,
                        Assignment.section == sa.section,
                        Assignment.section_position == sa.section_position,
                        Assignment.assignment_text == sa.assignment_text,
                    )
                    .first()
                )

            # Map participant IDs
            sp_id = self.participant_id_map.get(sa.participant_id) if sa.participant_id else None
            sa_id = self.participant_id_map.get(sa.assistant_id) if sa.assistant_id else None

            if ta:
                # Побеждает более свежая версия: на обоих устройствах полная
                # копия базы, и без сравнения времени устаревшее назначение
                # с планшета перетёрло бы новое на ПК.
                if _source_is_newer(sa, ta):
                    ta.participant_id = sp_id
                    ta.assistant_id = sa_id
                    ta.status = sa.status
                    ta.slip_given_at = sa.slip_given_at
                    if sa.updated_at is not None:
                        ta.updated_at = sa.updated_at
            else:
                # Insert new assignment if not present
                new_a = Assignment(
                    week_id=target_week_id,
                    assignment_text=sa.assignment_text,
                    assignment_type=sa.assignment_type,
                    assignment_number=sa.assignment_number,
                    section=sa.section,
                    section_position=sa.section_position,
                    duration=sa.duration,
                    participant_id=sp_id,
                    assistant_id=sa_id,
                    status=sa.status,
                    updated_at=sa.updated_at,
                    slip_given_at=sa.slip_given_at,
                )
                target_sess.add(new_a)

    def _merge_notification_responses(self, target_sess, source_sess):
        """Ответы на уведомления с планшета: побеждает более свежий. Ответ старше
        последнего письма на ПК не переносится — новое уведомление сняло его
        (NotificationService), он был о прежнем письме. Снятая на планшете
        отметка на ПК не снимается: удаления не синхронизируются."""
        table = NotificationResponse.__tablename__
        if not (
            inspect(self.source_engine).has_table(table)
            and inspect(self.target_engine).has_table(table)
        ):
            return  # база до миграции 018
        for sr in source_sess.query(NotificationResponse).all():
            pid = self.participant_id_map.get(sr.participant_id)
            wid = self.week_id_map.get(sr.week_id)
            if not pid or not wid or sr.responded_at is None:
                continue
            last_sent = target_sess.execute(
                select(func.max(NotificationHistory.sent_at)).where(
                    NotificationHistory.participant_id == pid,
                    NotificationHistory.week_id == wid,
                    NotificationHistory.status == "success",
                )
            ).scalar()
            if last_sent is not None and sr.responded_at < last_sent:
                continue
            tr = (
                target_sess.query(NotificationResponse)
                .filter_by(participant_id=pid, week_id=wid)
                .one_or_none()
            )
            if tr is not None and tr.responded_at and tr.responded_at >= sr.responded_at:
                continue
            if tr is None:
                tr = NotificationResponse(participant_id=pid, week_id=wid)
                target_sess.add(tr)
            tr.response, tr.source, tr.responded_at = sr.response, sr.source, sr.responded_at

    def _merge_settings(self, target_sess, source_sess):
        """Merge configuration settings."""
        source_settings = source_sess.query(Setting).all()
        for ss in source_settings:
            # Пароли и параметры самой синхронизации у каждого устройства свои
            if ss.key in SECRET_KEYS or ss.key.startswith("sync_"):
                continue
            # Списки удалённых уже объединены в merge()
            if ss.key == participant_tombstones.SETTING_KEY:
                continue
            ts = target_sess.query(Setting).filter(Setting.key == ss.key).first()
            if ts:
                # Update setting value from source
                ts.value = ss.value
            else:
                new_s = Setting(key=ss.key, value=ss.value)
                target_sess.add(new_s)


def get_local_ip() -> str:
    """Find the local IP address in the Wi-Fi network."""
    import socket

    # Адрес не обязан быть доступен: connect UDP лишь выбирает интерфейс.
    # Без маршрута по умолчанию (Wi-Fi без интернета) пробуем адреса локальных сетей.
    for target in ("10.255.255.255", "192.168.1.1", "192.168.0.1", "172.16.0.1", "10.0.0.1"):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((target, 1))
            ip = s.getsockname()[0]
        except OSError:
            continue
        finally:
            s.close()
        if ip and not ip.startswith("127."):
            return ip
    return "127.0.0.1"


class SyncHTTPHandler(object):
    """
    Фабрика обработчика HTTP-сервера синхронизации (сервер — на планшете).

    GET  /db    (код в заголовке X-Sync-Code) — отдать свою базу ПК;
    POST /sync  (multipart: token, database)  — принять объединённую базу от ПК.

    Код — в заголовке, а не в адресе: строка запроса пишется в журнал.
    Счётчик неверных кодов общий для обоих запросов.
    """

    @staticmethod
    def create_handler(db_path: str, auth_token: str, on_status_change, accept_database=None):
        """accept_database(bytes) заменяет базу и бросает исключение при неудаче;
        по умолчанию — replace_database(db_path, …) прямо в потоке сервера."""
        failed_attempts = [0]

        if accept_database is None:

            def accept_database(data: bytes) -> None:
                replace_database(db_path, data)

        from http.server import BaseHTTPRequestHandler

        class Handler(BaseHTTPRequestHandler):
            # Сервер однопоточный: молчащий клиент не должен держать его вечно
            timeout = 30

            def log_message(self, format, *args):
                logger.info(f"SyncServer: {format % args}")

            def _check_code(self, code: str) -> bool:
                """Проверка кода с лимитом попыток; при отказе ответ уже отправлен."""
                if failed_attempts[0] >= MAX_FAILED_ATTEMPTS:
                    self.send_error(429, "Too many failed attempts")
                    return False
                # Сравнение за постоянное время: неверный код не подобрать по задержке
                if not code or not secrets.compare_digest(
                    normalize_sync_code(code).encode("utf-8"),
                    normalize_sync_code(auth_token).encode("utf-8"),
                ):
                    failed_attempts[0] += 1
                    logger.warning("SyncServer: rejected request with invalid token")
                    if failed_attempts[0] >= MAX_FAILED_ATTEMPTS and on_status_change:
                        on_status_change(
                            _(
                                "Слишком много неверных кодов — синхронизация остановлена. "
                                "Закройте окно и откройте заново."
                            )
                        )
                    self.send_error(401, "Invalid sync token")
                    return False
                return True

            def do_GET(self):
                if self.path == "/":
                    self.send_response(200)
                    self.send_header("Content-type", "text/html")
                    self.end_headers()
                    self.wfile.write(b"Cerastilo Sync Server is active.")
                    return
                if self.path != "/db":
                    self.send_error(404)
                    return
                if not self._check_code(self.headers.get("X-Sync-Code", "")):
                    return
                try:
                    data = read_database_bytes(db_path)
                except Exception as e:
                    logger.error(f"Error reading database for sync: {e}", exc_info=True)
                    self.send_error(500, "Internal server error")
                    return
                self.send_response(200)
                self.send_header("Content-type", "application/x-sqlite3")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                if on_status_change:
                    on_status_change(_("ПК забрал базу и объединяет…"))

            def do_POST(self):
                if not self.path.startswith("/sync"):
                    self.send_error(404)
                    return

                try:
                    content_type = self.headers.get("content-type", "")
                    if not content_type.startswith("multipart/form-data"):
                        self.send_error(400, "Expected multipart/form-data")
                        return

                    # Лимит тела до чтения: иначе клиент заявит любой
                    # Content-Length и исчерпает память.
                    raw_length = self.headers.get("content-length", "")
                    try:
                        content_length = int(raw_length)
                    except (TypeError, ValueError):
                        self.send_error(411, "Length Required")
                        return
                    if content_length <= 0:
                        self.send_error(400, "Empty request")
                        return
                    if content_length > MAX_UPLOAD_BYTES:
                        logger.warning(
                            "SyncServer: rejected %d bytes (limit %d)",
                            content_length,
                            MAX_UPLOAD_BYTES,
                        )
                        self.send_error(413, "Payload Too Large")
                        return

                    # Код — до чтения тела: чужой клиент не заставит читать 64 МБ
                    header_code = self.headers.get("X-Sync-Code", "")
                    if header_code and not self._check_code(header_code):
                        return

                    body_raw = self.rfile.read(content_length)

                    headers_raw = b""
                    for name, val in self.headers.items():
                        headers_raw += f"{name}: {val}\r\n".encode("utf-8")

                    from email.parser import BytesParser

                    msg = BytesParser().parsebytes(headers_raw + b"\r\n" + body_raw)

                    fields = {}
                    if msg.is_multipart():
                        for part in msg.get_payload():
                            name = part.get_param("name", header="content-disposition")
                            if name:
                                fields[name] = part.get_payload(decode=True)

                    if not header_code:
                        token = fields.get("token") or b""
                        if not self._check_code(token.decode("utf-8", "replace")):
                            return

                    payload = fields.get("database")
                    if not payload:
                        self.send_error(400, "Missing database file")
                        return
                    if not is_sqlite(payload):
                        logger.warning("SyncServer: uploaded file is not a SQLite database")
                        self.send_error(400, "Uploaded file is not a SQLite database")
                        return

                    if on_status_change:
                        on_status_change(_("Получена объединённая база, заменяю…"))

                    # Отвечаем «готово» только после настоящей замены базы
                    accept_database(payload)

                    self.send_response(200)
                    self.send_header("Content-type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"OK")

                    if on_status_change:
                        on_status_change(sync_success_message())

                except Exception as e:
                    # Подробности — в журнал; клиенту ничего полезного для атакующего
                    logger.error(f"Error handling sync request: {e}", exc_info=True)
                    self.send_error(500, "Internal server error")

        return Handler


class SyncServer(object):
    """HTTP-сервер синхронизации (работает на планшете в отдельном потоке)."""

    def __init__(
        self,
        db_path: str,
        auth_token: str,
        port: int = DEFAULT_PORT,
        on_status_change=None,
        host: str = DEFAULT_BIND_HOST,
        accept_database=None,
    ):
        self.db_path = db_path
        self.auth_token = auth_token
        self.port = port
        self.host = host
        self.on_status_change = on_status_change
        self.accept_database = accept_database
        self.httpd = None
        self._serving = False
        self._stopped = False
        import threading

        self._lock = threading.Lock()

    def bind(self, busy_wait: float = 1.5) -> None:
        """Занять порт. Занят — SyncServerBusyError «синхронизация уже запущена».

        Только что закрытое окно освобождает порт с задержкой до полсекунды,
        поэтому занятый порт перепроверяем ещё busy_wait секунд.
        """
        import errno
        import time
        from http.server import HTTPServer

        handler_cls = SyncHTTPHandler.create_handler(
            self.db_path, self.auth_token, self.on_status_change, self.accept_database
        )
        deadline = time.monotonic() + busy_wait
        while True:
            try:
                self.httpd = HTTPServer((self.host, self.port), handler_cls)
                break
            except OSError as e:
                if e.errno != errno.EADDRINUSE:
                    raise
                if time.monotonic() >= deadline:
                    raise SyncServerBusyError(
                        e.errno,
                        _(
                            "Синхронизация уже запущена: порт {port} занят. Закройте другое "
                            "окно синхронизации и попробуйте снова.",
                            port=self.port,
                        ),
                    ) from e
                time.sleep(0.2)
        self.port = self.httpd.server_address[1]
        if self.host == ALL_INTERFACES_HOST:
            # Всем интерфейсам — значит, всем устройствам сети; защита — код
            logger.warning(
                "Sync HTTP server listens on %s:%d — reachable from the whole "
                "network, protected only by the token",
                self.host,
                self.port,
            )
        else:
            logger.info(
                "Sync HTTP server listening on %s:%d (this machine only)", self.host, self.port
            )

    def start(self):
        """Обслуживать запросы до stop() (блокирует поток)."""
        with self._lock:
            if self._stopped:
                return
            if self.httpd is None:
                self.bind(busy_wait=0)
            httpd = self.httpd
            self._serving = True
        httpd.serve_forever()

    def stop(self, wait: bool = True):
        """Остановить сервер. wait=False — не ждать в вызывающем потоке
        (окно Qt не должно зависнуть, пока обработчик ждёт главный поток)."""
        with self._lock:
            self._stopped = True
            httpd, self.httpd = self.httpd, None
            serving = self._serving
        if httpd is None:
            return
        logger.info("Stopping sync HTTP server...")

        def _shutdown():
            # shutdown() без запущенного serve_forever() ждал бы вечно
            if serving:
                httpd.shutdown()
            httpd.server_close()

        if wait:
            _shutdown()
        else:
            import threading

            threading.Thread(target=_shutdown, daemon=True).start()


# ---------------------------------------------------------------------------
# Клиент (ПК): забрать базу планшета, объединить у себя, отправить обратно
# ---------------------------------------------------------------------------


class SyncClientError(Exception):
    """Понятная пользователю ошибка синхронизации."""


class SyncPushError(SyncClientError):
    """База на ПК уже объединена, но планшет её не получил."""


def parse_server_address(address: str):
    """'192.168.1.5' или '192.168.1.5:8765' → (host, port)."""
    address = address.strip()
    for prefix in ("http://", "https://"):
        if address.startswith(prefix):
            address = address[len(prefix) :]
    address = address.split("/", 1)[0]
    if not address:
        raise SyncClientError(tr("Введите адрес планшета"))
    host, _sep, port = address.partition(":")
    if not port:
        return host, DEFAULT_PORT
    if not port.isdigit():
        raise SyncClientError(tr("Неверный порт: {port}", port=port))
    return host, int(port)


def _http_error_message(e) -> str:
    messages = {
        401: _("Неверный код. Проверьте код в окне синхронизации на планшете."),
        429: _(
            "Слишком много неверных кодов. Закройте окно синхронизации на планшете "
            "и откройте заново."
        ),
        413: _("База слишком большая для синхронизации."),
    }
    return messages.get(e.code, _("Планшет ответил ошибкой {code}", code=e.code))


def _connect_error_message(host, port) -> str:
    return _(
        "Не удалось подключиться к планшету {host}:{port}. Проверьте: ПК и планшет в одной "
        "сети Wi-Fi, адрес совпадает с окном синхронизации на планшете, окно открыто.",
        host=host,
        port=port,
    )


def _open_url(request, timeout):
    """Без системного прокси: планшет — в локальной сети."""
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(request, timeout=timeout)


def download_database(address: str, code: str, timeout: float = 60.0) -> bytes:
    """Забирает базу с планшета."""
    import urllib.error
    import urllib.request

    host, port = parse_server_address(address)
    request = urllib.request.Request(
        f"http://{host}:{port}/db", headers={"X-Sync-Code": normalize_sync_code(code)}
    )
    try:
        with _open_url(request, timeout) as response:
            data = response.read(MAX_UPLOAD_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise SyncClientError(_http_error_message(e)) from e
    except (urllib.error.URLError, OSError) as e:
        raise SyncClientError(_connect_error_message(host, port)) from e
    if len(data) > MAX_UPLOAD_BYTES:
        raise SyncClientError(_("База слишком большая для синхронизации."))
    if not is_sqlite(data):
        raise SyncClientError(_("Планшет прислал не базу данных"))
    return data


def upload_database(address: str, code: str, db_path: str, timeout: float = 60.0) -> None:
    """Отправляет базу на планшет (тот заменяет ею свою)."""
    import urllib.error
    import urllib.request

    host, port = parse_server_address(address)
    db_bytes = read_database_bytes(db_path)

    boundary = "----NHJSSync" + secrets.token_hex(12)
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="token"\r\n\r\n',
            normalize_sync_code(code).encode(),
            b"\r\n",
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="database"; filename="scheduler.db"\r\n',
            b"Content-Type: application/x-sqlite3\r\n\r\n",
            db_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    request = urllib.request.Request(
        f"http://{host}:{port}/sync",
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "X-Sync-Code": normalize_sync_code(code),
        },
    )
    try:
        with _open_url(request, timeout) as response:
            response.read()
    except urllib.error.HTTPError as e:
        raise SyncClientError(_http_error_message(e)) from e
    except (urllib.error.URLError, OSError) as e:
        raise SyncClientError(_connect_error_message(host, port)) from e


def sync_with_tablet(address: str, code: str, db_path: str, timeout: float = 60.0) -> str:
    """ПК: забрать базу планшета, объединить с базой ПК, отправить результат обратно.

    Правила слияния прежние: база ПК — цель, база планшета — источник.
    Возвращает путь копии базы ПК до слияния. SyncPushError — ПК уже
    объединён, а планшет базу не получил (повтор безопасен).
    """
    tablet_bytes = download_database(address, code, timeout=timeout)

    backup_path = backup_database(db_path)
    fd, tmp_path = tempfile.mkstemp(suffix=".db")
    try:
        with os.fdopen(fd, "wb") as tmp:
            tmp.write(tablet_bytes)
        if not DatabaseMerger(target_db_path=db_path, source_db_path=tmp_path).merge():
            raise SyncClientError(_("Не удалось объединить базы. База на ПК не изменилась."))
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    try:
        # Планшет отвечает после замены базы (до минуты) — ждём дольше
        upload_database(address, code, db_path, timeout=timeout + 30)
    except SyncClientError as e:
        raise SyncPushError(
            _(
                "База на ПК объединена, но планшет её не получил: {e}\n"
                "Повторите синхронизацию — это безопасно.",
                e=e,
            )
        ) from e
    return backup_path


def replace_database(db_path: str, new_db: bytes, keep_settings=("sync_last_address",)) -> str:
    """Заменяет локальную базу присланной; старую сохраняет рядом. Возвращает путь бэкапа.

    Настройки из keep_settings (своё для этого устройства) переносятся в новую базу.
    Присланное сперва проверяется (SQLite, quick_check) — битым файлом базу не заменяем.
    """
    tmp_path = db_path + ".sync-new"
    with open(tmp_path, "wb") as f:
        f.write(new_db)
    try:
        conn = sqlite3.connect(tmp_path)
        try:
            ok = conn.execute("PRAGMA quick_check").fetchone()
        finally:
            conn.close()
        if not ok or ok[0] != "ok":
            raise ValueError("received database failed quick_check")
    except (sqlite3.DatabaseError, ValueError):
        os.remove(tmp_path)
        raise

    kept = {}
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        try:
            for key in keep_settings:
                row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
                if row:
                    kept[key] = row[0]
        except sqlite3.DatabaseError:
            pass
        finally:
            conn.close()

    backup_path = backup_database(db_path)
    if kept:
        conn = sqlite3.connect(tmp_path)
        try:
            for key, value in kept.items():
                conn.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
                )
            conn.commit()
        finally:
            conn.close()
    os.replace(tmp_path, db_path)
    return backup_path
