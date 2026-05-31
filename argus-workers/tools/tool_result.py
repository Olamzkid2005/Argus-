"""
tools/tool_result.py — StructuredToolResult (backward-compat re-export)

**DEPRECATED:** Import directly from ``tool_core.result`` instead.

.. code-block:: python

    # Old (still works):
    from tools.tool_result import StructuredToolResult, ToolStatus

    # New (preferred):
    from tool_core.result import UnifiedToolResult, ToolStatus
"""

from tool_core.result import ToolStatus, UnifiedToolResult  # noqa: F401

# Backward-compat alias — StructuredToolResult is now UnifiedToolResult
StructuredToolResult = UnifiedToolResult

__all__ = ["StructuredToolResult", "ToolStatus"]
