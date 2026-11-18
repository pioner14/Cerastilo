"""Синхронизация ПК ↔ планшет по Wi-Fi: сервер на планшете, ПК — клиент sync_with_tablet."""

import os
import socket
import sqlite3
import threading
import time

import pytest

from core.database import DatabaseManager
from core.sync_service import (
    DEFAULT_PORT,
    MAX_FAILED_ATTEMPTS,
    SyncClientError,
    SyncServer,
    generate_sync_code,
    parse_server_address,
    replace_database,
    sync_with_tablet,
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server(tmp_path):
    """Сервер синхронизации на «планшете» с базой из _tablet_db."""
    tablet_db = _tablet_db(tmp_path)
    code = generate_sync_code()
    port = _free_port()
    srv = SyncServer(tablet_db, code, port=port, host="127.0.0.1")
    srv.bind()
    thread = threading.Thread(target=srv.start, daemon=True)
    thread.start()
    yield {"address": f"127.0.0.1:{port}", "code": code, "tablet_db": tablet_db}
    srv.stop()


def _pc_db(tmp_path):
    path = str(tmp_path / "pc.db")
    DatabaseManager(path).close()
    return path


def _tablet_db(tmp_path, cong_name="С планшета"):
    path = str(tmp_path / "tablet.db")
    db = DatabaseManager(path)
    db.save_setting("cong_name", cong_name)
    db.save_setting("sync_last_address", "192.168.1.5")
    db.close()
    return path


def _setting(path, key):
    conn = sqlite3.connect(path)
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def test_code_is_short_and_unambiguous():
    code = generate_sync_code()
    assert len(code) == 6
    assert not set(code) & set("01OI")


def test_parse_address_defaults_port():
    assert parse_server_address("192.168.1.5") == ("192.168.1.5", DEFAULT_PORT)
    assert parse_server_address(" http://192.168.1.5:9000/sync ") == ("192.168.1.5", 9000)


def test_sync_merges_tablet_into_pc_and_sends_back(server, tmp_path):
    pc = _pc_db(tmp_path)

    sync_with_tablet(server["address"], server["code"].lower(), pc)

    assert _setting(pc, "cong_name") == "С планшета"
    # Своё для устройства на ПК не переносится
    assert _setting(pc, "sync_last_address") is None
    # Планшет получил объединённую базу, своё для устройства сохранил
    assert _setting(server["tablet_db"], "cong_name") == "С планшета"
    assert _setting(server["tablet_db"], "sync_last_address") == "192.168.1.5"


def test_wrong_code_is_rejected_then_locked(server, tmp_path):
    pc = _pc_db(tmp_path)

    with pytest.raises(SyncClientError, match="Неверный код"):
        sync_with_tablet(server["address"], "WRONG1", pc)
    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        with pytest.raises(SyncClientError):
            sync_with_tablet(server["address"], "WRONG1", pc)
    with pytest.raises(SyncClientError, match="Слишком много"):
        sync_with_tablet(server["address"], server["code"], pc)


def test_unreachable_server_gives_clear_error(tmp_path):
    pc = _pc_db(tmp_path)
    with pytest.raises(SyncClientError, match="Не удалось подключиться"):
        sync_with_tablet(f"127.0.0.1:{_free_port()}", "ABC234", pc, timeout=2)


def test_second_server_on_same_port_says_already_running(server):
    """Порт один и тот же: второе окно — «уже запущена», а не тихий перескок на 8766."""
    from core.sync_service import SyncServerBusyError

    port = int(server["address"].rsplit(":", 1)[1])
    second = SyncServer(server["tablet_db"], "ABC234", port=port, host="127.0.0.1")
    with pytest.raises(SyncServerBusyError) as exc:
        second.bind(busy_wait=0)
    assert "уже запущена" in exc.value.strerror
    assert second.httpd is None


def test_get_db_without_code_is_rejected(server):
    import urllib.error
    import urllib.request

    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(f"http://{server['address']}/db", timeout=5)
    assert exc.value.code == 401


def test_push_failure_leaves_pc_merged_with_backup(tmp_path):
    """Планшет не принял базу: ПК уже объединён, копия до слияния есть, планшет не тронут."""
    from core.sync_service import SyncPushError

    tablet = _tablet_db(tmp_path)
    before = open(tablet, "rb").read()

    def refuse(_data):
        raise RuntimeError("disk full")

    port = _free_port()
    code = generate_sync_code()
    srv = SyncServer(tablet, code, port=port, host="127.0.0.1", accept_database=refuse)
    srv.bind()
    threading.Thread(target=srv.start, daemon=True).start()
    pc = _pc_db(tmp_path)
    try:
        with pytest.raises(SyncPushError, match="Повторите синхронизацию"):
            sync_with_tablet(f"127.0.0.1:{port}", code, pc)
    finally:
        srv.stop()

    assert _setting(pc, "cong_name") == "С планшета"
    backups = [p for p in os.listdir(tmp_path) if p.startswith("pc.db.pre-sync-")]
    assert backups and _setting(str(tmp_path / backups[0]), "cong_name") != "С планшета"
    assert open(tablet, "rb").read() == before


def test_replace_database_rejects_corrupt_file(tmp_path):
    """Битая присланная база не заменяет рабочую."""
    local = _tablet_db(tmp_path)
    before = open(local, "rb").read()
    corrupt = b"SQLite format 3\x00" + b"\xff" * 4000
    with pytest.raises(sqlite3.DatabaseError):
        replace_database(local, corrupt)
    assert open(local, "rb").read() == before
    assert not os.path.exists(local + ".sync-new")


def test_replace_database_keeps_device_settings(tmp_path):
    local = _tablet_db(tmp_path)
    incoming_path = str(tmp_path / "incoming.db")
    db = DatabaseManager(incoming_path)
    db.save_setting("cong_name", "С ПК")
    db.close()

    backup = replace_database(local, open(incoming_path, "rb").read())

    assert _setting(local, "cong_name") == "С ПК"
    assert _setting(local, "sync_last_address") == "192.168.1.5"
    assert backup and _setting(backup, "cong_name") == "С планшета"


# --- Слияние назначений по времени изменения ---------------------------------

from datetime import date, datetime, timedelta  # noqa: E402

from core.models import Assignment, Participant, Week  # noqa: E402
from core.sync_service import DatabaseMerger  # noqa: E402


def _db_with_assignment(path, who, when, status="assigned"):
    """База с неделей, двумя участниками и одним назначением (на кого и когда менялось)."""
    db = DatabaseManager(path)
    with db.get_session() as s:
        ids = {}
        for name in ("Иванов", "Петров"):
            p = Participant(name=name)
            s.add(p)
            s.flush()
            ids[name] = p.id
        w = Week(week_title="1–7 февраля", start_date=date(2027, 2, 1))
        s.add(w)
        s.flush()
        s.add(
            Assignment(
                week_id=w.id,
                assignment_text="Чтение Библии",
                assignment_number="3",
                section="treasures",
                section_position="3",
                participant_id=ids[who] if who else None,
                status=status,
                updated_at=when,
            )
        )
        s.commit()
    db.close()


def _assigned_name(path):
    db = DatabaseManager(path)
    with db.get_session() as s:
        a = s.query(Assignment).one()
        name = s.get(Participant, a.participant_id).name if a.participant_id else None
    db.close()
    return name


def test_newer_change_on_pc_is_not_overwritten(tmp_path):
    now = datetime(2027, 1, 20, 12, 0)
    pc, tablet = str(tmp_path / "pc.db"), str(tmp_path / "tablet.db")
    _db_with_assignment(pc, "Петров", now)
    _db_with_assignment(tablet, "Иванов", now - timedelta(days=1))

    assert DatabaseMerger(pc, tablet).merge()

    assert _assigned_name(pc) == "Петров"


def test_newer_change_on_tablet_wins(tmp_path):
    now = datetime(2027, 1, 20, 12, 0)
    pc, tablet = str(tmp_path / "pc.db"), str(tmp_path / "tablet.db")
    _db_with_assignment(pc, "Петров", now - timedelta(days=1))
    _db_with_assignment(tablet, "Иванов", now)

    assert DatabaseMerger(pc, tablet).merge()

    assert _assigned_name(pc) == "Иванов"


def test_newer_clear_on_tablet_clears_pc(tmp_path):
    now = datetime(2027, 1, 20, 12, 0)
    pc, tablet = str(tmp_path / "pc.db"), str(tmp_path / "tablet.db")
    _db_with_assignment(pc, "Петров", now - timedelta(days=1))
    _db_with_assignment(tablet, None, now, status="empty")

    assert DatabaseMerger(pc, tablet).merge()

    assert _assigned_name(pc) is None


def test_assignment_change_sets_updated_at(tmp_path):
    path = str(tmp_path / "a.db")
    _db_with_assignment(path, "Иванов", None)
    db = DatabaseManager(path)
    with db.get_session() as s:
        a = s.query(Assignment).one()
        assert a.updated_at is not None  # проставлено при создании
        before = a.updated_at
        a.participant_id = s.query(Participant).filter_by(name="Петров").one().id
        s.commit()
        assert s.query(Assignment).one().updated_at >= before
    db.close()


def test_old_database_without_column_gets_it(tmp_path):
    import sqlite3 as sq

    path = str(tmp_path / "old.db")
    DatabaseManager(path).close()
    conn = sq.connect(path)
    conn.execute("ALTER TABLE assignments DROP COLUMN updated_at")
    conn.commit()
    conn.close()

    DatabaseManager(path).close()

    conn = sq.connect(path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(assignments)")}
    conn.close()
    assert "updated_at" in cols


def _add_rows(path, *rows_factory):
    db = DatabaseManager(path)
    with db.get_session() as s:
        pid = s.query(Participant).filter_by(name="Иванов").one().id
        wid = s.query(Week).one().id
        for make in rows_factory:
            s.add(make(pid, wid))
        s.commit()
    db.close()


def _response(path):
    from core.models import NotificationResponse

    db = DatabaseManager(path)
    with db.get_session() as s:
        row = s.query(NotificationResponse).one_or_none()
        result = row.response if row else None
    db.close()
    return result


def test_notification_response_from_tablet_reaches_pc(tmp_path):
    from core.models import NotificationHistory, NotificationResponse

    now = datetime(2027, 1, 20, 12, 0)
    pc, tablet = str(tmp_path / "pc.db"), str(tmp_path / "tablet.db")
    _db_with_assignment(pc, "Иванов", now)
    _db_with_assignment(tablet, "Иванов", now)
    sent = lambda pid, wid: NotificationHistory(
        participant_id=pid, week_id=wid, status="success", sent_at=now - timedelta(days=2)
    )
    _add_rows(pc, sent)
    _add_rows(
        tablet,
        lambda pid, wid: NotificationResponse(
            participant_id=pid,
            week_id=wid,
            response="confirmed",
            source="manual",
            responded_at=now - timedelta(days=1),
        ),
    )

    assert DatabaseMerger(pc, tablet).merge()

    assert _response(pc) == "confirmed"


def test_tablet_response_older_than_new_notification_is_dropped(tmp_path):
    """После отметки на планшете ПК отправил новое письмо — старый ответ не о нём."""
    from core.models import NotificationHistory, NotificationResponse

    now = datetime(2027, 1, 20, 12, 0)
    pc, tablet = str(tmp_path / "pc.db"), str(tmp_path / "tablet.db")
    _db_with_assignment(pc, "Иванов", now)
    _db_with_assignment(tablet, "Иванов", now)
    _add_rows(
        pc,
        lambda pid, wid: NotificationHistory(
            participant_id=pid, week_id=wid, status="success", sent_at=now
        ),
    )
    _add_rows(
        tablet,
        lambda pid, wid: NotificationResponse(
            participant_id=pid,
            week_id=wid,
            response="declined",
            source="manual",
            responded_at=now - timedelta(days=1),
        ),
    )

    assert DatabaseMerger(pc, tablet).merge()

    assert _response(pc) is None


# --- Контакты и недели-исключения участников -------------------------------

from core.models import ParticipantExcludedWeek  # noqa: E402


def test_new_tablet_participant_with_contacts_is_added_to_pc(tmp_path):
    pc, tablet = str(tmp_path / "pc.db"), str(tmp_path / "tablet.db")

    db = DatabaseManager(pc)
    db.close()

    db = DatabaseManager(tablet)
    with db.get_session() as s:
        s.add(
            Participant(
                name="Сидоров",
                email="sidorov@example.com",
                phone="+7 900 000-00-00",
            )
        )
        s.commit()
    db.close()

    assert DatabaseMerger(pc, tablet).merge()

    db = DatabaseManager(pc)
    with db.get_session() as s:
        p = s.query(Participant).filter_by(name="Сидоров").one()
        assert p.email == "sidorov@example.com"
        assert p.phone == "+7 900 000-00-00"
    db.close()


def test_tablet_email_overwrites_pc_but_empty_email_does_not_erase_pc(tmp_path):
    pc, tablet = str(tmp_path / "pc.db"), str(tmp_path / "tablet.db")
    db = DatabaseManager(pc)
    with db.get_session() as s:
        s.add(Participant(name="Иванов", email="pc@example.com"))
        s.commit()
    db.close()

    db = DatabaseManager(tablet)
    with db.get_session() as s:
        s.add(Participant(name="Иванов", email="tablet@example.com"))
        s.commit()
    db.close()

    assert DatabaseMerger(pc, tablet).merge()

    db = DatabaseManager(pc)
    with db.get_session() as s:
        assert s.query(Participant).filter_by(name="Иванов").one().email == "tablet@example.com"
    db.close()

    pc, tablet = str(tmp_path / "pc_empty.db"), str(tmp_path / "tablet_empty.db")
    db = DatabaseManager(pc)
    with db.get_session() as s:
        s.add(Participant(name="Иванов", email="pc@example.com"))
        s.commit()
    db.close()

    db = DatabaseManager(tablet)
    with db.get_session() as s:
        s.add(Participant(name="Иванов", email=""))
        s.commit()
    db.close()

    assert DatabaseMerger(pc, tablet).merge()

    db = DatabaseManager(pc)
    with db.get_session() as s:
        assert s.query(Participant).filter_by(name="Иванов").one().email == "pc@example.com"
    db.close()


def test_tablet_excluded_week_is_linked_to_pc_participant_and_not_duplicated(tmp_path):
    pc, tablet = str(tmp_path / "pc.db"), str(tmp_path / "tablet.db")

    db = DatabaseManager(pc)
    with db.get_session() as s:
        p = Participant(name="Иванов")
        s.add(p)
        s.commit()
        pc_participant_id = p.id
    db.close()

    db = DatabaseManager(tablet)
    with db.get_session() as s:
        s.add(Participant(name="Петров"))
        s.commit()
        p = Participant(name="Иванов")
        s.add(p)
        s.flush()
        tablet_participant_id = p.id
        s.add(
            ParticipantExcludedWeek(
                participant_id=tablet_participant_id,
                week_start=date(2027, 2, 1),
            )
        )
        s.commit()
    db.close()

    assert tablet_participant_id != pc_participant_id
    assert DatabaseMerger(pc, tablet).merge()

    db = DatabaseManager(pc)
    with db.get_session() as s:
        rows = s.query(ParticipantExcludedWeek).all()
        assert len(rows) == 1
        assert rows[0].participant_id == pc_participant_id
        assert rows[0].week_start == date(2027, 2, 1)
    db.close()

    assert DatabaseMerger(pc, tablet).merge()

    db = DatabaseManager(pc)
    with db.get_session() as s:
        assert s.query(ParticipantExcludedWeek).count() == 1
    db.close()
