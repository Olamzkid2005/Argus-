"""
LLM Refiner — standalone function for LLM-driven replanning.

Bridges the existing mcp_server.py handle_phase_complete() logic to the CLI
without needing the full MCP bridge. After each phase completes, the LLM
analyzes accumulated findings and suggests next capabilities.

Usage:
    from reporting.llm_refiner import llm_replan_from_findings

    result = llm_replan_from_findings(
        engagement_id="...",
        phase="scan",
        target="https://example.com",
        findings=[...],
    )
    if not result.get("stop"):
        next_caps = result.get("next_capabilities", [])
        # Feed next_caps into the planner for the next phase

Architecture:
    This is the standalone CLI bridge for the LLM replanning feedback loop
    (Tier 2.2a from the re-scoped plan). The actual LLM orchestration is
    handled by ReActAgent.plan_next_phase().
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def llm_replan_from_findings(
    engagement_id: str,
    phase: str,
    target: str,
    findings: list[dict] | None = None,
) -> dict[str, Any]:
    """Use an LLM to analyze findings and suggest next capabilities.

    This is the standalone equivalent of mcp_server.MCPServer.handle_phase_complete().
    It does NOT require the MCP bridge, websocket connection, or Redis.

    Args:
        engagement_id: Engagement UUID.
        phase: The phase that just completed (e.g. "recon", "scan").
        target: The assessment target URL.
        findings: Accumulated findings so far.

    Returns:
        Dict with:
            - next_capabilities: list[str] — suggested capabilities for next phase
            - reasoning: str — LLM reasoning text
            - stop: bool — whether to stop the assessment
    """
    findings = findings or []

    if not engagement_id:
        return {
            "next_capabilities": [],
            "reasoning": "No engagement_id provided",
            "stop": True,
        }

    # Build LLM refiner prompt context
    if not findings:
        return {
            "next_capabilities": [],
            "reasoning": "No findings to analyze — continuing with default plan",
            "stop": False,
        }

    try:
        from llm_client import LLMClient

        llm_client = LLMClient()
    except Exception as e:
        logger.debug("Failed to create LLMClient for replan: %s", e)
        return _fallback_replan(phase, findings)

    if not llm_client.is_available():
        logger.debug("LLM not available for replan — using fallback")
        return _fallback_replan(phase, findings)

    try:
        from agent.react_agent import ReActAgent
        from tool_core.registry import ToolRegistry

        registry = ToolRegistry()
        agent = ReActAgent(
            registry,
            llm_client=llm_client,
            engagement_id=engagement_id,
            phase=phase,
        )

        result = agent.plan_next_phase(
            findings=findings,
            phase=phase,
            target=target,
        )

        logger.info(
            "LLM replan for engagement=%s phase=%s: next_capabilities=%s, stop=%s",
            engagement_id,
            phase,
            result.get("next_capabilities", []),
            result.get("stop", False),
        )

        return result

    except Exception as e:
        logger.warning(
            "LLM replan failed for engagement=%s: %s. Using fallback.",
            engagement_id,
            e,
        )
        return _fallback_replan(phase, findings)


def _fallback_replan(phase: str, findings: list[dict] | None = None) -> dict[str, Any]:
    """Fallback phase progression when LLM is unavailable.

    Uses deterministic rules based on finding severity to suggest
    next capabilities.

    Args:
        phase: The phase that just completed.
        findings: Accumulated findings.

    Returns:
        Dict with next_capabilities, reasoning, stop.
    """
    findings = findings or []

    if not findings:
        return {
            "next_capabilities": [],
            "reasoning": "No findings produced — stopping assessment",
            "stop": True,
        }

    # Check for high/critical findings that warrant escalation
    has_critical = any(
        (f.get("severity") or "").upper() == "CRITICAL" for f in findings
    )
    has_high = any(
        (f.get("severity") or "").upper() == "HIGH" for f in findings
    )

    if has_critical:
        return {
            "next_capabilities": [
                "vulnerability_scanning",
                "exploitation",
                "post_exploitation",
            ],
            "reasoning": (
                f"Found CRITICAL findings after {phase} phase — "
                "escalating to exploitation and post-exploitation"
            ),
            "stop": False,
        }

    if has_high:
        return {
            "next_capabilities": [
                "vulnerability_scanning",
                "deep_scan",
            ],
            "reasoning": (
                f"Found HIGH findings after {phase} phase — "
                "recommending deeper scanning"
            ),
            "stop": False,
        }

    # Default: continue with standard next phase
    next_phase_map = {
        "recon": ["vulnerability_scanning"],
        "scan": ["security_analysis"],
        "analyze": ["report_generation"],
    }

    return {
        "next_capabilities": next_phase_map.get(phase, []),
        "reasoning": (
            f"No critical findings after {phase} phase — "
            "continuing with standard progression"
        ),
        "stop": False,
    }
