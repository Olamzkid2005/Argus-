"""
DeterministicRuntime — Pure fallback runtime for when LLM is unavailable.

Extracted from orchestrator._run_deterministic_scan() logic.
Used ONLY as a fallback — never as primary execution path.
"""

import logging
from typing import Any

from pipeline_router import execute_scan_pipeline

logger = logging.getLogger(__name__)


class DeterministicRuntime:
    """
    Fallback execution runtime for when the LLM / agent is unavailable.

    Responsibilities:
    - Execute deterministic scan pipeline with phase-appropriate tools
    - No LLM calls, no reasoning, no dynamic planning
    - Pure pipeline execution with skip_tools to avoid duplication

    This runtime MUST NOT leak planning assumptions into:
    - orchestrator
    - execution layer
    - EngagementState
    - streaming layer
    """

    def __init__(
        self,
        ctx: Any,
        execution_engine: Any | None = None,
    ):
        self.ctx = ctx
        self.execution_engine = execution_engine

    def run(
        self,
        targets: list[str],
        budget: dict,
        aggressiveness: str = "default",
        auth_config: dict | None = None,
        tech_stack: list[str] | None = None,
        skip_tools: set | None = None,
        recon_context: Any = None,
    ) -> list[dict]:
        """
        Execute deterministic fallback scan.

        Args:
            targets: List of target URLs
            budget: Budget configuration
            aggressiveness: Scan aggressiveness level
            auth_config: Authentication configuration
            tech_stack: Detected technology stack for SPA detection
            skip_tools: Set of tool names to skip (already run by agent)
            recon_context: Optional ReconContext

        Returns:
            List of finding dicts
        """
        logger.info(
            "DeterministicRuntime: scanning %d targets (skip_tools=%s)",
            len(targets), skip_tools,
        )

        return execute_scan_pipeline(
            self.ctx,
            targets,
            budget,
            aggressiveness,
            auth_config,
            tech_stack=tech_stack,
            skip_tools=skip_tools,
            recon_context=recon_context,
        )

    def run_recon(
        self,
        target: str,
        budget: dict,
        aggressiveness: str = "default",
    ) -> tuple[list, Any]:
        """Execute deterministic recon."""
        from pipeline_router import execute_recon_pipeline

        logger.info("DeterministicRuntime: recon target=%s", target)
        return execute_recon_pipeline(self.ctx, target, budget, aggressiveness)
