"""
Re-exports from the agent package for backward compatibility.

DEPRECATED: Import directly from the agent package instead.
"""
from agent.agent_result import AgentResult  # noqa: F401
from agent.tool_registry import ToolRegistry  # noqa: F401
from agent.react_agent import ReActAgent  # noqa: F401
from agent.coordinator import CoordinatorAgent, create_phase_agent  # noqa: F401
