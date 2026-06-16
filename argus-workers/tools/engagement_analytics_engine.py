"""
Engagement Analytics Engine — cross-engagement analysis, trends, benchmarks.
"""

from __future__ import annotations

import logging
from collections import Counter

from tool_core.base import AbstractTool, ToolContext
from tool_core.finding_builder import FindingBuilder
from tool_core.result import ToolStatus, UnifiedToolResult

logger = logging.getLogger(__name__)


class EngagementAnalyticsEngine(AbstractTool):
    """Analyzes findings across engagements for portfolio-wide insights."""

    tool_name: str = "engagement_analytics_engine"

    def execute(self, ctx: ToolContext) -> UnifiedToolResult:
        result = UnifiedToolResult(tool_name=self.tool_name, target=ctx.target)
        builder = FindingBuilder(self.tool_name, engagement_id=ctx.engagement_id)

        all_findings = getattr(ctx, "_analytics_findings", None)
        engagements = getattr(ctx, "_analytics_engagements", None)

        if not all_findings and not engagements:
            result.status = ToolStatus.SUCCESS_EMPTY
            result.mark_finished()
            return result

        analysis = self._analyze(all_findings or [], engagements or [])
        builder.info("ENGAGEMENT_ANALYTICS", ctx.target, analysis)

        result.findings = builder.findings
        result.findings_count = len(builder.findings)
        result.status = ToolStatus.SUCCESS
        result.mark_finished()
        return result

    def _analyze(self, all_findings: list[dict], engagements: list[dict]) -> dict:
        cwe_counter: Counter = Counter()
        type_counter: Counter = Counter()
        severity_counter: Counter = Counter()
        tool_counter: Counter = Counter()

        for f in all_findings:
            cwe_counter[f.get("cwe") or f.get("cwe_id") or "UNKNOWN"] += 1
            type_counter[f.get("type", "UNKNOWN")] += 1
            severity_counter[f.get("severity", "INFO")] += 1
            tool_counter[f.get("source_tool", "unknown")] += 1

        top_cwes = [{"cwe": c, "count": n} for c, n in cwe_counter.most_common(10)]
        top_types = [{"type": t, "count": n} for t, n in type_counter.most_common(10)]

        return {
            "total_engagements": len(engagements),
            "total_findings": len(all_findings),
            "severity_distribution": dict(severity_counter),
            "most_common_cwe": top_cwes[0]["cwe"] if top_cwes else "N/A",
            "most_common_type": top_types[0]["type"] if top_types else "N/A",
            "top_cwes": top_cwes,
            "top_finding_types": top_types,
        }
