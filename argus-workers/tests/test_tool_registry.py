"""Tests for agent.tool_registry — Category: class"""

from agent.agent_result import AgentResult
from agent.tool_registry import ToolRegistry


class _UnifiedToolResultLike:
    """Simulates UnifiedToolResult shape — the non-AgentResult return type
    that tool functions return via tool_runner.run().
    """

    def __init__(
        self,
        success: bool = True,
        findings: list | None = None,
        output: str = "",
        error: str = "",
        error_message: str = "",
    ):
        self.success = success
        self.findings = findings or []
        self.output = output
        self.error = error
        self.error_message = error_message

    def __str__(self) -> str:
        return f"[_UnifiedToolResultLike] success={self.success} findings={len(self.findings)}"


def _make_tool_registry() -> ToolRegistry:
    """Create a ToolRegistry with a simple tool registered."""
    reg = ToolRegistry()

    def simple_tool(target: str = "", **kwargs):
        return _UnifiedToolResultLike(
            success=True,
            findings=[{"id": "f1", "type": "XSS"}],
            output="found 1 vulnerability",
            error="",
        )

    reg.register(
        "simple_tool",
        simple_tool,
        {
            "name": "simple_tool",
            "description": "A simple test tool",
            "parameters": [
                {"name": "target", "description": "Target URL", "required": True},
            ],
        },
    )
    return reg


class TestToolRegistry:
    """Tests for the ToolRegistry class."""

    def test_instantiation(self):
        """Default instantiation succeeds."""
        instance = ToolRegistry()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = ToolRegistry()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)


class TestToolRegistryCall:
    """Tests for ToolRegistry.call() — especially the fix that preserves
    findings and success from non-AgentResult returns.
    """

    def test_unknown_tool_returns_error(self):
        """Calling an unregistered tool returns an error AgentResult."""
        reg = _make_tool_registry()
        result = reg.call("nonexistent_tool")
        assert isinstance(result, AgentResult)
        assert result.success is False
        assert "Unknown tool" in result.error

    def test_tool_function_exception_returns_error(self):
        """When the tool function raises, call() returns an error AgentResult."""
        reg = ToolRegistry()

        def broken_tool():
            raise RuntimeError("Something broke")

        reg.register("broken_tool", broken_tool, {"name": "broken_tool"})

        result = reg.call("broken_tool")
        assert isinstance(result, AgentResult)
        assert result.success is False
        assert "Something broke" in result.error

    def test_preserves_findings_from_non_agent_result(self):
        """Findings from a UnifiedToolResult-like object are preserved
        in the returned AgentResult."""
        reg = _make_tool_registry()
        result = reg.call("simple_tool", target="https://example.com")
        assert isinstance(result, AgentResult)
        assert result.success is True
        assert len(result.findings) == 1
        assert result.findings[0]["id"] == "f1"
        assert result.findings[0]["type"] == "XSS"

    def test_preserves_success_from_non_agent_result(self):
        """When UnifiedToolResult-like object has success=False, the
        AgentResult should reflect that."""
        reg = ToolRegistry()

        def failing_tool():
            return _UnifiedToolResultLike(
                success=False,
                findings=[],
                output="",
                error="Connection refused",
            )

        reg.register("failing_tool", failing_tool, {"name": "failing_tool"})
        result = reg.call("failing_tool")
        assert isinstance(result, AgentResult)
        assert result.success is False
        assert "Connection refused" in result.error

    def test_preserves_empty_findings_from_non_agent_result(self):
        """When UnifiedToolResult-like has empty findings, AgentResult
        has empty findings list (not None)."""
        reg = ToolRegistry()

        def empty_tool():
            return _UnifiedToolResultLike(
                success=True, findings=[], output="no issues found"
            )

        reg.register("empty_tool", empty_tool, {"name": "empty_tool"})
        result = reg.call("empty_tool")
        assert isinstance(result, AgentResult)
        assert result.success is True
        assert result.findings == []

    def test_empty_output_falls_back_to_str(self):
        """When the result has no output attribute, call() falls back to
        str(result) for the output field."""
        reg = ToolRegistry()

        class MinimalResult:
            """Result object with no output attribute — tests fallback path."""

            def __init__(self):
                self.success = True
                self.findings = []
                self.error = ""

            def __str__(self):
                return "[MinimalResult] ok"

        reg.register(
            "minimal_tool",
            lambda: MinimalResult(),
            {"name": "minimal_tool"},
        )
        result = reg.call("minimal_tool")
        assert isinstance(result, AgentResult)
        assert result.success is True
        assert "[MinimalResult]" in result.output

    def test_passes_through_agent_result_directly(self):
        """When a tool function returns an AgentResult directly, it is
        passed through (not wrapped)."""
        reg = ToolRegistry()

        def agent_result_tool():
            return AgentResult(
                tool="agent_result_tool",
                success=True,
                output="direct agent result",
                findings=[{"id": "f2"}],
            )

        reg.register(
            "agent_result_tool",
            agent_result_tool,
            {"name": "agent_result_tool"},
        )
        result = reg.call("agent_result_tool")
        assert isinstance(result, AgentResult)
        assert result.success is True
        assert result.findings == [{"id": "f2"}]
        assert result.duration_ms >= 0  # duration was set by call()

    def test_preserves_error_message_attribute(self):
        """When UnifiedToolResult uses 'error_message' instead of 'error'
        (as UnifiedToolResult.error is a property returning self.error_message),
        call() should extract it correctly."""
        reg = ToolRegistry()

        class ErrorMessageResult:
            """Like UnifiedToolResult — has .error_message but .error
            is a property returning None when empty."""

            def __init__(self):
                self.success = False
                self.findings = []
                self.output = ""
                self.error_message = "TimeoutExpired: tool exceeded limit"

            @property
            def error(self) -> str | None:
                return self.error_message or None

        reg.register(
            "timeout_tool",
            lambda: ErrorMessageResult(),
            {"name": "timeout_tool"},
        )
        result = reg.call("timeout_tool")
        assert isinstance(result, AgentResult)
        assert result.success is False
        assert "TimeoutExpired" in result.error

    def test_none_findings_falls_back_to_empty_list(self):
        """When result.findings is None, call() falls back to [] safely."""
        reg = ToolRegistry()

        class NoneFindingsResult:
            def __init__(self):
                self.success = True
                self.findings = None
                self.output = "ok"
                self.error = ""

        reg.register(
            "none_findings_tool",
            lambda: NoneFindingsResult(),
            {"name": "none_findings_tool"},
        )
        result = reg.call("none_findings_tool")
        assert isinstance(result, AgentResult)
        assert result.success is True
        assert result.findings == []

    def test_findings_from_multi_finding_result(self):
        """Multiple findings are all preserved."""
        reg = ToolRegistry()

        def multi_finding_tool():
            return _UnifiedToolResultLike(
                success=True,
                findings=[
                    {"id": "f1", "type": "XSS"},
                    {"id": "f2", "type": "SQLI"},
                    {"id": "f3", "type": "SSRF"},
                ],
                output="3 vulnerabilities found",
            )

        reg.register(
            "multi_finding_tool",
            multi_finding_tool,
            {"name": "multi_finding_tool"},
        )
        result = reg.call("multi_finding_tool")
        assert isinstance(result, AgentResult)
        assert len(result.findings) == 3
        assert result.findings[0]["type"] == "XSS"
        assert result.findings[1]["type"] == "SQLI"
        assert result.findings[2]["type"] == "SSRF"

