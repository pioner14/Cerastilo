"""Фабрика EventBus и экспорт публичного API.

Этот модуль предоставляет унифицированный интерфейс для работы с событиями.
По умолчанию используется SimpleEventBus (без внешних зависимостей).
Для десктопной версии с PySide6 используйте set_event_bus(get_qt_event_bus()).

Обратная совместимость:
- EventBus - класс с API, совместимым со старым кодом
- Event - перечисление типов событий
- bus - глобальный экземпляр (устарело, используйте get_event_bus())
"""

from typing import Optional, Callable
from enum import Enum

from .events_base import IEventBus, SimpleEventBus, Event as BaseEvent

# Глобальный экземпляр
_event_bus: Optional[IEventBus] = None


class Event(Enum):
    """Перечисление типов событий (для обратной совместимости)."""

    # Data Changes
    ASSIGNMENT_CHANGED = "assignment_changed"
    PARTICIPANT_CHANGED = "participant_changed"
    SCHEDULE_IMPORTED = "schedule_imported"

    # UI State
    WEEK_SELECTED = "week_selected"

    # System
    SETTINGS_CHANGED = "settings_changed"
    ERROR_OCCURRED = "error_occurred"


class EventBus(SimpleEventBus):
    """
    EventBus с поддержкой старого API.

    Обеспечивает обратную совместимость с кодом, использующим:
    - emit(Event.XXX, *args, **kwargs)
    - subscribe(Event.XXX, handler)
    """

    def emit(self, event_or_name, *args, **kwargs) -> None:
        """
        Отправить событие.

        Поддерживает два режима:
        1. Новый API: emit("event_name", data)
        2. Старый API: emit(Event.XXX, p_id=123, ...)
        """
        # Определяем имя события
        if isinstance(event_or_name, Event):
            event_name = event_or_name.value
            # Старый API: данные передаются как kwargs или args
            data = {"args": args, "kwargs": kwargs} if args or kwargs else None
        else:
            event_name = event_or_name
            data = args[0] if args else kwargs or None

        super().emit(event_name, data)

    def subscribe(self, event_or_name, handler: Callable) -> None:
        """
        Подписаться на событие.

        Поддерживает два режима:
        1. Новый API: subscribe("event_name", handler)
        2. Старый API: subscribe(Event.XXX, handler)
        """
        if isinstance(event_or_name, Event):
            event_name = event_or_name.value
        else:
            event_name = event_or_name

        super().subscribe(event_name, handler)


def get_event_bus() -> IEventBus:
    """Получить глобальный экземпляр EventBus."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def set_event_bus(bus: IEventBus) -> None:
    """Установить глобальный экземпляр EventBus."""
    global _event_bus
    _event_bus = bus


def reset_event_bus() -> None:
    """Сбросить глобальный экземпляр EventBus (полезно для тестов)."""
    global _event_bus
    _event_bus = None


# Глобальный экземпляр для обратной совместимости
bus = None  # Инициализируется при первом использовании


def _get_bus():
    """Ленивая инициализация глобального bus."""
    global bus
    if bus is None:
        bus = EventBus()
    return bus


# Заменяем bus на property-like объект для ленивой инициализации
class _BusProxy:
    """Прокси для ленивой инициализации bus."""

    def __getattr__(self, name):
        return getattr(get_event_bus(), name)

    def __call__(self):
        return get_event_bus()


bus = _BusProxy()


# Экспорт для удобства
__all__ = [
    "IEventBus",
    "SimpleEventBus",
    "EventBus",
    "Event",
    "BaseEvent",
    "get_event_bus",
    "set_event_bus",
    "reset_event_bus",
    "bus",
]
