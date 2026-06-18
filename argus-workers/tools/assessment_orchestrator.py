"""
Assessment Orchestrator — coordinates all assessment phases.

Executes tools in each phase by delegating to the MCP server's
planning pipeline (handle_agent_init / handle_agent_next / handle_agent_observe).
Fixes H7: orchestrator actually executes tools instead of just logging phases.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server import get_mcp_server
from tool_core.base import AbstractTool, ToolContext
from tool_core.finding_builder import FindingBuilder
from tool_core.result import ToolStatus, UnifiedToolResult

logger = logging.getLogger(__name__)

PHASE_ORDER = ["recon", "scan", "deep_scan", "repo_scan", "analyze", "report"]
PHASE_DESCRIPTIONS = {
    "recon": "Reconnaissance",
    "scan": "Vulnerability scanning",
    "deep_scan": "Deep scanning",
    "repo_scan": "Repository scanning",
    "analyze": "Analysis",
    "report": "Reporting",
}

# Phase → pipeline tool IDs used to seed the planning engine
PHASE_PIPELINE_TOOLS: dict[str, list[str]] = {
    "recon": ["subfinder", "httpx", "whatweb", "nmap", "gospider"],
    "scan": ["nuclei", "nikto", "dalfox", "wafw00f"],
    "deep_scan": ["nuclei", "sqlmap", "testssl", "commix"],
    "repo_scan": ["semgrep", "gitleaks", "trufflehog", "bandit"],
    "analyze": [],
    "report": [],
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
        end_idx = (
            PHASE_ORDER.index(end_phase)
            if end_phase in PHASE_ORDER
            else len(PHASE_ORDER) - 1
        )
        planned_phases = PHASE_ORDER[start_idx : end_idx + 1]

        builder.info(
            "ORCHESTRATION_PLAN",
            ctx.target,
            {"total_phases": len(planned_phases), "phases": planned_phases},
        )

        phase_results: dict[str, list[dict[str, Any]]] = {}
        mcp = get_mcp_server()

        for phase in planned_phases:
            builder.info(
                "PHASE_STARTED",
                ctx.target,
                {"phase": phase, "description": PHASE_DESCRIPTIONS.get(phase, phase)},
            )

            # Initialize a plan for this phase via the MCP server's planning engine
            pipeline_tools = PHASE_PIPELINE_TOOLS.get(phase, [])
            init_params = {
                "target": ctx.target,
                "phase": phase,
                "techStack": ctx.tech_stack or [],
                "pipeline": [{"tool": t} for t in pipeline_tools],
                "context": {
                    "engagement_id": ctx.engagement_id,
                    "authorized_scope": ctx.authorized_scope,
                },
            }
            session_result = mcp.handle_agent_init(init_params)
            session_id = session_result.get("session_id", "")
            tool_order = session_result.get("plan", [])

            phase_tool_results = []
            for tool_name in tool_order:
                try:
                    tool_result = mcp.call_tool(
                        tool_name,
                        arguments={"target": ctx.target},
                        timeout=getattr(ctx, "timeout", 120),
                    )
                    phase_tool_results.append(tool_result)

                    # Emit via builder
                    if tool_result.get("meta", {}).get("data", {}).get("structured"):
                        for finding_data in tool_result["meta"]["data"]["structured"]:
                            builder.add(
                                finding_type=finding_data.get("type", "SCAN_RESULT"),
                                severity=finding_data.get("severity", "INFO"),
                                endpoint=finding_data.get("endpoint", ctx.target),
                                evidence=finding_data.get("evidence", {}),
                                confidence=finding_data.get("confidence", 0.5),
                            )

                    # Record observation for planning engine
                    mcp.handle_agent_observe(
                        {
                            "session_id": session_id,
                            "tool": tool_name,
                            "arguments": {"target": ctx.target},
                            "success": tool_result.get("isError", False) is False,
                            "findingCount": len(
                                tool_result.get("meta", {})
                                .get("data", {})
                                .get("structured", [])
                            ),
                            "summary": f"Executed {tool_name} against {ctx.target}",
                        }
                    )
                except Exception as tool_err:
                    logger.warning(
                        "Tool %s failed in phase %s: %s", tool_name, phase, tool_err
                    )
                    phase_tool_results.append({"error": str(tool_err)})
                    mcp.handle_agent_observe(
                        {
                            "session_id": session_id,
                            "tool": tool_name,
                            "arguments": {"target": ctx.target},
                            "success": False,
                            "findingCount": 0,
                            "summary": f"Tool {tool_name} failed: {tool_err}",
                        }
                    )

            phase_results[phase] = phase_tool_results
            builder.info(
                "PHASE_COMPLETE",
                ctx.target,
                {
                    "phase": phase,
                    "tools_executed": len(phase_tool_results),
                    "findings": len(builder.findings),
                },
            )

        builder.info(
            "ORCHESTRATION_COMPLETE",
            ctx.target,
            {
                "total_phases": len(planned_phases),
                "results_by_phase": {k: len(v) for k, v in phase_results.items()},
            },
        )

        result.findings = builder.findings
        result.findings_count = len(builder.findings)
        result.status = ToolStatus.SUCCESS
        result.mark_finished()
        return result
