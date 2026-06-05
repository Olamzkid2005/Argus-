"""Tests for budget_persistence_service.py"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from orchestrator_pkg.analysis.budget_persistence_service import (
    BudgetPersistenceService,
)


class TestBudgetPersistenceService:
    def test_persist_with_none_budget_mgr_returns_none(self):
        result = BudgetPersistenceService.persist(None)
        assert result is None

    def test_persist_with_budget_mgr_calls_persist_to_db(self):
        mock_mgr = MagicMock()
        BudgetPersistenceService.persist(mock_mgr)
        mock_mgr.persist_to_db.assert_called_once_with()

    @patch("orchestrator_pkg.analysis.budget_persistence_service.logger")
    def test_persist_when_persist_to_db_raises_logs_warning(self, mock_logger):
        mock_mgr = MagicMock()
        mock_mgr.persist_to_db.side_effect = RuntimeError("DB error")
        BudgetPersistenceService.persist(mock_mgr)
        mock_logger.warning.assert_called_once()
        msg = mock_logger.warning.call_args[0][0]
        assert "Failed to persist loop budget" in msg
