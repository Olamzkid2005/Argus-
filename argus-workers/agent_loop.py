"""
ReAct Agent Loop - LLM-driven tool selection and execution.

DEPRECATED: This module now re-exports from the agent package.
New code should import directly from agent.* modules.
"""
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

from agent import (
    AgentAction,
    AgentResult,
    ToolRegistry,
    ReActAgent,
    CoordinatorAgent,
    create_phase_agent,
)
