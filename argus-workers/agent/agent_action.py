"""
Agent Action - A decision the agent made to call a tool.
"""


class AgentAction:
    """An action the agent decided to take."""
    def __init__(self, tool: str, arguments: dict, reasoning: str = "", cost_usd: float = 0.0):
        self.tool = tool
        self.arguments = arguments
        self.reasoning = reasoning
        self.cost_usd = cost_usd

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "arguments": self.arguments,
            "reasoning": self.reasoning,
        }
