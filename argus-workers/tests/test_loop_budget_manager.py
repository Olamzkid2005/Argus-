"""
Tests for Loop Budget Manager
"""
from loop_budget_manager import LoopBudgetManager


class TestLoopBudgetManager:
    """Test suite for LoopBudgetManager"""

    def test_initialization_with_defaults(self):
        """Test initialization with default values"""
        manager = LoopBudgetManager("eng-123")

        assert manager.max_cycles == 5
        assert manager.max_depth == 3
        assert manager.current_cycles == 0
        assert manager.current_depth == 0

    def test_initialization_with_custom_config(self):
        """Test initialization with custom config"""
        config = {
            "max_cycles": 10,
            "max_depth": 5,
        }
        manager = LoopBudgetManager("eng-123", config)

        assert manager.max_cycles == 10
        assert manager.max_depth == 5

    def test_can_continue_within_budget(self):
        """Test can_continue returns True when within budget"""
        manager = LoopBudgetManager("eng-123")
        action = {"type": "recon_expand"}

        can_continue, reason = manager.can_continue(action)

        assert can_continue is True
        assert reason == "within_budget"

    def test_can_continue_cycles_exceeded(self):
        """Test can_continue returns False when cycles exceeded"""
        manager = LoopBudgetManager("eng-123")
        manager.current_cycles = 5
        action = {"type": "recon_expand"}

        can_continue, reason = manager.can_continue(action)

        assert can_continue is False
        assert reason == "cycles_exceeded"

    def test_can_continue_depth_exceeded(self):
        """Test can_continue returns False when depth exceeded"""
        manager = LoopBudgetManager("eng-123")
        manager.current_depth = 3
        action = {"type": "deep_scan"}

        can_continue, reason = manager.can_continue(action)

        assert can_continue is False
        assert reason == "depth_exceeded"

    def test_consume_increments_cycles_for_recon_expand(self):
        """Test consume increments cycles for recon_expand"""
        manager = LoopBudgetManager("eng-123")
        action = {"type": "recon_expand"}

        manager.consume(action)

        assert manager.current_cycles == 1

    def test_consume_increments_depth_for_deep_scan(self):
        """Test consume increments depth for deep_scan"""
        manager = LoopBudgetManager("eng-123")
        action = {"type": "deep_scan"}

        manager.consume(action)

        assert manager.current_depth == 1

    def test_consume_accumulates_multiple_actions(self):
        """Test consume tracks multiple actions correctly"""
        manager = LoopBudgetManager("eng-123")

        manager.consume({"type": "recon_expand"})
        manager.consume({"type": "deep_scan"})
        manager.consume({"type": "recon_expand"})

        assert manager.current_cycles == 2
        assert manager.current_depth == 1

    def test_get_status_returns_current_and_max(self):
        """Test get_status returns current vs max values"""
        manager = LoopBudgetManager("eng-123")
        manager.current_cycles = 2
        manager.current_depth = 1

        status = manager.get_status()

        assert status["cycles"]["current"] == 2
        assert status["cycles"]["max"] == 5
        assert status["cycles"]["remaining"] == 3
        assert status["depth"]["current"] == 1
        assert status["depth"]["max"] == 3
        assert status["depth"]["remaining"] == 2

    def test_reset_clears_current_values(self):
        """Test reset clears current values"""
        manager = LoopBudgetManager("eng-123")
        manager.current_cycles = 3
        manager.current_depth = 2

        manager.reset()

        assert manager.current_cycles == 0
        assert manager.current_depth == 0

    def test_to_dict_returns_all_values(self):
        """Test to_dict returns all budget values"""
        manager = LoopBudgetManager("eng-123")
        manager.current_cycles = 2

        data = manager.to_dict()

        assert data["engagement_id"] == "eng-123"
        assert data["max_cycles"] == 5
        assert data["current_cycles"] == 2
        assert "max_depth" in data
        assert "current_depth" in data
