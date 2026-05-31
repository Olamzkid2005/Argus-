"""
tool_core/result.py — UnifiedToolResult

Single return type for all tool execution in Argus.

Evolves ``tools.tool_result.StructuredToolResult`` (which already has
``mark_finished()``, class-method constructors, ``to_report_dict()``, etc.)
by adding port-scan-specific fields and backward-compatibility methods
that make it a drop-in replacement for the legacy ``tools.models.ToolResult``.

Supersedes:
    - ``tools.models.ToolResult`` (legacy dict wrapper)
    - ``tools.port_scanner.PortScanResult``
    - Ad-hoc ``list[dict]`` returns from scanners

Backward-compat properties (so old callers accessing ``result.success``,
``result.returncode``, etc. continue working):
    - ``.success`` → ``.status.is_ok``
    - ``.returncode`` → ``.exit_code``
    - ``.tool`` → ``.tool_name``
    - ``.error`` → ``.error_message``
    - ``.duration_ms`` → ``int(.duration_seconds * 1000)``
    - ``.timeout`` → ``.status == ToolStatus.TIMEOUT``
    - ``.trace_id`` → ``""``
    - ``.output`` → combined stdout+stderr
    - ``.as_dict()`` → ``.to_legacy_dict()``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# Re-export ToolStatus for convenience
from tools.tool_result import StructuredToolResult, ToolStatus  # noqa: F401


@dataclass
class UnifiedToolResult(StructuredToolResult):
    """
    Single source of truth for one tool run.

    Built on ``StructuredToolResult`` (which already has ``ToolStatus``,
    ``mark_finished()``, class-method constructors, ``to_report_dict()``,
    ``from_exception()``, ``not_installed()``, ``timeout()``, ``skipped()``).

    Adds port-scan-specific fields and legacy compatibility methods.

    Backward-compat properties (``.success``, ``.returncode``, ``.tool``,
    ``.error``, ``.duration_ms``, ``.timeout``, ``.trace_id``, ``.output``)
    let callers treat this like the old ``tools.models.ToolResult`` with
    zero code changes.

    Example::

        result = UnifiedToolResult(tool_name="web_scanner", target="https://example.com")
        result.findings.append({...})
        result.status = ToolStatus.SUCCESS
        result.mark_finished()
        print(result.to_report_dict())
    """

    # ── Port-scan-specific (from PortScanResult) ─────────────────────
    ports: list[dict] = field(default_factory=list)
    # Each entry: {"port": 80, "protocol": "tcp", "service": "http",
    #              "version": "", "state": "open"}

    open_ports_count: int = 0

    # ── Lifecycle ────────────────────────────────────────────────────

    def mark_finished(self) -> None:
        """Extend parent to auto-count open ports."""
        super().mark_finished()
        if self.ports:
            self.open_ports_count = len(self.ports)

    # ── Backward compatibility (ToolResult shape) ────────────────────

    @property
    def success(self) -> bool:
        """Legacy ``ToolResult.success`` → ``.status.is_ok``."""
        return self.status.is_ok

    @property
    def returncode(self) -> int | None:
        """Legacy ``ToolResult.returncode`` → ``.exit_code``."""
        return self.exit_code

    @property
    def tool(self) -> str:
        """Legacy ``ToolResult.tool`` → ``.tool_name``."""
        return self.tool_name

    @property
    def error(self) -> str | None:
        """Legacy ``ToolResult.error`` → ``.error_message``."""
        return self.error_message or None

    @property
    def duration_ms(self) -> int:
        """Legacy ``ToolResult.duration_ms`` → computed from seconds."""
        return int(self.duration_seconds * 1000)

    @property
    def timeout(self) -> bool:
        """Legacy ``ToolResult.timeout`` → ``.status == ToolStatus.TIMEOUT``."""
        return self.status == ToolStatus.TIMEOUT

    @property
    def trace_id(self) -> str:
        """Legacy ``ToolResult.trace_id`` → empty (field removed in new model)."""
        return ""

    @property
    def output(self) -> str:
        """Legacy ``ToolResult.output`` → combined stdout+stderr."""
        if self.stderr and self.stdout:
            return self.stdout + "\n" + self.stderr
        return self.stdout or self.stderr or ""

    def as_dict(self) -> dict[str, Any]:
        """Legacy ``ToolResult.as_dict()`` → ``.to_legacy_dict()``."""
        return self.to_legacy_dict()

    def to_legacy_dict(self) -> dict[str, Any]:
        """
        Produce the old ``tools.models.ToolResult`` dict shape.

        Used during migration so callers expecting ``ToolResult`` can
        call ``result.to_legacy_dict()`` instead.
        """
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.exit_code if self.exit_code is not None else 0,
            "tool": self.tool_name,
            "success": self.status.is_ok,
            "duration_ms": int(self.duration_seconds * 1000),
            "timeout": self.status == ToolStatus.TIMEOUT,
            "error": self.error_message or None,
            "trace_id": "",
        }

    @classmethod
    def from_legacy_dict(cls, data: dict[str, Any], tool_name_hint: str = "") -> UnifiedToolResult:
        """
        Reconstruct from a legacy ``tools.models.ToolResult.as_dict()`` dict.

        Handles field-name mapping (``returncode`` → ``exit_code``,
        ``tool`` → ``tool_name``, ``success``/``timeout`` → ``status``).
        """
        exit_code: int | None = data.get("returncode", 0)
        timed_out = data.get("timeout", False)
        success = data.get("success", True)

        if timed_out:
            status = ToolStatus.TIMEOUT
        elif success:
            status = ToolStatus.SUCCESS
        else:
            status = ToolStatus.NONZERO_EXIT

        return cls(
            tool_name=data.get("tool", tool_name_hint),
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            exit_code=exit_code,
            status=status,
            duration_seconds=data.get("duration_ms", 0) / 1000.0,
        )

    def to_finding_list(self) -> list[dict[str, Any]]:
        """
        Extract findings as a plain list (what scanners currently return directly).

        Used during migration so ``scan()`` methods can return
        ``result.to_finding_list()`` without changing callers.
        """
        return list(self.findings)
