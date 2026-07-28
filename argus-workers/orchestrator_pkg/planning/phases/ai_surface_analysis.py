"""Phase: ai_surface_analysis — AI attack-surface scanning of source code.

Activated when source code access is available. Runs the ai-surface scanner
to detect MCP servers, agent frameworks, LLM SDKs, model gateways, vector
stores, AI provider keys, and API endpoints from source code.
"""

from __future__ import annotations

from ._types import ToolTask, _get_attr


def _activate_ai_surface_analysis(rc) -> tuple[bool, str]:
    """Activate when source code is available (repo scan type).

    Uses ReconContext.scan_type which is set during engagement
    creation (before any scanning phases begin), avoiding a timing
    dependency on has_source_access being populated by a scanner.
    """
    scan_type = _get_attr(rc, "scan_type", "url")
    if scan_type == "repo":
        return True, "source code access available — scanning for AI attack surfaces"
    return False, "no source code access — URL-scan engagement"


def _ai_surface_analysis_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for the source_analysis phase.

    Runs the ai-surface static scanner against the source code root.
    """
    return [
        ToolTask(
            tool_name="ai-surface",
            description="Static AI attack-surface scan: MCP, agents, LLMs, RAG, gateways, keys",
            priority=10,
            timeout=300,
            args_template=["{target}", "--output", "json"],
        ),
    ]
