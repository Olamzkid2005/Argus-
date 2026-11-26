#!/usr/bin/env python3
"""
Run an agent-internal tool by name via subprocess interface.

Called by the MCP server when a tool with `command: run_agent_tool` is invoked.
Dynamically imports the tool class and calls execute() with the given arguments.

Usage:
    python3 tools/run_agent_tool.py <tool_name> --target <url> [--param value ...]
"""

import argparse
import importlib
import json
import os
import sys
import time

# Ensure the parent directory is on the path so tools/ can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


_RUNNER_SCRIPT = "argus-workers/tools/run_agent_tool.py"


def _registry_agent_tools() -> frozenset[str]:
    """Agent-internal tool names from the canonical declarative registry.

    A tool runs through this launcher when the registry (generated from
    ``tools/definitions/*.yaml``) invokes it via this script with the tool
    name as the next argument. Deriving the set here keeps this allowlist
    from drifting out of sync with the YAML source of truth.
    """
    from tool_definitions import TOOLS

    names: set[str] = set()
    for name, tool in TOOLS.items():
        args = list(getattr(tool, "default_args", None) or [])
        if _RUNNER_SCRIPT in args:
            idx = args.index(_RUNNER_SCRIPT)
            if idx + 1 < len(args) and args[idx + 1] == name:
                names.add(name)
    return frozenset(names)


#: Standalone fallback when the registry cannot be imported (e.g. the script
#: is copied outside the worker tree). Must mirror ``_registry_agent_tools()``
#: — ``test_static_allowlist_matches_registry`` enforces this in CI.
_STATIC_ALLOWED_TOOLS = frozenset({
    "ai_vuln_scanner",
    "assessment_orchestrator",
    "attack_path_generator",
    "attack_surface_mapper",
    "browser_security_operator",
    "cloud_metadata_probe",
    "engagement_analytics_engine",
    "evidence_intelligence_engine",
    "executive_report_generator",
    "finding_correlation_engine",
    "infrastructure_security_analyzer",
    "login",
    "register",
    "secure_code_intelligence_engine",
    "threat_intelligence_aggregator",
    "verification_agent",
    "vulnerability_knowledge_engine",
    "web_scanner",
    "workflow_intelligence_engine",
})


def _load_allowed_tools() -> frozenset[str]:
    try:
        derived = _registry_agent_tools()
    except Exception as exc:  # registry unavailable — stay runnable
        logger.warning("registry unavailable (%s); using static tool allowlist", exc)
        return _STATIC_ALLOWED_TOOLS
    if not derived:
        logger.warning("registry yielded no agent tools; using static tool allowlist")
        return _STATIC_ALLOWED_TOOLS
    return derived


ALLOWED_TOOLS = _load_allowed_tools()


def resolve_tool_class(tool_name: str):
    """Dynamically import the tool module and find the AbstractTool subclass."""
    if tool_name not in ALLOWED_TOOLS:
        raise ValueError(
            f"Tool {tool_name!r} is not in the allowed tools list"
        )
    module = importlib.import_module(f"tools.{tool_name}")

    from tool_core.base import AbstractTool

    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if (
            isinstance(attr, type)
            and issubclass(attr, AbstractTool)
            and attr is not AbstractTool
        ):
            return attr

    raise ValueError(f"No AbstractTool subclass found in tools.{tool_name}")


def main():
    parser = argparse.ArgumentParser(description="Run an agent-internal tool")
    parser.add_argument("tool_name", help="Name of the tool to run")
    parser.add_argument("--target", required=True, help="Target URL or scope")
    parser.add_argument("--engagement-id", default="", help="Engagement ID")
    parser.add_argument(
        "--extra",
        default="{}",
        help='JSON-encoded extra parameters (e.g. \'{"tech_stack":["apache"]}\')',
    )
    parser.add_argument(
        "--goal-node-id",
        default="",
        help="Goal the claimed intent serves; stamped on every finding produced",
    )
    parser.add_argument(
        "--intent-node-id",
        default="",
        help="Intent this run works; stamped on every finding produced",
    )
    args = parser.parse_args()

    extra = json.loads(args.extra)
    start = time.time()

    from tool_core.base import ToolContext

    # Attribution may arrive as a flag (the MCP server forwards it from the
    # intent package) or inside --extra. Flags win.
    goal_node_id = args.goal_node_id or str(extra.get("goal_node_id") or "")
    intent_node_id = args.intent_node_id or str(extra.get("intent_node_id") or "")

    ctx = ToolContext(
        target=args.target,
        engagement_id=args.engagement_id,
        goal_node_id=goal_node_id,
        intent_node_id=intent_node_id,
        tech_stack=extra.get("tech_stack", []),
        authorized_scope=extra.get("scope", args.target),
        timeout=extra.get("timeout", 300),
        rate_limit=extra.get("rate_limit", 0),
        aggressiveness=extra.get("aggressiveness", "moderate"),
        emit_finding=None,
        trace_id=extra.get("trace_id", ""),
        dual_auth=None,
    )

    # Set extra context attributes that tools may expect (e.g. _correlation_input, _orchestrator_start_phase)
    for key, value in extra.items():
        setattr(ctx, f"_{key}", value)

    tool_class = resolve_tool_class(args.tool_name)
    tool_instance = tool_class()
    result = tool_instance.execute(ctx)
    duration_ms = int((time.time() - start) * 1000)

    # Stamp the worker's goal on the findings, including those a tool built
    # without a FindingBuilder (the verifier's own promotion keeps an explicit
    # attribution and is therefore never overwritten).
    from tool_core.goal_attribution import stamp_goal_attribution

    stamp_goal_attribution(
        result.findings, goal_node_id=goal_node_id, intent_node_id=intent_node_id
    )

    output = {
        "success": result.status.is_ok,
        "data": result.output,
        "findings": result.findings,
        "findings_count": result.findings_count,
        "goal_node_id": goal_node_id,
        "intent_node_id": intent_node_id,
        "signal_quality": getattr(result, "signal_quality", "PROBABLE"),
        "duration_ms": duration_ms,
        "error": result.error_message or "",
    }
    print(json.dumps(output))
    sys.exit(0 if result.status.is_ok else 1)


if __name__ == "__main__":
    main()
