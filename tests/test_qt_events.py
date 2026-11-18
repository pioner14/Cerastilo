"""QtEventBus: подписка по Enum доходит до обработчика, как и по имени."""

from PySide6.QtCore import QCoreApplication

from core.events import Event
from core.qt_events import QtEventBus


def _process_events():
    QCoreApplication.processEvents()


def test_subscribe_by_enum_receives_emit_by_enum(qapp):
    bus = QtEventBus()
    received = []
    bus.subscribe(Event.ERROR_OCCURRED, received.append)

    bus.emit(Event.ERROR_OCCURRED, "сбой")
    _process_events()

    assert len(received) == 1
    assert received[0].name == Event.ERROR_OCCURRED.value


def test_unsubscribe_by_enum(qapp):
    bus = QtEventBus()
    received = []
    bus.subscribe(Event.ERROR_OCCURRED, received.append)
    bus.unsubscribe(Event.ERROR_OCCURRED, received.append)

    bus.emit(Event.ERROR_OCCURRED, "сбой")
    _process_events()

    assert received == []
