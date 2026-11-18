"""Синхронизация не возвращает удалённых участников и переносит удаление."""

from datetime import datetime

from sqlalchemy import select

from core.database import DatabaseManager
from core.models import Participant, participant_qualifications
from core.sync_service import DatabaseMerger
from core import participant_tombstones


def _make_participant(path, name, updated_at, quals=(), **fields):
    db = DatabaseManager(path)
    with db.get_session() as s:
        p = Participant(name=name, updated_at=updated_at, **fields)
        s.add(p)
        s.flush()
        for qual in quals:
            s.execute(
                participant_qualifications.insert().values(
                    participant_id=p.id,
                    qualification_name=qual,
                )
            )
        s.commit()
    db.close()


def _record_tombstone(path, name, when):
    db = DatabaseManager(path)
    with db.get_session() as s:
        participant_tombstones.record(s, name, when)
        s.commit()
    db.close()


def _load_tombstones(path):
    db = DatabaseManager(path)
    with db.get_session() as s:
        tombstones = participant_tombstones.load(s)
    db.close()
    return tombstones


def _count_participants(path, name):
    db = DatabaseManager(path)
    with db.get_session() as s:
        count = s.query(Participant).filter_by(name=name).count()
    db.close()
    return count


def test_deleted_on_pc_is_not_restored_from_tablet(tmp_path):
    pc = str(tmp_path / "pc.db")
    tablet = str(tmp_path / "tablet.db")

    _record_tombstone(pc, "Alice", datetime(2027, 1, 15))
    _make_participant(tablet, "Alice", datetime(2027, 1, 10))

    assert DatabaseMerger(pc, tablet).merge()

    assert _count_participants(pc, "Alice") == 0
    assert _load_tombstones(pc)["Alice"] == datetime(2027, 1, 15)


def test_deleted_on_tablet_removes_pc_participant(tmp_path):
    pc = str(tmp_path / "pc.db")
    tablet = str(tmp_path / "tablet.db")

    _make_participant(pc, "Bob", datetime(2027, 1, 10))
    _record_tombstone(tablet, "Bob", datetime(2027, 1, 15))

    assert DatabaseMerger(pc, tablet).merge()

    assert _count_participants(pc, "Bob") == 0


def test_pc_participant_edited_after_tablet_deletion_survives(tmp_path):
    pc = str(tmp_path / "pc.db")
    tablet = str(tmp_path / "tablet.db")

    _make_participant(pc, "Carol", datetime(2027, 1, 20))
    _record_tombstone(tablet, "Carol", datetime(2027, 1, 15))

    assert DatabaseMerger(pc, tablet).merge()

    assert _count_participants(pc, "Carol") == 1


def test_tablet_recreated_participant_after_pc_deletion_is_added(tmp_path):
    pc = str(tmp_path / "pc.db")
    tablet = str(tmp_path / "tablet.db")

    _record_tombstone(pc, "Dave", datetime(2027, 1, 15))
    _make_participant(
        tablet,
        "Dave",
        datetime(2027, 1, 20),
        created_at=datetime(2027, 1, 20),
    )

    assert DatabaseMerger(pc, tablet).merge()

    assert _count_participants(pc, "Dave") == 1


def test_deleting_participant_records_tombstone(tmp_path):
    from core.events import EventBus
    from core.services import ParticipantService

    pc = str(tmp_path / "pc.db")
    _make_participant(pc, "Eve", datetime(2027, 1, 10))
    db = DatabaseManager(pc)
    with db.get_session() as s:
        p_id = s.query(Participant).filter_by(name="Eve").one().id
    assert ParticipantService(db, EventBus()).delete_participant(p_id)
    db.close()

    assert "Eve" in _load_tombstones(pc)
    assert _count_participants(pc, "Eve") == 0
