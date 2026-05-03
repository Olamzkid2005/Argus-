"""
Pipeline Router — single entry point for tool execution.

Routes to:
1. PipelineExecutor (newer, used by agent system)
2. Legacy recon/scan functions (older, used by Orchestrator)

The orchestrator should migrate to PipelineExecutor over time.
The legacy functions are retained for backward compat but emit a deprecation warning.
"""

import logging
import warnings

logger = logging.getLogger(__name__)

# When True, all executions go through PipelineExecutor.
# When False, legacy functions are used with a deprecation warning.
FORCE_PIPELINE_EXECUTOR = False


def execute_recon_pipeline(
    ctx, target: str, budget: dict, aggressiveness: str = "default"
) -> tuple[list, object]:
    """
    Execute reconnaissance tools via the appropriate pipeline.

    Args:
        ctx: ToolContext with tool_runner, parser, normalizer, ws_publisher
        target: Target URL
        budget: Budget config
        aggressiveness: Scan aggressiveness

    Returns:
        (findings list, ReconContext)
    """
    if FORCE_PIPELINE_EXECUTOR:
        from pipeline_executor import PipelineExecutor

        executor = PipelineExecutor(
            tool_runner=ctx.tool_runner,
            parser=ctx.parser,
            normalizer=ctx.normalizer,
            ws_publisher=ctx.ws_publisher,
            finding_repo=None,
        )
        return executor.execute_recon_tools(target, aggressiveness)
    else:
        warnings.warn(
            "Using legacy execute_recon_tools. Migrate to PipelineExecutor.",
            DeprecationWarning,
            stacklevel=2,
        )
        from orchestrator_pkg.recon import execute_recon_tools as _legacy_recon

        return _legacy_recon(ctx, target, budget, aggressiveness)


def execute_scan_pipeline(
    ctx, targets: list[str], budget: dict, aggressiveness: str = "default",
    auth_config: dict | None = None, tech_stack: list[str] | None = None,
    skip_tools: set | None = None,
) -> list[dict]:
    """
    Execute scanning tools via the appropriate pipeline.

    Args:
        ctx: ToolContext with tool_runner, parser, normalizer
        targets: List of target URLs
        budget: Budget config
        aggressiveness: Scan aggressiveness
        auth_config: Optional authentication configuration for scanning
        tech_stack: Detected technology stack (triggers browser scanner for SPAs)

    Returns:
        List of findings
    """
    if FORCE_PIPELINE_EXECUTOR:
        from pipeline_executor import PipelineExecutor

        executor = PipelineExecutor(
            tool_runner=ctx.tool_runner,
            parser=ctx.parser,
            normalizer=ctx.normalizer,
            ws_publisher=ctx.ws_publisher,
            finding_repo=None,
        )
        return executor.execute_scan_tools(targets, aggressiveness)
    else:
        warnings.warn(
            "Using legacy execute_scan_tools. Migrate to PipelineExecutor.",
            DeprecationWarning,
            stacklevel=2,
        )
        from orchestrator_pkg.scan import execute_scan_tools as _legacy_scan

        return _legacy_scan(ctx, targets, budget, aggressiveness, auth_config, tech_stack, skip_tools)
