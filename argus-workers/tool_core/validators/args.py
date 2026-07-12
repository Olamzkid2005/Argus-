"""
tool_core/validators/args.py — Argument validation facade.

Re-exports from ``tools.tool_runner`` — the canonical implementation.
During migration, the dangerous-pattern logic moves into ``tool_core``.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def is_dangerous(args: list[str], tool: str = "") -> tuple[bool, str]:
    """
    Check if a list of command-line arguments contains dangerous patterns.

    Delegates to ``tools.tool_runner.ToolRunner.is_dangerous()`` if available;
    otherwise performs a basic shell-metacharacter check.

    Args:
        args: List of CLI argument strings.
        tool: Optional tool name for more refined validation.

    Returns:
        ``(is_dangerous: bool, reason: str)`` — if safe, ``(False, "")``.
    """
    try:
        from tools.tool_runner import ToolRunner

        runner = ToolRunner()
        if runner.is_dangerous(tool, args):
            return True, f"ToolRunner flagged args for {tool!r} as dangerous"
        return False, ""
    except (ImportError, AttributeError, TypeError):
        pass

    # Fallback: basic shell metacharacter check matching mcp_server pattern
    dangerous_chars = set(";&|`$(){}[]!<>#\n\t")
    for i, arg in enumerate(args):
        if any(c in arg for c in dangerous_chars):
            return (
                True,
                f"Argument at position {i} contains shell metacharacters: {arg!r}",
            )
        if ".." in arg:
            return True, f"Argument at position {i} contains path traversal: {arg!r}"

    return False, ""


__all__ = ["is_dangerous"]
