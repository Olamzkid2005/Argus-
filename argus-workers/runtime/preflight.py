"""
runtime/preflight.py — Consolidated Startup Preflight Check

Aggregates ALL startup-time validation checks that were previously scattered
across the codebase into a single, structured report. Every check is optional
(reports warnings, never blocks startup unless an explicit env var is set),
so the worker always starts — even with missing tools or config.

Checks performed:
  1. Critical tools — binary exists on PATH (ToolHealthChecker probe)
  2. Placeholder credentials — env vars like POSTGRES_PASSWORD (startup_guard)
  3. SETTINGS_ENCRYPTION_KEY — is a persistent key set (not ephemeral)?
  4. AUTH_CHECKPOINT_KEY — is a valid Fernet key set?
  5. Scope config — is ARGUS_ALLOW_UNSCOPED set? Are authorized scopes configured?
  6. DNS resolution — can we resolve an external hostname?
  7. LLM configuration — are API keys configured?
  8. Database URL — is DATABASE_URL set?
  9. Tool binary health — probe critical tools for responsiveness (not just existence)

Usage:
    from runtime.preflight import PreflightReport, run_preflight

    report = run_preflight()
    if report.has_errors():
        logger.error("Preflight found %d issue(s)", len(report.errors))
    if report.has_warnings():
        logger.warning("Preflight found %d warning(s)", len(report.warnings))
    logger.info("Preflight summary: %s", report.summary)
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import ClassVar

logger = logging.getLogger(__name__)


# ── Severity levels ─────────────────────────────────────────────────────


class CheckSeverity:
    """Severity of a preflight check result."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


# ── Individual check result ─────────────────────────────────────────────


@dataclass
class CheckResult:
    """Result of a single preflight check."""

    name: str
    """Short check name (e.g. ``critical_tools``)."""

    severity: str
    """One of ``CheckSeverity.OK``, ``WARNING``, ``ERROR``."""

    message: str
    """Human-readable message describing the result."""

    detail: str = ""
    """Optional detail string (e.g. list of missing tools)."""


# ── Aggregated report ───────────────────────────────────────────────────


