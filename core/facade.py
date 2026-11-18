"""
ApplicationFacade - Desktop facade for PySide6 UI.

This module provides a facade for the desktop application that inherits
from BaseApplicationFacade and adds module support.
See spec://core/facade for specification.
"""

from core.base_facade import BaseApplicationFacade
from core.services import ParticipantService, ScheduleService
from core.error_service import ErrorService
from core.events import EventBus
from modules.registry import ModuleRegistry
from modules.announcement import AnnouncementModule


class ApplicationFacade(BaseApplicationFacade):
    """
    Desktop facade providing a unified interface for the PySide6 UI layer.

    Inherits from BaseApplicationFacade and adds:
    - Module registry support for extensibility
    - Direct exception propagation (no try/except wrapping)

    Exceptions are propagated to the UI layer for display in QMessageBox.
    """

    def __init__(
        self,
        participant_service: ParticipantService,
        schedule_service: ScheduleService,
        error_service: ErrorService,
        event_bus: EventBus,
    ):
        """
        Initialize the desktop facade with services and module registry.

        Args:
            participant_service: Service for participant management
            schedule_service: Service for schedule management
            error_service: Service for error handling
            event_bus: Event bus for publishing/subscribing to events
        """
        super().__init__(participant_service, schedule_service, error_service, event_bus)

        # Initialize module registry for extensibility
        self.registry = ModuleRegistry()
        self.registry.register(AnnouncementModule())

    def run_module_migrations(self, session) -> None:
        """
        Run migrations for all registered modules.

        Args:
            session: Database session for running migrations
        """
        self.registry.migrate_all(session)
