"""
Agent Package - ReAct Agent Loop for LLM-driven tool selection.

Provides:
- ReActAgent: Main agent loop with LLM-backed and deterministic modes
- CoordinatorAgent: Multi-phase agent coordinator
- ToolRegistry: Registry of available tools
- AgentAction / AgentResult: Core data types
"""
from .agent_action import AgentAction
from .agent_prompts import (
    BUGBOUNTY_STOPPING_RULES,
    BUGBOUNTY_TOOL_CATALOGUE,
    BUGBOUNTY_TOOL_SELECTION_SYSTEM_PROMPT,
    REPORT_SYSTEM_PROMPT,
    REPO_TOOL_CATALOGUE,
    REPO_STOPPING_RULES,
    REPO_TOOL_SELECTION_SYSTEM_PROMPT,
    SYNTHESIS_SYSTEM_PROMPT,
    TOOL_SELECTION_SYSTEM_PROMPT,
    WEBAPP_TOOL_CATALOGUE,
    WEBAPP_STOPPING_RULES,
    _load_bugbounty_context,
    build_report_prompt,
    build_synthesis_prompt,
    build_tool_selection_prompt,
)
from .agent_result import AgentResult
from .coordinator import CoordinatorAgent, create_phase_agent
from .react_agent import ReActAgent
from .tool_registry import ToolRegistry

__all__ = [
    "AgentAction",
    "AgentResult",
    "ToolRegistry",
    "ReActAgent",
    "CoordinatorAgent",
    "create_phase_agent",
    "BUGBOUNTY_STOPPING_RULES",
    "BUGBOUNTY_TOOL_CATALOGUE",
    "BUGBOUNTY_TOOL_SELECTION_SYSTEM_PROMPT",
    "REPORT_SYSTEM_PROMPT",
    "REPO_TOOL_CATALOGUE",
    "REPO_STOPPING_RULES",
    "REPO_TOOL_SELECTION_SYSTEM_PROMPT",
    "SYNTHESIS_SYSTEM_PROMPT",
    "TOOL_SELECTION_SYSTEM_PROMPT",
    "WEBAPP_TOOL_CATALOGUE",
    "WEBAPP_STOPPING_RULES",
    "_load_bugbounty_context",
    "build_tool_selection_prompt",
    "build_synthesis_prompt",
    "build_report_prompt",
]