@dataclass
class PreflightReport:
    """Aggregated preflight check report containing all results."""

    checks: list[CheckResult] = field(default_factory=list)

    total: int = 0
    ok_count: int = 0
    warning_count: int = 0
    error_count: int = 0

    def __post_init__(self) -> None:
        """Auto-compute counts from checks."""
        if not self.total and self.checks:
            self.total = len(self.checks)
            self.ok_count = sum(1 for c in self.checks if c.severity == CheckSeverity.OK)
            self.warning_count = sum(
                1 for c in self.checks if c.severity == CheckSeverity.WARNING
            )
            self.error_count = sum(
                1 for c in self.checks if c.severity == CheckSeverity.ERROR
            )

    def has_errors(self) -> bool:
        """True if any check reported ERROR severity."""
        return self.error_count > 0

    def has_warnings(self) -> bool:
        """True if any check reported WARNING severity."""
        return self.warning_count > 0

    @property
    def errors(self) -> list[CheckResult]:
        """All ERROR-severity checks."""
        return [c for c in self.checks if c.severity == CheckSeverity.ERROR]

    @property
    def warnings(self) -> list[CheckResult]:
        """All WARNING-severity checks."""
        return [c for c in self.checks if c.severity == CheckSeverity.WARNING]

    @property
    def summary(self) -> str:
        """Short human-readable summary line."""
        parts = []
        if self.ok_count:
            parts.append(f"{self.ok_count} ok")
        if self.warning_count:
            parts.append(f"{self.warning_count} warning(s)")
        if self.error_count:
            parts.append(f"{self.error_count} error(s)")
        return f"{' | '.join(parts)} ({self.total} total)" if parts else "no checks run"

    def log_summary(self) -> None:
        """Log the full preflight report at appropriate log levels."""
        # Log the summary line first
        if self.error_count > 0:
            logger.error("Preflight: %s", self.summary)
        elif self.warning_count > 0:
            logger.warning("Preflight: %s", self.summary)
        else:
            logger.info("Preflight: %s", self.summary)

        # Log each non-OK check individually
        for check in self.checks:
            if check.severity == CheckSeverity.OK:
                logger.debug("  ✓ %s: %s", check.name, check.message)
            elif check.severity == CheckSeverity.WARNING:
                logger.warning("  ⚠ %s: %s", check.name, check.message)
                if check.detail:
                    logger.warning("    Detail: %s", check.detail)
            else:
                logger.error("  ✗ %s: %s", check.name, check.message)
                if check.detail:
                    logger.error("    Detail: %s", check.detail)

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict for /health endpoint."""
        return {
            "total": self.total,
            "ok": self.ok_count,
            "warnings": self.warning_count,
            "errors": self.error_count,
            "summary": self.summary,
            "checks": [
                {
                    "name": c.name,
                    "severity": c.severity,
                    "message": c.message,
                    "detail": c.detail,
                }
                for c in self.checks
            ],
        }


# ── Individual check functions ──────────────────────────────────────────

# Critical tools that must be available for full functionality.
# Mirrors MCPServer.CRITICAL_TOOLS — kept here so preflight is self-contained.
_CRITICAL_TOOL_NAMES: ClassVar[list[str]] = [
    "nuclei",
    "nmap",
    "sqlmap",
    "subfinder",
    "httpx",
    "whatweb",
]


def _check_critical_tools() -> CheckResult:
    """Check that critical tool binaries are reachable via PATH.

    Uses shutil.which (fast, no subprocess) to verify the binary exists.
    For actual responsiveness probes, use _check_tool_health() instead.
    """
    # Build augmented PATH the same way MCPServer does
    _venv_bin = str(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "venv", "bin"))
    _go_bin = os.path.expanduser("~/go/bin")
    _homebrew_bin = "/opt/homebrew/bin"
    _extra_path = os.environ.get("ARGUS_EXTRA_PATH", "")
    _existing_path = os.environ.get("PATH", "")
    _augmented = f"{_venv_bin}:{_go_bin}:{_homebrew_bin}:{_extra_path}:{_existing_path}"

    missing = []
    for name in _CRITICAL_TOOL_NAMES:
        if not shutil.which(name, path=_augmented):
            missing.append(name)

    if not missing:
        return CheckResult(
            name="critical_tools",
            severity=CheckSeverity.OK,
            message=f"All {len(_CRITICAL_TOOL_NAMES)} critical tools found on PATH",
        )

    return CheckResult(
        name="critical_tools",
        severity=CheckSeverity.WARNING,
        message=f"{len(missing)} of {len(_CRITICAL_TOOL_NAMES)} critical tool(s) missing",
        detail=f"Missing: {', '.join(missing)}. Install them or add to PATH. "
        f"Set ARGUS_EXTRA_PATH for non-standard locations. "
        f"Set ARGUS_ENFORCE_TOOLS=1 to abort startup on missing tools.",
    )


def _check_placeholder_credentials() -> CheckResult:
    """Check for placeholder credentials (reuses startup_guard)."""
    try:
        from config.startup_guard import check_placeholder_credentials

        issues = check_placeholder_credentials()
    except ImportError:
        return CheckResult(
            name="placeholder_credentials",
            severity=CheckSeverity.OK,
            message="startup_guard module not available — skipping",
        )
    except Exception as e:
        return CheckResult(
            name="placeholder_credentials",
            severity=CheckSeverity.WARNING,
            message=f"Credential check failed: {e}",
        )

    if not issues:
        return CheckResult(
            name="placeholder_credentials",
            severity=CheckSeverity.OK,
            message="No placeholder credentials detected",
        )

    return CheckResult(
        name="placeholder_credentials",
        severity=CheckSeverity.ERROR if os.environ.get("ARGUS_AUTONOMOUS", "").lower() in ("1", "true") else CheckSeverity.WARNING,
        message=f"Found {len(issues)} placeholder credential(s)",
        detail="\n".join(issues),
    )


def _check_settings_encryption_key() -> CheckResult:
    """Check if SETTINGS_ENCRYPTION_KEY is set (not ephemeral).

    The settings repository generates a random key on the fly when none is set,
    which means stored API keys become undecryptable after a restart.
    """
    key = os.environ.get("SETTINGS_ENCRYPTION_KEY")
    if key:
        return CheckResult(
            name="settings_encryption_key",
            severity=CheckSeverity.OK,
            message="SETTINGS_ENCRYPTION_KEY is set",
        )

    return CheckResult(
        name="settings_encryption_key",
        severity=CheckSeverity.ERROR,
        message="SETTINGS_ENCRYPTION_KEY is not set — ephemeral key will be generated",
        detail="Stored API keys will become UNREADABLE after process restart. "
        "Set SETTINGS_ENCRYPTION_KEY to a valid Fernet key (44 URL-safe base64 chars). "
        "Generate one with: python3 -c \"from cryptography.fernet import Fernet; "
        "print(Fernet.generate_key().decode())\"",
    )


def _check_auth_checkpoint_key() -> CheckResult:
    """Check if AUTH_CHECKPOINT_KEY is set and is a valid Fernet key.

    Auth checkpoints store session tokens (cookies, Bearer tokens, CSRF tokens)
    that MUST be encrypted at rest. Without a valid key, auth state cannot be
    persisted across worker restarts in a secure way.
    """
    key = os.environ.get("AUTH_CHECKPOINT_KEY")
    if not key:
        return CheckResult(
            name="auth_checkpoint_key",
            severity=CheckSeverity.WARNING,
            message="AUTH_CHECKPOINT_KEY is not set",
            detail="Auth checkpoints (session tokens, cookies) will NOT be encrypted. "
            "Set AUTH_CHECKPOINT_KEY to a valid Fernet key. Generate one with: "
            "python3 -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"",
        )

    # Validate it's a valid Fernet key
    try:
        from cryptography.fernet import Fernet
        Fernet(key.encode())
        return CheckResult(
            name="auth_checkpoint_key",
            severity=CheckSeverity.OK,
            message="AUTH_CHECKPOINT_KEY is set and valid",
        )
    except Exception as e:
        return CheckResult(
            name="auth_checkpoint_key",
            severity=CheckSeverity.ERROR,
            message=f"AUTH_CHECKPOINT_KEY is invalid: {e}",
            detail="Generate a valid key with: python3 -c \"from cryptography.fernet "
            "import Fernet; print(Fernet.generate_key().decode())\"",
        )


def _check_scope_config() -> CheckResult:
    """Check scope configuration status.

    When ARGUS_AUTONOMOUS is active, we check whether ARGUS_ALLOW_UNSCOPED is set
    (which would allow scanning without explicit scope config) or whether the
    scope validator has been configured with authorized domains/IPs.
    """
    is_autonomous = os.environ.get("ARGUS_AUTONOMOUS", "").lower() in ("1", "true")
    allow_unscoped = os.environ.get("ARGUS_ALLOW_UNSCOPED", "").lower() in ("1", "true")

    if is_autonomous and not allow_unscoped:
        # In autonomous mode without unscoped permission, scope must be configured
        # via engagement-specific scope config. We can't check per-engagement scope
        # here since it's dynamic, but we can warn that no fallback is set.
        return CheckResult(
            name="scope_config",
            severity=CheckSeverity.WARNING,
            message="Autonomous mode without ARGUS_ALLOW_UNSCOPED=1",
            detail="In ARGUS_AUTONOMOUS mode without ARGUS_ALLOW_UNSCOPED=1, "
            "each engagement MUST have an authorized_scope configured, or "
            "ALL targets will be rejected. Set ARGUS_ALLOW_UNSCOPED=1 if "
            "you want to bypass scope validation (development only).",
        )

    if is_autonomous and allow_unscoped:
        return CheckResult(
            name="scope_config",
            severity=CheckSeverity.WARNING,
            message="Autonomous mode with ARGUS_ALLOW_UNSCOPED=1 — SCOPE VALIDATION BYPASSED",
            detail="ALL targets will be accepted. This is acceptable for development "
            "but dangerous for unattended production use. Configure authorized_scope "
            "in the engagement config for proper scope enforcement.",
        )

    return CheckResult(
        name="scope_config",
        severity=CheckSeverity.OK,
        message="Scope config check passed",
        detail="Scope validation is fail-closed by default. "
        "Set authorized_scope per engagement or ARGUS_ALLOW_UNSCOPED=1 to allow targets.",
    )


def _check_dns(timeout: float = 5.0) -> CheckResult:
    """Check external DNS resolution.

    Uses a short socket timeout to avoid blocking indefinitely on systems
    without internet access (common on Windows, container sandboxes, etc.).

    Args:
        timeout: Socket timeout in seconds. Default 5.0.
    """
    old_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(timeout)
        socket.getaddrinfo("dns.google", 53)
        return CheckResult(
            name="dns_resolution",
            severity=CheckSeverity.OK,
            message="DNS resolution works",
        )
    except socket.gaierror:
        return CheckResult(
            name="dns_resolution",
            severity=CheckSeverity.WARNING,
            message="DNS resolution failed",
            detail="DNS-reliant tools (subfinder, amass, dnsx) may not work. "
            "Check container DNS config or set --dns-servers 8.8.8.8",
        )
    except socket.timeout:
        return CheckResult(
            name="dns_resolution",
            severity=CheckSeverity.WARNING,
            message=f"DNS timed out after {timeout}s",
            detail="DNS-reliant tools (subfinder, amass, dnsx) may not work. "
            "Check container DNS config or set --dns-servers 8.8.8.8",
        )
    except OSError as e:
        # Include timeouts that manifest as OSError on some platforms
        return CheckResult(
            name="dns_resolution",
            severity=CheckSeverity.WARNING,
            message=f"DNS check failed: {e}",
            detail="DNS-reliant tools (subfinder, amass, dnsx) may not work. "
            "Check container DNS config or set --dns-servers 8.8.8.8",
        )
    except Exception as e:
        return CheckResult(
            name="dns_resolution",
            severity=CheckSeverity.WARNING,
            message=f"DNS check failed: {e}",
        )
    finally:
        socket.setdefaulttimeout(old_timeout)


def _check_llm_config() -> CheckResult:
    """Check if LLM API keys are configured.

    Checks for any of the supported LLM provider API keys in the environment.
    Does NOT make a network call — only checks env vars.
    """
    _PROVIDER_ENV_KEYS = {
        "OPENAI_API_KEY": "OpenAI",
        "ANTHROPIC_API_KEY": "Anthropic",
        "GEMINI_API_KEY": "Gemini",
        "OPENROUTER_API_KEY": "OpenRouter",
        "AZURE_OPENAI_API_KEY": "Azure OpenAI",
        "LLM_API_KEY": "Generic LLM",
    }

    configured = []
    for env_key, provider in _PROVIDER_ENV_KEYS.items():
        value = os.environ.get(env_key, "")
        if value and not value.startswith("your_"):
            # Mask the key for the report
            masked = value[:8] + "..." + value[-4:] if len(value) > 12 else "(set)"
            configured.append(f"{provider} ({masked})")

    if configured:
        return CheckResult(
            name="llm_config",
            severity=CheckSeverity.OK,
            message=f"LLM configured: {', '.join(configured)}",
        )

    return CheckResult(
        name="llm_config",
        severity=CheckSeverity.WARNING,
        message="No LLM API keys configured",
        detail="No supported LLM provider API keys found in environment. "
        "Without an LLM, the agent will operate in fallback mode "
        "(deterministic tool execution, no intelligent replanning). "
        "Set OPENAI_API_KEY, ANTHROPIC_API_KEY, or GEMINI_API_KEY.",
    )


def _check_database_url() -> CheckResult:
    """Check if DATABASE_URL is configured."""
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        # Mask credentials in the URL for the report
        masked = db_url
        if "@" in db_url:
            # Show just the host: database type + hostname
            try:
                protocol = db_url.split("://")[0] if "://" in db_url else "db"
                host_part = db_url.split("@")[1] if "@" in db_url else db_url
                hostname = host_part.split(":")[0] if ":" in host_part else host_part
                masked = f"{protocol}://***@{hostname}"
            except Exception:
                masked = "(configured)"
        return CheckResult(
            name="database_url",
            severity=CheckSeverity.OK,
            message=f"DATABASE_URL is set: {masked}",
        )

    return CheckResult(
        name="database_url",
        severity=CheckSeverity.WARNING,
        message="DATABASE_URL is not set",
        detail="Without DATABASE_URL, the worker will use SQLite local mode. "
        "Set DATABASE_URL to a PostgreSQL connection string for full functionality.",
    )


def _check_tool_health() -> CheckResult:
    """Probe critical tools for binary health (exists + responsive).

    Uses ToolHealthChecker to run --version probes on critical tools.
    Reports degraded tools (binary exists but doesn't respond) separately
    from unavailable tools (binary not found).
    """
    try:
        from tool_core.health_checker import ToolHealthChecker

        checker = ToolHealthChecker(probe_timeout=5)
        report = checker.check_all(
            tool_names=_CRITICAL_TOOL_NAMES, max_workers=6
        )
    except ImportError:
        return CheckResult(
            name="tool_health",
            severity=CheckSeverity.OK,
            message="ToolHealthChecker not available — skipping probe",
        )
    except Exception as e:
        return CheckResult(
            name="tool_health",
            severity=CheckSeverity.WARNING,
            message=f"Tool health probe failed: {e}",
        )

    if report.unavailable_count == 0 and report.degraded_count == 0:
        return CheckResult(
            name="tool_health",
            severity=CheckSeverity.OK,
            message=f"All {report.total} critical tools healthy",
        )

    parts = []
    if report.degraded_count:
        parts.append(
            f"{report.degraded_count} degraded: "
            + ", ".join(t.name for t in report.degraded)
        )
    if report.unavailable_count:
        parts.append(
            f"{report.unavailable_count} unavailable: "
            + ", ".join(t.name for t in report.unavailable)
        )

    severity = (
        CheckSeverity.WARNING
        if report.unavailable_count < len(_CRITICAL_TOOL_NAMES)
        else CheckSeverity.ERROR
    )

    return CheckResult(
        name="tool_health",
        severity=severity,
        message=f"{report.summary}",
        detail="; ".join(parts),
    )


# ── Check registry ──────────────────────────────────────────────────────

# All checks in execution order. Each is a callable that returns a CheckResult.
_DEFAULT_CHECKS: list[tuple[str, Callable]] = [
    ("critical_tools", _check_critical_tools),
    ("placeholder_credentials", _check_placeholder_credentials),
    ("settings_encryption_key", _check_settings_encryption_key),
    ("auth_checkpoint_key", _check_auth_checkpoint_key),
    ("scope_config", _check_scope_config),
    ("dns_resolution", _check_dns),
    ("llm_config", _check_llm_config),
    ("database_url", _check_database_url),
    ("tool_health", _check_tool_health),
]


# ── Run all checks ──────────────────────────────────────────────────────


def run_preflight(
    include_checks: list[str] | None = None,
    exclude_checks: list[str] | None = None,
) -> PreflightReport:
    """Run all preflight checks and return an aggregated report.

    Each check:
    - Is self-contained (imports its dependencies lazily)
    - Returns a CheckResult with severity, message, and optional detail
    - Never raises (exceptions are caught and reported as ERROR)
    - Is optional — the worker always starts regardless of results

    Args:
        include_checks: Optional list of check names to run.
            If None, runs all default checks.
        exclude_checks: Optional list of check names to skip.

    Returns:
        PreflightReport with all check results.
    """
    checks_to_run = _DEFAULT_CHECKS
    if include_checks is not None:
        checks_to_run = [(name, fn) for name, fn in _DEFAULT_CHECKS if name in include_checks]
    if exclude_checks is not None:
        checks_to_run = [(name, fn) for name, fn in checks_to_run if name not in exclude_checks]

    results: list[CheckResult] = []
    for name, check_fn in checks_to_run:
        try:
            result = check_fn()
            results.append(result)
        except Exception as e:
            logger.error("Preflight check '%s' raised unexpected exception: %s", name, e)
            results.append(
                CheckResult(
                    name=name,
                    severity=CheckSeverity.ERROR,
                    message=f"Check raised exception: {e}",
                    detail="This is a bug in the preflight check function. "
                    "The worker will continue startup.",
                )
            )

    report = PreflightReport(checks=results)
    return report


def log_startup_preflight(
    include_checks: list[str] | None = None,
    exclude_checks: list[str] | None = None,
) -> PreflightReport:
    """Run preflight checks and log the results.

    Convenience wrapper around run_preflight() that also logs the report.
    Intended to be called at worker startup.

    Returns:
        PreflightReport with all check results.
    """
    report = run_preflight(include_checks=include_checks, exclude_checks=exclude_checks)
    report.log_summary()
    return report


# ── Display formatter for CLI ───────────────────────────────────────────


def _extract_remediation_tips(detail: str) -> list[str]:
    """Extract copy-pasteable remediation commands from a check detail string.

    Looks for known patterns like ``Generate one with:``, ``Set ... in your``,
    ``Install ...``, and returns each as a separate tip line.
    """
    tips: list[str] = []
    for line in detail.split(". "):
        line = line.strip()
        if not line:
            continue
        # Detect actionable commands
        if line.startswith("Generate one with:") or line.startswith("Generate a valid key with:"):
            # Extract the command from the line
            cmd_start = line.find(":") + 1
            cmd = line[cmd_start:].strip()
            if cmd:
                tips.append(f"  $ {cmd}")
        elif line.startswith("Set "):
            # Environment variable setting tip
            tips.append(f"  {line}")
        elif line.startswith("Install") or line.startswith("Check container"):
            tips.append(f"  {line}")
        elif line.startswith("Missing:"):
            # Include missing items
            tips.append(f"  {line}")
        elif line.startswith("Without"):
            tips.append(f"  {line}")
        elif "Set ARGUS_EXTRA_PATH" in line:
            tips.append(f"  {line}")
    return tips


def display_preflight_report(report: PreflightReport, verbose: bool = False) -> str:
    """Format a preflight report as a human-readable table for the CLI.

    Includes a "Remediation" section below the summary that provides
    actionable steps (copy-pasteable commands) for each issue found.

    Args:
        report: PreflightReport to format.
        verbose: If True, show all checks including OK ones.
            If False (default), only show warnings and errors.

    Returns:
        Formatted string with the report table and remediation tips.
    """
    lines: list[str] = []
    sep = "-" * 70

    lines.append("")
    lines.append("  Preflight Configuration Check")
    lines.append(f"  {sep}")
    lines.append(f"  {'Check':<35} {'Status':<10} {'Message':<35}")
    lines.append(f"  {sep}")

    # Filter based on verbose
    checks_to_show: list[CheckResult] = []
    if verbose:
        checks_to_show = list(report.checks)
    else:
        # Show only non-OK checks
        checks_to_show = [
            c for c in report.checks
            if c.severity != CheckSeverity.OK
        ]
        if not checks_to_show:
            lines.append(f"  All {report.total} preflight checks passed!")
            lines.append(f"  {sep}")
            lines.append(f"  {report.summary}")
            lines.append("")
            return "\n".join(lines)

    # Sort: errors first, then warnings, then ok
    severity_order = {
        CheckSeverity.ERROR: 0,
        CheckSeverity.WARNING: 1,
        CheckSeverity.OK: 2,
    }
    checks_to_show.sort(key=lambda c: (severity_order.get(c.severity, 9), c.name))

    for check in checks_to_show:
        status_display = check.severity.upper()
        display_message = check.message[:33] if not verbose else check.message
        lines.append(f"  {check.name:<35} {status_display:<10} {display_message:<35}")

    lines.append(f"  {sep}")
    lines.append(f"  {report.summary}")

    # ── Remediation section ──
    # For each non-OK check with detail, show actionable tips
    remediation_checks = [c for c in checks_to_show if c.severity != CheckSeverity.OK and c.detail]
    if remediation_checks:
        lines.append("")
        lines.append("  Remediation")
        lines.append(f"  {sep}")
        for check in remediation_checks:
            tips = _extract_remediation_tips(check.detail)
            if tips:
                lines.append(f"  [{check.severity.upper()}] {check.name}:")
                for tip in tips:
                    lines.append(f"    {tip}")
            else:
                # Show full detail as fallback
                lines.append(f"  [{check.severity.upper()}] {check.name}: {check.detail}")

    lines.append("")
    return "\n".join(lines)


# ── Command-line usage ──────────────────────────────────────────────────


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    report = log_startup_preflight()
    print(display_preflight_report(report, verbose=True))
    print(f"\nPreflight complete: {report.summary}")
    print("Use log_startup_preflight() in production startup code.")
