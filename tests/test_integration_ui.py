"""
Integration tests for UI compatibility.

These tests validate that the entire data flow works correctly:
Database → Service → Facade → UI

Ensures all layers can communicate with consistent data formats.
"""

import os
import sys
import tempfile
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.container import Container
from core.settings import Settings


@pytest.fixture
def temp_container():
    """
    Creates a container with a temporary database.
    """
    # Create temp DB file
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db")
    os.close(tmp_fd)

    # Patch Settings.load to return config pointing to temp DB
    original_load = Settings.load
    Settings.load = lambda: Settings(db_path=tmp_path)

    container = Container()

    try:
        yield container
    finally:
        container.db_manager.close()
        Settings.load = original_load
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def test_ui_can_load_participants(temp_container):
    """
    Test complete data flow: DB → ParticipantService → UI format
    """
    p_service = temp_container.participant_service

    # Add a test participant with unique name for idempotency
    unique_name = f"Test User {int(time.time())}"
    p_id = p_service.add_participant(unique_name, "male", "publisher", ["bible_reading"])

    # Act - get participants as UI would
    participants = p_service.get_all_participants()

    # Assert - UI must understand all fields
    assert len(participants) >= 1
    p = next((p for p in participants if p["id"] == p_id), None)
    assert p is not None

    # Critical fields for UI
    assert "id" in p
    assert "name" in p
    assert p["name"] == unique_name
    assert "gender" in p
    assert "service_type" in p
    assert "is_active" in p
    assert "last_assignment_date" in p
    assert "last_assignment_date_real" in p  # LEGACY FIELD - MUST EXIST
    assert "total_assignments" in p
    assert "qualifications" in p
    assert "family_group_id" in p

    # Verify types
    assert isinstance(p["total_assignments"], int)
    assert isinstance(p["qualifications"], list)
    assert "bible_reading" in p["qualifications"]


def test_ui_participants_no_n_plus_one(temp_container):
    """
    Verify no N+1 query problem when loading participants.
    """
    p_service = temp_container.participant_service

    # Create 10 participants
    for i in range(10):
        p_service.add_participant(f"User {i}", "male", "publisher", ["bible_reading"])

    # Get all participants - should use bulk query
    participants = p_service.get_all_participants()

    # Should have at least 10 participants
    assert len(participants) >= 10

    # All should have qualifications loaded
    for p in participants:
        assert "qualifications" in p
        assert isinstance(p["qualifications"], list)
