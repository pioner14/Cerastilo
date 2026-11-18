"""
Tests for schedule logic functions.

Note: auto_assign_week() and auto_assign_all() are deprecated.
Use AutoAssignmentService instead. See tests/test_logic_orm.py for current tests.
"""

from unittest.mock import MagicMock
from core.auto_assignment_service import AutoAssignmentService


def test_auto_assign_week_no_assignments():
    """Test auto-assign when there are no assignments."""
    # Create mock session factory
    mock_session = MagicMock()
    mock_session.execute().scalars().all.return_value = []

    mock_session_factory = MagicMock(return_value=mock_session)

    # Use AutoAssignmentService instead of deprecated function
    service = AutoAssignmentService(session_factory=mock_session_factory)
    result = service.auto_assign_week(1, session=mock_session)

    assert result["success"] is True
    assert result["count"] == 0


# Николай, это заготовка. Для полноценных тестов
# рекомендуется использовать pytest + fxt_db (in-memory sqlite).
# См. tests/test_logic_orm.py для актуальных тестов.
