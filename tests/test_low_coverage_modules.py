"""Tests for low coverage modules: exceptions, migration, workers, error_service, events_base."""

import pytest
from unittest.mock import Mock, patch
import tempfile
import os
import sqlite3

# Import actual classes from the modules
from core.exceptions import (
    AppError,
    DataError,
    ParticipantNotFoundError,
    DuplicateParticipantError,
    ScheduleError,
    ImportExportError,
)
from core.error_service import ErrorService
from core.events_base import Event as BaseEvent, IEventBus, SimpleEventBus
from core.events import EventBus
from core.migration import _parse_legacy_date, migrate_participants
from core.workers import TaskWorker, WorkerFactory


class TestExceptions:
    """Tests for core/exceptions.py."""

    def test_app_error_basic(self):
        """Test basic AppError exception."""
        error = AppError("Test error message")
        assert str(error) == "Test error message"
        assert isinstance(error, Exception)

    def test_app_error_inheritance(self):
        """Test AppError is an Exception."""
        error = AppError("test")
        assert isinstance(error, Exception)

    def test_data_error(self):
        """Test DataError exception."""
        error = DataError("Database error")
        assert str(error) == "Database error"
        assert isinstance(error, AppError)

    def test_participant_not_found_error(self):
        """Test ParticipantNotFoundError exception."""
        error = ParticipantNotFoundError("Participant not found")
        assert str(error) == "Participant not found"
        assert isinstance(error, DataError)
        assert isinstance(error, AppError)

    def test_duplicate_participant_error(self):
        """Test DuplicateParticipantError exception."""
        error = DuplicateParticipantError("Participant already exists")
        assert str(error) == "Participant already exists"
        assert isinstance(error, DataError)
        assert isinstance(error, AppError)

    def test_schedule_error(self):
        """Test ScheduleError exception."""
        error = ScheduleError("Schedule conflict")
        assert str(error) == "Schedule conflict"
        assert isinstance(error, AppError)

    def test_import_export_error(self):
        """Test ImportExportError exception."""
        error = ImportExportError("Export failed")
        assert str(error) == "Export failed"
        assert isinstance(error, AppError)

    def test_exception_can_be_raised_and_caught(self):
        """Test that exceptions can be raised and caught properly."""
        with pytest.raises(AppError) as exc_info:
            raise DataError("Connection timeout")
        assert "Connection timeout" in str(exc_info.value)

    def test_catch_specific_exception(self):
        """Test catching specific exception type."""
        with pytest.raises(ParticipantNotFoundError):
            raise ParticipantNotFoundError("Not found")

    def test_catch_parent_exception(self):
        """Test catching parent exception type."""
        with pytest.raises(DataError):
            raise ParticipantNotFoundError("Not found")

    def test_exception_without_message(self):
        """Test exception without message."""
        error = AppError()
        # Should work without message
        assert isinstance(error, Exception)


class TestErrorService:
    """Tests for core/error_service.py."""

    @pytest.fixture
    def event_bus(self):
        """Create an EventBus instance."""
        return EventBus()

    def test_error_service_initialization(self, event_bus):
        """Test ErrorService initialization."""
        service = ErrorService(event_bus)
        assert service.event_bus is event_bus

    def test_error_service_handle_exception(self, event_bus):
        """Test ErrorService handling an exception."""
        service = ErrorService(event_bus)
        error = ValueError("Test error")

        result = service.handle_exception(error, context="test_context")

        assert result["success"] is False
        assert "error" in result
        assert result["context"] == "test_context"

    def test_error_service_handle_exception_emits_event(self, event_bus):
        """Test ErrorService emits event when handling exception."""
        service = ErrorService(event_bus)
        error = ValueError("Test error")

        # Subscribe to error event
        received_events = []

        def on_error(event):
            received_events.append(event)

        event_bus.subscribe("error_occurred", on_error)

        service.handle_exception(error, context="test")

        assert len(received_events) == 1
        assert received_events[0].name == "error_occurred"

    def test_error_service_handle_exception_with_extra(self, event_bus):
        """Test ErrorService handling exception with extra data."""
        service = ErrorService(event_bus)
        error = ValueError("Test error")

        result = service.handle_exception(error, context="test", extra={"key": "value"})

        assert result["success"] is False

    def test_error_service_report_error(self, event_bus):
        """Test ErrorService report_error method."""
        service = ErrorService(event_bus)

        result = service.report_error("Something went wrong", context="test")

        assert result["success"] is False
        assert result["error"] == "Something went wrong"

    def test_error_service_report_error_emits_event(self, event_bus):
        """Test ErrorService emits event when reporting error."""
        service = ErrorService(event_bus)

        # Subscribe to error event
        received_events = []

        def on_error(event):
            received_events.append(event)

        event_bus.subscribe("error_occurred", on_error)

        service.report_error("Error message", context="test")

        assert len(received_events) == 1


