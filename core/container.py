"""
Simple Dependency Injection Container.
Centralizes the assembly of application components without external libraries.

Reference: spec://architecture/di_container
"""

from core.database import DatabaseManager
from core.validation_service import ValidationService
from core.events import EventBus, set_event_bus
from core.settings import Settings
from core.services import ParticipantService, ScheduleService
from core.error_service import ErrorService
from core.facade import ApplicationFacade
from core.unit_of_work import UnitOfWorkManager

# Repositories
from core.repositories.week_repository import WeekRepository
from core.repositories.assignment_repository import AssignmentRepository
from core.repositories.participant_repository import ParticipantRepository

# Domain Services
from core.schedule_service import ScheduleDomainService


def _create_event_bus():
    """Создаёт подходящий EventBus для текущей платформы."""
    try:
        # Пробуем использовать QtEventBus для десктопа (thread-safe)
        from core.qt_events import QtEventBus

        return QtEventBus()
    except ImportError:
        # Fallback на SimpleEventBus (без PySide6)
        return EventBus()


class Container:
    """
    Dependency Injection Container for application components.

    This container follows the Composition Root pattern, assembling
    all dependencies in a single location. It provides:
    - Singleton lifecycle for infrastructure components
    - Lazy initialization for optional dependencies
    - Clear dependency graph for maintainability

    Reference: spec://architecture/di_container
    """

    def __init__(self):
        # Configuration
        self.settings = Settings.load()

        # Infrastructure - используем QtEventBus если доступен
        self.event_bus = _create_event_bus()
        set_event_bus(self.event_bus)

        # Database Layer
        self.db_manager = DatabaseManager(db_path=self.settings.db_path)

        # Unit of Work Manager for transactions
        self.uow_manager = UnitOfWorkManager(self.db_manager)

        # Repositories (Data Access Layer)
        self.week_repo = WeekRepository(self.db_manager)
        self.assignment_repo = AssignmentRepository(self.db_manager)
        self.participant_repo = ParticipantRepository(self.db_manager)

        # Domain Services (Business Logic Layer)
        self.schedule_domain_service = ScheduleDomainService(
            db_manager=self.db_manager,
            event_bus=self.event_bus,
            week_repo=self.week_repo,
            assignment_repo=self.assignment_repo,
            participant_repo=self.participant_repo,
        )

        # Service Layer (Application Services)
        self.validation_service = ValidationService()
        self.participant_service = ParticipantService(self.db_manager, self.event_bus)
        self.schedule_service = ScheduleService(
            db=self.db_manager,
            event_bus=self.event_bus,
            schedule_domain_service=self.schedule_domain_service,
        )
        self.error_service = ErrorService(self.event_bus)

        # Application Layer (Facade)
        self.facade = ApplicationFacade(
            self.participant_service, self.schedule_service, self.error_service, self.event_bus
        )
