"""
Tests for Engagement State Machine
"""
from unittest.mock import Mock, patch

import pytest

from state_machine import EngagementStateMachine, InvalidStateTransition

# Valid UUID for testing (matches the format UUID columns expect)
TEST_ENGAGEMENT_ID = "550e8400-e29b-41d4-a716-446655440000"


class TestEngagementStateMachine:
    """Test suite for EngagementStateMachine"""

    def test_initialization_with_valid_state(self):
        """Test initialization with valid state"""
        with patch('state_machine.psycopg2.connect'):
            machine = EngagementStateMachine(TEST_ENGAGEMENT_ID, "postgresql://localhost", "created")

            assert machine.current_state == "created"
            assert machine.engagement_id == TEST_ENGAGEMENT_ID

    def test_initialization_with_invalid_state_raises_error(self):
        """Test initialization with invalid state raises ValueError"""
        with patch('state_machine.psycopg2.connect'):
            with pytest.raises(ValueError):
                EngagementStateMachine(TEST_ENGAGEMENT_ID, "postgresql://localhost", "invalid_state")

    def test_initialization_with_invalid_uuid_raises_error(self):
        """Test initialization with non-UUID string raises ValueError"""
        with patch('state_machine.psycopg2.connect'):
            with pytest.raises(ValueError, match="not a valid UUID"):
                EngagementStateMachine("not-a-uuid", "postgresql://localhost", "created")

    def test_can_transition_to_valid_state(self):
        """Test can_transition_to returns True for valid transitions"""
        with patch('state_machine.psycopg2.connect'):
            machine = EngagementStateMachine(TEST_ENGAGEMENT_ID, "postgresql://localhost", "created")

            assert machine.can_transition_to("recon") is True
            assert machine.can_transition_to("failed") is True

    def test_can_transition_to_invalid_state(self):
        """Test can_transition_to returns False for invalid transitions"""
        with patch('state_machine.psycopg2.connect'):
            machine = EngagementStateMachine(TEST_ENGAGEMENT_ID, "postgresql://localhost", "created")

            assert machine.can_transition_to("complete") is False
            assert machine.can_transition_to("scanning") is False

    def test_transition_to_valid_state_succeeds(self):
        """Test transition to valid state succeeds and SQL is correct"""
        with patch('database.connection.psycopg2.connect') as mock_connect:
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_connect.return_value = mock_conn
            mock_conn.cursor.return_value = mock_cursor

            mock_cursor.fetchone.return_value = ("created",)
            machine = EngagementStateMachine(TEST_ENGAGEMENT_ID, "postgresql://localhost", "created")
            machine.transition("recon", "Starting reconnaissance")

            assert machine.current_state == "recon"
            # Verify SQL was executed
            assert mock_cursor.execute.called
            # Verify the INSERT was called with engagement_states table and valid UUID
            insert_call = mock_cursor.execute.call_args_list[1]
            assert "engagement_states" in insert_call[0][0]
            assert mock_conn.commit.called

    def test_transition_to_invalid_state_raises_error(self):
        """Test transition to invalid state raises InvalidStateTransition"""
        with patch('state_machine.psycopg2.connect'):
            machine = EngagementStateMachine(TEST_ENGAGEMENT_ID, "postgresql://localhost", "created")

            with pytest.raises(InvalidStateTransition):
                machine.transition("complete")

    def test_loop_back_transition_allowed(self):
        """Test that analyzing->recon loop-back is allowed"""
        with patch('state_machine.psycopg2.connect') as mock_connect:
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_connect.return_value = mock_conn
            mock_conn.cursor.return_value = mock_cursor

            machine = EngagementStateMachine(TEST_ENGAGEMENT_ID, "postgresql://localhost", "analyzing")

            assert machine.can_transition_to("recon") is True

    def test_transition_persists_state_and_budget(self):
        """Test transition executes both INSERT and UPDATE SQL"""
        with patch('database.connection.psycopg2.connect') as mock_connect:
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_connect.return_value = mock_conn
            mock_conn.cursor.return_value = mock_cursor

            mock_cursor.fetchone.return_value = ("created",)
            machine = EngagementStateMachine(TEST_ENGAGEMENT_ID, "postgresql://localhost", "created")
            machine.transition("recon")

            # Should have called execute three times: SELECT FOR UPDATE, INSERT into engagement_states + UPDATE engagements
            assert mock_cursor.execute.call_count == 3
            assert mock_conn.commit.called

    def test_get_valid_transitions_returns_correct_list(self):
        """Test get_valid_transitions returns correct list"""
        with patch('state_machine.psycopg2.connect'):
            machine = EngagementStateMachine(TEST_ENGAGEMENT_ID, "postgresql://localhost", "created")

            valid = machine.get_valid_transitions()

            assert "recon" in valid
            assert "failed" in valid
            assert "paused" in valid
            assert len(valid) == 3

    def test_terminal_states_have_no_transitions(self):
        """Test that terminal states have no valid transitions"""
        with patch('state_machine.psycopg2.connect'):
            complete_machine = EngagementStateMachine(TEST_ENGAGEMENT_ID, "postgresql://localhost", "complete")
            failed_machine = EngagementStateMachine(TEST_ENGAGEMENT_ID, "postgresql://localhost", "failed")

            assert len(complete_machine.get_valid_transitions()) == 0
            assert len(failed_machine.get_valid_transitions()) == 0

    def test_paused_state_can_resume(self):
        """Test that paused state can resume to multiple states"""
        with patch('state_machine.psycopg2.connect'):
            machine = EngagementStateMachine(TEST_ENGAGEMENT_ID, "postgresql://localhost", "paused")

            valid = machine.get_valid_transitions()

            assert "recon" in valid
            assert "scanning" in valid
            assert "analyzing" in valid

    def test_uuid_is_validated_on_construction(self):
        """Test that non-UUID strings are rejected at construction time"""
        with patch('state_machine.psycopg2.connect'):
            with pytest.raises(ValueError, match="not a valid UUID"):
                EngagementStateMachine("eng-123", "postgresql://localhost", "created")

    def test_get_transition_history_executes_correct_query(self):
        """Test get_transition_history uses correct SQL"""
        with patch('database.connection.psycopg2.connect') as mock_connect:
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_connect.return_value = mock_conn
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchall.return_value = [
                ("created", "recon", "Starting", None),
            ]

            machine = EngagementStateMachine(TEST_ENGAGEMENT_ID, "postgresql://localhost", "created")
            history = machine.get_transition_history()

            assert len(history) == 1
            assert history[0]["from_state"] == "created"
            assert history[0]["to_state"] == "recon"