class TestEventsBase:
    """Tests for core/events_base.py."""

    def test_event_creation(self):
        """Test Event creation."""
        event = BaseEvent(name="test_event")
        assert event.name == "test_event"
        assert event.data is None

    def test_event_with_data(self):
        """Test Event with data."""
        data = {"key": "value"}
        event = BaseEvent(name="test_event", data=data)
        assert event.name == "test_event"
        assert event.data == data

    def test_event_dataclass(self):
        """Test Event is a dataclass."""
        event1 = BaseEvent(name="test", data=1)
        event2 = BaseEvent(name="test", data=1)
        # Dataclasses with same values should be equal
        assert event1 == event2

    def test_simple_event_bus_creation(self):
        """Test SimpleEventBus creation."""
        bus = SimpleEventBus()
        assert bus is not None
        assert isinstance(bus, IEventBus)

    def test_simple_event_bus_subscribe(self):
        """Test SimpleEventBus subscribe."""
        bus = SimpleEventBus()
        handler = Mock()

        bus.subscribe("test_event", handler)

        # Handler should be registered
        assert "test_event" in bus._handlers
        assert handler in bus._handlers["test_event"]

    def test_simple_event_bus_unsubscribe(self):
        """Test SimpleEventBus unsubscribe."""
        bus = SimpleEventBus()
        handler = Mock()
        bus.subscribe("test_event", handler)

        bus.unsubscribe("test_event", handler)

        assert handler not in bus._handlers.get("test_event", [])

    def test_simple_event_bus_emit(self):
        """Test SimpleEventBus emit."""
        bus = SimpleEventBus()
        handler = Mock()
        bus.subscribe("test_event", handler)

        bus.emit("test_event", data={"key": "value"})

        handler.assert_called_once()
        # Check that handler received an Event
        call_arg = handler.call_args[0][0]
        assert isinstance(call_arg, BaseEvent)
        assert call_arg.name == "test_event"

    def test_simple_event_bus_emit_no_handlers(self):
        """Test SimpleEventBus emit with no handlers."""
        bus = SimpleEventBus()

        # Should not raise
        bus.emit("nonexistent_event")

    def test_simple_event_bus_multiple_handlers(self):
        """Test SimpleEventBus with multiple handlers."""
        bus = SimpleEventBus()
        handler1 = Mock()
        handler2 = Mock()
        bus.subscribe("test_event", handler1)
        bus.subscribe("test_event", handler2)

        bus.emit("test_event")

        handler1.assert_called_once()
        handler2.assert_called_once()

    def test_simple_event_bus_handler_exception(self):
        """Test SimpleEventBus handles handler exceptions."""
        bus = SimpleEventBus()

        def bad_handler(event):
            raise ValueError("Handler error")

        bus.subscribe("test_event", bad_handler)

        # Should not raise, should catch exception internally
        bus.emit("test_event")

    def test_simple_event_bus_unsubscribe_nonexistent(self):
        """Test SimpleEventBus unsubscribe nonexistent handler."""
        bus = SimpleEventBus()
        handler = Mock()

        # Should not raise
        bus.unsubscribe("test_event", handler)


