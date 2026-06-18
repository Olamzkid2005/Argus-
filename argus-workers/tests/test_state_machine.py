"""
Tests for Engagement State Machine
"""

from unittest.mock import MagicMock, patch

import pytest

from database.connection import ConnectionManager
from state_machine import EngagementStateMachine, InvalidStateTransitionError

# Valid UUID for testing (matches the format UUID columns expect)
TEST_ENGAGEMENT_ID = "550e8400-e29b-41d4-a716-446655440000"


def _mock_db():
    """Return a mocked get_db() that provides a mock connection with cursor."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_db = MagicMock(spec=ConnectionManager)
    mock_db.get_connection.return_value = mock_conn
    return mock_db, mock_conn, mock_cursor


class TestEngagementStateMachine:
    """Test suite for EngagementStateMachine"""

    def test_initialization_with_valid_state(self):
        """Test initialization with valid state"""
        machine = EngagementStateMachine(TEST_ENGAGEMENT_ID, current_state="created")

        assert machine.current_state == "created"
        assert machine.engagement_id == TEST_ENGAGEMENT_ID

    def test_initialization_with_invalid_state_raises_error(self):
        """Test initialization with invalid state raises ValueError"""
        with pytest.raises(ValueError):
            EngagementStateMachine(TEST_ENGAGEMENT_ID, current_state="invalid_state")

    def test_initialization_with_invalid_uuid_raises_error(self):
        """Test initialization with non-UUID string raises ValueError"""
        with pytest.raises(ValueError, match="not a valid UUID"):
            EngagementStateMachine("not-a-uuid", current_state="created")

    def test_can_transition_to_valid_state(self):
        """Test can_transition_to returns True for valid transitions"""
        machine = EngagementStateMachine(TEST_ENGAGEMENT_ID, current_state="created")

        assert machine.can_transition_to("recon") is True
        assert machine.can_transition_to("failed") is True

    def test_can_transition_to_invalid_state(self):
        """Test can_transition_to returns False for invalid transitions"""
        machine = EngagementStateMachine(TEST_ENGAGEMENT_ID, current_state="created")

        assert machine.can_transition_to("complete") is False
        assert machine.can_transition_to("scanning") is False

    def test_transition_to_valid_state_succeeds(self):
        """Test transition to valid state succeeds and SQL is correct"""
        mock_db, mock_conn, mock_cursor = _mock_db()
        mock_cursor.fetchone.return_value = ("created",)

        with patch("state_machine.get_db", return_value=mock_db):
            machine = EngagementStateMachine(
                TEST_ENGAGEMENT_ID, current_state="created"
            )
            machine.transition("recon", "Starting reconnaissance")

        assert machine.current_state == "recon"
        # Verify SQL was executed
        assert mock_cursor.execute.called
        # Verify the INSERT was called with engagement_states table and valid UUID
        insert_call = mock_cursor.execute.call_args_list[1]
        assert "engagement_states" in insert_call[0][0]
        assert mock_conn.commit.called

    def test_transition_to_invalid_state_raises_error(self):
        """Test transition to invalid state raises InvalidStateTransitionError"""
        machine = EngagementStateMachine(TEST_ENGAGEMENT_ID, current_state="created")

        with pytest.raises(InvalidStateTransitionError):
            machine.transition("complete")

    def test_loop_back_transition_allowed(self):
        """Test that analyzing->recon loop-back is allowed"""
        machine = EngagementStateMachine(TEST_ENGAGEMENT_ID, current_state="analyzing")

        assert machine.can_transition_to("recon") is True

    def test_transition_persists_state_and_budget(self):
        """Test transition executes both INSERT and UPDATE SQL"""
        mock_db, mock_conn, mock_cursor = _mock_db()
        mock_cursor.fetchone.return_value = ("created",)

        with patch("state_machine.get_db", return_value=mock_db):
            machine = EngagementStateMachine(
                TEST_ENGAGEMENT_ID, current_state="created"
            )
            machine.transition("recon")

        # Should have called execute three times: SELECT FOR UPDATE, INSERT, UPDATE
        assert mock_cursor.execute.call_count == 3
        assert mock_conn.commit.called

    def test_get_valid_transitions_returns_correct_list(self):
        """Test get_valid_transitions returns correct list"""
        machine = EngagementStateMachine(TEST_ENGAGEMENT_ID, current_state="created")

        valid = machine.get_valid_transitions()

        assert "recon" in valid
        assert "failed" in valid
        assert "paused" in valid
        assert len(valid) == 3

    def test_terminal_states_have_no_transitions(self):
        """Test that terminal states have no valid transitions"""
        complete_machine = EngagementStateMachine(
            TEST_ENGAGEMENT_ID, current_state="complete"
        )
        failed_machine = EngagementStateMachine(
            TEST_ENGAGEMENT_ID, current_state="failed"
        )

        assert len(complete_machine.get_valid_transitions()) == 0
        assert len(failed_machine.get_valid_transitions()) == 0

    def test_paused_state_can_resume(self):
        """Test that paused state can resume to multiple states"""
        machine = EngagementStateMachine(TEST_ENGAGEMENT_ID, current_state="paused")

        valid = machine.get_valid_transitions()

        assert "recon" in valid
        assert "scanning" in valid
        assert "analyzing" in valid

    def test_uuid_is_validated_on_construction(self):
        """Test that non-UUID strings are rejected at construction time"""
        with pytest.raises(ValueError, match="not a valid UUID"):
            EngagementStateMachine("eng-123", current_state="created")

    def test_get_transition_history_executes_correct_query(self):
        """Test get_transition_history uses correct SQL"""
        mock_db, mock_conn, mock_cursor = _mock_db()
        mock_cursor.fetchall.return_value = [
            ("created", "recon", "Starting", None),
        ]

        with patch("state_machine.get_db", return_value=mock_db):
            machine = EngagementStateMachine(
                TEST_ENGAGEMENT_ID, current_state="created"
            )
            history = machine.get_transition_history()

        assert len(history) == 1
        assert history[0]["from_state"] == "created"
        assert history[0]["to_state"] == "recon"
