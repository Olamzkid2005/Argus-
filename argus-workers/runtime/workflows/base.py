"""
Workflow Primitives — Base classes and dataclasses for step-based workflows.

V1 implements BolaWorkflow only. The Workflow ABC exists for V2+ workflow
types (IdorWorkflow, PrivilegeEscWorkflow, etc.) and is not inherited by
BolaWorkflow — YAGNI for a single concrete implementation.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    import requests

    from runtime.engagement_state import EngagementState
    from utils.logging_utils import ScanLogger

logger = logging.getLogger(__name__)


@dataclass
class WorkflowContext:
    """Per-execution state shared across workflow steps.

    Constructed by BolaWorkflow.execute(), mutated by steps, read by
    WorkflowResult construction. Not persisted — lives only in the
    Celery worker's memory for the duration of one workflow run.

    Session ownership: The sessions created by AuthManager.authenticate()
    are owned by the workflow caller (BolaWorkflow.execute()), not by
    AuthManager or the step. BolaWorkflow.execute()'s finally block
    closes both sessions. No global session pool or shared session cache.
    """

    target: str
    engagement_id: str
    state: EngagementState
    emit_finding_callback: Callable
    slog: ScanLogger  # passed from orchestrator; used for structured step logging

    # Auth configs (set by BolaWorkflow constructor, read by AuthenticateStep)
    auth_config_a: dict
    auth_config_b: dict

    # Workflow-internal state (mutated by steps)
    session_a: requests.Session | None = None
    session_b: requests.Session | None = None
    owned_resources: dict = field(default_factory=dict)
    bola_findings: int = 0
    bopla_findings: int = 0
    skip_bola: bool = False


@dataclass
class StepResult:
    """Per-step return value.

    The workflow sums findings_emitted across steps to get the total
    findings_created for WorkflowResult. skipped=True means the step
    was a no-op (e.g., session_a was None, obstacle already emitted
    by an earlier step).
    """

    success: bool
    skipped: bool = False
    findings_emitted: int = 0


@dataclass
class WorkflowResult:
    """Uniform return type for all workflow classes.

    success is set EXPLICITLY by the workflow, not derived from state.
    A clean run with zero findings is success=True, findings_created=0.
    A partially-completed run with obstacles is success=True, outcome="partial".

    findings_created is the LOCAL count of findings emitted by the workflow
    during this run. It is NOT len(state.findings) — that field is populated
    by the orchestrator's _save_findings() AFTER the scan phase completes.
    Reading state.findings during the workflow would always return 0.
    """

    success: bool
    outcome: Literal["complete", "partial"]  # complete = clean run, partial = obstacles encountered
    findings_created: int  # local sum of step.findings_emitted
    obstacles_encountered: int  # from len(ctx.state.obstacles) at execute() end
    identities_created: int  # always 0 in V1
    resources_created: int  # always 0 in V1
    requests_captured: int  # always 0 in V1
    metadata: dict = field(default_factory=dict)

    def merge_metadata(self, **kwargs: Any) -> None:
        """Update metadata dict with additional key-value pairs."""
        self.metadata.update(kwargs)


class WorkflowStep(ABC):
    """Abstract base step. Each concrete step implements run()."""

    name: str = ""

    @abstractmethod
    def run(self, ctx: WorkflowContext) -> StepResult:
        """Execute the step's logic.

        Args:
            ctx: Shared per-execution context.

        Returns:
            StepResult with success/failure, optional skip flag,
            and count of findings emitted during this step.
        """
        ...


class Workflow(ABC):
    """Abstract base for workflow orchestrators (V2+).

    V1 concrete implementations (BolaWorkflow) do NOT necessarily
    inherit from this class — it is an interface contract for future
    workflow types (IdorWorkflow, PrivilegeEscWorkflow, etc.).
    """

    @abstractmethod
    def execute(self) -> WorkflowResult:
        """Run all steps in sequence and return the aggregated result."""
        ...