class TestMigration:
    """Tests for core/migration.py."""

    def test_parse_legacy_date_dd_mm_yyyy(self):
        """Test _parse_legacy_date with DD.MM.YYYY format."""
        result = _parse_legacy_date("15.03.2024")
        assert result == "2024-03-15 00:00:00"

    def test_parse_legacy_date_iso_format(self):
        """Test _parse_legacy_date with ISO format."""
        result = _parse_legacy_date("2024-03-15")
        assert result == "2024-03-15 00:00:00"

    def test_parse_legacy_date_empty(self):
        """Test _parse_legacy_date with empty string."""
        result = _parse_legacy_date("")
        assert result is None

    def test_parse_legacy_date_none(self):
        """Test _parse_legacy_date with None."""
        result = _parse_legacy_date(None)
        assert result is None

    def test_parse_legacy_date_invalid(self):
        """Test _parse_legacy_date with invalid format."""
        result = _parse_legacy_date("invalid-date")
        assert result is None

    def test_parse_legacy_date_iso_with_time(self):
        """Test _parse_legacy_date with ISO format including time."""
        result = _parse_legacy_date("2024-03-15 10:30:00")
        # Should extract just the date part and add 00:00:00
        assert result == "2024-03-15 00:00:00"

    @pytest.fixture
    def temp_dbs(self):
        """Create temporary source and target databases."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_db = os.path.join(tmpdir, "source.db")
            target_db = os.path.join(tmpdir, "target.db")
            yield source_db, target_db

    def test_migrate_participants_no_source(self, temp_dbs):
        """Test migrate_participants when source doesn't exist."""
        source_db, target_db = temp_dbs

        # Should not raise, just log warning
        migrate_participants(source_db, target_db)

    def test_migrate_participants_success(self, temp_dbs):
        """Test migrate_participants with valid data."""
        source_db, target_db = temp_dbs

        # Create source database with participants
        conn_src = sqlite3.connect(source_db)
        cur_src = conn_src.cursor()
        cur_src.execute(
            """
            CREATE TABLE participants (
                name TEXT,
                gender TEXT,
                service_type TEXT,
                is_active INTEGER,
                last_assignment_date TEXT
            )
        """
        )
        cur_src.execute(
            """
            INSERT INTO participants VALUES 
            ('John Doe', 'male', 'publisher', 1, '15.03.2024'),
            ('Jane Smith', 'female', 'publisher', 1, '2024-03-10')
        """
        )
        conn_src.commit()
        conn_src.close()

        # Create target database with table
        conn_dst = sqlite3.connect(target_db)
        cur_dst = conn_dst.cursor()
        cur_dst.execute(
            """
            CREATE TABLE participants (
                id INTEGER PRIMARY KEY,
                name TEXT,
                gender TEXT,
                service_type TEXT,
                is_active INTEGER,
                last_assignment_date TEXT
            )
        """
        )
        conn_dst.commit()
        conn_dst.close()

        # Run migration
        migrate_participants(source_db, target_db)

        # Verify migration
        conn_dst = sqlite3.connect(target_db)
        cur_dst = conn_dst.cursor()
        cur_dst.execute("SELECT COUNT(*) FROM participants")
        count = cur_dst.fetchone()[0]
        conn_dst.close()

        assert count == 2

    def test_migrate_participants_no_duplicates(self, temp_dbs):
        """Test migrate_participants doesn't create duplicates."""
        source_db, target_db = temp_dbs

        # Create source database
        conn_src = sqlite3.connect(source_db)
        cur_src = conn_src.cursor()
        cur_src.execute(
            """
            CREATE TABLE participants (
                name TEXT,
                gender TEXT,
                service_type TEXT,
                is_active INTEGER,
                last_assignment_date TEXT
            )
        """
        )
        cur_src.execute(
            """
            INSERT INTO participants VALUES ('John Doe', 'male', 'publisher', 1, NULL)
        """
        )
        conn_src.commit()
        conn_src.close()

        # Create target database with existing participant
        conn_dst = sqlite3.connect(target_db)
        cur_dst = conn_dst.cursor()
        cur_dst.execute(
            """
            CREATE TABLE participants (
                id INTEGER PRIMARY KEY,
                name TEXT,
                gender TEXT,
                service_type TEXT,
                is_active INTEGER,
                last_assignment_date TEXT
            )
        """
        )
        cur_dst.execute(
            """
            INSERT INTO participants (name, gender, service_type, is_active) 
            VALUES ('John Doe', 'male', 'publisher', 1)
        """
        )
        conn_dst.commit()
        conn_dst.close()

        # Run migration
        migrate_participants(source_db, target_db)

        # Verify no duplicate
        conn_dst = sqlite3.connect(target_db)
        cur_dst = conn_dst.cursor()
        cur_dst.execute("SELECT COUNT(*) FROM participants WHERE name = 'John Doe'")
        count = cur_dst.fetchone()[0]
        conn_dst.close()

        assert count == 1


