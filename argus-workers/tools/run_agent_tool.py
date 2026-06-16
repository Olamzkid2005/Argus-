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


def resolve_tool_class(tool_name: str):
    """Dynamically import the tool module and find the AbstractTool subclass."""
    module = importlib.import_module(f"tools.{tool_name}")

    from tool_core.base import AbstractTool
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if isinstance(attr, type) and issubclass(attr, AbstractTool) and attr is not AbstractTool:
            return attr

    raise ValueError(f"No AbstractTool subclass found in tools.{tool_name}")


def main():
    parser = argparse.ArgumentParser(description="Run an agent-internal tool")
    parser.add_argument("tool_name", help="Name of the tool to run")
    parser.add_argument("--target", required=True, help="Target URL or scope")
    parser.add_argument("--engagement-id", default="", help="Engagement ID")
    parser.add_argument("--extra", default="{}", help='JSON-encoded extra parameters (e.g. \'{"tech_stack":["apache"]}\')')
    args = parser.parse_args()

    extra = json.loads(args.extra)
    start = time.time()

    from tool_core.base import ToolContext
    ctx = ToolContext(
        target=args.target,
        engagement_id=args.engagement_id,
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

    output = {
        "success": result.status.is_ok,
        "data": result.output,
        "findings": result.findings,
        "findings_count": result.findings_count,
        "signal_quality": getattr(result, "signal_quality", "PROBABLE"),
        "duration_ms": duration_ms,
        "error": result.error_message or "",
    }
    print(json.dumps(output))
    sys.exit(0 if result.status.is_ok else 1)


if __name__ == "__main__":
    main()
