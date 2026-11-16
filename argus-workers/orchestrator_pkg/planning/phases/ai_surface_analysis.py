"""Phase: ai_surface_analysis — source-code security analysis.

Activated when source code access is available. ai-surface itself now probes
live HTTP AI endpoints, so this phase runs the code-intelligence engine over
the source tree (secrets, SAST, dependencies). The AI/LLM surface detection
for URL targets happens in-process during recon (detect_ai_surface).
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

    Runs the code-intelligence engine against the source-code root. ai-surface is
    deliberately not used here: it probes HTTP endpoints, not files.
    """
    return [
        ToolTask(
            tool_name="secure_code_intelligence_engine",
            description="Source-code security analysis: secrets, SAST, dependency scanning",
            priority=10,
            timeout=300,
            args_template=["{target}"],
        ),
    ]
