"""
Coordinator Agent - Delegates to ReActAgent.create_for_phase().

This module exists for backward compatibility. New code should use
ReActAgent.create_for_phase() directly.
"""
import logging

from utils.logging_utils import ScanLogger

from .react_agent import ReActAgent

logger = logging.getLogger(__name__)


class CoordinatorAgent:
    """Multi-Agent Coordinator — delegates phases to ReActAgent.

    Deprecated: Use ReActAgent.create_for_phase() directly.
    """

    @classmethod
    def _ensure_phase_agents(cls):
        """Delegate to ReActAgent's phase tool loading."""
        ReActAgent._ensure_phase_tools()
        # Sync references after ReActAgent lazy-loads its class attributes
        cls.PHASE_AGENTS = ReActAgent.PHASE_AGENTS
        cls.VALID_TRANSITIONS = ReActAgent.VALID_TRANSITIONS

    # Default — replaced by _ensure_phase_agents() with ReActAgent's
    # lazy-loaded values. Backward-compatible: tests access
    # CoordinatorAgent.PHASE_AGENTS/VALID_TRANSITIONS directly.
    PHASE_AGENTS = ReActAgent.PHASE_AGENTS
    VALID_TRANSITIONS = ReActAgent.VALID_TRANSITIONS

    def __init__(self, engagement_id: str):
        self.engagement_id = engagement_id
        self.current_phase = "recon"
        self.phase_results: dict[str, list] = {}
        self._slog = ScanLogger("coordinator", engagement_id=engagement_id)

    def can_transition_to(self, next_phase: str) -> bool:
        """Check if transition to next phase is valid."""
        return next_phase in ReActAgent.VALID_TRANSITIONS.get(self.current_phase, [])

    def transition_to(self, next_phase: str) -> bool:
        """Transition to next phase if valid."""
        if not self.can_transition_to(next_phase):
            logger.warning("Invalid transition: %s -> %s",
                          self.current_phase, next_phase)
            return False
        self._slog.transition(self.current_phase, next_phase, "coordinator transition")
        self.current_phase = next_phase
        return True

    def get_phase_agent(self, phase: str, tool_runner=None,
                        llm_client=None, decision_repo=None,
                        engagement_id: str = None, mode: str | None = None) -> ReActAgent:
        """Create a ReAct agent for a specific phase (delegates to ReActAgent.create_for_phase)."""
        return ReActAgent.create_for_phase(
            phase,
            tool_runner=tool_runner,
            engagement_id=engagement_id or self.engagement_id,
            llm_client=llm_client,
            decision_repo=decision_repo,
            mode=mode,
        )

    def run_phase(self, phase: str, context: dict, tool_runner=None,
                  llm_client=None, decision_repo=None, mode: str | None = None) -> list:
        """Run a single phase with tools."""
        self._slog.phase_header(f"COORDINATOR RUN PHASE: {phase}")
        agent = ReActAgent.create_for_phase(
            phase,
            tool_runner=tool_runner,
            engagement_id=self.engagement_id,
            llm_client=llm_client,
            decision_repo=decision_repo,
            mode=mode,
        )
        task_desc = ReActAgent.PHASE_AGENTS.get(phase, {}).get("description", phase)
        results = agent.run(task_desc, initial_context=context)
        self._slog.info(f"Phase {phase} complete: {len(results)} results")
        self.phase_results[phase] = results
        return results


def create_phase_agent(
    phase: str,
    tool_runner=None,
    engagement_id: str = None,
    llm_client=None,
    decision_repo=None,
    mode: str | None = None,
) -> ReActAgent:
    """
    Create a ReActAgent for a specific phase.

    Delegates to ReActAgent.create_for_phase(). This function exists for
    backward compatibility. New code should use ReActAgent.create_for_phase().

    Args:
        phase: Phase name (recon, scan, repo_scan, analyze, report)
        tool_runner: Optional ToolRunner instance to register real tools
        engagement_id: Optional engagement ID for context
        llm_client: Optional LLMClient for LLM-driven tool selection
        decision_repo: Optional AgentDecisionRepository for logging
        mode: Optional mode ('bugbounty' for Bug-Reaper methodology, None for default)

    Returns:
        Configured ReActAgent
    """
    return ReActAgent.create_for_phase(
        phase=phase,
        tool_runner=tool_runner,
        engagement_id=engagement_id,
        llm_client=llm_client,
        decision_repo=decision_repo,
        mode=mode,
    )
