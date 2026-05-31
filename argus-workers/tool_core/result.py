"""
tool_core/result.py — UnifiedToolResult

Single return type for all tool execution in Argus.

Evolves ``tools.tool_result.StructuredToolResult`` (which already has
``mark_finished()``, class-method constructors, ``to_report_dict()``, etc.)
by adding port-scan-specific fields and backward-compatibility methods.

Supersedes:
    - ``tools.models.ToolResult`` (legacy dict wrapper)
    - ``tools.port_scanner.PortScanResult``
    - Ad-hoc ``list[dict]`` returns from scanners

Migration path:
    1. ``UnifiedToolResult`` inherits from ``StructuredToolResult`` — zero code duplication.
    2. After all callers migrate, ``StructuredToolResult`` is renamed to ``UnifiedToolResult``.
    3. ``PortScanResult`` becomes a thin wrapper/factory for ``UnifiedToolResult``.
    4. ``ToolResult`` (from ``tools/models.py``) kept as a thin wrapper with
       ``to_legacy_dict()`` until all ToolRunner callers migrate.
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

    # ── Lifecycle fields used by template methods ────────────────────
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    exit_code: int = 0

    # ── Lifecycle ────────────────────────────────────────────────────

    def mark_finished(self) -> None:
        """Extend parent to auto-count open ports."""
        super().mark_finished()
        if self.ports:
            self.open_ports_count = len(self.ports)

    # ── Backward compatibility ───────────────────────────────────────

    def to_legacy_dict(self) -> dict[str, Any]:
        """
        Produce the old ``tools.models.ToolResult`` dict shape.

        Used during migration so callers expecting ``ToolResult`` can
        call ``result.to_legacy_dict()`` instead.
        """
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.exit_code,
            "tool": self.tool_name,
            "success": self.status.is_ok,
            "duration_ms": int(self.duration_seconds * 1000),
            "timeout": self.status == ToolStatus.TIMEOUT,
            "error": self.error_message or None,
            "trace_id": "",
        }

    def to_finding_list(self) -> list[dict[str, Any]]:
        """
        Extract findings as a plain list (what scanners currently return directly).

        Used during migration so ``scan()`` methods can return
        ``result.to_finding_list()`` without changing callers.
        """
        return list(self.findings)
