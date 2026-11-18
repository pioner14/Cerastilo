"""Синхронизация карточек участников: побеждает более свежая правка (updated_at)."""

from datetime import date, datetime

from sqlalchemy import select

from core.database import DatabaseManager
from core.models import Participant, participant_qualifications
from core.sync_service import DatabaseMerger


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


def _qualifications(path, participant_name):
    db = DatabaseManager(path)
    with db.get_session() as s:
        p = s.query(Participant).filter_by(name=participant_name).one()
        names = set(
            s.execute(
                select(participant_qualifications.c.qualification_name).where(
                    participant_qualifications.c.participant_id == p.id
                )
            )
            .scalars()
            .all()
        )
    db.close()
    return names


def test_older_tablet_card_does_not_clear_newer_pc_vacation(tmp_path):
    pc = str(tmp_path / "pc.db")
    tablet = str(tmp_path / "tablet.db")

    later = datetime(2027, 1, 20, 12, 0)
    earlier = datetime(2027, 1, 10, 12, 0)

    _make_participant(
        pc,
        "Иванов",
        later,
        unavailable_from=date(2027, 2, 1),
        unavailable_to=date(2027, 2, 7),
    )
    _make_participant(
        tablet,
        "Иванов",
        earlier,
        unavailable_from=None,
        unavailable_to=None,
    )

    assert DatabaseMerger(pc, tablet).merge()

    db = DatabaseManager(pc)
    with db.get_session() as s:
        p = s.query(Participant).filter_by(name="Иванов").one()
        assert p.unavailable_from == date(2027, 2, 1)
        assert p.unavailable_to == date(2027, 2, 7)
    db.close()


def test_newer_tablet_service_status_applies_to_pc(tmp_path):
    pc = str(tmp_path / "pc.db")
    tablet = str(tmp_path / "tablet.db")

    _make_participant(
        pc,
        "Петров",
        datetime(2027, 1, 10, 12, 0),
        service_type="publisher",
    )
    _make_participant(
        tablet,
        "Петров",
        datetime(2027, 1, 20, 12, 0),
        service_type="ministerial_servant",
    )

    assert DatabaseMerger(pc, tablet).merge()

    db = DatabaseManager(pc)
    with db.get_session() as s:
        p = s.query(Participant).filter_by(name="Петров").one()
        assert p.service_type == "ministerial_servant"
    db.close()


def test_qualification_removed_on_newer_pc_is_not_restored_by_tablet(tmp_path):
    pc = str(tmp_path / "pc.db")
    tablet = str(tmp_path / "tablet.db")

    _make_participant(
        pc,
        "Иванов",
        datetime(2027, 1, 20, 12, 0),
        quals=("Чтение",),
    )
    _make_participant(
        tablet,
        "Иванов",
        datetime(2027, 1, 10, 12, 0),
        quals=("Чтение", "Микрофон"),
    )

    assert DatabaseMerger(pc, tablet).merge()

    assert _qualifications(pc, "Иванов") == {"Чтение"}


def test_qualification_removed_on_newer_tablet_is_removed_on_pc(tmp_path):
    pc = str(tmp_path / "pc.db")
    tablet = str(tmp_path / "tablet.db")

    _make_participant(
        pc,
        "Иванов",
        datetime(2027, 1, 10, 12, 0),
        quals=("Чтение", "Микрофон"),
    )
    _make_participant(
        tablet,
        "Иванов",
        datetime(2027, 1, 20, 12, 0),
        quals=("Чтение",),
    )

    assert DatabaseMerger(pc, tablet).merge()

    assert _qualifications(pc, "Иванов") == {"Чтение"}


def test_qualification_edit_alone_marks_participant_changed(tmp_path):
    from core.repositories.participant_repository import ParticipantRepository

    path = str(tmp_path / "pc.db")
    old = datetime(2020, 1, 1)
    _make_participant(path, "Иванов", old, quals=("Чтение",))
    db = DatabaseManager(path)
    with db.get_session() as s:
        pid = s.query(Participant).filter_by(name="Иванов").one().id
    ParticipantRepository(db).set_qualifications(pid, ["Чтение", "Молитва"])
    with db.get_session() as s:
        assert s.get(Participant, pid).updated_at > old
    db.close()
