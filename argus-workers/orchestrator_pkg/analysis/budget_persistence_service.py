"""
BudgetPersistenceService — persists loop budget counters to DB.

Extracted from Orchestrator.run_analysis() Section 6.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class BudgetPersistenceService:
    """Persists loop budget counters back to the database.

    This is the final phase of analysis: saving the updated budget state
    so that if analysis loops back to recon, the budget counters continue
    from where they left off in memory rather than starting from a stale
    DB value.
    """

    @staticmethod
    def persist(budget_mgr: Any) -> None:
        """Persist budget counters to the database.

        Args:
            budget_mgr: A ``LoopBudgetManager`` instance (already has
                ``persist_to_db()`` method).
        """
        if budget_mgr is None:
            return
        try:
            budget_mgr.persist_to_db()
        except Exception as e:
            logger.warning(
                "Failed to persist loop budget (non-fatal): %s", e,
            )
