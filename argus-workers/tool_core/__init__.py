"""
tool_core — Unified tool execution layer for Argus.

This is a **facade package** (Strangler Fig pattern). Initial implementations
import and re-export from existing locations. Implementations migrate into
``tool_core`` gradually as old code is removed.

Key types re-exported for convenience:
    - ``ToolContext``, ``AbstractTool``, ``AsyncTool``
    - ``UnifiedToolResult``, ``ToolStatus``
    - ``FindingBuilder``
    - ``ToolRegistry``
    - ``ToolRuntimeConfig``, ``ToolMetadata``
"""

from tool_core.base import AbstractTool, AsyncTool, ToolContext
from tool_core.result import ToolStatus, UnifiedToolResult
from tool_core.finding_builder import FindingBuilder
from tool_core.registry import ToolRegistry
from tool_core.config.models import ToolMetadata, ToolRuntimeConfig

__all__ = [
    "AbstractTool",
    "AsyncTool",
    "ToolContext",
    "UnifiedToolResult",
    "ToolStatus",
    "FindingBuilder",
    "ToolRegistry",
    "ToolMetadata",
    "ToolRuntimeConfig",
]
