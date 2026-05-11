"""
tools/tool_result.py

Structured return type for every tool execution in Argus.
Replaces the silent (success=False, stderr="") anti-pattern.
"""
from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class ToolStatus(StrEnum):
    """Granular outcome for a single tool run."""

    SUCCESS = "success"              # Ran, exit 0, produced output
    SUCCESS_EMPTY = "success_empty"  # Ran, exit 0, but produced no findings (not a bug)
    TIMEOUT = "timeout"              # Exceeded time limit
    NOT_INSTALLED = "not_installed"  # Binary not found on PATH
    IMPORT_ERROR = "import_error"    # Python ModuleNotFoundError in subprocess
    SANDBOX_ERROR = "sandbox_error"  # Generic environment/permission problem
    NONZERO_EXIT = "nonzero_exit"    # Ran but returned non-zero (tool-level error)
    EXCEPTION = "exception"          # Python exception inside ToolRunner itself
    SKIPPED = "skipped"              # Deliberately not run (wrong language, etc.)

    @property
    def is_fatal(self) -> bool:
        """True when the failure means findings are unreliable / absent."""
        return self in {
            self.NOT_INSTALLED,
            self.IMPORT_ERROR,
            self.SANDBOX_ERROR,
            self.EXCEPTION,
            self.TIMEOUT,       # timed-out tool produces no findings
        }

    @property
    def is_ok(self) -> bool:
        return self in {self.SUCCESS, self.SUCCESS_EMPTY, self.SKIPPED}


@dataclass
class StructuredToolResult:
    """
    Single-source-of-truth for everything that happened during one tool run.

    Every field is populated regardless of success/failure so callers never
    have to guard against AttributeError or parse empty strings for clues.

    NOTE: This is the richer replacement for tools.models.ToolResult.
    Import as: from tools.tool_result import StructuredToolResult
    Do NOT import the legacy ToolResult from tools.models.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    tool_name: str
    command: list[str] = field(default_factory=list)
    target: str = ""

    # ── Outcome ───────────────────────────────────────────────────────────────
    status: ToolStatus = ToolStatus.EXCEPTION
    exit_code: int | None = None

    # ── Raw output ────────────────────────────────────────────────────────────
    stdout: str = ""
    stderr: str = ""

    # ── Parsed findings ───────────────────────────────────────────────────────
    findings: list[dict[str, Any]] = field(default_factory=list)
    findings_count: int = 0

    # ── Timing ────────────────────────────────────────────────────────────────
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    duration_seconds: float = 0.0

    # ── Error details (populated on any non-success) ───────────────────────────
    error_type: str = ""          # e.g. "ModuleNotFoundError", "TimeoutExpired"
    error_message: str = ""       # Human-readable one-liner
    error_detail: str = ""        # Full traceback or extended stderr
    fix_hint: str = ""            # Actionable remediation hint

    # ── Sandbox metadata ──────────────────────────────────────────────────────
    sandbox_dir: str = ""
    effective_env: dict[str, str] = field(default_factory=dict)  # PATH, PYTHONPATH, etc.

    # ── Internal notes (debug-only, stripped from engagement reports) ──────────
    debug_notes: list[str] = field(default_factory=list)

    # ─────────────────────────────────────────────────────────────────────────

    def mark_finished(self) -> None:
        """Call immediately after subprocess returns."""
        self.finished_at = datetime.now(UTC)
        self.duration_seconds = (self.finished_at - self.started_at).total_seconds()
        self.findings_count = len(self.findings)

    # ── Convenience constructors ──────────────────────────────────────────────

    @classmethod
    def not_installed(cls, tool_name: str, command: list[str], target: str = "") -> ToolResult:
        return cls(
            tool_name=tool_name,
            command=command,
            target=target,
            status=ToolStatus.NOT_INSTALLED,
            error_type="FileNotFoundError",
            error_message=f"{tool_name!r} binary not found on PATH.",
            fix_hint=(
                f"Install {tool_name} and ensure its binary is on the PATH used by the "
                f"Celery worker. Run: which {tool_name}"
            ),
        )

    @classmethod
    def from_exception(
        cls,
        tool_name: str,
        command: list[str],
        exc: Exception,
        target: str = "",
        sandbox_dir: str = "",
        effective_env: dict[str, str] | None = None,
    ) -> ToolResult:
        tb = traceback.format_exc()
        error_type = type(exc).__name__
        status = ToolStatus.IMPORT_ERROR if isinstance(exc, ModuleNotFoundError) else ToolStatus.EXCEPTION

        fix_hint = ""
        if isinstance(exc, ModuleNotFoundError):
            # exc.name is None on some Python versions when constructed with a string
            _raw_name = getattr(exc, "name", None)
            missing = _raw_name if _raw_name else str(exc).replace("No module named ", "").strip("'\" ")
            fix_hint = (
                f"Python cannot find '{missing}' inside the sandbox. "
                f"Add the user site-packages directory to PYTHONPATH in _locked_env(). "
                f"Quick check: python3 -c 'import {missing}'"
            )

        result = cls(
            tool_name=tool_name,
            command=command,
            target=target,
            status=status,
            error_type=error_type,
            error_message=str(exc),
            error_detail=tb,
            fix_hint=fix_hint,
            sandbox_dir=sandbox_dir,
            effective_env=effective_env or {},
        )
        result.mark_finished()
        return result

    @classmethod
    def timeout(
        cls,
        tool_name: str,
        command: list[str],
        limit_seconds: int,
        target: str = "",
    ) -> ToolResult:
        result = cls(
            tool_name=tool_name,
            command=command,
            target=target,
            status=ToolStatus.TIMEOUT,
            error_type="TimeoutExpired",
            error_message=f"{tool_name!r} exceeded time limit of {limit_seconds}s.",
            fix_hint=(
                f"Increase the timeout for {tool_name} in ToolRunner.TIMEOUTS, "
                f"or reduce the scan scope."
            ),
        )
        result.mark_finished()
        return result

    @classmethod
    def skipped(cls, tool_name: str, reason: str, target: str = "") -> StructuredToolResult:
        return cls(
            tool_name=tool_name,
            target=target,
            status=ToolStatus.SKIPPED,
            error_message=reason,
        )

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_report_dict(self, include_debug: bool = False) -> dict[str, Any]:
        """
        Dict safe to embed in an engagement report.
        Strips raw env vars and (optionally) debug notes.
        """
        d: dict[str, Any] = {
            "tool": self.tool_name,
            "status": self.status.value,
            "target": self.target,
            "exit_code": self.exit_code,
            "duration_seconds": round(self.duration_seconds, 2),
            "findings_count": self.findings_count,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }
        if not self.status.is_ok:
            d["error"] = {
                "type": self.error_type,
                "message": self.error_message,
                "fix_hint": self.fix_hint,
                # full traceback only in debug mode — too noisy for client reports
                "detail": self.error_detail if include_debug else "",
            }
        if include_debug:
            d["debug"] = {
                "command": self.command,
                "sandbox_dir": self.sandbox_dir,
                "pythonpath": self.effective_env.get("PYTHONPATH", ""),
                "notes": self.debug_notes,
            }
        return d

    def __str__(self) -> str:
        status_icon = "✅" if self.status.is_ok else "❌"
        base = f"{status_icon} [{self.tool_name}] {self.status.value}"
        if self.findings_count:
            base += f" — {self.findings_count} finding(s)"
        if self.error_message:
            base += f" — {self.error_message}"
        return base
