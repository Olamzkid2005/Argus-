"""
Formal types for the tool execution layer.

**DEPRECATED:** Use ``tool_core.result.UnifiedToolResult`` instead.

``ToolResult`` is kept as a backward-compatible alias that constructs
a ``UnifiedToolResult`` under the hood. All new code should import
from ``tool_core.result``.
"""

from __future__ import annotations

import logging
from typing import Any

from tool_core.result import ToolStatus, UnifiedToolResult

logger = logging.getLogger(__name__)


class ToolResult(UnifiedToolResult):
    """
    **DEPRECATED:** Legacy return type for ``ToolRunner.run()``.

    Replaced by ``UnifiedToolResult`` from ``tool_core.result``.
    This class is kept for backward compatibility and constructs a
    ``UnifiedToolResult`` under the hood. All fields are mapped to
    their ``UnifiedToolResult`` equivalents.

    .. deprecated::
        Use ``from tool_core.result import UnifiedToolResult`` instead.
    """

    def __init__(
        self,
        stdout: str = "",
        stderr: str = "",
        returncode: int = 0,
        tool: str = "",
        success: bool = True,
        duration_ms: int = 0,
        timeout: bool = False,
        error: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        logger.warning(
            "DEPRECATED: tools.models.ToolResult is deprecated. "
            "Use tool_core.result.UnifiedToolResult instead. "
            "Called from %s",
            __import__("traceback").extract_stack(limit=2)[-2].name,
        )

        # Map legacy fields to UnifiedToolResult
        if timeout:
            status = ToolStatus.TIMEOUT
        elif success:
            status = ToolStatus.SUCCESS
        else:
            status = ToolStatus.NONZERO_EXIT

        super().__init__(
            tool_name=tool,
            status=status,
            stdout=stdout,
            stderr=stderr,
            exit_code=returncode,
            duration_seconds=duration_ms / 1000.0,
            error_message=error or "",
        )

    # Legacy property aliases (read/write for backward compat)
    @property
    def returncode(self) -> int | None:
        return self.exit_code

    @returncode.setter
    def returncode(self, value: int) -> None:
        self.exit_code = value

    @property
    def tool(self) -> str:
        return self.tool_name

    @tool.setter
    def tool(self, value: str) -> None:
        self.tool_name = value

    @property
    def success(self) -> bool:
        return self.status.is_ok

    @success.setter
    def success(self, value: bool) -> None:
        self.status = ToolStatus.SUCCESS if value else ToolStatus.NONZERO_EXIT

    @property
    def timeout(self) -> bool:
        return self.status == ToolStatus.TIMEOUT

    @timeout.setter
    def timeout(self, value: bool) -> None:
        if value:
            self.status = ToolStatus.TIMEOUT

    @property
    def error(self) -> str | None:
        return self.error_message or None

    @error.setter
    def error(self, value: str | None) -> None:
        self.error_message = value or ""

    @property
    def duration_ms(self) -> int:
        return int(self.duration_seconds * 1000)

    @duration_ms.setter
    def duration_ms(self, value: int) -> None:
        self.duration_seconds = value / 1000.0

    @property
    def trace_id(self) -> str:
        return ""

    @trace_id.setter
    def trace_id(self, value: str) -> None:
        pass  # No-op — field removed in UnifiedToolResult

    def as_dict(self) -> dict[str, Any]:
        """Return as plain dict (for JSON serialization, backward compat)."""
        return self.to_legacy_dict()
