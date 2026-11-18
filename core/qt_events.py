"""PySide6 реализация EventBus для десктопной версии."""

from typing import Callable, Dict, List, Any
from enum import Enum
from PySide6.QtCore import QObject, Signal

from .events_base import Event as BaseEvent
from .events import Event  # noqa: F401  (единое определение)


class QtEventBus(QObject):
    """
    Thread-safe Event Bus using Qt Signals.
    Ensures that handlers are executed in the thread where EventBus was created (Main Thread).

    Реализует IEventBus интерфейс (без наследования из-за конфликта метаклассов).
    """

    # Signal to dispatch events across threads: (event_name, data)
    _dispatch_signal = Signal(str, object)

    def __init__(self):
        super().__init__()
        self._handlers: Dict[str, List[Callable]] = {}
        # Connect signal to the internal handler (runs in Main Thread via QueuedConnection)
        self._dispatch_signal.connect(self._on_dispatch)

    def subscribe(self, event_name: "str | Enum", handler: Callable[[BaseEvent], None]) -> None:
        """Подписаться на событие (имя или Enum — как и в emit)."""
        if isinstance(event_name, Enum):
            event_name = event_name.value
        if event_name not in self._handlers:
            self._handlers[event_name] = []
        self._handlers[event_name].append(handler)

    def unsubscribe(self, event_name: "str | Enum", handler: Callable[[BaseEvent], None]) -> None:
        """Отписаться от события."""
        if isinstance(event_name, Enum):
            event_name = event_name.value
        if event_name in self._handlers:
            try:
                self._handlers[event_name].remove(handler)
            except ValueError:
                pass

    def emit(self, event_or_name, *args, **kwargs) -> None:
        """
        Отправить событие. Безопасно вызывать из любого потока.
        Обработка произойдёт в главном потоке.

        Поддерживает два режима:
        1. Новый API: emit("event_name", data)
        2. Старый API: emit(Event.XXX, p_id=123, ...)
        """
        # Определяем имя события
        # Поддерживаем любой Enum (Event из этого модуля или из core.events)
        if isinstance(event_or_name, Enum):
            event_name = event_or_name.value
            # Старый API: данные передаются как kwargs или args
            data = {"args": args, "kwargs": kwargs} if args or kwargs else None
        else:
            event_name = event_or_name
            data = args[0] if args else kwargs or None

        self._dispatch_signal.emit(event_name, data)

    def _on_dispatch(self, event_name: str, data: Any):
        """Внутренний обработчик диспетчеризации (выполняется в главном потоке)."""
        event = BaseEvent(name=event_name, data=data)
        for handler in self._handlers.get(event_name, []):
            try:
                handler(event)
            except Exception as e:
                import logging

                logging.error(f"Error in event handler for {event_name}: {e}")

    # Обратная совместимость со старым API
    def subscribe_event(self, event: Event, handler: Callable) -> None:
        """Устаревший метод для обратной совместимости."""
        self.subscribe(event.value, handler)

    def emit_event(self, event: Event, *args, **kwargs) -> None:
        """Устаревший метод для обратной совместимости."""
        data = {"args": args, "kwargs": kwargs} if args or kwargs else None
        self.emit(event.value, data)


# Глобальный экземпляр для обратной совместимости
_bus: QtEventBus = None


def get_qt_event_bus() -> QtEventBus:
    """Получить или создать QtEventBus."""
    global _bus
    if _bus is None:
        _bus = QtEventBus()
    return _bus
