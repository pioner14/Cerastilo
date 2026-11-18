"""Абстрактный интерфейс EventBus для кроссплатформенности."""

from abc import ABC, abstractmethod
from typing import Callable, Any
from dataclasses import dataclass


@dataclass
class Event:
    """Базовый класс события."""

    name: str
    data: Any = None


class IEventBus(ABC):
    """Абстрактный интерфейс шины событий."""

    @abstractmethod
    def subscribe(self, event_name: str, handler: Callable[[Event], None]) -> None:
        """Подписаться на событие."""

    @abstractmethod
    def unsubscribe(self, event_name: str, handler: Callable[[Event], None]) -> None:
        """Отписаться от события."""

    @abstractmethod
    def emit(self, event_name: str, data: Any = None) -> None:
        """Отправить событие."""


class SimpleEventBus(IEventBus):
    """Простая реализация EventBus без внешних зависимостей."""

    def __init__(self):
        self._handlers: dict[str, list[Callable]] = {}

    def subscribe(self, event_name: str, handler: Callable[[Event], None]) -> None:
        if event_name not in self._handlers:
            self._handlers[event_name] = []
        self._handlers[event_name].append(handler)

    def unsubscribe(self, event_name: str, handler: Callable[[Event], None]) -> None:
        if event_name in self._handlers:
            try:
                self._handlers[event_name].remove(handler)
            except ValueError:
                pass  # Handler not in list

    def emit(self, event_name: str, data: Any = None) -> None:
        """Отправить событие всем подписчикам."""
        event = Event(name=event_name, data=data)
        for handler in self._handlers.get(event_name, []):
            try:
                handler(event)
            except Exception as e:
                import logging

                logging.error(f"Error in event handler for {event_name}: {e}")
