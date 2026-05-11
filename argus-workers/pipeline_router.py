"""
Pipeline Router — entry point for tool execution.

Routes directly to the orchestrator_pkg recon and scan execution functions.
"""

import logging

logger = logging.getLogger(__name__)


def execute_recon_pipeline(
    ctx, target: str, budget: dict, aggressiveness: str = "default"
) -> tuple[list, object]:
    """
    Execute reconnaissance tools.

    Args:
        ctx: ToolContext with tool_runner, parser, normalizer, ws_publisher
        target: Target URL
        budget: Budget config
        aggressiveness: Scan aggressiveness

    Returns:
        (findings list, ReconContext)
    """
    from orchestrator_pkg.recon import execute_recon_tools
    return execute_recon_tools(ctx, target, budget, aggressiveness)


def execute_scan_pipeline(
    ctx, targets: list[str], budget: dict, aggressiveness: str = "default",
    auth_config: dict | None = None, tech_stack: list[str] | None = None,
    skip_tools: set | None = None,
) -> list[dict]:
    """
    Execute scanning tools.

    Args:
        ctx: ToolContext with tool_runner, parser, normalizer
        targets: List of target URLs
        budget: Budget config
        aggressiveness: Scan aggressiveness
        auth_config: Optional authentication configuration for scanning
        tech_stack: Detected technology stack (triggers browser scanner for SPAs)
        skip_tools: Set of tool names to skip

    Returns:
        List of findings
    """
    from orchestrator_pkg.scan import execute_scan_tools
    return execute_scan_tools(ctx, targets, budget, aggressiveness, auth_config, tech_stack, skip_tools)
