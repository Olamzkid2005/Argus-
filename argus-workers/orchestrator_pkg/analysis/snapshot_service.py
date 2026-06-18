"""
SnapshotService — loads findings from DB, creates snapshot, loads loop budget.

Extracted from Orchestrator.run_analysis() Section 1 (Snapshot/Load phase).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class SnapshotService:
    """Loads findings, creates snapshot, and loads loop budget from DB.

    This is the first phase of analysis: preparing the snapshot dict that
    the IntelligenceEngine will evaluate.
    """

    def __init__(
        self,
        db_conn: str,
        engagement_id: str,
        finding_repo: Any,  # FindingRepository or None
        get_org_id_fn: Callable[[], str | None],
        load_priority_vuln_classes_fn: Callable[[], list[str]],
        state: Any = None,  # Optional EngagementState reference
    ) -> None:
        self.db_conn = db_conn
        self.engagement_id = engagement_id
        self.finding_repo = finding_repo
        self._get_org_id = get_org_id_fn
        self._load_priority_vuln_classes = load_priority_vuln_classes_fn
        self._state = state

    def load_and_build(self, job: dict) -> tuple[dict, Any, list[dict], str | None]:
        """Load findings from DB, create snapshot, load loop budget.

        Args:
            job: The analysis job dict (contains ``budget`` config).

        Returns:
            Tuple of (snapshot_dict, budget_mgr, findings_list, org_id).
            ``budget_mgr`` is a ``LoopBudgetManager`` instance with DB state loaded.
        """
        # ── Load findings from DB ──
        findings: list[dict] = []
        if self.finding_repo:
            try:
                raw_findings, _ = self.finding_repo.get_findings_by_engagement(
                    self.engagement_id,
                    limit=100000,
                )
                findings = [
                    f.to_dict()
                    if hasattr(f, "to_dict")
                    else dict(f)
                    if isinstance(f, dict)
                    else f
                    for f in raw_findings
                ]
            except Exception as e:
                logger.warning("Failed to load findings: %s", e)

        # ── Create snapshot ──
        from loop_budget_manager import LoopBudgetManager
        from snapshot_manager import SnapshotManager

        if not self.db_conn:
            raise OSError(
                "DATABASE_URL is not set — cannot create snapshot for analysis"
            )

        snapshot_mgr = SnapshotManager(self.db_conn)
        snapshot = snapshot_mgr.create_snapshot(self.engagement_id)

        budget_config = job.get("budget", {})
        budget_mgr = LoopBudgetManager(self.engagement_id, budget_config)

        # Load current budget state from database so max_cycles cap is effective
        try:
            from database.connection import db_cursor

            with db_cursor() as cursor:
                cursor.execute(
                    "SELECT current_cycles, current_depth, current_llm_reviews "
                    "FROM loop_budgets WHERE engagement_id = %s",
                    (self.engagement_id,),
                )
                row = cursor.fetchone()
                if row:
                    budget_mgr.load_from_db(
                        {
                            "current_cycles": row[0],
                            "current_depth": row[1],
                            "current_llm_reviews": row[2] or 0,
                        }
                    )
        except Exception:
            logger.debug(
                "Could not load loop budget from DB for %s",
                self.engagement_id,
            )

        # ── Populate snapshot ──
        snapshot["findings"] = findings
        snapshot["loop_budget"] = budget_mgr.to_dict()

        org_id = self._get_org_id()
        snapshot["org_id"] = org_id

        priority_classes = self._load_priority_vuln_classes()
        if priority_classes:
            snapshot["priority_vuln_classes"] = priority_classes
            logger.info(
                "Loaded %d priority vuln classes for engagement %s: %s",
                len(priority_classes),
                self.engagement_id,
                priority_classes,
            )

        # Pass EngagementState reference for AttackGraph integration
        if self._state is not None:
            snapshot["_engagement_state"] = self._state

        return snapshot, budget_mgr, findings, org_id
