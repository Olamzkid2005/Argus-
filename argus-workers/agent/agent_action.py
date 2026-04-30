"""
Agent Action - A decision the agent made to call a tool.
"""
from typing import Dict, Optional


class AgentAction:
    """An action the agent decided to take."""
    def __init__(self, tool: str, arguments: Dict, reasoning: str = "", cost_usd: float = 0.0):
        self.tool = tool
        self.arguments = arguments
        self.reasoning = reasoning
        self.cost_usd = cost_usd

    def to_dict(self) -> Dict:
        return {
            "tool": self.tool,
            "arguments": self.arguments,
            "reasoning": self.reasoning,
        }