class TestWorkers:
    """Tests for core/workers.py."""

    def test_task_worker_creation(self):
        """Test TaskWorker creation."""

        def task():
            return "result"

        worker = TaskWorker(task)
        assert worker.task_func is task

    def test_task_worker_with_args(self):
        """Test TaskWorker with arguments."""

        def task(a, b):
            return a + b

        worker = TaskWorker(task, 1, 2)
        assert worker.args == (1, 2)

    def test_task_worker_with_kwargs(self):
        """Test TaskWorker with keyword arguments."""

        def task(name, value=None):
            return {"name": name, "value": value}

        worker = TaskWorker(task, "test", value=42)
        assert worker.kwargs == {"value": 42}

    def test_task_worker_with_error_service(self):
        """Test TaskWorker with error_service."""

        def task():
            return "result"

        mock_error_service = Mock()
        worker = TaskWorker(task, error_service=mock_error_service)
        assert worker.error_service is mock_error_service

    def test_worker_factory_run_task(self):
        """Test WorkerFactory.run_task."""

        def task():
            return "result"

        def on_finished(result):
            pass

        mock_facade = Mock()

        # Note: This creates a real QThread which requires Qt event loop
        # We just test that it creates the worker without error
        with patch.object(TaskWorker, "start"):
            worker = WorkerFactory.run_task(mock_facade, task, on_finished)
            assert isinstance(worker, TaskWorker)

    def test_task_worker_run_success(self):
        """Test TaskWorker run with successful task."""

        def task():
            return "result"

        worker = TaskWorker(task)

        # Connect to finished signal
        results = []

        def on_finished(result):
            results.append(result)

        worker.finished.connect(on_finished)

        # Run the worker (directly, not in thread)
        worker.run()

        # Check result
        assert len(results) == 1
        assert results[0]["success"] is True
        assert results[0]["data"] == "result"

    def test_task_worker_run_none_result(self):
        """Test TaskWorker run with None result."""

        def task():
            return None

        worker = TaskWorker(task)
        results = []
        worker.finished.connect(lambda r: results.append(r))

        worker.run()

        assert results[0]["success"] is True

    def test_task_worker_run_bool_result(self):
        """Test TaskWorker run with bool result."""

        def task():
            return True

        worker = TaskWorker(task)
        results = []
        worker.finished.connect(lambda r: results.append(r))

        worker.run()

        assert results[0]["success"] is True

    def test_task_worker_run_dict_result(self):
        """Test TaskWorker run with dict result."""

        def task():
            return {"status": "ok", "data": 42}

        worker = TaskWorker(task)
        results = []
        worker.finished.connect(lambda r: results.append(r))

        worker.run()

        assert results[0] == {"status": "ok", "data": 42}

    def test_task_worker_run_exception(self):
        """Test TaskWorker run with exception."""

        def task():
            raise ValueError("Task error")

        worker = TaskWorker(task)
        results = []
        worker.finished.connect(lambda r: results.append(r))

        worker.run()

        assert results[0]["success"] is False
        assert "error" in results[0]

    def test_task_worker_run_exception_with_error_service(self):
        """Test TaskWorker run with exception and error_service."""

        def task():
            raise ValueError("Task error")

        mock_error_service = Mock()
        mock_error_service.handle_exception.return_value = {
            "success": False,
            "error": "Handled error",
        }

        worker = TaskWorker(task, error_service=mock_error_service)
        results = []
        worker.finished.connect(lambda r: results.append(r))

        worker.run()

        mock_error_service.handle_exception.assert_called_once()
        assert results[0]["success"] is False


class TestIntegration:
    """Integration tests combining multiple modules."""

    def test_error_service_with_event_bus(self):
        """Test ErrorService with EventBus."""
        bus = EventBus()
        service = ErrorService(bus)

        # Subscribe to error events
        error_events = []

        def on_error(event):
            error_events.append(event)

        bus.subscribe("error_occurred", on_error)

        # Handle an exception
        service.handle_exception(ValueError("Test error"), context="test")

        # Should have received an event
        assert len(error_events) == 1
        assert error_events[0].name == "error_occurred"

    def test_event_bus_with_multiple_event_types(self):
        """Test EventBus with multiple event types."""
        bus = EventBus()

        error_handler = Mock()
        success_handler = Mock()

        bus.subscribe("error", error_handler)
        bus.subscribe("success", success_handler)

        bus.emit("error", data={"msg": "failed"})
        bus.emit("success", data={"msg": "ok"})

        error_handler.assert_called_once()
        success_handler.assert_called_once()

    def test_exception_handling_in_error_service(self):
        """Test that ErrorService properly formats different exception types."""
        bus = EventBus()
        service = ErrorService(bus)

        # Test with different exception types
        exceptions = [
            ValueError("value error"),
            ParticipantNotFoundError("not found"),
            ScheduleError("schedule conflict"),
            ImportExportError("export failed"),
        ]

        for exc in exceptions:
            result = service.handle_exception(exc, context="test")
            assert result["success"] is False
            assert "error" in result
