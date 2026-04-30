"""
Coordinator Agent - Multi-Agent Coordinator that delegates phases to specialized sub-agents.
"""
import logging
from typing import Dict, List, Optional

from .react_agent import ReActAgent
from .tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


class CoordinatorAgent:
    """Multi-Agent Coordinator — delegates phases to specialized sub-agents."""

    PHASE_AGENTS = {}
    _phase_agents_loaded = False

    @classmethod
    def _ensure_phase_agents(cls):
        if not cls._phase_agents_loaded:
            from tool_definitions import get_tools_for_phase
            cls.PHASE_AGENTS = {
                phase: {
                    "description": f"{phase.capitalize().replace('_', ' ')}",
                    "tools": [t.name for t in get_tools_for_phase(phase)],
                }
                for phase in ["recon", "scan", "deep_scan", "repo_scan", "analyze", "report"]
            }
            cls._phase_agents_loaded = True

    VALID_TRANSITIONS = {
        "recon": ["scan"],
        "scan": ["analyze", "deep_scan"],
        "deep_scan": ["analyze"],
        "repo_scan": ["scan"],
        "analyze": ["report", "recon"],
        "report": [],
    }

    def __init__(self, engagement_id: str):
        self.engagement_id = engagement_id
        self.current_phase = "recon"
        self.phase_results: Dict[str, List] = {}

    def can_transition_to(self, next_phase: str) -> bool:
        """Check if transition to next phase is valid."""
        self._ensure_phase_agents()
        return next_phase in self.VALID_TRANSITIONS.get(self.current_phase, [])

    def transition_to(self, next_phase: str) -> bool:
        """Transition to next phase if valid."""
        if not self.can_transition_to(next_phase):
            logger.warning("Invalid transition: %s -> %s",
                          self.current_phase, next_phase)
            return False
        self.current_phase = next_phase
        return True

    def get_phase_agent(self, phase: str, tool_runner=None,
                        llm_client=None, decision_repo=None,
                        engagement_id: str = None) -> ReActAgent:
        """Create a ReAct agent for a specific phase."""
        return create_phase_agent(
            phase,
            tool_runner=tool_runner,
            engagement_id=engagement_id or self.engagement_id,
            llm_client=llm_client,
            decision_repo=decision_repo,
        )

    def run_phase(self, phase: str, context: Dict, tool_runner=None,
                  llm_client=None, decision_repo=None) -> List:
        """Run a single phase with tools."""
        self._ensure_phase_agents()
        agent = create_phase_agent(
            phase,
            tool_runner=tool_runner,
            engagement_id=self.engagement_id,
            llm_client=llm_client,
            decision_repo=decision_repo,
        )
        task_desc = self.PHASE_AGENTS.get(phase, {}).get("description", phase)
        results = agent.run(task_desc, initial_context=context)
        self.phase_results[phase] = results
        return results


def create_phase_agent(
    phase: str,
    tool_runner=None,
    engagement_id: str = None,
    llm_client=None,
    decision_repo=None,
) -> ReActAgent:
    """
    Create a ReActAgent for a specific phase with tools pre-registered.

    Args:
        phase: Phase name (recon, scan, repo_scan, analyze, report)
        tool_runner: Optional ToolRunner instance to register real tools
        engagement_id: Optional engagement ID for context
        llm_client: Optional LLMClient for LLM-driven tool selection
        decision_repo: Optional AgentDecisionRepository for logging

    Returns:
        Configured ReActAgent
    """
    registry = ToolRegistry()
    ReActAgent._ensure_phase_tools()
    phase_tools = ReActAgent.PHASE_TOOLS.get(phase, [])

    if tool_runner:
        for tool_name in phase_tools:
            def make_runner(tn):
                def run_tool(target: str = "", **kwargs):
                    args = kwargs.pop("args", [])
                    timeout = kwargs.pop("timeout", 300)
                    if target:
                        args = [target] + (args or [])
                    return tool_runner.run(tn, args, timeout=timeout)
                run_tool.__name__ = tn
                return run_tool

            registry.register(
                tool_name,
                make_runner(tool_name),
                {"name": tool_name, "description": f"Run {tool_name}", "parameters": []}
            )

    agent = ReActAgent(
        registry,
        llm_client=llm_client,
        decision_repo=decision_repo,
        engagement_id=engagement_id,
        phase=phase,
    )
    return agent
