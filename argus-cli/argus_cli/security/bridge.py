"""
Security Bridge — connects CLI to Argus workers.

Provides clean integration points:
  - Lazy imports from argus-workers
  - Graceful degradation when workers unavailable
  - Deterministic fallback mode
  - Feature flag awareness
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Path to argus-workers
WORKERS_PATH = Path(__file__).parent.parent.parent.parent / "argus-workers"


def _ensure_workers_path() -> None:
    """Ensure argus-workers is on sys.path."""
    if str(WORKERS_PATH) not in sys.path:
        sys.path.insert(0, str(WORKERS_PATH))


def import_orchestrator() -> Any:
    """Lazy import the Argus Orchestrator."""
    try:
        _ensure_workers_path()
        from orchestrator_pkg import Orchestrator
        return Orchestrator
    except ImportError as e:
        logger.warning("Orchestrator not available: %s", e)
        return None


def import_agent() -> Any:
    """Lazy import the ReAct Agent."""
    try:
        _ensure_workers_path()
        from agent import ReActAgent
        return ReActAgent
    except ImportError as e:
        logger.warning("ReActAgent not available: %s", e)
        return None


def import_intelligence_engine() -> Any:
    """Lazy import the Intelligence Engine."""
    try:
        _ensure_workers_path()
        from intelligence_engine import IntelligenceEngine
        return IntelligenceEngine
    except ImportError as e:
        logger.warning("IntelligenceEngine not available: %s", e)
        return None


def import_state_machine() -> Any:
    """Lazy import the State Machine."""
    try:
        _ensure_workers_path()
        from state_machine import EngagementStateMachine
        return EngagementStateMachine
    except ImportError as e:
        logger.warning("EngagementStateMachine not available: %s", e)
        return None


def import_streaming() -> Any:
    """Lazy import the streaming system."""
    try:
        _ensure_workers_path()
        from streaming import get_stream_manager
        return get_stream_manager()
    except ImportError as e:
        logger.warning("Stream manager not available: %s", e)
        return None


def import_llm_client() -> Any:
    """Lazy import the LLM Client."""
    try:
        _ensure_workers_path()
        from llm_client import LLMClient
        return LLMClient
    except ImportError as e:
        logger.warning("LLMClient not available: %s", e)
        return None


def import_mcp_server() -> Any:
    """Lazy import the MCP Server."""
    try:
        _ensure_workers_path()
        from mcp_server import MCPServer
        return MCPServer
    except ImportError as e:
        logger.warning("MCPServer not available: %s", e)
        return None


def import_tool_definitions() -> Any:
    """Lazy import tool definitions."""
    try:
        _ensure_workers_path()
        from tool_definitions import TOOLS, get_tools_for_phase
        return TOOLS, get_tools_for_phase
    except ImportError as e:
        logger.warning("Tool definitions not available: %s", e)
        return None, None


def check_workers_available() -> dict[str, bool]:
    """Check which Argus worker components are available."""
    _ensure_workers_path()

    components = {
        "orchestrator": "orchestrator_pkg",
        "agent": "agent",
        "intelligence_engine": "intelligence_engine",
        "state_machine": "state_machine",
        "streaming": "streaming",
        "llm_client": "llm_client",
        "mcp_server": "mcp_server",
        "tool_definitions": "tool_definitions",
    }

    results = {}
    for name, module in components.items():
        try:
            __import__(module)
            results[name] = True
        except ImportError:
            results[name] = False

    return results


def get_bridge_status() -> dict[str, Any]:
    """Get full bridge status for diagnostics."""
    return {
        "workers_path": str(WORKERS_PATH),
        "workers_path_exists": WORKERS_PATH.exists(),
        "components": check_workers_available(),
        "sys_path_includes_workers": str(WORKERS_PATH) in sys.path,
        "python_path": sys.path[:3],
    }
