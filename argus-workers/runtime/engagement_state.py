"""
EngagementState — Canonical Runtime State for an engagement.

Centralizes all runtime state that was previously fragmented across:
- Celery task memory (ReActAgent.history)
- Orchestrator instance vars (_last_agent_tried_tools, _bug_bounty_mode)
- Redis (ReconContext serialization)
- LoopBudgetManager (in-memory budget)
- StateMachine (state transitions)

Every mutation increments state_version for replay safety.
"""

import logging
import time
from typing import Any

from state_machine import EngagementStateMachine
from loop_budget_manager import LoopBudgetManager

logger = logging.getLogger(__name__)


class ToolExecutionRecord:
    """Record of a single tool execution within the engagement."""

    def __init__(
        self,
        tool: str,
        args: dict,
        timestamp: float,
        result_summary: str = "",
        token_usage: int = 0,
        execution_cost: float = 0.0,
        success: bool = True,
        failure_state: str = "",
    ):
        self.tool = tool
        self.args = args
        self.timestamp = timestamp
        self.result_summary = result_summary
        self.token_usage = token_usage
        self.execution_cost = execution_cost
        self.success = success
        self.failure_state = failure_state

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "args": self.args,
            "timestamp": self.timestamp,
            "result_summary": self.result_summary[:500],
            "token_usage": self.token_usage,
            "execution_cost": self.execution_cost,
            "success": self.success,
            "failure_state": self.failure_state,
        }


class EngagementState:
    """
    Canonical runtime state for a single engagement.

    Wraps:
      - EngagementStateMachine (state transitions)
      - LoopBudgetManager (cycle/depth/LLM budgets)
      - Agent history / observations
      - Attack graph snapshot

    All runtime reads MUST come from this object — never from Redis raw reads,
    Celery task memory, or orchestrator instance variables.
    """

    def __init__(
        self,
        engagement_id: str,
        state_machine: EngagementStateMachine | None = None,
        budget_manager: LoopBudgetManager | None = None,
    ):
        self.engagement_id = engagement_id
        self.state_machine = state_machine
        self.budget_manager = budget_manager or LoopBudgetManager(engagement_id)

        # ── State fields ──
        self.recon_context: dict = {}
        self.findings: list[dict] = []
        self.observations: list[dict] = []
        self.hypotheses: list[str] = []
        self.tool_history: list[ToolExecutionRecord] = []
        self.failed_actions: list[dict] = []
        self.attack_graph: dict = {}
        self.confidence_scores: dict = {}
        self.memory_summary: str = ""
        self.current_goal: str = ""
        self.current_phase: str = "created"
        self.execution_iteration: int = 0
        self.state_version: int = 0
        self._bug_bounty_mode: bool = False
        self._agent_mode_enabled: bool = True
        self._last_agent_tried_tools: set[str] = set()

    # ── Versioned mutation ──

    def _bump_version(self):
        """Increment state_version on every mutation."""
        self.state_version += 1

    # ── Phase management ──

    @property
    def current_state(self) -> str:
        if self.state_machine:
            return self.state_machine.current_state
        return self.current_phase

    def can_transition_to(self, new_state: str) -> bool:
        if self.state_machine:
            return self.state_machine.can_transition_to(new_state)
        return True

    def transition(self, new_state: str, reason: str | None = None):
        if self.state_machine:
            self.state_machine.transition(new_state, reason)
        self.current_phase = new_state
        self._bump_version()

    # ── Observation building ──

    def add_observation(self, role: str, content: str, data: dict | None = None):
        """Add an observation to history (replaces ReActAgent.history)."""
        self.observations.append({
            "role": role,
            "content": content[:2000],
            "data": data or {},
            "timestamp": time.time(),
        })
        # Cap to last 50 entries
        if len(self.observations) > 50:
            self.observations = self.observations[-50:]
        self._bump_version()

    def get_context(self, max_entries: int = 6) -> str:
        """Build observation context string (replaces ReActAgent.get_context())."""
        recent = self.observations[-max_entries:]
        parts = [f"[{e['role']}]: {e['content']}" for e in recent]
        return "\n".join(parts)

    # ── Tool execution tracking ──

    def record_tool_execution(self, record: ToolExecutionRecord):
        """Record a tool execution (replaces ad-hoc tool tracking)."""
        self.tool_history.append(record)
        if record.success:
            self._last_agent_tried_tools.add(record.tool)
        self._bump_version()

    def mark_tool_tried(self, tool_name: str):
        """Mark a tool as tried with no result record (for fallback tracking)."""
        self._last_agent_tried_tools.add(tool_name)

    @property
    def tried_tools(self) -> set[str]:
        return self._last_agent_tried_tools

    # ── Budget delegation ──

    def budget_can_continue(self, action: dict) -> tuple[bool, str]:
        return self.budget_manager.can_continue(action)

    def budget_consume(self, action: dict):
        self.budget_manager.consume(action)
        self._bump_version()

    def budget_status(self) -> dict:
        return self.budget_manager.get_status()

    # ── Serialization ──

    def to_dict(self) -> dict:
        return {
            "engagement_id": self.engagement_id,
            "current_phase": self.current_phase,
            "current_state": self.current_state,
            "execution_iteration": self.execution_iteration,
            "state_version": self.state_version,
            "findings_count": len(self.findings),
            "observations_count": len(self.observations),
            "tool_history_count": len(self.tool_history),
            "failed_actions_count": len(self.failed_actions),
            "tried_tools": list(self._last_agent_tried_tools),
            "bug_bounty_mode": self._bug_bounty_mode,
            "budget": self.budget_manager.to_dict(),
            "memory_summary": self.memory_summary[:500] if self.memory_summary else "",
            "current_goal": self.current_goal,
        }

    def to_snapshot_dict(self) -> dict:
        """Build a snapshot-ready dict for SnapshotManager persistence."""
        return {
            "engagement_id": self.engagement_id,
            "state_version": self.state_version,
            "execution_iteration": self.execution_iteration,
            "observations": self.observations[-10:],  # last 10 observations
            "tool_history": [t.to_dict() for t in self.tool_history[-20:]],  # last 20 tools
            "tried_tools": list(self._last_agent_tried_tools),
            "attack_graph": self.attack_graph,
            "budget": self.budget_manager.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict, state_machine=None) -> "EngagementState":
        """Reconstruct from a dict (for loading from snapshots)."""
        state = cls(
            engagement_id=data.get("engagement_id", ""),
            state_machine=state_machine,
        )
        state.state_version = data.get("state_version", 0)
        state.execution_iteration = data.get("execution_iteration", 0)
        state.observations = data.get("observations", [])
        state.attack_graph = data.get("attack_graph", {})
        state._last_agent_tried_tools = set(data.get("tried_tools", []))
        state.current_phase = data.get("current_phase", "created")
        if data.get("budget"):
            state.budget_manager.load_from_db(data["budget"])
        return state

    # ── Bug bounty mode ──

    @property
    def bug_bounty_mode(self) -> bool:
        return self._bug_bounty_mode

    @bug_bounty_mode.setter
    def bug_bounty_mode(self, value: bool):
        self._bug_bounty_mode = value
        self._bump_version()
