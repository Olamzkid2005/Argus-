"""
tools/tool_result.py — StructuredToolResult (backward-compat re-export)

**DEPRECATED:** Import directly from ``tool_core.result`` instead.

.. code-block:: python

    # Old (still works, but emits a DeprecationWarning):
    from tools.tool_result import StructuredToolResult, ToolStatus

    # New (preferred):
    from tool_core.result import UnifiedToolResult, ToolStatus

.. versionchanged:: 0.2.0
    ``StructuredToolResult`` is now an alias for ``UnifiedToolResult``.
    This file may be removed in a future release.
"""

from __future__ import annotations

import warnings

from tool_core.result import ToolStatus, UnifiedToolResult  # noqa: F401

# Backward-compat alias — StructuredToolResult is now UnifiedToolResult
StructuredToolResult = UnifiedToolResult

warnings.warn(
    "tools.tool_result is deprecated; import from tool_core.result instead. "
    "See https://argus.readthedocs.io/en/latest/migration/tool-core.html",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["StructuredToolResult", "ToolStatus"]
