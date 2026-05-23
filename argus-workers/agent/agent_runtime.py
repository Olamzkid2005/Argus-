"""
AgentRuntime — Clean facade over ReActAgent + runtime modules.

Wires together:
- ReActAgent (LLM-driven tool selection loop)
- EngagementState (canonical state tracking)
- ExecutionEngine (tool dispatch with middleware chain)
- Governance (safety controls)
- MemoryRetriever (3-tier context retrieval)

Usage:
    runtime = AgentRuntime(
        engagement_id="...",
        tool_runner=tool_runner,
        llm_client=llm_client,
    )
    results = runtime.run_phase("scan", target="https://example.com")
"""

import logging
from typing import Any

from feature_flags import is_enabled as _ff_enabled

logger = logging.getLogger(__name__)


class AgentRuntime:
    """
    Clean facade integrating ReActAgent with runtime modules.

    Single entry point for running an agent-driven engagement phase.
    Automatically wires EngagementState, ExecutionEngine, Governance,
    and MemoryRetriever when available.
    """

    def __init__(
        self,
        engagement_id: str,
        tool_runner: Any,
        llm_client: Any = None,
        phase: str = "scan",
        mode: str | None = None,
        authorized_scope: list[str] | None = None,
        decision_repo: Any = None,
        governance: Any | None = None,
        memory_retriever: Any | None = None,
        engagement_state: Any | None = None,
    ):
        self.engagement_id = engagement_id
        self.tool_runner = tool_runner
        self.llm_client = llm_client
        self.phase = phase
        self.mode = mode
        self.authorized_scope = authorized_scope
        self.decision_repo = decision_repo
        self.governance = governance
        self.memory_retriever = memory_retriever
        self.engagement_state = engagement_state

        # Lazy imports to avoid circular deps
        self._react_agent: Any | None = None
        self._execution_engine: Any | None = None

    def _ensure_agent(self) -> Any:
        """Create or return the ReActAgent instance with all wiring."""
        if self._react_agent is not None:
            return self._react_agent

        from .react_agent import ReActAgent
        from .tool_registry import ToolRegistry

        registry = ToolRegistry()

        agent = ReActAgent(
            registry=registry,
            llm_client=self.llm_client,
            decision_repo=self.decision_repo,
            engagement_id=self.engagement_id,
            phase=self.phase,
            mode=self.mode,
            governance=self.governance,
            memory_retriever=self.memory_retriever,
            engagement_state=self.engagement_state,
        )
        agent.set_tool_runner(self.tool_runner)

        # Wire ExecutionEngine for scope validation middleware
        if self.authorized_scope:
            from runtime import ExecutionEngine
            from tools.scope_validator import ScopeValidator

            self._execution_engine = ExecutionEngine(
                tool_runner=self.tool_runner,
                scope_validator=ScopeValidator(self.engagement_id, self.authorized_scope),
            )
            # Wrap agent registry.call with scope middleware
            _original_call = agent.registry.call
            _ee = self._execution_engine

            def _scoped_dispatch(name, _ee=_ee, _orig=_original_call, **kwargs):
                args = []
                for fn in _ee._middleware:
                    result = fn(name, args, kwargs)
                    if result is None:
                        from .agent_result import AgentResult
                        return AgentResult(tool=name, success=False, error="Blocked by scope validation")
                    if isinstance(result, tuple) and len(result) == 3:
                        name, args, kwargs = result
                return _orig(name, **kwargs)

            agent.registry.call = _scoped_dispatch

        self._react_agent = agent
        return agent

    def run_phase(
        self,
        phase: str,
        task: str,
        recon_context: Any = None,
    ) -> list[Any]:
        """
        Run a single phase of the engagement.

        Args:
            phase: Phase name ("scan", "recon", etc.)
            task: Task description (e.g., "scan: https://example.com")
            recon_context: ReconContext for LLM tool selection

        Returns:
            List of tool execution results (AgentResult objects)
        """
        agent = self._ensure_agent()
        agent.set_phase(phase)
        results = agent.run(
            task=task,
            recon_context=recon_context,
        )
        return results

    def set_candidate_list(self, candidate_list) -> None:
        """Pass a CandidateList from recon for agent reasoning."""
        agent = self._ensure_agent()
        agent.set_candidate_list(candidate_list)

    def cancel(self) -> None:
        """Signal the agent to stop."""
        if self._react_agent:
            self._react_agent.cancel()
