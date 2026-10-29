"""
Agent Result - Result from a tool execution within the agent loop.
"""


class AgentResult:
    """Result from a tool execution within the agent loop."""

    def __init__(
        self,
        tool: str,
        success: bool,
        output: str = "",
        error: str = "",
        duration_ms: int = 0,
        findings: list = None,
        retryable: bool | None = None,
    ):
        self.tool = tool
        self.success = success
        self.output = output
        self.error = error
        self.duration_ms = duration_ms
        self.findings = findings or []
        # None means "decide from the failure message"; False means the call was
        # rejected before it ran (invalid arguments), so retrying is pointless.
        self.retryable = retryable

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "success": self.success,
            "summary": (self.output[:500] if self.output else self.error)[:500],
            "duration_ms": self.duration_ms,
            "findings_count": len(self.findings),
        }
