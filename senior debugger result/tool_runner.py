"""
tools/tool_runner.py  (hardened)

Runs external security tools in a locked-down subprocess and returns a
ToolResult for every execution — success OR failure.

Key improvements over the original:
  • Never swallows exceptions silently — every crash is captured with full
    traceback, error type, and a fix_hint.
  • _locked_env() builds PYTHONPATH portably (no hardcoded user paths).
  • Timeout, missing-binary, and import-error are distinct ToolStatus values.
  • Callers receive the same ToolResult shape regardless of outcome.
"""
from __future__ import annotations

import logging
import os
import site
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .tool_result import ToolResult, ToolStatus

logger = logging.getLogger(__name__)


# ── Per-tool timeout overrides (seconds) ─────────────────────────────────────
TOOL_TIMEOUTS: dict[str, int] = {
    "semgrep":  300,   # large repos can be slow
    "nuclei":   240,
    "sqlmap":   300,
    "nikto":    180,
    "dalfox":   120,
    "bandit":    90,
    "snyk":     180,
    "httpx":     60,
    "nmap":     120,
    "default":  120,
}


class ToolRunner:
    """
    Executes a single security tool in an isolated subprocess.

    Usage
    -----
        runner = ToolRunner(tool_name="semgrep", target="/path/to/repo")
        result = runner.run(["semgrep", "--config", "p/php", "/path/to/repo"])
        if result.status.is_fatal:
            logger.error("Tool crash: %s", result)
    """

    def __init__(self, tool_name: str, target: str = "", work_dir: str | None = None):
        self.tool_name = tool_name
        self.target = target
        self.work_dir = work_dir or tempfile.mkdtemp(prefix=f"argus_{tool_name}_")
        self.sandbox_dir = tempfile.mkdtemp(prefix=f"argus_sandbox_{tool_name}_")
        self._timeout = TOOL_TIMEOUTS.get(tool_name, TOOL_TIMEOUTS["default"])

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self, command: list[str]) -> ToolResult:
        """
        Execute *command* in the sandbox and return a fully-populated ToolResult.
        Never raises — all exceptions are captured into the result.
        """
        result = ToolResult(
            tool_name=self.tool_name,
            command=command,
            target=self.target,
            started_at=datetime.now(timezone.utc),
        )

        env = self._locked_env()
        result.sandbox_dir = self.sandbox_dir
        result.effective_env = {
            k: env[k]
            for k in ("PATH", "PYTHONPATH", "HOME")
            if k in env
        }

        logger.debug(
            "[%s] Running: %s | PYTHONPATH=%s",
            self.tool_name,
            " ".join(command),
            env.get("PYTHONPATH", "(not set)"),
        )

        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                env=env,
                cwd=self.work_dir,
            )

        except FileNotFoundError as exc:
            # Binary not on PATH
            logger.error(
                "[%s] Binary not found. PATH=%s",
                self.tool_name,
                env.get("PATH"),
            )
            return ToolResult.not_installed(self.tool_name, command, self.target)

        except subprocess.TimeoutExpired:
            logger.error("[%s] Timed out after %ds", self.tool_name, self._timeout)
            return ToolResult.timeout(self.tool_name, command, self._timeout, self.target)

        except Exception as exc:  # noqa: BLE001  (broad — intentional catch-all)
            logger.exception("[%s] Unexpected exception in ToolRunner.run()", self.tool_name)
            return ToolResult.from_exception(
                self.tool_name, command, exc, self.target,
                self.sandbox_dir, env,
            )

        # ── Subprocess finished — now analyse stdout/stderr ───────────────────
        result.exit_code = proc.returncode
        result.stdout = proc.stdout or ""
        result.stderr = proc.stderr or ""
        result.mark_finished()

        # Detect Python import errors that surface as stderr text (not exceptions)
        if self._stderr_has_import_error(result.stderr):
            return self._build_import_error_result(result, env)

        if proc.returncode != 0:
            return self._build_nonzero_result(result)

        # ── Success path ──────────────────────────────────────────────────────
        result.status = ToolStatus.SUCCESS
        logger.info("[%s] Completed in %.1fs", self.tool_name, result.duration_seconds)
        return result

    # ── Environment construction ──────────────────────────────────────────────

    def _locked_env(self) -> dict[str, str]:
        """
        Build the subprocess environment.

        PYTHONPATH is constructed portably from the live interpreter — never
        hardcoded paths.  This survives Python upgrades and other machines.
        """
        venv_bin = str(Path(sys.executable).parent)

        # --- PYTHONPATH assembly -------------------------------------------------
        # Start with the standard site-packages directories for this interpreter.
        python_paths: list[str] = []

        # 1. System / venv site-packages
        try:
            python_paths.extend(
                p for p in site.getsitepackages() if os.path.isdir(p)
            )
        except AttributeError:
            # getsitepackages() absent in some venv builds
            pass

        # 2. User site-packages  (~/.local/lib/... or ~/Library/Python/...)
        user_site = site.getusersitepackages()
        if user_site and os.path.isdir(user_site):
            python_paths.append(user_site)

        # 3. Everything on the running interpreter's sys.path (catches editable
        #    installs, .pth files, namespace packages, etc.)
        python_paths.extend(p for p in sys.path if p and os.path.isdir(p))

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique_paths: list[str] = []
        for p in python_paths:
            if p not in seen:
                seen.add(p)
                unique_paths.append(p)

        return {
            "PATH": f"{venv_bin}:/usr/local/bin:/usr/bin:/bin",
            "HOME": self.sandbox_dir,   # isolated — tools can't read ~/.config etc.
            "TMPDIR": self.sandbox_dir,
            "PYTHONPATH": os.pathsep.join(unique_paths),
            "PYTHONDONTWRITEBYTECODE": "1",
            # Suppress semgrep telemetry / version-check latency
            "SEMGREP_SEND_METRICS": "off",
            "SEMGREP_ENABLE_VERSION_CHECK": "0",
            # Prevent tools from trying to reach home-directory config
            "XDG_CONFIG_HOME": str(Path(self.sandbox_dir) / ".config"),
            "XDG_DATA_HOME": str(Path(self.sandbox_dir) / ".local" / "share"),
        }

    # ── Error classification helpers ──────────────────────────────────────────

    @staticmethod
    def _stderr_has_import_error(stderr: str) -> bool:
        """
        Detect Python ModuleNotFoundError / ImportError that land in stderr
        rather than raising inside the ToolRunner process.
        e.g. semgrep writing its own crash traceback to stderr.
        """
        markers = (
            "ModuleNotFoundError",
            "ImportError",
            "No module named",
        )
        return any(m in stderr for m in markers)

    def _build_import_error_result(
        self, partial: ToolResult, env: dict[str, str]
    ) -> ToolResult:
        """
        Promote a stderr-detected import error into a proper IMPORT_ERROR result.
        """
        # Extract the module name if possible
        missing_module = ""
        for line in partial.stderr.splitlines():
            if "No module named" in line:
                # e.g. "ModuleNotFoundError: No module named 'typing_extensions'"
                missing_module = line.split("'")[1] if "'" in line else line
                break

        partial.status = ToolStatus.IMPORT_ERROR
        partial.error_type = "ModuleNotFoundError"
        partial.error_message = (
            f"{self.tool_name} crashed with a Python import error"
            + (f": missing '{missing_module}'" if missing_module else "")
        )
        partial.error_detail = partial.stderr   # full crash traceback from the tool
        partial.fix_hint = (
            f"The sandbox PYTHONPATH does not include the directory containing "
            f"'{missing_module or 'the missing module'}'. "
            f"Verify _locked_env() is assembling PYTHONPATH correctly, then "
            f"restart the Celery worker.\n"
            f"Current PYTHONPATH: {env.get('PYTHONPATH', '(empty)')}"
        )
        partial.sandbox_dir = self.sandbox_dir
        partial.effective_env = {k: env[k] for k in ("PATH", "PYTHONPATH", "HOME") if k in env}

        logger.error(
            "[%s] Import error in subprocess: %s\nFix hint: %s\nFull stderr:\n%s",
            self.tool_name,
            partial.error_message,
            partial.fix_hint,
            partial.stderr[:2000],  # cap log length
        )
        return partial

    def _build_nonzero_result(self, partial: ToolResult) -> ToolResult:
        """
        Classify a non-zero exit code.  Some tools (e.g. semgrep, bandit) use
        exit code 1 to mean "findings present" — that is not an error.
        """
        findings_exit_codes: dict[str, set[int]] = {
            "semgrep": {1},    # 1 = findings found (not an error)
            "bandit":  {1},
            "dalfox":  {1},
        }
        ok_codes = findings_exit_codes.get(self.tool_name, set())

        if partial.exit_code in ok_codes:
            # Exit code is expected — treat as SUCCESS
            partial.status = ToolStatus.SUCCESS
            partial.debug_notes.append(
                f"Exit code {partial.exit_code} is normal for {self.tool_name} "
                f"(means findings were produced)."
            )
            logger.info(
                "[%s] Exited %d (findings present) in %.1fs",
                self.tool_name, partial.exit_code, partial.duration_seconds,
            )
            return partial

        # Genuine error exit
        partial.status = ToolStatus.NONZERO_EXIT
        partial.error_type = "NonZeroExit"
        partial.error_message = (
            f"{self.tool_name} exited with code {partial.exit_code}."
        )
        partial.error_detail = (
            f"STDOUT:\n{partial.stdout[:1000]}\n\nSTDERR:\n{partial.stderr[:1000]}"
        )
        partial.fix_hint = (
            f"Check {self.tool_name} documentation for exit code {partial.exit_code}. "
            f"Run the command manually to reproduce: {' '.join(partial.command)}"
        )

        logger.error(
            "[%s] Non-zero exit %d.\nstdout: %s\nstderr: %s",
            self.tool_name,
            partial.exit_code,
            partial.stdout[:500],
            partial.stderr[:500],
        )
        return partial
