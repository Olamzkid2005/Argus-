"""
Finding Correlation Engine — deduplication, root cause analysis, attack chains.

Combines:
- Semantic deduplication (not just hash-based)
- Root cause grouping (CWE/type/host based)
- Attack chain detection (finding → finding paths)
- Priority ranking (exploitability × impact × evidence)
"""

from __future__ import annotations

import logging

from tool_core.base import AbstractTool, ToolContext
from tool_core.finding_builder import FindingBuilder
from tool_core.result import ToolStatus, UnifiedToolResult

from .correlation.attack_chain_detector import detect_attack_chains
from .correlation.deduplicator import deduplicate
from .correlation.root_cause import find_root_causes
from .correlation.priority_ranker import rank_findings

logger = logging.getLogger(__name__)


class FindingCorrelationEngine(AbstractTool):
    """Correlates findings: dedup, root cause, attack chains, priority ranking."""

    tool_name: str = "finding_correlation_engine"

    def execute(self, ctx: ToolContext) -> UnifiedToolResult:
        result = UnifiedToolResult(
            tool_name=self.tool_name,
            target=ctx.target,
        )

        input_findings = getattr(ctx, "_correlation_input", None)
        if not input_findings or not isinstance(input_findings, list):
            result.status = ToolStatus.SUCCESS_EMPTY
            result.mark_finished()
            return result

        builder = FindingBuilder(self.tool_name, engagement_id=ctx.engagement_id)

        unique_findings, dupes_removed = deduplicate(input_findings)

        root_causes = find_root_causes(unique_findings)

        attack_chains = detect_attack_chains(unique_findings)

        ranked = rank_findings(unique_findings)

        result.findings = ranked
        result.findings_count = len(ranked)

        builder.info(
            "CORRELATION_SUMMARY",
            ctx.target,
            {
                "original_count": len(input_findings),
                "duplicates_removed": dupes_removed,
                "unique_count": len(unique_findings),
                "root_causes": len(root_causes),
                "attack_chains": len(attack_chains),
            },
        )
        result.findings.extend(builder.findings)

        result.status = ToolStatus.SUCCESS
        result.mark_finished()
        return result
