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
    "repo_scan": ["semgrep", "bandit", "brakeman", "eslint", "gosec", "phpcs", "spotbugs", "dependency_check", "govulncheck", "npm-audit", "pip-audit", "trivy", "gitleaks", "trufflehog"],
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

            # Create scope validator once per phase (reused for all tools)
            _scope_validator = None
            if getattr(ctx, "authorized_scope", None):
                try:
                    from tools.scope_validator import ScopeValidator

                    _scope_validator = ScopeValidator(
                        ctx.engagement_id, ctx.authorized_scope
                    )
                except Exception as _scope_err:
                    logger.warning(
                        "Failed to create scope validator for phase %s (engagement %s): %s — "
                        "scope enforcement disabled for this phase",
                        phase,
                        ctx.engagement_id,
                        _scope_err,
                    )

            # Phase 4.1.1: Checkpoint manager for mid-phase tool-level checkpointing
            try:
                from checkpoint_manager import CheckpointManager
                _cp_mgr = CheckpointManager()
                # Query completed tools for this phase (if resuming)
                _completed_tools = _cp_mgr.get_completed_tools(ctx.engagement_id, phase) if ctx.engagement_id else []
            except Exception:
                _cp_mgr = None
                _completed_tools = []

            phase_tool_results = []
            for tool_name in tool_order:
                # Phase 4.1.3: Skip tools that already have checkpoints (on resume)
                if tool_name in _completed_tools:
                    logger.info("Skipping tool %s — already checkpointed in phase %s (resume)", tool_name, phase)
                    continue

                try:
                    tool_result = mcp.call_tool(
                        tool_name,
                        arguments={"target": ctx.target},
                        timeout=getattr(ctx, "timeout", 120),
                        engagement_id=ctx.engagement_id,
                        scope_validator=_scope_validator,
                    )
                    phase_tool_results.append(tool_result)

                    # Phase 4.1.2: Save checkpoint after each successful tool execution
                    if _cp_mgr and ctx.engagement_id and tool_result.get("isError", False) is False:
                        _cp_mgr.save_tool_checkpoint(
                            ctx.engagement_id,
                            phase,
                            tool_name,
                            {"status": "completed", "tool": tool_name, "phase": phase},
                        )

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

            # ── Phase 3.1.1: Browser verification recommendation ──
            # After each phase's tools complete, check if findings exceed a
            # configurable threshold. If so, emit a VERIFICATION_RECOMMENDED
            # finding so the TypeScript workflow runner can trigger browser
            # verification on the most severe findings.
            _verification_threshold = getattr(ctx, "verification_threshold", 3)
            _high_crit = [
                f for f in builder.findings
                if f.get("severity", 0) >= _verification_threshold
            ]
            if len(_high_crit) >= _verification_threshold:
                builder.info(
                    "VERIFICATION_RECOMMENDED",
                    ctx.target,
                    {
                        "phase": phase,
                        "high_severity_count": len(_high_crit),
                        "threshold": _verification_threshold,
                        "recommendation": (
                            f"Browser verification recommended for {len(_high_crit)} "
                            f"findings in phase '{phase}'"
                        ),
                    },
                )
                logger.info(
                    "Phase %s: %d findings exceed threshold %d — "
                    "browser verification recommended",
                    phase,
                    len(_high_crit),
                    _verification_threshold,
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
