from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget
    from sqlalchemy.orm import Session

class BaseModule(ABC):
    """
    Базовый класс для всех модулей приложения.
    Обеспечивает единый интерфейс для UI, экспорта и миграций.
    """
    
    @property
    @abstractmethod
    def id(self) -> str:
        """Уникальный ID модуля, например 'announcements'. Используется в настройках."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Отображаемое имя, например '📢 Объявления'."""
    
    @abstractmethod
    def migrate(self, session: 'Session'):
        """
        Создать/обновить таблицы модуля в БД.
        Вызывается при старте приложения.
        """

    @abstractmethod
    def get_week_widget(self, week_id: int, facade) -> Optional['QWidget']:
        """
        Вернуть виджет для вставки в форму недели.
        facade передается для доступа к данным и методам сохранения.
        """

    @abstractmethod
    def get_export_content(self, week, session: 'Session') -> Optional[str]:
        """
        Вернуть текст для вставки в DOCX-экспорт.
        """
