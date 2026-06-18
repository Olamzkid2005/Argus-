"""
Workflow Intelligence Engine — execution metrics, bottleneck detection.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from tool_core.base import AbstractTool, ToolContext
from tool_core.finding_builder import FindingBuilder
from tool_core.result import ToolStatus, UnifiedToolResult

logger = logging.getLogger(__name__)


class WorkflowIntelligenceEngine(AbstractTool):
    """Analyzes workflow execution metrics and recommends optimizations."""

    tool_name: str = "workflow_intelligence_engine"

    def execute(self, ctx: ToolContext) -> UnifiedToolResult:
        result = UnifiedToolResult(tool_name=self.tool_name, target=ctx.target)
        builder = FindingBuilder(self.tool_name, engagement_id=ctx.engagement_id)
        metrics = getattr(ctx, "_workflow_metrics", None)

        if not metrics or not isinstance(metrics, list):
            result.status = ToolStatus.SUCCESS_EMPTY
            result.mark_finished()
            return result

        analysis = self._analyze_metrics(metrics)
        builder.info("WORKFLOW_ANALYSIS", ctx.target, analysis)
        for rec in analysis.get("recommendations", []):
            builder.info("WORKFLOW_RECOMMENDATION", ctx.target, rec)

        result.findings = builder.findings
        result.findings_count = len(builder.findings)
        result.status = ToolStatus.SUCCESS
        result.mark_finished()
        return result

    def _analyze_metrics(self, metrics: list[dict]) -> dict:
        tool_times: dict[str, list[float]] = defaultdict(list)
        tool_failures: dict[str, int] = defaultdict(int)
        tool_calls: dict[str, int] = defaultdict(int)

        for m in metrics:
            tool = m.get("tool", "unknown")
            tool_times[tool].append(m.get("duration_seconds", 0))
            tool_calls[tool] += 1
            if not m.get("success", True):
                tool_failures[tool] += 1

        avg_times = {t: round(sum(ts) / len(ts), 2) for t, ts in tool_times.items()}
        slowest = sorted(avg_times.items(), key=lambda x: x[1], reverse=True)

        recommendations = []
        for tool, avg_time in slowest[:3]:
            if avg_time > 300:
                recommendations.append(
                    {
                        "tool": tool,
                        "type": "slow_execution",
                        "message": f"{tool} averages {avg_time}s",
                    }
                )
        for tool, failures in tool_failures.items():
            calls = tool_calls.get(tool, 1)
            if failures / calls > 0.3:
                recommendations.append(
                    {
                        "tool": tool,
                        "type": "high_failure_rate",
                        "message": f"{tool} has {failures}/{calls} failures",
                    }
                )

        total_calls = sum(tool_calls.values())
        total_failures = sum(tool_failures.values())
        return {
            "total_tool_calls": total_calls,
            "total_failures": total_failures,
            "failure_rate": round(total_failures / total_calls, 3)
            if total_calls > 0
            else 0,
            "slowest_tools": [{"tool": t, "avg_seconds": s} for t, s in slowest[:5]],
            "recommendations": recommendations,
        }
