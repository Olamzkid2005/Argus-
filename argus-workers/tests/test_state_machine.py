"""
Tests for Engagement State Machine
"""
import pytest
from unittest.mock import Mock, patch
from state_machine import EngagementStateMachine, InvalidStateTransition


class TestEngagementStateMachine:
    """Test suite for EngagementStateMachine"""
    
    def test_initialization_with_valid_state(self):
        """Test initialization with valid state"""
        with patch('state_machine.psycopg2.connect'):
            machine = EngagementStateMachine("eng-123", "postgresql://localhost", "created")
            
            assert machine.current_state == "created"
            assert machine.engagement_id == "eng-123"
    
    def test_initialization_with_invalid_state_raises_error(self):
        """Test initialization with invalid state raises ValueError"""
        with patch('state_machine.psycopg2.connect'):
            with pytest.raises(ValueError):
                EngagementStateMachine("eng-123", "postgresql://localhost", "invalid_state")
    
    def test_can_transition_to_valid_state(self):
        """Test can_transition_to returns True for valid transitions"""
        with patch('state_machine.psycopg2.connect'):
            machine = EngagementStateMachine("eng-123", "postgresql://localhost", "created")
            
            assert machine.can_transition_to("recon") is True
            assert machine.can_transition_to("failed") is True
    
    def test_can_transition_to_invalid_state(self):
        """Test can_transition_to returns False for invalid transitions"""
        with patch('state_machine.psycopg2.connect'):
            machine = EngagementStateMachine("eng-123", "postgresql://localhost", "created")
            
            assert machine.can_transition_to("complete") is False
            assert machine.can_transition_to("scanning") is False
    
    def test_transition_to_valid_state_succeeds(self):
        """Test transition to valid state succeeds"""
        with patch('state_machine.psycopg2.connect') as mock_connect:
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_connect.return_value = mock_conn
            mock_conn.cursor.return_value = mock_cursor
            
            machine = EngagementStateMachine("eng-123", "postgresql://localhost", "created")
            machine.transition("recon", "Starting reconnaissance")
            
            assert machine.current_state == "recon"
            assert mock_cursor.execute.called
            assert mock_conn.commit.called
    
    def test_transition_to_invalid_state_raises_error(self):
        """Test transition to invalid state raises InvalidStateTransition"""
        with patch('state_machine.psycopg2.connect'):
            machine = EngagementStateMachine("eng-123", "postgresql://localhost", "created")
            
            with pytest.raises(InvalidStateTransition):
                machine.transition("complete")
    
    def test_loop_back_transition_allowed(self):
        """Test that analyzing->recon loop-back is allowed"""
        with patch('state_machine.psycopg2.connect') as mock_connect:
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_connect.return_value = mock_conn
            mock_conn.cursor.return_value = mock_cursor
            
            machine = EngagementStateMachine("eng-123", "postgresql://localhost", "analyzing")
            
            assert machine.can_transition_to("recon") is True
    
    def test_get_valid_transitions_returns_correct_list(self):
        """Test get_valid_transitions returns correct list"""
        with patch('state_machine.psycopg2.connect'):
            machine = EngagementStateMachine("eng-123", "postgresql://localhost", "created")
            
            valid = machine.get_valid_transitions()
            
            assert "recon" in valid
            assert "failed" in valid
            assert len(valid) == 2
    
    def test_terminal_states_have_no_transitions(self):
        """Test that terminal states have no valid transitions"""
        with patch('state_machine.psycopg2.connect'):
            complete_machine = EngagementStateMachine("eng-123", "postgresql://localhost", "complete")
            failed_machine = EngagementStateMachine("eng-123", "postgresql://localhost", "failed")
            
            assert len(complete_machine.get_valid_transitions()) == 0
            assert len(failed_machine.get_valid_transitions()) == 0
    
    def test_paused_state_can_resume(self):
        """Test that paused state can resume to multiple states"""
        with patch('state_machine.psycopg2.connect'):
            machine = EngagementStateMachine("eng-123", "postgresql://localhost", "paused")
            
            valid = machine.get_valid_transitions()
            
            assert "recon" in valid
            assert "scanning" in valid
            assert "analyzing" in valid
