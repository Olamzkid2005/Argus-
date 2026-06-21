"""
tool_core/sandbox.py — AsyncToolRunner

Async execution engine for external binary tools.

Wraps the existing synchronous ``tools/tool_runner.ToolRunner`` for security
measures (env locking, dangerous detection, output caps, circuit breaker,
arg redaction) while providing async subprocess execution via
``asyncio.create_subprocess_exec()``.

Adds scope validation on every ``run()`` invocation — the only security gap
from the audit findings that wasn't already present in ``ToolRunner``.

Usage::

    runner = AsyncToolRunner()
    result = await runner.run("nuclei", ["-u", "https://example.com", "-json"])
    print(result.to_report_dict())
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from tool_core.registry import ToolRegistry
from tool_core.result import ToolStatus, UnifiedToolResult

logger = logging.getLogger(__name__)


class AsyncToolRunner:
    """
    Async execution engine for external binary tools.

    Delegates to the existing ``tools/tool_runner.ToolRunner`` for:
    - ``is_dangerous()`` — dangerous pattern detection
    - ``_locked_env()`` — environment sanitisation
    - ``_redact_sensitive_args()`` — API token redaction from CLI args
    - ``_resolve_tool_path()`` — binary path resolution
    - Circuit breaker state management

    Provides as its own addition:
    - ``asyncio.create_subprocess_exec()`` instead of ``subprocess.run()``
    - Scope validation on every ``run()``
    - ``UnifiedToolResult`` return type (vs legacy ``ToolResult``)
    - Async output streaming with per-line callbacks
    """

    MAX_OUTPUT_BYTES: int = 10 * 1024 * 1024  # 10 MB — matches ToolRunner

    # Tool-specific exit codes that signal "findings present, not an error"
    FINDINGS_EXIT_CODES: dict[str, set[int]] = {
        "semgrep": {1},
        "bandit": {1},
        "gitleaks": {1},
        "dalfox": {1},
        "trivy": {1},
        "pip-audit": {1},
    }

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        tool_runner: Any | None = None,
        engagement_id: str = "",
    ) -> None:
        """
        Args:
            registry: Shared ``ToolRegistry`` instance (created if None).
            tool_runner: Existing ``ToolRunner`` instance to delegate to.
                If None, one is created lazily on first ``run()``.
            engagement_id: Default engagement UUID for scope validation
                and logging.
        """
        self.registry = registry or ToolRegistry()
        self._runner: Any = tool_runner
        self.engagement_id = engagement_id

    # ── Lazy ToolRunner factory ──────────────────────────────────────

    def _get_runner(self) -> Any:
        """Get or create the delegate ``ToolRunner`` instance."""
        if self._runner is None:
            from tools.tool_runner import ToolRunner

            self._runner = ToolRunner(engagement_id=self.engagement_id)
        return self._runner

    # ── Public API ───────────────────────────────────────────────────

    async def run(
        self,
        tool: str,
        args: list[str],
        timeout: int = 180,
        target: str = "",
        engagement_id: str = "",
    ) -> UnifiedToolResult:
        """
        Execute a tool binary asynchronously.

        Flow:
        1. Dangerous-arg detection (via ``ToolRunner.is_dangerous()``)
        2. Scope validation (via ``validate_target_scope()``)
        3. Circuit-breaker check
        4. Tool path resolution
        5. Locked env + arg redaction
        6. ``asyncio.create_subprocess_exec()`` with timeout
        7. Output size capping
        8. ``UnifiedToolResult`` construction

        Args:
            tool: Tool name (e.g. ``"nuclei"``, ``"httpx"``).
            args: List of CLI arguments.
            timeout: Seconds before the subprocess is killed.
            target: Target URL / hostname (for scope validation and result).
            engagement_id: Override default engagement ID.

        Returns:
            ``UnifiedToolResult`` with status, stdout, stderr, exit code, etc.

        Raises:
            ``SecurityError``: if dangerous patterns are detected in args.
        """
        from tools.tool_runner import SecurityError

        runner = self._get_runner()
        eng_id = engagement_id or self.engagement_id

        # 1. Dangerous-arg detection
        if runner.is_dangerous(tool, args):
            raise SecurityError(f"Blocked dangerous payload: {tool} {' '.join(args)}")

        # 2. Scope validation (fail-closed — out-of-scope targets are denied)
        if target and eng_id:
            from tool_core.validators.scope import validate_target_scope

            if not validate_target_scope(target, eng_id):
                result = UnifiedToolResult(
                    tool_name=tool,
                    target=target,
                    command=[tool, *args],
                    status=ToolStatus.SKIPPED,
                    error_message=(
                        f"Target {target!r} is out of scope for engagement {eng_id}"
                    ),
                )
                result.mark_finished()
                return result

        # 3. Circuit-breaker check
        if not runner.is_tool_available(tool):
            from tools.circuit_breaker import CircuitOpenError

            raise CircuitOpenError(
                f"Circuit breaker is OPEN for tool {tool!r}. Wait before retrying."
            )

        # 4. Resolve tool path
        tool_path = self.registry.resolve(tool) or runner._resolve_tool_path(tool)
        if not tool_path:
            raise RuntimeError(
                f"Tool {tool!r} could not be resolved — no path found via registry or runner"
            )

        # 5. Locked env + arg redaction
        env = runner._locked_env(tool)
        safe_args, env = runner._redact_sensitive_args(args, env)

        # 6. Async subprocess execution
        result = UnifiedToolResult(
            tool_name=tool,
            target=target,
            command=[tool_path, *safe_args],
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                tool_path,
                *safe_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=str(runner.sandbox_dir),
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except TimeoutError:
                proc.kill()
                await proc.wait()
                result.status = ToolStatus.TIMEOUT
                result.error_message = f"Tool execution timed out after {timeout}s"
                result.mark_finished()
                return result

            stdout = (
                stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
            )
            stderr = (
                stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
            )

            # 7. Output size capping
            if len(stdout) > self.MAX_OUTPUT_BYTES:
                logger.warning(
                    "Truncating stdout for %s (%d bytes > %d limit)",
                    tool,
                    len(stdout),
                    self.MAX_OUTPUT_BYTES,
                )
                stdout = stdout[: self.MAX_OUTPUT_BYTES]
            if len(stderr) > self.MAX_OUTPUT_BYTES:
                logger.warning(
                    "Truncating stderr for %s (%d bytes > %d limit)",
                    tool,
                    len(stderr),
                    self.MAX_OUTPUT_BYTES,
                )
                stderr = stderr[: self.MAX_OUTPUT_BYTES]

            exit_code = proc.returncode or 0

            # 8. Build UnifiedToolResult
            result.stdout = stdout
            result.stderr = stderr
            result.exit_code = exit_code

            result.status = (
                ToolStatus.SUCCESS
                if (
                    exit_code == 0
                    or exit_code in self.FINDINGS_EXIT_CODES.get(tool, set())
                )
                else ToolStatus.NONZERO_EXIT
            )

        except SecurityError:
            raise  # Re-raise — caller handles it

        except Exception as e:
            result = UnifiedToolResult.from_exception(
                tool,
                [tool_path, *safe_args],
                e,
                target=target,
            )

        finally:
            result.mark_finished()

        # Record circuit breaker outcome
        try:
            if result.status.is_ok:
                runner.record_tool_success(tool)
            else:
                runner.record_tool_failure(tool)
        except Exception:
            logger.debug("Circuit-breaker recording failed for %s", tool)

        return result

    async def run_streaming(
        self,
        tool: str,
        args: list[str],
        timeout: int = 180,
        on_line: Callable[[str], bool | None] | None = None,
        target: str = "",
        engagement_id: str = "",
    ) -> UnifiedToolResult:
        """
        Execute a tool asynchronously, streaming stdout line by line.

        Each line of stdout is passed to ``on_line()``. If the callback
        returns ``False``, the process is killed early.

        Stderr is collected in full and returned in the result.

        Args:
            tool: Tool name.
            args: CLI arguments.
            timeout: Maximum execution time.
            on_line: Called with each line of stdout (stripped).
                Return ``False`` to abort.
            target: Target URL.
            engagement_id: Engagement UUID.

        Returns:
            ``UnifiedToolResult`` with streamed stdout + full stderr.
        """
        from tools.tool_runner import SecurityError

        runner = self._get_runner()
        eng_id = engagement_id or self.engagement_id

        # 1. Dangerous-arg detection
        if runner.is_dangerous(tool, args):
            raise SecurityError(f"Blocked dangerous payload: {tool} {' '.join(args)}")

        # 2. Scope validation
        if target and eng_id:
            from tool_core.validators.scope import validate_target_scope

            if not validate_target_scope(target, eng_id):
                result = UnifiedToolResult(
                    tool_name=tool,
                    target=target,
                    command=[tool, *args],
                    status=ToolStatus.SKIPPED,
                    error_message=(
                        f"Target {target!r} is out of scope for engagement {eng_id}"
                    ),
                )
                result.mark_finished()
                return result

        # 3. Circuit-breaker check
        if not runner.is_tool_available(tool):
            from tools.circuit_breaker import CircuitOpenError

            raise CircuitOpenError(f"Circuit breaker is OPEN for tool {tool!r}.")

        # 4. Resolve tool path
        tool_path = self.registry.resolve(tool) or runner._resolve_tool_path(tool)

        # 5. Locked env + arg redaction
        env = runner._locked_env(tool)
        safe_args, env = runner._redact_sensitive_args(args, env)

        # 6. Async streaming subprocess
        result = UnifiedToolResult(
            tool_name=tool,
            target=target,
            command=[tool_path, *safe_args],
        )

        stdout_lines: list[str] = []
        total_bytes = 0
        timed_out = False

        try:
            proc = await asyncio.create_subprocess_exec(
                tool_path,
                *safe_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=str(runner.sandbox_dir),
            )

            async def _read_stdout() -> None:
                """Read stdout line by line, calling on_line if provided."""
                nonlocal total_bytes
                assert proc.stdout is not None
                while True:
                    line_bytes = await proc.stdout.readline()
                    if not line_bytes:
                        break
                    total_bytes += len(line_bytes)
                    if total_bytes > self.MAX_OUTPUT_BYTES:
                        logger.warning(
                            "Streaming output for %s exceeded %d byte limit",
                            tool,
                            self.MAX_OUTPUT_BYTES,
                        )
                        proc.kill()
                        break
                    line = line_bytes.decode("utf-8", errors="replace")
                    stdout_lines.append(line)
                    if on_line is not None:
                        try:
                            if on_line(line.rstrip("\n\r")) is False:
                                proc.kill()
                                break
                        except Exception as cb_err:
                            logger.debug(
                                "on_line callback failed for %s: %s", tool, cb_err
                            )

            async def _read_stderr() -> str:
                """Read full stderr output."""
                assert proc.stderr is not None
                stderr_bytes = await proc.stderr.read()
                return (
                    stderr_bytes.decode("utf-8", errors="replace")
                    if stderr_bytes
                    else ""
                )

            # Run stdout reader and stderr reader concurrently
            stderr_future = asyncio.ensure_future(_read_stderr())

            try:
                await asyncio.wait_for(_read_stdout(), timeout=timeout)
            except TimeoutError:
                timed_out = True
                proc.kill()

            # Wait for stderr reader to finish
            stderr = await stderr_future
            await proc.wait()

            stderr_output = stderr or ""
            if len(stderr_output) > self.MAX_OUTPUT_BYTES:
                stderr_output = stderr_output[: self.MAX_OUTPUT_BYTES]

            result.stdout = "".join(stdout_lines)
            result.stderr = stderr_output
            result.exit_code = proc.returncode or 0

            if timed_out:
                result.status = ToolStatus.TIMEOUT
                result.error_message = (
                    f"Streaming tool execution timed out after {timeout}s"
                )
            else:
                result.status = (
                    ToolStatus.SUCCESS
                    if (
                        result.exit_code == 0
                        or result.exit_code in self.FINDINGS_EXIT_CODES.get(tool, set())
                    )
                    else ToolStatus.NONZERO_EXIT
                )

        except SecurityError:
            raise
        except Exception as e:
            result = UnifiedToolResult.from_exception(
                tool,
                [tool_path, *safe_args],
                e,
                target=target,
            )
        finally:
            result.mark_finished()

        # Record circuit breaker outcome
        try:
            if result.status.is_ok:
                runner.record_tool_success(tool)
            else:
                runner.record_tool_failure(tool)
        except Exception:
            logger.debug("Circuit-breaker recording failed for %s", tool)

        return result

    # ── Sync wrapper ─────────────────────────────────────────────────

    def run_sync(
        self,
        tool: str,
        args: list[str],
        timeout: int = 180,
        target: str = "",
        engagement_id: str = "",
    ) -> UnifiedToolResult:
        """
        Synchronous wrapper for callers not yet migrated to async.

        Runs ``self.run()`` via ``asyncio.run()``. This creates a new
        event loop each call, so it's fine for occasional use but not
        for hot loops.
        """
        import asyncio

        return asyncio.run(
            self.run(
                tool, args, timeout=timeout, target=target, engagement_id=engagement_id
            )
        )
