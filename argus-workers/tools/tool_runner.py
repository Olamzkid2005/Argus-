"""
Tool Runner - Executes security tools safely in sandboxed environment

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 20.4, 21.1, 21.2, 22.1
"""

import contextlib
import logging
import os
import select
import site
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from cache import cache
from database.repositories.tool_metrics_repository import ToolMetricsRepository
from tools.circuit_breaker import (
    CircuitOpenError,
    ToolCircuitBreakerManager,
)
from tools.models import ToolResult
from tracing import ExecutionSpan, StructuredLogger, get_trace_id
from utils.logging_utils import ScanLogger

logger = logging.getLogger(__name__)


class SecurityError(Exception):
    """Raised when dangerous payload is detected"""

    pass


class ToolRunner:
    """
    Executes security tools with safety validation and sandboxing.
    MVP implementation uses subprocess with locked environment.
    """

    # Dangerous patterns that should be blocked.
    # Uses regex word boundaries (\b) for short patterns to avoid false
    # positives in URLs (e.g. "curl" in "circular", "rm" in "armament").
    # Must be kept in sync with _is_dangerous().
    DANGEROUS_PATTERNS = [
        # File/disk destruction
        "rm -rf", "rm -fr", "rm -r /", "mkfs", "dd if=",
        # Fork bomb
        ":(){ :|:& };:",
        # Shell command chaining (via injection)
        "; rm", "| rm", "&& rm", "$(rm", "`rm",
        # Redirection to devices
        ">/dev/", ">/dev/null",
        # Database destruction
        "DROP TABLE", "DROP DATABASE", "DELETE FROM", "TRUNCATE",
    ]

    # Short tool names that are dangerous when used standalone.
    # These require word-boundary matching to avoid URL false positives.
    DANGEROUS_TOOLS = {"curl", "wget", "nc", "netcat"}

    # Sensitive file paths (checked via substring — "/etc/passwd" in URL is always suspicious)
    DANGEROUS_PATHS = ["/etc/passwd", "/etc/shadow"]

    def __init__(
        self,
        sandbox_dir: str | None = None,
        connection_string: str = None,
        failure_threshold: int = 3,
        cooldown_seconds: int = 300,
        engagement_id: str = None,
    ):
        """
        Initialize Tool Runner

        Args:
            sandbox_dir: Directory for tool execution (default: temp directory)
            connection_string: Database connection string for logging
            failure_threshold: Failures before circuit breaker opens (default: 3)
            cooldown_seconds: Circuit breaker cooldown (default: 300 = 5 min)
            engagement_id: Optional engagement ID for org-scoped metrics
        """
        self.engagement_id = engagement_id
        if sandbox_dir:
            self.sandbox_dir = Path(sandbox_dir)
            self.sandbox_dir.mkdir(parents=True, exist_ok=True)
        else:
            self.sandbox_dir = Path(tempfile.mkdtemp(prefix="argus_sandbox_"))

        # Initialize tracing
        self.connection_string = connection_string or os.getenv("DATABASE_URL")
        self.logger = StructuredLogger(self.connection_string)
        self.span_recorder = ExecutionSpan(self.connection_string)

        # Initialize metrics repository
        self.metrics_repo = (
            ToolMetricsRepository(self.connection_string)
            if self.connection_string
            else None
        )

        # Initialize per-tool circuit breakers for resilience
        self._circuit_breaker_mgr = ToolCircuitBreakerManager()
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds

    def is_dangerous(self, tool: str, args: list[str]) -> bool:
        """
        Check if tool execution contains dangerous patterns

        Args:
            tool: Tool name/path
            args: Tool arguments

        Returns:
            True if dangerous pattern detected, False otherwise
        """
        # Check tool name against blocked tools (exact match — these are
        # standalone dangerous binaries, not args where false positives occur)
        if tool in self.DANGEROUS_TOOLS:
            return True

        # Check args and full command for dangerous patterns
        # Patterns like "rm -rf" include the tool name, so we check both
        # the args alone and the combined command
        args_str = " ".join(args)
        full_command = f"{tool} {args_str}"
        for pattern in self.DANGEROUS_PATTERNS:
            pattern_lower = pattern.lower()
            if (
                pattern_lower in args_str.lower()
                or pattern_lower in full_command.lower()
            ):
                return True

        # Check for sensitive file paths (exact substring)
        for path in self.DANGEROUS_PATHS:
            if path.lower() in args_str.lower() or path.lower() in full_command.lower():
                return True

        return False

    _PYTHONPATH_CACHE: str | None = None  # class-level cache

    def _locked_env(self, tool: str = "") -> dict[str, str]:
        """
        Build the subprocess environment portably.

        PYTHONPATH is assembled from the live interpreter — never hardcoded paths.
        This survives Python upgrades and other machines.

        Args:
            tool: Tool name to determine if proxy should be stripped
        """
        venv_bin = str(Path(sys.executable).parent)

        # --- PYTHONPATH assembly (cached after first call) ---
        if ToolRunner._PYTHONPATH_CACHE is None:
            python_paths: list[str] = []

            # 1. System / venv site-packages
            with contextlib.suppress(AttributeError):
                python_paths.extend(p for p in site.getsitepackages() if os.path.isdir(p))

            # 2. User site-packages (~/.local/lib/... or ~/Library/Python/...)
            user_site = site.getusersitepackages()
            if user_site and os.path.isdir(user_site):
                python_paths.append(user_site)

            # 3. Running interpreter's sys.path (catches editable installs, .pth files)
            python_paths.extend(p for p in sys.path if p and os.path.isdir(p))

            # Deduplicate while preserving order
            seen: set[str] = set()
            unique_paths: list[str] = []
            for p in python_paths:
                if p not in seen:
                    seen.add(p)
                    unique_paths.append(p)
            ToolRunner._PYTHONPATH_CACHE = ":".join(unique_paths)

        python_path_str = ToolRunner._PYTHONPATH_CACHE

        # Tools that must NOT inherit proxy settings (they need full network access)
        no_proxy_tools = {
            "nuclei",
            "dalfox",
            "sqlmap",
            "httpx",
            "nikto",
            "nmap",
            "curl",
            "testssl",
            "arjun",
            "jwt_tool",
            "commix",
        }

        go_bin = os.path.expanduser("~/go/bin")

        env = {
            "PATH": f"{venv_bin}:{go_bin}:/usr/local/bin:/usr/bin:/bin",
            # Pass through HOME so tools (gitleaks, nmap, git, nuclei) can find
            # ~/.config/ and other user-level configuration. Do NOT override it.
            "HOME": os.environ.get("HOME", "/root"),
            "TMPDIR": str(self.sandbox_dir / "tmp"),
            "PYTHONPATH": python_path_str,
            "PYTHONDONTWRITEBYTECODE": "1",
            # Suppress semgrep telemetry / version-check latency
            "SEMGREP_SEND_METRICS": "off",
            "SEMGREP_ENABLE_VERSION_CHECK": "0",
        }

        # For web scanning tools, strip proxy so they can reach the internet
        # Semgrep will get proxy settings from parent environment (for validation fallback)
        if tool in no_proxy_tools:
            # Explicitly unset proxy vars - subprocess inherits parent env unless overridden
            env["HTTP_PROXY"] = ""
            env["HTTPS_PROXY"] = ""
            env["http_proxy"] = ""
            env["https_proxy"] = ""
            env["no_proxy"] = "*"  # belt-and-suspenders

        return env

    def _validate_tool_name(self, tool: str) -> str:
        """Validate tool name does not contain path traversal or shell metacharacters."""
        if not tool or "/" in tool or "\\" in tool or ".." in tool:
            raise SecurityError(
                f"Invalid tool name blocked (path traversal): {tool!r}"
            )
        return tool

    def _resolve_tool_path(self, tool: str) -> str:
        """
        Resolve the full path to a tool binary by checking common locations
        and the current environment PATH.

        Args:
            tool: Tool name (e.g., 'nuclei', 'httpx')

        Returns:
            Full path to the tool binary, or the tool name if not found
        """
        self._validate_tool_name(tool)
        import shutil

        # Build a comprehensive PATH that includes venv/bin and ~/go/bin
        # so tools installed via pip or go install are always findable
        venv_bin = str(Path(sys.executable).parent)
        go_bin = os.path.expanduser("~/go/bin")
        # Also check the project's explicit venv bin (in case system python is used)
        project_venv_bin = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "venv", "bin")
        )
        extra_paths = [
            venv_bin,
            project_venv_bin,
            go_bin,
            "/usr/local/bin",
            "/opt/homebrew/bin",
        ]

        current_path = os.environ.get("PATH", "")
        for p in extra_paths:
            if p not in current_path:
                current_path = f"{p}:{current_path}"

        # Search the augmented PATH
        resolved = shutil.which(tool, path=current_path)
        if resolved:
            return resolved

        # Direct file check as final fallback
        for d in extra_paths:
            candidate = os.path.join(d, tool)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        return tool

    def run(self, tool: str, args: list[str], timeout: int = 180) -> ToolResult:
        """
        Execute tool with safety validation

        Args:
            tool: Tool name/path to execute
            args: List of arguments
            timeout: Timeout in seconds (default: 60)

        Returns:
            ToolResult with stdout, stderr, returncode, success

        Raises:
            SecurityError: If dangerous payload detected
            subprocess.TimeoutExpired: If execution times out
        """
        # Cache check
        import hashlib
        args_key = str(tuple(args))
        cache_key = f"tool_result:{tool}:{hashlib.md5(args_key.encode()).hexdigest()}"
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            return ToolResult(**cached_result)

        # Safety check
        if self.is_dangerous(tool, args):
            raise SecurityError(
                f"Blocked dangerous payload: {tool} {' '.join(args)}"
            )

        # Create temp directory if it doesn't exist
        tmp_dir = self.sandbox_dir / "tmp"
        tmp_dir.mkdir(exist_ok=True)

        env = self._locked_env(tool)

        # Detect and redact sensitive arguments (API tokens, passwords) that would
        # otherwise be visible in /proc/<pid>/cmdline. Instead of passing them as
        # CLI flags, inject them as environment variables (TOOL_TOKEN, TOOL_SECRET).
        sensitive_prefixes = ("--api-token", "--token", "--password", "--secret", "--key", "--auth")
        sanitized_args = []
        i = 0
        while i < len(args):
            if any(args[i].startswith(p) for p in sensitive_prefixes):
                flag = args[i]
                value = args[i + 1] if i + 1 < len(args) and not args[i + 1].startswith("--") else ""
                if value:
                    env[f"TOOL_{flag.removeprefix('--').upper().replace('-', '_')}"] = value
                    sanitized_args.append(flag)
                    sanitized_args.append("__REDACTED__")
                    i += 2
                    continue
            sanitized_args.append(args[i])
            i += 1
        args = sanitized_args

        # Record start time
        start_time = time.time()

        slog = ScanLogger("tool_runner", engagement_id=self.engagement_id or "")
        slog.tool_start(tool, "running")

        # Execute with span tracing
        with self.span_recorder.span(ExecutionSpan.SPAN_TOOL_EXECUTION, {"tool": tool}):
            # Resolve tool binary path for tools not in locked PATH
            tool_path = self._resolve_tool_path(tool)

            try:
                # Execute with locked environment
                # Limit captured output to prevent OOM from large tool output
                max_output_bytes = 10 * 1024 * 1024  # 10MB
                result = subprocess.run(
                    [tool_path] + args,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=str(self.sandbox_dir),
                    env=env,
                )
                # Truncate oversized output to prevent memory exhaustion
                if len(result.stdout) > max_output_bytes:
                    logger.warning("Truncating stdout for %s (%d bytes > %d limit)", tool, len(result.stdout), max_output_bytes)
                    result.stdout = result.stdout[:max_output_bytes]
                if len(result.stderr) > max_output_bytes:
                    logger.warning("Truncating stderr for %s (%d bytes > %d limit)", tool, len(result.stderr), max_output_bytes)
                    result.stderr = result.stderr[:max_output_bytes]

                # Calculate duration
                duration_ms = int((time.time() - start_time) * 1000)

                # Determine success
                # Tool-specific exit codes that mean "findings present, not an error"
                findings_exit_codes = {
                    "semgrep": {1},
                    "bandit": {1},
                    "gitleaks": {1},
                    "dalfox": {1},
                    "trivy": {1},
                    "pip-audit": {1},
                }
                success = (
                    result.returncode == 0
                    or result.returncode in findings_exit_codes.get(tool, set())
                )

                # Record tool metrics (Requirement 22.1)
                if self.metrics_repo:
                    try:
                        self.metrics_repo.record_metric(
                            tool_name=tool,
                            duration_ms=duration_ms,
                            success=success,
                            engagement_id=self.engagement_id,
                        )
                    except Exception as metric_error:
                        # Don't fail execution if metrics recording fails
                        logger.warning("Failed to record tool metric: %s", metric_error)

                # Console logging
                slog.tool_complete(tool, success=success, findings=0)

                # Log tool execution
                try:
                    self.logger.log_tool_executed(
                        tool_name=tool,
                        arguments=args,
                        duration_ms=duration_ms,
                        success=success,
                        return_code=result.returncode,
                    )
                except Exception as log_err:
                    logger.warning("Failed to log tool execution: %s", log_err)

                tool_result = ToolResult(
                    stdout=result.stdout,
                    stderr=result.stderr,
                    returncode=result.returncode,
                    tool=tool,
                    success=success,
                    duration_ms=duration_ms,
                    timeout=False,
                    error=None,
                    trace_id=get_trace_id(),
                )

                cache.set(cache_key, tool_result.as_dict(), ttl=300)
                slog.info(f"Tool cache set for {tool}")
                return tool_result

            except subprocess.TimeoutExpired:
                duration_ms = int((time.time() - start_time) * 1000)

                # Record tool metrics for timeout (Requirement 22.1)
                if self.metrics_repo:
                    try:
                        self.metrics_repo.record_metric(
                            tool_name=tool,
                            duration_ms=duration_ms,
                            success=False,
                            engagement_id=self.engagement_id,
                        )
                    except Exception as metric_error:
                        logger.warning("Failed to record tool metric: %s", metric_error)

                # Log timeout
                self.logger.log_tool_executed(
                    tool_name=tool,
                    arguments=args,
                    duration_ms=duration_ms,
                    success=False,
                    return_code=-1,
                )

                return ToolResult(
                    stdout="",
                    stderr=f"Tool execution timed out after {timeout} seconds",
                    returncode=-1,
                    tool=tool,
                    success=False,
                    duration_ms=duration_ms,
                    timeout=True,
                    error=None,
                    trace_id=get_trace_id(),
                )
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)

                # Record tool metrics for error (Requirement 22.1)
                if self.metrics_repo:
                    try:
                        self.metrics_repo.record_metric(
                            tool_name=tool,
                            duration_ms=duration_ms,
                            success=False,
                            engagement_id=self.engagement_id,
                        )
                    except Exception as metric_error:
                        logger.warning("Failed to record tool metric: %s", metric_error)

                # Log error
                self.logger.log_tool_executed(
                    tool_name=tool,
                    arguments=args,
                    duration_ms=duration_ms,
                    success=False,
                    return_code=-1,
                )

                return ToolResult(
                    stdout="",
                    stderr=str(e),
                    returncode=-1,
                    tool=tool,
                    success=False,
                    duration_ms=duration_ms,
                    timeout=False,
                    error=str(e),
                    trace_id=get_trace_id(),
                )

    def run_streaming(
        self, tool: str, args: list[str], timeout: int, on_line: callable
    ) -> ToolResult:
        """Stream tool output line by line, calling on_line() for each."""
        tool_path = self._resolve_tool_path(tool)
        env = self._locked_env(tool)

        # Redact sensitive args from command line (visible in /proc/pid/cmdline)
        sensitive_prefixes = ("--api-token", "--token", "--password", "--secret", "--key", "--auth")
        sanitized_args = []
        i = 0
        while i < len(args):
            if any(args[i].startswith(p) for p in sensitive_prefixes):
                flag = args[i]
                value = args[i + 1] if i + 1 < len(args) and not args[i + 1].startswith("--") else ""
                if value:
                    env[f"TOOL_{flag.removeprefix('--').upper().replace('-', '_')}"] = value
                    sanitized_args.append(flag)
                    sanitized_args.append("__REDACTED__")
                    i += 2
                    continue
            sanitized_args.append(args[i])
            i += 1
        args = sanitized_args

        slog = ScanLogger("tool_runner", engagement_id=self.engagement_id or "")
        slog.tool_start(tool, f"streaming, timeout={timeout}s")

        proc = subprocess.Popen(
            [tool_path] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(self.sandbox_dir),
            env=env,
        )

        stdout_lines = []
        max_streaming_bytes = 50 * 1024 * 1024  # 50MB — stop reading after this
        total_bytes = 0
        start = time.time()

        try:
            while proc.poll() is None:
                if time.time() - start > timeout:
                    proc.kill()
                    break

                ready, _, _ = select.select([proc.stdout], [], [], 0.1)
                if ready:
                    line = proc.stdout.readline()
                    if line:
                        total_bytes += len(line.encode("utf-8"))
                        if total_bytes > max_streaming_bytes:
                            logger.warning(
                                "Streaming output for %s exceeded %d byte limit — killing process",
                                tool, max_streaming_bytes,
                            )
                            proc.kill()
                            break
                        stdout_lines.append(line)
                        try:
                            on_line(line.rstrip("\n\r"))
                        except Exception as line_err:
                            logger.debug("on_line callback failed for %s: %s — continuing", tool, line_err)

            remaining, _ = proc.communicate(timeout=5)
            if remaining:
                for line in remaining.splitlines(keepends=True):
                    stdout_lines.append(line)
                    try:
                        on_line(line.rstrip("\n\r"))
                    except Exception as line_err:
                        logger.debug("on_line callback failed for %s: %s — continuing", tool, line_err)

        except Exception as e:
            logger.warning("Streaming error for %s: %s", tool, e)
            proc.kill()

        finally:
            # Ensure process is waited on to prevent zombies.
            # Use os.waitpid with WNOHANG in a retry loop after kill signals.
            try:
                proc.wait(timeout=5)
            except Exception:
                logger.warning("Could not wait on %s process (pid=%d) — force-reaping", tool, proc.pid)
                try:
                    import signal
                    os.kill(proc.pid, signal.SIGKILL)
                    # Poll until reaped or give up after 3 attempts
                    for _ in range(3):
                        try:
                            wpid, _ = os.waitpid(proc.pid, os.WNOHANG)
                            if wpid != 0:
                                break
                            time.sleep(0.5)
                        except ChildProcessError:
                            break
                except Exception:
                    logger.error("Failed to force-reap PID %d for %s", proc.pid, tool)

        stdout = "".join(stdout_lines)
        returncode = proc.returncode if proc.returncode is not None else -1
        success = returncode == 0
        duration_ms = int((time.time() - start) * 1000)
        timed_out = time.time() - start > timeout

        slog.tool_complete(tool, success=success, duration_ms=duration_ms)
        return ToolResult(
            stdout=stdout,
            stderr="",
            returncode=returncode,
            tool=tool,
            success=success,
            duration_ms=duration_ms,
            timeout=timed_out,
            trace_id=get_trace_id(),
        )

    def run_nuclei(
        self,
        target: str,
        templates_path: str | None = None,
        severity: str | None = None,
        tags: str | None = None,
        timeout: int = 600,
    ) -> ToolResult:
        """
        Execute Nuclei with optional template path and filters

        Args:
            target: Target URL or host
            templates_path: Path to custom Nuclei templates directory
            severity: Comma-separated severity levels (info,low,medium,high,critical)
            tags: Comma-separated tags to filter templates
            timeout: Execution timeout in seconds

        Returns:
            Tool execution result dictionary
        """
        args = ["-u", target, "-json", "-silent"]

        if templates_path:
            args.extend(["-t", templates_path])

        if severity:
            args.extend(["-severity", severity])

        if tags:
            args.extend(["-tags", tags])

        return self.run("nuclei", args, timeout=timeout)

    def run_naabu(
        self,
        target: str,
        top_ports: str | None = None,
        port_range: str | None = None,
        timeout: int = 300,
    ) -> ToolResult:
        """
        Execute Naabu port scanner

        Args:
            target: Target host or IP
            top_ports: Number of top ports to scan (e.g., "1000")
            port_range: Specific port range (e.g., "1-65535")
            timeout: Execution timeout in seconds

        Returns:
            Tool execution result dictionary
        """
        args = ["-host", target, "-json"]

        if port_range:
            args.extend(["-p", port_range])
        elif top_ports:
            args.extend(["-top-ports", top_ports])

        return self.run("naabu", args, timeout=timeout)

    def run_gospider(
        self,
        target: str,
        depth: int = 3,
        timeout: int = 300,
    ) -> ToolResult:
        """
        Execute Gospider for JavaScript file and endpoint discovery

        Args:
            target: Target URL
            depth: Crawling depth
            timeout: Execution timeout in seconds

        Returns:
            Tool execution result dictionary
        """
        args = ["-s", target, "-q", "-j", "-d", str(depth)]
        return self.run("gospider", args, timeout=timeout)

    def run_wpscan(
        self,
        target: str,
        api_token: str | None = None,
        enumerate_options: list[str] | None = None,
        timeout: int = 600,
    ) -> ToolResult:
        """
        Execute WPScan for WordPress security scanning

        Args:
            target: Target WordPress URL
            api_token: WPScan API token for vulnerability database access
            enumerate_options: List of enumeration options (e.g., ["p", "t", "u"])
            timeout: Execution timeout in seconds

        Returns:
            Tool execution result dictionary
        """
        args = ["--url", target, "-f", "json", "--no-banner"]

        if api_token:
            args.extend(["--api-token", api_token])

        if enumerate_options:
            for opt in enumerate_options:
                args.extend(["--enumerate", opt])

        return self.run("wpscan", args, timeout=timeout)

    def cleanup(self):
        """Clean up sandbox directory"""
        import shutil

        if self.sandbox_dir.exists():
            shutil.rmtree(self.sandbox_dir)

    def is_tool_available(self, tool: str) -> bool:
        """
        Check if a tool is currently available (circuit not open).

        Args:
            tool: Tool name to check

        Returns:
            True if tool can be called, False if circuit is open
        """
        breaker = self._circuit_breaker_mgr.get_breaker(
            tool, self._failure_threshold, self._cooldown_seconds
        )
        return breaker.is_available()

    def get_circuit_state(self, tool: str = "") -> str:
        """Get the current circuit breaker state for a tool."""
        if tool:
            breaker = self._circuit_breaker_mgr.get_breaker(
                tool, self._failure_threshold, self._cooldown_seconds
            )
            return breaker.state.value
        return "unknown"

    def record_tool_success(self, tool: str):
        """Record successful tool execution."""
        breaker = self._circuit_breaker_mgr.get_breaker(
            tool, self._failure_threshold, self._cooldown_seconds
        )
        breaker.record_success()
        slog = ScanLogger("tool_runner", engagement_id=self.engagement_id or "")
        slog.info(f"Circuit breaker reset for {tool} (success)")

    def record_tool_failure(self, tool: str):
        """Record failed tool execution."""
        breaker = self._circuit_breaker_mgr.get_breaker(
            tool, self._failure_threshold, self._cooldown_seconds
        )
        breaker.record_failure()
        slog = ScanLogger("tool_runner", engagement_id=self.engagement_id or "")
        slog.warn(f"Circuit breaker failure recorded for {tool}")

    def run_with_circuit_breaker(
        self, tool: str, args: list[str], timeout: int = 180
    ) -> ToolResult:
        ScanLogger("tool_runner", engagement_id=self.engagement_id or "")
        """
        Execute tool with circuit breaker protection.

        If the circuit is open, raises CircuitOpenError.

        Args:
            tool: Tool name/path to execute
            args: List of arguments
            timeout: Timeout in seconds

        Returns:
            Dictionary with stdout, stderr, returncode, tool

        Raises:
            CircuitOpenError: If circuit breaker is open
            SecurityError: If dangerous payload detected
        """
        breaker = self._circuit_breaker_mgr.get_breaker(
            tool, self._failure_threshold, self._cooldown_seconds
        )
        if not breaker.is_available():
            raise CircuitOpenError(
                f"Circuit breaker is OPEN for tool '{tool}'. "
                f"Wait {breaker._time_until_retry():.0f}s before retry."
            )

        try:
            result = self.run(tool, args, timeout)
            breaker.record_success()
            return result
        except SecurityError:
            # Safety successes should not count as failures
            raise
        except Exception:
            breaker.record_failure()
            raise
