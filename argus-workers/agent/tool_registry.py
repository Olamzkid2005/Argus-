"""
Tool Registry - Registry of available tools for the agent to use.
Bridges to the MCP protocol server for tool discovery.
"""

import logging
import time
from collections.abc import Callable

from .agent_result import AgentResult

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Registry of available tools for the agent to use."""

    def __init__(self):
        self._tools: dict[str, Callable] = {}
        self._tool_metadata: dict[str, dict] = {}

    def register(self, name: str, func: Callable, metadata: dict = None):
        """Register a callable tool function."""
        self._tools[name] = func
        self._tool_metadata[name] = metadata or {
            "name": name,
            "description": "",
            "parameters": [],
        }

    def get_tool(self, name: str) -> Callable | None:
        """Get a tool function by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[dict]:
        """List all available tools with their metadata."""
        return list(self._tool_metadata.values())

    def _validate_arguments(self, name: str, kwargs: dict) -> None:
        """Validate that provided arguments match the tool's parameter schema.

        Raises ValueError with details on first validation failure.
        """
        metadata = self._tool_metadata.get(name, {})
        parameters = metadata.get("parameters", [])
        if not parameters:
            return  # no schema → no validation

        allowed_keys = {p.get("name", "") for p in parameters}
        for key in kwargs:
            if key not in allowed_keys:
                raise ValueError(
                    f"Tool '{name}' received unknown parameter '{key}'. "
                    f"Allowed: {sorted(allowed_keys)}"
                )

        for param in parameters:
            pname = param.get("name", "")
            if pname not in kwargs:
                if param.get("required", False):
                    raise ValueError(
                        f"Tool '{name}' missing required parameter '{pname}'"
                    )
                continue

            value = kwargs[pname]
            enum_values = param.get("enum")
            if enum_values and value not in enum_values:
                raise ValueError(
                    f"Tool '{name}' parameter '{pname}' value '{value}' "
                    f"not in allowed values: {enum_values}"
                )

            param_type = param.get("type", "")
            if param_type == "integer" and not isinstance(value, int):
                raise ValueError(
                    f"Tool '{name}' parameter '{pname}' expected integer, got {type(value).__name__}"
                )
            if param_type == "boolean" and not isinstance(value, bool):
                raise ValueError(
                    f"Tool '{name}' parameter '{pname}' expected boolean, got {type(value).__name__}"
                )

            max_val = param.get("max")
            if (
                max_val is not None
                and isinstance(value, (int, float))
                and value > max_val
            ):
                raise ValueError(
                    f"Tool '{name}' parameter '{pname}' value {value} exceeds max {max_val}"
                )
            min_val = param.get("min")
            if (
                min_val is not None
                and isinstance(value, (int, float))
                and value < min_val
            ):
                raise ValueError(
                    f"Tool '{name}' parameter '{pname}' value {value} below min {min_val}"
                )

    def call(self, name: str, timeout: float | None = None, **kwargs) -> AgentResult:
        """Call a tool function by name with arguments.

        ``timeout`` is the execution timeout, not a tool parameter. It stayed in
        ``kwargs`` before, so schema validation rejected every call with
        ``received unknown parameter 'timeout'`` — an error that mentions a
        retryable word and therefore burned all retries on arguments the tool
        never got. A tool that declares its own ``timeout`` parameter still
        receives the value as an argument.
        """
        start = time.time()
        func = self._tools.get(name)
        if not func:
            return AgentResult(tool=name, success=False, error=f"Unknown tool: {name}")

        metadata_parameters = self._tool_metadata.get(name, {}).get("parameters", [])
        if timeout is not None and any(
            p.get("name") == "timeout" for p in metadata_parameters
        ):
            kwargs["timeout"] = timeout
            timeout = None

        try:
            self._validate_arguments(name, kwargs)
        except ValueError as e:
            # The call never reached the tool. Retrying cannot change a
            # parameter that does not exist or is over its limit, and the
            # message alone must not decide that: a rejected name such as
            # `connection_timeout` reads like a transient failure.
            return AgentResult(
                tool=name,
                success=False,
                error=f"Invalid arguments: {e}",
                duration_ms=int((time.time() - start) * 1000),
                retryable=False,
            )
        call_kwargs = dict(kwargs)
        if timeout is not None:
            call_kwargs["timeout"] = timeout
        try:
            result = func(**call_kwargs)
            duration = int((time.time() - start) * 1000)
            if isinstance(result, AgentResult):
                result.duration_ms = duration
                return result
            # Preserve findings and success from non-AgentResult returns
            # (e.g., UnifiedToolResult from tool_runner.run()).
            # Previously these were hardcoded to success=True with empty findings.
            _findings = getattr(result, "findings", None) or []
            _success = getattr(result, "success", True)
            _error = getattr(result, "error", "") or getattr(result, "error_message", "")
            _output = getattr(result, "output", "")
            return AgentResult(
                tool=name,
                success=bool(_success),
                output=str(_output) if _output else str(result),
                error=str(_error),
                findings=_findings,
                duration_ms=duration,
            )
        except Exception as e:
            duration = int((time.time() - start) * 1000)
            return AgentResult(
                tool=name, success=False, error=str(e), duration_ms=duration
            )
