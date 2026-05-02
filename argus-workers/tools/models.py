"""
Formal types for the tool execution layer.
Consolidates the implicit dict contract of ToolRunner.run() into a typed dataclass.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    """
    Formal return type for ToolRunner.run().

    Replaces the implicit dict contract (callers doing .get("stdout", ""))
    with a typed dataclass that all callers can depend on.
    """

    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    tool: str = ""
    success: bool = True
    duration_ms: int = 0
    timeout: bool = False
    error: str | None = None
    trace_id: str | None = None

    @property
    def output(self) -> str:
        """Combined stdout+stderr for convenience."""
        if self.stderr and self.stdout:
            return self.stdout + "\n" + self.stderr
        return self.stdout or self.stderr or ""

    def as_dict(self) -> dict[str, Any]:
        """Return as plain dict (for JSON serialization, backward compat)."""
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
            "tool": self.tool,
            "success": self.success,
            "duration_ms": self.duration_ms,
            "timeout": self.timeout,
            "error": self.error,
            "trace_id": self.trace_id,
        }
