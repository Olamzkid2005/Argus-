"""
Agent Result - Result from a tool execution within the agent loop.
"""
from typing import Dict, Optional


class AgentResult:
    """Result from a tool execution within the agent loop."""
    def __init__(self, tool: str, success: bool, output: str = "",
                 error: str = "", duration_ms: int = 0, findings: list = None):
        self.tool = tool
        self.success = success
        self.output = output
        self.error = error
        self.duration_ms = duration_ms
        self.findings = findings or []

    def to_dict(self) -> Dict:
        return {
            "tool": self.tool,
            "success": self.success,
            "summary": (self.output[:500] if self.output else self.error)[:500],
            "duration_ms": self.duration_ms,
            "findings_count": len(self.findings),
        }
