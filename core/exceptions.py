class AppError(Exception):
    """Base class for application exceptions."""


class DataError(AppError):
    """Database or data integrity related error."""


class ParticipantNotFoundError(DataError):
    """Raised when a participant is not found."""


class DuplicateParticipantError(DataError):
    """Raised when adding a participant that already exists."""


class ScheduleError(AppError):
    """Scheduling or assignment related error."""


class ImportExportError(AppError):
    """Errors during import/export operations."""
