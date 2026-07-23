"""
tool_core/health_checker.py — Tool Health Checker

Probes each registered tool binary to verify it actually works (not just
exists on PATH). Runs ``--version`` or ``--help`` probes and caches results
with TTL. Reports:

- **available**: binary found on PATH
- **responsive**: binary runs and returns a version string
- **version**: extracted version string
- **status**: ``healthy`` | ``degraded`` | ``unavailable``

Usage::

    checker = ToolHealthChecker()
    report = checker.check_all()
    for tool in report:
        print(tool.name, tool.status, tool.version)
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

logger = logging.getLogger(__name__)


@dataclass
class ToolHealthResult:
    """Health probe result for a single tool."""

    name: str
    """Tool name (matches ToolDefinition.name)."""

    binary: str
    """Binary name on PATH."""

    status: str
    """``healthy`` | ``degraded`` | ``unavailable``."""

    available: bool
    """Binary exists on PATH (shutil.which)."""

    responsive: bool
    """Binary responded to version probe."""

    version: str
    """Extracted version string, or empty string."""

    probe_command: str
    """The command/flag used for the version probe (e.g. ``--version``)."""

    error: str
    """Error message if probe failed, or empty string."""

    path: str
    """Resolved full path to binary, or empty string."""


@dataclass
class HealthReport:
    """Aggregate health report for all registered tools."""

    healthy: list[ToolHealthResult] = field(default_factory=list)
    degraded: list[ToolHealthResult] = field(default_factory=list)
    unavailable: list[ToolHealthResult] = field(default_factory=list)
    total: int = 0
    healthy_count: int = 0
    degraded_count: int = 0
    unavailable_count: int = 0

    def __post_init__(self) -> None:
        """Auto-compute counts from lists if not explicitly set."""
        if not self.total and (self.healthy or self.degraded or self.unavailable):
            self.healthy_count = len(self.healthy)
            self.degraded_count = len(self.degraded)
            self.unavailable_count = len(self.unavailable)
            self.total = self.healthy_count + self.degraded_count + self.unavailable_count

    @property
    def summary(self) -> str:
        """Short human-readable summary."""
        return (
            f"{self.healthy_count} healthy, "
            f"{self.degraded_count} degraded, "
            f"{self.unavailable_count} unavailable"
            f" ({self.total} total)"
        )


# ── Default version probes per tool category ──
# Maps tool name patterns to version probe flags.
# Most tools use --version, but some use -v, version, or --help.
_DEFAULT_PROBE: str = "--version"
_SPECIAL_PROBES: dict[str, str] = {
    # ProjectDiscovery tools
    "httpx": "-version",
    "subfinder": "-version",
    "alterx": "-version",
    "dnsx": "-version",
    "naabu": "-version",
    "katana": "-version",
    "chaos": "-version",
    "shuffledns": "-version",
    "cloud_enum": "--help",
    # Nmap
    "nmap": "--version",
    # Go tools
    "govulncheck": "--help",
    # Node tools
    "npm-audit": "version --json",  # npm audit version
    "eslint": "--version",
    # Python tools
    "bandit": "--version",
    "semgrep": "--version",
    "pip-audit": "--version",
    # Ruby tools
    "brakeman": "--version",
    "wpscan": "--version",
    # Java tools
    "spotbugs": "-version",
    "dependency-check": "--version",
    # Web tools
    "whatweb": "--version",
    "nikto": "--version",
    "wafw00f": "--help",
    "testssl": "--version",
    "jwt_tool": "--help",
    "dalfox": "--version",
    "sqlmap": "--version",
    "commix": "--version",
    "arjun": "--version",
    "ffuf": "--version",
    "gau": "--version",
    "waybackurls": "--help",
    "gospider": "--version",
    "amass": "--version",
    "gitleaks": "--version",
    "trufflehog": "--version",
    "trivy": "--version",
    "gosec": "--version",
    "phpcs": "--version",
}


class ToolHealthChecker:
    """
    Probes tool binaries to verify they are responsive and extracts versions.

    Results are cached with TTL to avoid re-probing on every check.
    Thread-safe (read-only after initial probe).
    """

    # TTL for cached results (seconds)
    CACHE_TTL: ClassVar[int] = 600  # 10 minutes

    # Timeout for each version probe (seconds)
    PROBE_TIMEOUT: ClassVar[int] = 10

    def __init__(
        self,
        probe_timeout: int | None = None,
        cache_ttl: int | None = None,
    ) -> None:
        self._cache: dict[str, ToolHealthResult] = {}
        self._cache_time: float = 0.0
        self._probe_timeout: int = probe_timeout or self.PROBE_TIMEOUT
        self._cache_ttl: int = cache_ttl or self.CACHE_TTL
        # Override from env
        if os.environ.get("ARGUS_PROBE_TIMEOUT"):
            self._probe_timeout = int(os.environ["ARGUS_PROBE_TIMEOUT"])

    # ── Public API ───────────────────────────────────────────────────

    def check(self, tool_name: str) -> ToolHealthResult:
        """Check a single tool by name.

        Returns cached result if available and fresh, otherwise probes
        the binary and caches the result.

        Args:
            tool_name: Tool name (e.g. ``nuclei``).

        Returns:
            ToolHealthResult with probe results.
        """
        cached = self._get_cached(tool_name)
        if cached is not None:
            return cached
        result = self._probe(tool_name)
        self._cache[tool_name] = result
        self._cache_time = time.time()
        return result

    MAX_WORKERS: ClassVar[int] = 10
    """Max parallel workers for probing tools."""

    def check_all(
        self,
        tool_names: list[str] | None = None,
        max_workers: int | None = None,
    ) -> HealthReport:
        """Check all registered tools and return an aggregate report.

        Probes tools in parallel using a thread pool for performance.
        Results are cached to avoid re-probing on subsequent calls.

        Args:
            tool_names: Optional list of tool names to check.
                If None, loads all tools from ``tool_definitions.TOOLS``.
            max_workers: Max parallel workers (default: 10).

        Returns:
            HealthReport with healthy/degraded/unavailable breakdown.
        """
        if tool_names is None:
            tool_names = self._get_all_tool_names()

        report = HealthReport(total=len(tool_names))
        workers = max_workers or self.MAX_WORKERS

        # Probe tools in parallel using a thread pool. Each check() call
        # runs a subprocess, so the GIL is released during I/O wait.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {
                pool.submit(self.check, name): name for name in tool_names
            }
            for future in as_completed(future_map):
                try:
                    result = future.result()
                    if result.status == "healthy":
                        report.healthy.append(result)
                        report.healthy_count += 1
                    elif result.status == "degraded":
                        report.degraded.append(result)
                        report.degraded_count += 1
                    else:
                        report.unavailable.append(result)
                        report.unavailable_count += 1
                except Exception as e:
                    name = future_map[future]
                    logger.debug("Tool health probe failed for %s: %s", name, e)
                    report.unavailable.append(
                        ToolHealthResult(
                            name=name,
                            binary=self._get_binary_name(name),
                            status="unavailable",
                            available=False,
                            responsive=False,
                            version="",
                            probe_command="",
                            error=str(e),
                            path="",
                        )
                    )
                    report.unavailable_count += 1

        return report

    def invalidate(self, tool_name: str | None = None) -> None:
        """Invalidate cached result for a tool, or all tools.

        Args:
            tool_name: Tool name, or None to clear all cache.
        """
        if tool_name:
            self._cache.pop(tool_name, None)
        else:
            self._cache.clear()
            self._cache_time = 0.0

    def get_version(self, tool_name: str) -> str:
        """Get version string for a tool (from cache or probe).

        Args:
            tool_name: Tool name.

        Returns:
            Version string, or empty string if unavailable.
        """
        result = self.check(tool_name)
        return result.version

    # ── Internal helpers ─────────────────────────────────────────────

    def _get_cached(self, tool_name: str) -> ToolHealthResult | None:
        """Get cached result if fresh."""
        if tool_name in self._cache:
            age = time.time() - self._cache_time
            if age < self._cache_ttl:
                return self._cache[tool_name]
        return None

    def _get_all_tool_names(self) -> list[str]:
        """Load all registered tool names from tool_definitions."""
        try:
            from tool_definitions import TOOLS
            from tool_definitions import _AGENT_INTERNAL_TOOLS

            names = []
            for name in TOOLS:
                # Skip agent-internal tools (they have no binary)
                if name not in _AGENT_INTERNAL_TOOLS:
                    names.append(name)
            return sorted(names)
        except ImportError:
            logger.warning("Could not import tool_definitions — no tools to check")
            return []

    def _get_binary_name(self, tool_name: str) -> str:
        """Get the binary name for a tool (respects ToolDefinition.binary)."""
        try:
            from tool_definitions import TOOLS

            tool = TOOLS.get(tool_name)
            if tool and tool.binary:
                return tool.binary
        except ImportError:
            pass
        return tool_name

    def _get_version_probe(self, tool_name: str) -> str:
        """Get the version probe flag for a tool.

        Checks the special probes map first, then falls back to ``--version``.
        """
        return _SPECIAL_PROBES.get(tool_name, _DEFAULT_PROBE)

    def _resolve_binary(self, tool_name: str) -> str | None:
        """Resolve full path to tool binary using augmented PATH."""
        binary = self._get_binary_name(tool_name)
        from tool_core.registry import ToolRegistry

        registry = ToolRegistry()
        return registry.resolve(binary) or shutil.which(binary)

    def _probe(self, tool_name: str) -> ToolHealthResult:
        """Probe a single tool binary to check if it's responsive.

        Steps:
        1. Check if binary exists on PATH
        2. Run version probe command
        3. Parse version from output

        Args:
            tool_name: Tool name.

        Returns:
            ToolHealthResult with probe results.
        """
        binary = self._get_binary_name(tool_name)
        path = self._resolve_binary(tool_name)
        probe_flag = self._get_version_probe(tool_name)

        # Step 1: Check if binary exists
        if not path:
            return ToolHealthResult(
                name=tool_name,
                binary=binary,
                status="unavailable",
                available=False,
                responsive=False,
                version="",
                probe_command=probe_flag,
                error=f"Binary '{binary}' not found on PATH",
                path="",
            )

        # Step 2: Run version probe
        try:
            # Split probe flag into args (e.g. "version --json" -> ["version", "--json"])
            probe_args = probe_flag.split()
            cmd = [path] + probe_args

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._probe_timeout,
            )

            # Extract version from stdout or stderr
            output = (result.stdout or "") + "\n" + (result.stderr or "")
            version = self._parse_version(output, tool_name)

            if version:
                return ToolHealthResult(
                    name=tool_name,
                    binary=binary,
                    status="healthy",
                    available=True,
                    responsive=True,
                    version=version,
                    probe_command=probe_flag,
                    error="",
                    path=path,
                )
            else:
                # Binary ran but we couldn't parse a version
                return ToolHealthResult(
                    name=tool_name,
                    binary=binary,
                    status="degraded",
                    available=True,
                    responsive=True,
                    version="",
                    probe_command=probe_flag,
                    error="Binary responded but version not detected",
                    path=path,
                )

        except FileNotFoundError:
            return ToolHealthResult(
                name=tool_name,
                binary=binary,
                status="unavailable",
                available=False,
                responsive=False,
                version="",
                probe_command=probe_flag,
                error=f"Binary '{binary}' not found",
                path="",
            )
        except subprocess.TimeoutExpired:
            return ToolHealthResult(
                name=tool_name,
                binary=binary,
                status="degraded",
                available=True,
                responsive=False,
                version="",
                probe_command=probe_flag,
                error=f"Version probe timed out after {self._probe_timeout}s",
                path=path,
            )
        except PermissionError:
            return ToolHealthResult(
                name=tool_name,
                binary=binary,
                status="degraded",
                available=False,
                responsive=False,
                version="",
                probe_command=probe_flag,
                error=f"Binary '{binary}' exists but is not executable",
                path=path,
            )
        except OSError as e:
            return ToolHealthResult(
                name=tool_name,
                binary=binary,
                status="unavailable",
                available=False,
                responsive=False,
                version="",
                probe_command=probe_flag,
                error=str(e),
                path="",
            )

    @staticmethod
    def _parse_version(output: str, tool_name: str) -> str:
        """Extract version string from tool output.

        Uses tool-specific parsing if available, otherwise falls back
        to a generic regex pattern.

        Args:
            output: Combined stdout + stderr from the version probe.
            tool_name: Tool name for tool-specific parsing.

        Returns:
            Extracted version string, or empty string if not found.
        """
        # Tool-specific parsers for tools with unusual version output
        # ProjectDiscovery tools: "Current Version: x.y.z" or "x.y.z"
        if tool_name in ("httpx", "subfinder", "alterx", "naabu", "katana", "dalfox"):
            for line in output.splitlines():
                line = line.strip()
                if line and not line.startswith("["):
                    # Take first non-empty, non-bracket line as version
                    for part in line.split():
                        if part[0:1].isdigit():
                            return part
                    return line[:60]

        # nuclei: "x.y.z" from " Nuclei Engine x.y.z (community)"
        if tool_name == "nuclei":
            for line in output.splitlines():
                if "nuclei" in line.lower():
                    import re
                    m = re.search(r"(\d+\.\d+\.\d+)", line)
                    if m:
                        return m.group(1)

        # nmap: "Nmap version x.y.z"
        if tool_name == "nmap":
            import re
            m = re.search(r"Nmap version (\d+\.\d+)", output)
            if m:
                return m.group(1)

        # Generic version regex: try common version patterns
        import re
        patterns = [
            r"(\d+\.\d+\.\d+[a-zA-Z0-9.-]*)",  # semver (3.2.0, 1.2.3-alpha)
            r"(\d+\.\d+\.\d+)",                   # semver bare
            r"v(\d+\.\d+\.\d+)",                  # v-prefixed semver
            r"version\s+(\d+\.\d+[.\d]*)",        # "version x.y[.z]"
            r"(\d+\.\d+\.\d+)\s",                 # semver with trailing space
        ]
        for pattern in patterns:
            m = re.search(pattern, output, re.IGNORECASE)
            if m:
                return m.group(1)

        # Last resort: first line of output
        first_line = output.splitlines()[0] if output.splitlines() else ""
        if first_line and len(first_line) < 100:
            return first_line.strip()[:60]

        return ""


# ── Convenience functions ─────────────────────────────────────────────


def check_tool_health(tool_name: str) -> ToolHealthResult:
    """Quick convenience function to check a single tool.

    Args:
        tool_name: Tool name.

    Returns:
        ToolHealthResult.
    """
    checker = ToolHealthChecker()
    return checker.check(tool_name)


def check_all_tools() -> HealthReport:
    """Quick convenience function to check all registered tools.

    Returns:
        HealthReport with all results.
    """
    checker = ToolHealthChecker()
    return checker.check_all()


def display_health_report(report: HealthReport, verbose: bool = False) -> str:
    """Format a health report as a human-readable table.

    Args:
        report: HealthReport to format.
        verbose: If True, show all tools including healthy ones.
            If False (default), only show degraded/unavailable.

    Returns:
        Formatted string with table.
    """
    lines: list[str] = []
    sep = "-" * 80

    lines.append("")
    lines.append("  Tool Health Report")
    lines.append(f"  {sep}")
    lines.append(f"  {'Tool':<30} {'Status':<15} {'Version':<20} {'Details':<25}")
    lines.append(f"  {sep}")

    # Show all or filter based on verbose
    results: list[ToolHealthResult] = []
    if verbose:
        results = report.healthy + report.degraded + report.unavailable
    else:
        results = report.degraded + report.unavailable
        if not results:
            lines.append(f"  All {report.total} tools are healthy!")
            lines.append(f"  {sep}")
            lines.append(f"  {report.summary}")
            lines.append("")
            return "\n".join(lines)

    # Sort: unhealthy first, then degraded, then healthy
    status_order = {"unavailable": 0, "degraded": 1, "healthy": 2}
    results.sort(key=lambda r: (status_order.get(r.status, 9), r.name))

    for r in results:
        status_display = r.status.upper()
        version_display = r.version[:18] if r.version else "-"
        details = r.error[:23] if r.error else (r.path[:23] if r.path else "")

        if r.status == "healthy":
            lines.append(f"  {r.name:<30} {status_display:<15} {version_display:<20} {details:<25}")
        elif r.status == "degraded":
            lines.append(f"  {r.name:<30} {status_display:<15} {version_display:<20} {details:<25}")
        else:
            lines.append(f"  {r.name:<30} {status_display:<15} {version_display:<20} {details:<25}")

    lines.append(f"  {sep}")
    lines.append(f"  {report.summary}")
    lines.append("")
    return "\n".join(lines)
