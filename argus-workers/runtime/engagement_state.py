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
from datetime import UTC
from typing import Any

from loop_budget_manager import LoopBudgetManager
from state_machine import EngagementStateMachine

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
        duration_ms: int = 0,
    ):
        self.tool = tool
        self.args = args
        self.timestamp = timestamp
        self.result_summary = result_summary
        self.token_usage = token_usage
        self.execution_cost = execution_cost
        self.success = success
        self.failure_state = failure_state
        self.duration_ms = duration_ms

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
            "duration_ms": self.duration_ms,
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
        attack_graph: Any | None = None,
        state_cache: Any | None = None,
    ):
        self.engagement_id = engagement_id
        self.state_machine = state_machine
        self.budget_manager = budget_manager or LoopBudgetManager(engagement_id)

        # ── Redis fast-access cache (optional, wired on creation) ──
        self._state_cache: Any | None = state_cache

        # ── State fields ──
        self.recon_context: dict = {}
        self.findings: list[dict] = []
        self.observations: list[dict] = []
        self.hypotheses: list[dict] = []
        self._hypothesis_write_failures: int = 0
        self.tool_history: list[ToolExecutionRecord] = []
        self.failed_actions: list[dict] = []
        self.attack_graph: dict = {}
        self._attack_graph_instance: Any | None = attack_graph
        self.confidence_scores: dict = {}
        self.memory_summary: str = ""
        self.current_goal: str = ""
        self.current_phase: str = "created"
        self.execution_iteration: int = 0
        self.state_version: int = 0
        self._bug_bounty_mode: bool = False
        self._agent_mode_enabled: bool = True
        self._last_agent_tried_tools: set[str] = set()
        self.obstacles: list[
            dict
        ] = []  # NEW — BolaWorkflow obstacles (in-memory only; count exposed via to_dict)

    # ── Versioned mutation ──

    def _bump_version(self):
        """Increment state_version on every mutation.

        If a Redis state_cache is attached, auto-persists the snapshot
        so the agent loop always reads fresh data without a DB round-trip.
        """
        self.state_version += 1
        if self._state_cache is not None:
            self._state_cache.save(self.engagement_id, self.to_dict())

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

    def safe_transition(self, new_state: str, reason: str | None = None) -> bool:
        """
        Attempt a state transition, silently skip if terminal.
        Delegates to EngagementStateMachine.safe_transition().

        Returns True if the transition was applied, False if skipped.
        """
        if self.state_machine:
            return self.state_machine.safe_transition(new_state, reason)
        if self.current_phase in ("complete", "failed"):
            return False
        self.current_phase = new_state
        self._bump_version()
        return True

    def chain_transition(
        self, states: list[tuple[str, str]], trace_id: str | None = None
    ) -> str:
        """
        Perform multiple state transitions atomically.
        Delegates to EngagementStateMachine.chain_transition().

        Args:
            states: List of (new_state, reason) tuples to chain through

        Returns:
            The final state after all transitions
        """
        if self.state_machine:
            return self.state_machine.chain_transition(states, trace_id)
        for new_state, _reason in states:
            self.current_phase = new_state
        self._bump_version()
        return self.current_phase

    # ── Observation building ──

    def add_observation(self, role: str, content: str, data: dict | None = None):
        """Add an observation to history (replaces ReActAgent.history)."""
        self.observations.append(
            {
                "role": role,
                "content": content[:2000],
                "data": data or {},
                "timestamp": time.time(),
            }
        )
        # Cap to last 50 entries
        if len(self.observations) > 50:
            self.observations = self.observations[-50:]
        self._bump_version()

    def get_context(self, max_entries: int = 6) -> str:
        """Build observation context string (replaces ReActAgent.get_context())."""
        recent = self.observations[-max_entries:]
        parts = [f"[{e['role']}]: {e['content']}" for e in recent]
        return "\n".join(parts)

    # ── Obstacle tracking (BolaWorkflow / future workflow obstacles) ──

    def add_obstacle(self, obstacle: dict) -> None:
        """Append an obstacle to the obstacle list.

        Standard fields: type, detected_at, step, recoverable, recovery_paths, metadata.
        Sets detected_at if not provided. Triggers _bump_version() to persist
        the obstacle COUNT to Redis (full list is in-memory only).

        OBSERVABILITY: Each call site should ALSO log the obstacle via
        slog.warning() with type and step, since the full dict is not persisted.

        SECURITY: Obstacle metadata MUST NOT contain credentials (passwords,
        cookie strings, tokens) or AuthError message strings. The AuthError
        exception at auth_manager.py:659,744 can include response bodies, URLs,
        and form field names in its message. Store only error_class: str(e) is
        prohibited. See plan's mitigation log item "AuthError message leak."
        """
        obstacle.setdefault("detected_at", time.time())
        self.obstacles.append(obstacle)
        self._bump_version()

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

    def set_attack_graph_instance(self, graph: Any) -> None:
        """Attach an AttackGraph instance for live path computation.

        When set, build_observation() includes actual attack paths from
        the graph instead of the static attack_graph dict placeholder.

        Args:
            graph: An AttackGraph instance (or anything with to_snapshot_dict())
        """
        self._attack_graph_instance = graph
        self._bump_version()

    # ── Budget delegation ──

    def budget_can_continue(self, action: dict) -> tuple[bool, str]:
        return self.budget_manager.can_continue(action)

    def budget_consume(self, action: dict):
        self.budget_manager.consume(action)
        self._bump_version()

    def budget_status(self) -> dict:
        return self.budget_manager.get_status()

    # ── Observation building ──

    def build_observation(self) -> dict:
        """
        Build a complete observation dict for the agent loop.
        Includes all state needed for the LLM to reason about next actions.
        This replaces the ad-hoc observation history in ReActAgent.

        When ATTACK_GRAPH_V2 is enabled and an AttackGraph instance has been
        attached via set_attack_graph_instance(), attack_graph_paths contains
        live-computed attack paths with risk scores, prerequisites, and impacts.
        Otherwise, falls back to the static attack_graph dict placeholder.

        Note: Hypotheses are explicitly excluded from this dict to avoid a third
        copy of hypothesis data. Postgres is the authoritative store. Consumers
        that need hypotheses call get_active_hypotheses() explicitly.
        """
        from feature_flags import is_enabled as _ff_enabled

        if (
            _ff_enabled("ATTACK_GRAPH_V2", default=False)
            and self._attack_graph_instance is not None
        ):
            try:
                snapshot = self._attack_graph_instance.to_snapshot_dict()
                attack_paths = snapshot.get("paths", [])[:5]
            except Exception:
                attack_paths = self.attack_graph.get("paths", [])[:5]
        else:
            attack_paths = self.attack_graph.get("paths", [])[:5]

        return {
            "engagement_id": self.engagement_id,
            "current_phase": self.current_phase,
            "execution_iteration": self.execution_iteration,
            "recent_observations": self.get_context(max_entries=5),
            "findings_count": len(self.findings),
            "recent_tools": [t.to_dict() for t in self.tool_history[-10:]],
            "failed_actions": self.failed_actions[-5:],
            "attack_graph_paths": attack_paths,
            "budget_status": self.budget_manager.get_status(),
            "tried_tools": list(self._last_agent_tried_tools),
            "memory_summary": self.memory_summary[:1000] if self.memory_summary else "",
            "hypothesis_write_failures": self._hypothesis_write_failures,
        }

    def is_complete(self) -> bool:
        """Check if the engagement is in a terminal state."""
        return self.current_state in ("complete", "failed")

    # ── Hypothesis management ──

    def add_hypothesis(self, hypothesis: dict) -> None:
        """Populate in-memory cache. Caller must have written to Postgres first."""
        self.hypotheses.append(hypothesis)

    def update_hypothesis(self, hypothesis_id: str, updates: dict) -> bool:
        """Update in-memory cache. Caller must have written to Postgres first.

        Returns True if the hypothesis was found and updated, False otherwise.
        """
        from datetime import datetime

        for h in self.hypotheses:
            if h.get("id") == hypothesis_id:
                h.update(updates)
                h["updated_at"] = datetime.now(UTC).isoformat()
                return True
        return False

    def get_active_hypotheses(self, max_count: int = 10) -> list[dict]:
        """Get top unverified hypotheses by confidence.

        Checks in-memory cache first. If cold (worker restart / no writes yet),
        falls back to Postgres. Redis is never consulted for hypotheses directly.

        Returns empty list on any failure — agent continues without hypothesis context.
        """
        unverified = [
            h for h in self.hypotheses if h.get("status") == "UNVERIFIED"
        ]
        if not unverified:
            try:
                from database.repositories.hypothesis_repository import (
                    HypothesisRepository,
                )

                repo = HypothesisRepository()
                unverified = repo.get_by_engagement(
                    self.engagement_id, status="UNVERIFIED"
                )
                # Re-populate in-memory cache for next call
                self.hypotheses = unverified
            except Exception as e:
                logger.warning(
                    "Could not recover hypotheses from Postgres — "
                    "agent runs without them",
                    extra={
                        "engagement_id": self.engagement_id,
                        "error": str(e),
                    },
                    exc_info=True,
                )
                return []
        unverified.sort(key=lambda h: h.get("confidence", 0), reverse=True)
        return unverified[:max_count]

    # ── Serialization ──

    def to_dict(self) -> dict:
        return {
            "engagement_id": self.engagement_id,
            "current_phase": self.current_phase,
            "current_state": self.current_state,
            "execution_iteration": self.execution_iteration,
            "state_version": self.state_version,
            "obstacles_count": len(
                self.obstacles
            ),  # count only; full list is in-memory
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
            "tool_history": [
                t.to_dict() for t in self.tool_history[-20:]
            ],  # last 20 tools
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
        if data.get("budget") is not None:
            state.budget_manager.load_from_db(data["budget"])
        return state

    # ── Redis cache convenience ──

    def save_to_cache(self) -> bool:
        """Persist current state to Redis cache (if attached).

        Returns:
            True if saved, False if no cache attached or Redis unavailable.
        """
        if self._state_cache is None:
            return False
        return self._state_cache.save(self.engagement_id, self.to_dict())

    @classmethod
    def load_from_cache(
        cls,
        engagement_id: str,
        state_cache: Any,
        state_machine: EngagementStateMachine | None = None,
    ) -> "EngagementState | None":
        """Load engagement state from Redis cache (fast path).

        Falls back gracefully by returning None if not cached, allowing
        callers to reconstruct from Postgres instead.

        Args:
            engagement_id: Engagement UUID.
            state_cache: RedisStateCache instance.
            state_machine: Optional state machine to attach.

        Returns:
            EngagementState if found in cache, None otherwise.
        """
        data = state_cache.load(engagement_id)
        if data is None:
            return None
        state = cls.from_dict(data, state_machine=state_machine)
        state._state_cache = state_cache
        return state

    # ── Bug bounty mode ──

    @property
    def bug_bounty_mode(self) -> bool:
        return self._bug_bounty_mode

    @bug_bounty_mode.setter
    def bug_bounty_mode(self, value: bool):
        self._bug_bounty_mode = value
        self._bump_version()
