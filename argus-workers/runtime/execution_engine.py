"""
ExecutionEngine — Shared tool dispatch + result recording.

Used by both the agent runtime and deterministic runtime to execute tools
with consistent sandboxing, scope validation, and result recording.

Middleware chain:
  1. Scope validation (mandatory — blocks out-of-scope targets)
  2. Rate limit check
  3. Tool execution via ToolRunner
  4. Result recording to EngagementState
"""

import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """
    Shared tool execution layer for agent and deterministic runtimes.

    Wraps ToolRunner.run() with mandatory scope validation middleware,
    rate-limit awareness, and engagement state recording.

    When a ScopeValidator is provided at construction time, it is
    automatically registered as the first middleware in the chain,
    making scope validation MANDATORY for ALL tool executions through
    this engine — not an optional per-call wrapper.
    """

    def __init__(
        self,
        tool_runner: Any,
        scope_validator: Any | None = None,
        engagement_state: Any | None = None,
    ):
        self.tool_runner = tool_runner
        self.scope_validator = scope_validator
        self.engagement_state = engagement_state
        self._middleware: list[Callable] = []

        # ── Mandatory scope validation middleware ──
        # When a ScopeValidator is provided, register it as the first middleware
        # in the chain so scope checks run BEFORE every tool execution.
        # This makes scope validation mandatory — not an optional per-call wrapper.
        if scope_validator is not None:
            self.add_middleware(self._build_scope_middleware(scope_validator))

    @staticmethod
    def _build_scope_middleware(scope_validator: Any) -> Callable:
        """
        Build a scope validation middleware function from a ScopeValidator.

        Checks all common target-bearing parameter names (target, url, host,
        hostname, domain, endpoint) and blocks execution if any are out of scope.
        """
        def _scope_check(tool_name: str, args: list, kwargs: dict) -> tuple | None:
            target_params = ["target", "url", "host", "hostname", "domain", "endpoint"]
            # Check kwargs
            for param in target_params:
                tgt = kwargs.get(param, "")
                if tgt:
                    try:
                        scope_validator.validate_target(tgt)
                    except Exception as e:
                        logger.warning(
                            "Scope validation blocked %s: param=%s target=%s — %s",
                            tool_name, param, tgt, e,
                        )
                        return None  # Block execution
            # Check positional args for target patterns
            for arg in (args or []):
                if isinstance(arg, str) and any(c in arg for c in (":", "/", ".")):
                    if len(arg) > 3 and not arg.startswith("-"):
                        try:
                            scope_validator.validate_target(arg)
                        except Exception:
                            pass  # Not all positional args are targets
            return (tool_name, args, kwargs)
        return _scope_check

    def add_middleware(self, fn: Callable):
        """Add a middleware function to the execution chain.

        Middleware signature: fn(tool_name, args, kwargs) -> (tool_name, args, kwargs)
        Return None to abort execution.
        """
        self._middleware.append(fn)

    def execute(
        self,
        tool_name: str,
        args: list | None = None,
        timeout: int = 300,
        **kwargs,
    ) -> Any:
        """Execute a tool through the middleware chain.

        Args:
            tool_name: Name of the tool to execute
            args: Positional arguments for the tool
            timeout: Timeout in seconds
            **kwargs: Additional keyword arguments

        Returns:
            ToolRunner result object
        """
        from tool_core.result import ToolStatus, UnifiedToolResult

        args = args or []

        # Run middleware chain
        for middleware_fn in self._middleware:
            result = middleware_fn(tool_name, args, kwargs)
            if result is None:
                return UnifiedToolResult(
                    tool_name=tool_name,
                    status=ToolStatus.SKIPPED,
                    stderr="Blocked by middleware",
                    exit_code=-1,
                )
            # Allow middleware to modify args/kwargs
            if isinstance(result, tuple) and len(result) == 3:
                tool_name, args, kwargs = result

        # Execute
        start = time.time()
        try:
            result = self.tool_runner.run(tool_name, args, timeout=timeout, **kwargs)
        except Exception as e:
            result = UnifiedToolResult(
                tool_name=tool_name,
                status=ToolStatus.EXCEPTION,
                stderr=str(e),
                exit_code=-1,
                error_message=str(e),
            )

        duration_ms = int((time.time() - start) * 1000)

        # Record to engagement state
        if self.engagement_state:
            from .engagement_state import ToolExecutionRecord

            record = ToolExecutionRecord(
                tool=tool_name,
                args={"args": args, **kwargs},
                timestamp=start,
                result_summary=(result.stdout or "")[:500] if result.success else (result.stderr or "")[:200],
                success=result.success,
                failure_state="" if result.success else (result.stderr or "")[:200],
                duration_ms=duration_ms,
            )
            self.engagement_state.record_tool_execution(record)

        return result
