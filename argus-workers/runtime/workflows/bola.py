"""
BolaWorkflow — Step-based BOLA + BOPLA workflow engine.

Replaces DualAuthScanner.execute() with an explicit step pipeline that emits
structured obstacles and reuses existing detection via
DualAuthScanner.for_phase_execution().
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from runtime.workflows.base import WorkflowContext, WorkflowResult
from runtime.workflows.steps import (
    AuthenticateStep,
    DiscoverOwnedResourcesStep,
    TestBolaStep,
    TestBoplaStep,
    WorkflowStep,
)

if TYPE_CHECKING:
    from runtime.engagement_state import EngagementState
    from utils.logging_utils import ScanLogger

logger = logging.getLogger(__name__)


class BolaWorkflow:
    """Step-based BOLA + BOPLA workflow.

    Runs 4 steps in sequence:
      1. AuthenticateStep  — authenticate as User A and User B
      2. DiscoverOwnedResourcesStep — crawl target as User A
      3. TestBolaStep      — test cross-account access (B vs A's resources)
      4. TestBoplaStep     — check sensitive field exposure on both sessions

    Sessions are closed in a ``finally`` block. The workflow never raises —
    all step exceptions become obstacles. ``SoftTimeLimitExceeded`` at the
    Celery level is the only exception that propagates.
    """

    def __init__(
        self,
        *,
        target: str,
        auth_config_a: dict,
        auth_config_b: dict,
        engagement_id: str,
        state: EngagementState,
        emit_finding_callback: Callable,
        slog: ScanLogger,
    ) -> None:
        self.ctx = WorkflowContext(
            target=target,
            engagement_id=engagement_id,
            state=state,
            emit_finding_callback=emit_finding_callback,
            slog=slog,
            auth_config_a=auth_config_a,
            auth_config_b=auth_config_b,
        )
        self.steps: list[WorkflowStep] = [
            AuthenticateStep(),
            DiscoverOwnedResourcesStep(),
            TestBolaStep(),
            TestBoplaStep(),
        ]

    def execute(self) -> WorkflowResult:
        """Run all 4 steps in sequence.

        Tracks findings_created locally (NOT from state.findings, which is
        always 0 mid-workflow). Closes sessions in finally block to prevent
        connection-pool FD leaks.
        """
        findings_total = 0
        try:
            for step in self.steps:
                try:
                    result = step.run(self.ctx)
                    findings_total += result.findings_emitted
                except Exception as e:
                    obstacle_type = f"step_failed:{step.name}"
                    self.ctx.slog.warning(
                        f"Obstacle: {obstacle_type}",
                        extra={"step": step.name, "error": str(e)[:200]},
                    )
                    self.ctx.state.add_obstacle({
                        "type": obstacle_type,
                        "detected_at": time.time(),
                        "step": step.name,
                        "recoverable": False,
                        "recovery_paths": ["skip"],
                        "metadata": {"error_class": type(e).__name__},
                    })
        finally:
            # Always close sessions to prevent FD leaks across engagements.
            for session_attr in ("session_a", "session_b"):
                session = getattr(self.ctx, session_attr)
                if session is not None:
                    try:
                        session.close()
                    except Exception:
                        logger.warning("Failed to close session %s in BOLA workflow cleanup", session_attr, exc_info=True)

        outcome = "partial" if len(self.ctx.state.obstacles) > 0 else "complete"
        return WorkflowResult(
            success=True,
            outcome=outcome,
            findings_created=findings_total,
            obstacles_encountered=len(self.ctx.state.obstacles),
            identities_created=0,
            resources_created=0,
            requests_captured=0,
            metadata={
                "engagement_id": self.ctx.engagement_id,
                "current_phase": self.ctx.state.current_phase,
                "state_version": self.ctx.state.state_version,
                "target": self.ctx.target,
            },
        )
