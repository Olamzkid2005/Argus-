"""
Agent Action - A decision the agent made to call a tool.
"""

import uuid


class AgentAction:
    """An action the agent decided to take."""

    def __init__(
        self,
        tool: str,
        arguments: dict,
        reasoning: str = "",
        cost_usd: float = 0.0,
        action_id: str | None = None,
        confidence: float = 0.5,
        estimated_runtime: int = 300,
        expected_signal: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
    ):
        self.action_id = action_id or str(uuid.uuid4())
        self.tool = tool
        self.arguments = arguments
        self.reasoning = reasoning
        self.cost_usd = cost_usd
        self.confidence = confidence
        self.estimated_runtime = estimated_runtime
        self.expected_signal = expected_signal
        # Actual LLM token counts from the response (blocker 48)
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens

    def to_dict(self) -> dict:
        return {
            "action_id": self.action_id,
            "tool": self.tool,
            "arguments": self.arguments,
            "reasoning": self.reasoning,
            "cost_usd": self.cost_usd,
            "confidence": self.confidence,
            "estimated_runtime": self.estimated_runtime,
            "expected_signal": self.expected_signal,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }
