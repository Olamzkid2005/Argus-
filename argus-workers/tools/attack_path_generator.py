"""
Attack Path Generator — graph-based attack path discovery.

Combines:
- Asset graph building from findings
- BFS path finding from entry to crown jewels
- Path scoring by severity and length
- Text and Mermaid visualization
- LLM-assisted narrative generation
"""

from __future__ import annotations

import logging

from tool_core.base import AbstractTool, ToolContext
from tool_core.finding_builder import FindingBuilder
from tool_core.result import ToolStatus, UnifiedToolResult

from .attack_paths.asset_graph_builder import build_asset_graph
from .attack_paths.path_finder import find_paths
from .attack_paths.path_scorer import rank_paths
from .attack_paths.path_visualizer import render_all_paths, render_mermaid
from .attack_paths.narrative_generator import generate_narrative

logger = logging.getLogger(__name__)


class AttackPathGenerator(AbstractTool):
    """Generates attack paths from findings using graph analysis."""

    tool_name: str = "attack_path_generator"

    def execute(self, ctx: ToolContext) -> UnifiedToolResult:
        result = UnifiedToolResult(
            tool_name=self.tool_name,
            target=ctx.target,
        )

        input_findings = getattr(ctx, "_attack_path_input", None)
        if not input_findings or not isinstance(input_findings, list):
            result.status = ToolStatus.SUCCESS_EMPTY
            result.mark_finished()
            return result

        builder = FindingBuilder(self.tool_name, engagement_id=ctx.engagement_id)

        graph = build_asset_graph(input_findings)
        paths = find_paths(graph, input_findings)
        ranked = rank_paths(paths, input_findings)

        text_output = render_all_paths(ranked)
        mermaid_output = render_mermaid(ranked)

        narratives = [generate_narrative(rp, input_findings) for rp in ranked[:3]]

        builder.info(
            "ATTACK_PATHS",
            ctx.target,
            {
                "path_count": len(ranked),
                "text": text_output,
                "mermaid": mermaid_output,
                "narratives": narratives,
            },
        )
        result.findings = builder.findings
        result.findings_count = len(builder.findings)

        result.status = ToolStatus.SUCCESS
        result.mark_finished()
        return result
