"""
Agent Package - ReAct Agent Loop for LLM-driven tool selection.

Provides:
- ReActAgent: Main agent loop with LLM-backed and deterministic modes
- CoordinatorAgent: Multi-phase agent coordinator
- ToolRegistry: Registry of available tools
- AgentAction / AgentResult: Core data types
"""
from .agent_action import AgentAction
from .agent_result import AgentResult
from .tool_registry import ToolRegistry
from .react_agent import ReActAgent
from .coordinator import CoordinatorAgent, create_phase_agent
from .agent_prompts import (
    TOOL_SELECTION_SYSTEM_PROMPT,
    SYNTHESIS_SYSTEM_PROMPT,
    REPORT_SYSTEM_PROMPT,
    build_tool_selection_prompt,
    build_synthesis_prompt,
    build_report_prompt,
)

__all__ = [
    "AgentAction",
    "AgentResult",
    "ToolRegistry",
    "ReActAgent",
    "CoordinatorAgent",
    "create_phase_agent",
    "TOOL_SELECTION_SYSTEM_PROMPT",
    "SYNTHESIS_SYSTEM_PROMPT",
    "REPORT_SYSTEM_PROMPT",
    "build_tool_selection_prompt",
    "build_synthesis_prompt",
    "build_report_prompt",
]
