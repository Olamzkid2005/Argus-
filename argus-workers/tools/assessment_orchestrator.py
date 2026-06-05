"""
Assessment Orchestrator — coordinates all assessment phases.
"""

from __future__ import annotations

import logging

from tool_core.base import AbstractTool, ToolContext
from tool_core.finding_builder import FindingBuilder
from tool_core.result import ToolStatus, UnifiedToolResult

logger = logging.getLogger(__name__)

PHASE_ORDER = ["recon", "scan", "deep_scan", "repo_scan", "analyze", "report"]
PHASE_DESCRIPTIONS = {
    "recon": "Reconnaissance", "scan": "Vulnerability scanning", "deep_scan": "Deep scanning",
    "repo_scan": "Repository scanning", "analyze": "Analysis", "report": "Reporting",
}


class AssessmentOrchestrator(AbstractTool):
    """Orchestrates the full assessment workflow across all phases."""

    tool_name: str = "assessment_orchestrator"

    def execute(self, ctx: ToolContext) -> UnifiedToolResult:
        result = UnifiedToolResult(tool_name=self.tool_name, target=ctx.target)
        builder = FindingBuilder(self.tool_name, engagement_id=ctx.engagement_id)

        start_phase = getattr(ctx, "_orchestrator_start_phase", "recon")
        end_phase = getattr(ctx, "_orchestrator_end_phase", "report")
        start_idx = PHASE_ORDER.index(start_phase) if start_phase in PHASE_ORDER else 0
        end_idx = PHASE_ORDER.index(end_phase) if end_phase in PHASE_ORDER else len(PHASE_ORDER) - 1
        planned_phases = PHASE_ORDER[start_idx:end_idx + 1]

        builder.info("ORCHESTRATION_PLAN", ctx.target, {"total_phases": len(planned_phases), "phases": planned_phases})
        for phase in planned_phases:
            builder.info("PHASE_PLANNED", ctx.target, {"phase": phase, "description": PHASE_DESCRIPTIONS.get(phase, phase)})

        result.findings = builder.findings
        result.findings_count = len(builder.findings)
        result.status = ToolStatus.SUCCESS
        result.mark_finished()
        return result
