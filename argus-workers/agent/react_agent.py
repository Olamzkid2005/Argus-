"""
ReAct Agent - LLM-driven tool selection and execution loop.

Flow:
1. LLM receives full recon context + rich tool descriptions
2. LLM selects the best tool and explains its reasoning
3. Tool executes; meaningful output summary fed back to LLM
4. LLM decides next tool (or stops when coverage is complete)

Key design decisions:
- set_tool_runner() reads real descriptions from tool_definitions.py SSOT
- observation history records actual output content, not just "succeeded/failed"
- Zero-finding stop uses output length, not AgentResult.findings (which is always [])
- Repo scans use REPO_TOOL_SELECTION_SYSTEM_PROMPT automatically
"""

import logging
import time
from typing import Any

from config.constants import (
    LLM_AGENT_CONTEXT_MAX_TOKENS,
    LLM_AGENT_MAX_COST_USD,
    LLM_AGENT_MAX_ITERATIONS,
    LLM_AGENT_TEMPERATURE,
    LLM_AGENT_ZERO_FINDING_STOP,
)
from feature_flags import is_enabled as _ff_enabled
from llm_service import LLMService
from utils.logging_utils import ScanLogger

from .agent_action import AgentAction
from .agent_prompts import (
    BUGBOUNTY_TOOL_SELECTION_SYSTEM_PROMPT,
    REPO_TOOL_SELECTION_SYSTEM_PROMPT,
    _load_bugbounty_context,
    build_observation_summary,
    build_tech_aware_system_prompt,
    build_tool_selection_prompt,
)
from .agent_result import AgentResult
from .tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


class _DoneSentinel:
    """Sentinel value returned when LLM signals __done__."""
    pass


_DONE = _DoneSentinel()


class ReActAgent:
    """
    ReAct (Reasoning + Acting) Agent Loop.

    The agent:
    1. Receives a task description and the full recon context
    2. Has access to tools via ToolRegistry (with real descriptions from SSOT)
    3. In each iteration, calls the LLM to pick the next tool
    4. Feeds meaningful output summaries back so the LLM can reason about results
    5. Stops only when coverage rules are met — not on empty tool output

    Phase management (folded from CoordinatorAgent):
    - PHASE_AGENTS: maps phase names to descriptions and tool lists
    - VALID_TRANSITIONS: defines allowed phase transitions
    - create_for_phase(): creates a configured ReActAgent for a given phase
    """

    _phase_tools_loaded = False

    @classmethod
    def _ensure_phase_tools(cls):
        """Lazy-load PHASE_TOOLS and PHASE_AGENTS from tool_definitions SSOT."""
        if not cls._phase_tools_loaded:
            from tool_definitions import build_phase_tools_dict, get_tools_for_phase
            cls.PHASE_TOOLS = build_phase_tools_dict()
            cls.PHASE_AGENTS = {
                phase: {
                    "description": f"{phase.capitalize().replace('_', ' ')}",
                    "tools": [t.name for t in get_tools_for_phase(phase)],
                }
                for phase in ["recon", "scan", "deep_scan", "repo_scan", "analyze", "report"]
            }
            cls._phase_tools_loaded = True

    PHASE_TOOLS = {}
    PHASE_AGENTS = {}

    VALID_TRANSITIONS = {
        "recon": ["scan"],
        "scan": ["analyze", "deep_scan"],
        "deep_scan": ["analyze"],
        "repo_scan": ["scan"],
        "analyze": ["report", "recon"],
        "report": [],
    }

    @classmethod
    def create_for_phase(
        cls,
        phase: str,
        tool_runner=None,
        engagement_id: str = None,
        llm_client=None,
        decision_repo=None,
        mode: str | None = None,
        governance=None,
        memory_retriever=None,
        engagement_state=None,
    ) -> "ReActAgent":
        """
        Create a ReActAgent for a specific phase with tools pre-registered.

        Args:
            phase: Phase name (recon, scan, repo_scan, analyze, report)
            tool_runner: Optional ToolRunner instance to register real tools
            engagement_id: Optional engagement ID for context
            llm_client: Optional LLMClient for LLM-driven tool selection
            decision_repo: Optional AgentDecisionRepository for logging
            mode: Optional mode ('bugbounty' for Bug-Reaper methodology)
            governance: Optional Governance instance for safety controls
            memory_retriever: Optional MemoryRetriever for context retrieval
            engagement_state: Optional EngagementState for canonical state

        Returns:
            Configured ReActAgent
        """
        registry = ToolRegistry()
        cls._ensure_phase_tools()
        phase_tools = cls.PHASE_TOOLS.get(phase, [])

        if tool_runner:
            try:
                from tool_definitions import TOOLS
            except ImportError:
                TOOLS = {}

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

                tool_def = TOOLS.get(tool_name)
                if tool_def:
                    description = tool_def.description
                    try:
                        parameters = [
                            {
                                "name": p.name,
                                "description": p.description,
                                "required": p.required,
                            }
                            for p in tool_def.parameters
                        ]
                    except Exception:
                        parameters = []
                else:
                    description = f"Security tool: {tool_name}"
                    parameters = [{"name": "target", "description": "Target URL or path", "required": True}]

                registry.register(
                    tool_name,
                    make_runner(tool_name),
                    {"name": tool_name, "description": description, "parameters": parameters},
                )

        return cls(
            registry,
            llm_client=llm_client,
            decision_repo=decision_repo,
            engagement_id=engagement_id,
            phase=phase,
            mode=mode,
            governance=governance,
            memory_retriever=memory_retriever,
            engagement_state=engagement_state,
        )

    def __init__(
        self,
        registry: ToolRegistry,
        max_iterations: int = LLM_AGENT_MAX_ITERATIONS,
        llm_client: Any = None,
        decision_repo: Any = None,
        engagement_id: str = None,
        phase: str = "scan",
        mode: str | None = None,
        governance: Any = None,
        memory_retriever: Any = None,
        engagement_state: Any = None,
    ):
        self.registry = registry
        self.max_iterations = max_iterations
        self.llm_client = llm_client
        self.decision_repo = decision_repo
        self.engagement_id = engagement_id
        self.governance = governance
        self.memory_retriever = memory_retriever
        self.engagement_state = engagement_state
        # Fallback history list when EngagementState is not provided
        self.history: list[dict] = []
        self._phase = phase
        self._mode = mode
        self._candidate_list = None
        self._cancelled = False

    def set_candidate_list(self, candidate_list) -> None:
        """Accept a CandidateList from the scan phase for agent reasoning."""
        self._candidate_list = candidate_list

    def cancel(self) -> None:
        """Signal the agent to stop after the current iteration."""
        self._cancelled = True

    def add_to_history(self, role: str, content: str, data: dict = None):
        """Add an entry to the agent's history/context.

        When EngagementState is available, delegates to state.add_observation()
        for canonical state tracking. Otherwise falls back to self.history.

        Content is truncated to 2000 chars to prevent unbounded token growth
        from large tool outputs (nuclei can produce thousands of JSON lines).
        """
        from feature_flags import is_enabled as _ff_enabled
        max_history_entry = 2000
        if (
            _ff_enabled("ENGAGEMENT_STATE", default=False)
            and self.engagement_state is not None
            and hasattr(self.engagement_state, "add_observation")
        ):
            self.engagement_state.add_observation(role, content[:max_history_entry], data)
        else:
            self.history.append(
                {
                    "role": role,
                    "content": content[:max_history_entry],
                    "data": data or {},
                    "timestamp": time.time(),
                }
            )
            # Cap history to last 50 entries to prevent memory growth
            if len(self.history) > 50:
                self.history = self.history[-50:]

    def get_context(self, max_tokens: int = LLM_AGENT_CONTEXT_MAX_TOKENS) -> str:
        """
        Build observation history string from tool results.
        Trims to stay under token budget — keeps most recent entries.

        When EngagementState is available, reads from state.observations
        for canonical state tracking. Falls back to self.history.
        """
        from feature_flags import is_enabled as _ff_enabled
        if (
            _ff_enabled("ENGAGEMENT_STATE", default=False)
            and self.engagement_state is not None
            and hasattr(self.engagement_state, "get_context")
        ):
            return self.engagement_state.get_context(max_entries=6)

        recent = self.history[-6:]  # last 6 entries (up from 5)
        parts = [f"[{e['role']}]: {e['content']}" for e in recent]
        context = "\n".join(parts)

        if len(context) / 4 > max_tokens:
            parts = [f"[{e['role']}]: {e['content']}" for e in self.history[-3:]]
            context = "\n".join(parts)

        return context

    def set_phase(self, phase: str):
        """Set the current phase to determine which tools to use."""
        self._ensure_phase_tools()
        self._phase = phase

    def can_transition_to(self, next_phase: str) -> bool:
        """Check if transition to next phase is valid."""
        return next_phase in self.VALID_TRANSITIONS.get(self._phase, [])

    def transition_to(self, next_phase: str) -> bool:
        """Transition to next phase if valid."""
        if not self.can_transition_to(next_phase):
            logger.warning(
                "Invalid phase transition: %s -> %s",
                self._phase, next_phase,
            )
            return False
        self._phase = next_phase
        return True

    def set_tool_runner(self, tool_runner):
        """
        Register all tools from a ToolRunner instance.

        FIX: reads real descriptions and parameter schemas from tool_definitions.py
        so the LLM receives meaningful tool information, not generic "Run <tool>" strings.
        """
        self._ensure_phase_tools()

        # Import SSOT so we can read real descriptions
        try:
            from tool_definitions import TOOLS
        except ImportError:
            TOOLS = {}  # noqa: N806

        phase_tools = self.PHASE_TOOLS.get(self._phase, [])

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

            if self.registry.get_tool(tool_name) is None:
                # Pull real description and parameters from SSOT
                tool_def = TOOLS.get(tool_name)
                if tool_def:
                    description = tool_def.description
                    try:
                        parameters = [
                            {
                                "name": p.name,
                                "description": p.description,
                                "required": p.required,
                            }
                            for p in tool_def.parameters
                        ]
                    except Exception:
                        parameters = []
                else:
                    description = f"Security tool: {tool_name}"
                    parameters = [{"name": "target", "description": "Target URL or path", "required": True}]

                self.registry.register(
                    tool_name,
                    make_runner(tool_name),
                    {
                        "name": tool_name,
                        "description": description,
                        "parameters": parameters,
                    },
                )

    def _get_system_prompt(self, recon_context: Any = None) -> str:
        """
        Return the correct system prompt based on scan type and mode.
        - bugbounty mode → Bug-Reaper ROI-ordered methodology
        - repo scans → SAST-focused prompt
        - default → standard webapp scanning prompt with tech-stack highlights
        """
        # Bug-Reaper mode takes priority
        if self._mode == "bugbounty":
            return BUGBOUNTY_TOOL_SELECTION_SYSTEM_PROMPT

        if recon_context and hasattr(recon_context, "scan_type") and recon_context.scan_type == "repo":
            return REPO_TOOL_SELECTION_SYSTEM_PROMPT

        return build_tech_aware_system_prompt(recon_context)

    def _call_llm_for_action(
        self,
        _task: str,
        context: str,
        tried_tools: set,
        recon_context: Any,
        llm_service: LLMService | None = None,
    ) -> AgentAction | None:
        """
        Call LLM to decide next tool via LLMService.
        Returns _DONE, AgentAction, or None on failure.
        """
        if not llm_service or not llm_service.is_available():
            return None

        recon_structured = (
            recon_context.to_llm_structured()
            if hasattr(recon_context, "to_llm_structured")
            else "{}"
        )
        recon_summary = (
            recon_context.to_llm_summary()
            if hasattr(recon_context, "to_llm_summary")
            else str(recon_context)
        )

        # Sanitize recon context to prevent prompt injection from attacker-controlled data
        # (e.g., reflected XSS payloads, crawled endpoints with injected content).
        # Truncate to 5000 chars, strip control characters and backtick delimiters.
        import re as _re
        def _sanitize(text: str) -> str:
            cleaned = _re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text[:5000])
            # Remove backtick fences that could break prompt structure
            cleaned = cleaned.replace('```', '` ` `')
            return cleaned

        recon_section = f"""=== RECON FINDINGS (STRUCTURED) ===
{_sanitize(str(recon_structured))}

=== RECON SUMMARY (PROSE) ===
{_sanitize(str(recon_summary))}"""

        # Load Bug-Reaper methodology context in bug bounty mode
        bugbounty_context = ""
        if self._mode == "bugbounty":
            bugbounty_context = _load_bugbounty_context(recon_context, tried_tools)

        # Extract target_profile from recon_context if available
        _target_profile = (
            recon_context.target_profile
            if hasattr(recon_context, "target_profile")
            else None
        )

        # ── Memory context retrieval (Phase 5) ──
        _memory_context = ""
        if (
            _ff_enabled("MEMORY_RETRIEVAL", default=False)
            and self.memory_retriever is not None
        ):
            try:
                _memory_context = self.memory_retriever.get_observation_summary(
                    self, max_tokens=800,
                )
            except Exception as e:
                logger.debug("Memory retrieval failed: %s", e)

        user_prompt = build_tool_selection_prompt(
            recon_section,
            self.registry.list_tools(),
            tried_tools,
            context,  # observation history
            target_profile=_target_profile,
            bugbounty_context=bugbounty_context,
            candidate_list=self._candidate_list,
            memory_context=_memory_context,
        )

        system_prompt = self._get_system_prompt(recon_context)

        try:
            decision = llm_service.chat_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=400,  # slightly more room for reasoning
                temperature=LLM_AGENT_TEMPERATURE,
            )

            if decision.get("_fallback"):
                logger.warning(f"LLM fallback: {decision.get('_reason')}")
                return None

            tool_name = decision.get("tool")

            if tool_name == "__done__":
                return _DONE

            if not self.registry.get_tool(tool_name):
                logger.warning(f"LLM selected unknown tool '{tool_name}', falling back")
                raise ValueError(f"Unknown tool: {tool_name}")

            return AgentAction(
                tool=tool_name,
                arguments=decision.get("arguments", {}),
                reasoning=decision.get("reasoning", ""),
                cost_usd=decision.get("cost_usd", 0.0),
            )

        except Exception as e:
            logger.warning(f"LLM tool selection failed: {e}. Using deterministic fallback.")
            return None

    def _deterministic_plan(self, task: str, tried_tools: set) -> AgentAction | None:
        """Fallback: deterministic phase-based tool planning when LLM is unavailable."""
        self._ensure_phase_tools()
        phase_tools = None

        for phase_name, tools in self.PHASE_TOOLS.items():
            if phase_name in task.lower() or task.lower() in phase_name:
                phase_tools = tools
                break

        if not phase_tools:
            available = [t["name"] for t in self.registry.list_tools()]
            for tool in available:
                if tool not in tried_tools:
                    return AgentAction(tool, {}, f"Trying {tool}")
            return None

        for tool_name in phase_tools:
            if tool_name not in tried_tools and self.registry.get_tool(tool_name) is not None:
                    return AgentAction(
                        tool_name, {"target": task}, f"Phase tool: {tool_name}"
                    )

        return None

    def _validate_arguments(self, action: AgentAction) -> bool:
        """Validate tool arguments against schema, including target scope."""
        tool_meta = None
        for t in self.registry.list_tools():
            if t.get("name") == action.tool:
                tool_meta = t
                break

        if not tool_meta:
            return True

        params = tool_meta.get("parameters", [])
        for param in params:
            if param.get("required", False):
                param_name = param.get("name", "")
                if param_name not in action.arguments:
                    logger.warning(f"Missing required param '{param_name}' for {action.tool}")
                    return False

        # Validate target is not internal/private if present.
        # Check all common target parameter names, not just "target".
        _target_params = ["target", "url", "host", "hostname", "domain", "endpoint"]
        for param_name in _target_params:
            target = action.arguments.get(param_name, "")
            if target:
                try:
                    import ipaddress
                    from urllib.parse import urlparse
                    hostname = urlparse(target).hostname
                    if hostname:
                        try:
                            ip = ipaddress.ip_address(hostname)
                            if ip.is_private or ip.is_loopback or ip.is_link_local:
                                logger.warning(
                                    "Blocked internal target '%s' (param=%s) for tool '%s'",
                                    target, param_name, action.tool,
                                )
                                return False
                        except ValueError:
                            if hostname.lower() in {"localhost", "169.254.169.254"}:
                                logger.warning(
                                    "Blocked internal hostname '%s' (param=%s) for tool '%s'",
                                    hostname, param_name, action.tool,
                                )
                                return False
                except Exception as e:
                    logger.debug("Target validation failed for '%s' (param=%s): %s", target, param_name, e)

        return True

    def plan_next_action(
        self,
        task: str,
        context: str,
        tried_tools: set = None,
        recon_context: Any = None,
        llm_client: Any = None,
    ) -> AgentAction | None:
        """
        Decide the next action.
        LLM branch: uses rich tool descriptions + recon context to select intelligently.
        Fallback: deterministic phase-based iteration (zero regression).
        """
        tried_tools = tried_tools or set()
        llm_client = llm_client or self.llm_client

        if (
            llm_client
            and hasattr(llm_client, "is_available")
            and llm_client.is_available()
            and recon_context
        ):
            llm_service = LLMService(llm_client=llm_client)
            action = self._call_llm_for_action(
                task, context, tried_tools, recon_context, llm_service=llm_service
            )
            if action is _DONE:
                return None
            if action is not None:
                return action

        return self._deterministic_plan(task, tried_tools)

    def _persist_decision_checkpoint(self, action: AgentAction, observation_context: str, reasoning: str) -> str | None:
        """Persist a DecisionCheckpoint for replay safety.

        This ensures that on Celery retry, the original LLM decision is
        replayed rather than making a new LLM call.

        Returns:
            checkpoint_id if persisted, None otherwise
        """
        from runtime import DecisionCheckpoint

        try:
            checkpoint = DecisionCheckpoint.from_action(
                action=action,
                observation_context=observation_context,
                reasoning=reasoning or action.reasoning,
                state_version=0,
                engagement_id=self.engagement_id or "",
            )
            from runtime.decision_checkpoint import DecisionCheckpointRepository
            repo = DecisionCheckpointRepository()
            repo.save(checkpoint)
            return checkpoint.checkpoint_id
        except Exception as e:
            logger.debug("Failed to persist DecisionCheckpoint: %s", e)
            return None

    def run(
        self,
        task: str,
        initial_context: dict = None,
        recon_context: Any = None,
        _reset_history: bool = True,
    ) -> list[AgentResult]:
        """
        Run the agent loop for a given task.

        Args:
            task: Task description (e.g., "scan: https://example.com")
            initial_context: Initial context data
            recon_context: ReconContext for LLM tool selection
            _reset_history: Reset history before starting (default True).
                            Set False when running within run_lifecycle() to
                            preserve context across phases.

        Returns:
            List of tool execution results
        """
        slog = ScanLogger("agent", engagement_id=self.engagement_id)
        slog.phase_header(f"AGENT RUN: {task[:80]}")
        if _reset_history:
            self.history = []
        # Incorporate initial context into history if provided
        if initial_context:
            self.add_to_history("system", f"Initial context: {initial_context}")
        results = []
        tried_tools = set()
        total_cost_usd = 0.0
        empty_output_consecutive = 0  # FIX: track empty output, not findings count

        self._ensure_phase_tools()
        self.add_to_history("system", f"Task: {task}")
        initial_target = task.split(":", 1)[-1].strip() if ":" in task else task

        for iteration in range(self.max_iterations):
            if self._cancelled:
                logger.info("Agent: cancelled at iteration %d", iteration)
                break

            # Check if engagement state signals completion
            from feature_flags import is_enabled as _ff_enabled
            if (
                _ff_enabled("ENGAGEMENT_STATE", default=False)
                and self.engagement_state is not None
                and hasattr(self.engagement_state, "is_complete")
                and self.engagement_state.is_complete()
            ):
                logger.info(
                    "Agent: engagement %s is in terminal state — stopping",
                    self.engagement_id,
                )
                break
            plan_kwargs = {"tried_tools": tried_tools}
            if recon_context is not None:
                plan_kwargs["recon_context"] = recon_context
            if self.llm_client is not None:
                plan_kwargs["llm_client"] = self.llm_client

            action = self.plan_next_action(
                task,
                self.get_context(),
                **plan_kwargs,
            )

            if action is None:
                logger.info("Agent: no more actions at iteration %d", iteration)
                break

            # ── Governance check (Phase 6) ──
            # When GOVERNANCE_V2 flag is enabled and a Governance instance
            # is provided, use unified safety controls instead of ad-hoc cost guard.
            if _ff_enabled("GOVERNANCE_V2", default=False) and self.governance is not None:
                can_proceed, reason = self.governance.check(action)
                if not can_proceed:
                    logger.warning(
                        "Governance: %s — engagement %s, switching to deterministic for remaining tools",
                        reason, self.engagement_id,
                    )
                    # Run remaining phase tools deterministically before shutdown
                    for tool_name in self.PHASE_TOOLS.get(self._phase, []):
                        if tool_name not in tried_tools and self.registry.get_tool(tool_name) is not None:
                            result = self.registry.call(tool_name, target=initial_target)
                            results.append(result)
                    break
            else:
                # Legacy cost guard (backward compatible when governance is absent)
                total_cost_usd += getattr(action, "cost_usd", 0.0)
                if total_cost_usd > LLM_AGENT_MAX_COST_USD:
                    logger.warning(
                        f"Cost guard: ${total_cost_usd:.4f} exceeds ${LLM_AGENT_MAX_COST_USD:.4f}. "
                        f"Switching to deterministic for remaining tools."
                    )
                    for tool_name in self.PHASE_TOOLS.get(self._phase, []):
                        if tool_name not in tried_tools and self.registry.get_tool(tool_name) is not None:
                            result = self.registry.call(tool_name, target=initial_target)
                            results.append(result)
                    break

            slog.agent_iteration(iteration, action.tool, action.reasoning[:80] if action.reasoning else "", cost=action.cost_usd)
            logger.info(
                "Agent iteration %d: %s — %s (cost: $%.6f)",
                iteration,
                action.tool,
                action.reasoning[:80] if action.reasoning else "no reasoning",
                action.cost_usd,
            )

            # ── Persist DecisionCheckpoint for replay safety (Phase 2) ──
            observation_context = self.get_context()
            checkpoint_id = self._persist_decision_checkpoint(
                action, observation_context, action.reasoning,
            )

            # Emit agent decision event for frontend reasoning feed
            try:
                from streaming import emit_agent_decision
                if self.engagement_id:
                    emit_agent_decision(
                        engagement_id=self.engagement_id,
                        iteration=iteration,
                        tool=action.tool,
                        reasoning=action.reasoning,
                        was_fallback=not (self.llm_client and self.llm_client.is_available()),
                    )
            except Exception:
                logger.warning("Agent: failed to emit decision event (non-fatal)", exc_info=True)

            # Execute tool
            result = self.registry.call(action.tool, **action.arguments)
            tried_tools.add(action.tool)
            results.append(result)

            # ── Record tool execution in EngagementState ──
            if (
                _ff_enabled("ENGAGEMENT_STATE", default=False)
                and self.engagement_state is not None
                and hasattr(self.engagement_state, "record_tool_execution")
            ):
                from runtime import ToolExecutionRecord
                try:
                    record = ToolExecutionRecord(
                        tool=action.tool,
                        args=action.arguments,
                        timestamp=time.time(),
                        result_summary=str(result.output)[:500] if hasattr(result, "output") and result.output else "",
                        execution_cost=getattr(action, "cost_usd", 0.0),
                        success=getattr(result, "success", False),
                        failure_state=getattr(result, "stderr", "")[:200] if not getattr(result, "success", True) else "",
                    )
                    self.engagement_state.record_tool_execution(record)
                except Exception as e:
                    logger.debug("Failed to record tool execution in state: %s", e)

            # Mark checkpoint execution result
            if checkpoint_id:
                try:
                    from runtime.decision_checkpoint import DecisionCheckpointRepository
                    repo = DecisionCheckpointRepository()
                    repo.mark_execution_result(
                        checkpoint_id,
                        success=result.success,
                        error=result.stderr if hasattr(result, "stderr") and not result.success else "",
                    )
                except Exception as e:
                    logger.debug("Failed to mark checkpoint result: %s", e)

            # ── Record result with governance (Phase 6) ──
            if _ff_enabled("GOVERNANCE_V2", default=False) and self.governance is not None:
                self.governance.record_result(result, action)
                # Check low-signal threshold
                is_low_signal, signal_reason = self.governance.check_low_signal()
                if is_low_signal:
                    logger.warning(
                        "Governance: %s — stopping agent for engagement %s",
                        signal_reason, self.engagement_id,
                    )
                    break

            # Legacy empty-output detection (only when governance is not active)
            if not (_ff_enabled("GOVERNANCE_V2", default=False) and self.governance is not None):
                if not result.success:
                    pass
                else:
                    output_content = (result.output or "").strip()
                    if len(output_content) < 30:
                        if output_content.startswith(('{', '[')):
                            try:
                                import json as _json
                                _json.loads(output_content)
                                empty_output_consecutive = 0
                            except (ValueError, _json.JSONDecodeError):
                                empty_output_consecutive += 1
                        else:
                            empty_output_consecutive += 1
                        logger.info(
                            "Agent: %s produced little/no output (%d consecutive)",
                            action.tool,
                            empty_output_consecutive,
                        )
                    else:
                        empty_output_consecutive = 0

                # Only stop on empty output if we've already run at least 4 tools
                # This prevents stopping before critical tools (nuclei, web_scanner) run
                if empty_output_consecutive >= LLM_AGENT_ZERO_FINDING_STOP and len(tried_tools) >= 4:
                    logger.info(
                        "Agent: %d consecutive empty tools after %d runs — stopping",
                        empty_output_consecutive,
                        len(tried_tools),
                    )
                    break

            # FIX: build meaningful observation from actual output content
            observation = build_observation_summary(action.tool, result)
            self.add_to_history("observation", observation)

            # Track execution iteration in EngagementState
            if (
                _ff_enabled("ENGAGEMENT_STATE", default=False)
                and self.engagement_state is not None
            ):
                try:
                    self.engagement_state.execution_iteration = iteration + 1
                except Exception as e:
                    logger.debug("Failed to track execution iteration: %s", e)

            # Log decision to repository
            if self.decision_repo:
                try:
                    self.decision_repo.log_decision(
                        engagement_id=self.engagement_id,
                        phase=self._phase,
                        iteration=iteration,
                        tool_selected=action.tool,
                        arguments=action.arguments,
                        reasoning=action.reasoning,
                        was_fallback=not (self.llm_client and self.llm_client.is_available()),
                        input_tokens=None,
                        output_tokens=None,
                    )
                except Exception as e:
                    logger.warning(f"Failed to log decision: {e}")

        slog.agent_complete(tools_ran=len(results), total_cost=total_cost_usd)
        return results

    def run_lifecycle(
        self,
        target: str,
        phases: list[str] | None = None,
        recon_context: Any = None,
        tool_runner=None,
    ) -> dict[str, list[AgentResult]]:
        """
        Run the full engagement lifecycle across multiple phases.

        A single agent instance transitions through each phase, preserving
        context across phases via EngagementState (when enabled) or history.
        Tools are reloaded per phase from the phase-specific tool set.

        This is the Phase 2 "True ReAct Loop" — the agent manages the full
        recon -> scan -> analyze -> report lifecycle rather than handling
        only scan-phase tool selection.

        Args:
            target: Target URL or identifier
            phases: List of phases to run (default: all standard phases)
            recon_context: ReconContext for LLM tool selection
            tool_runner: ToolRunner for registering phase-specific tools

        Returns:
            Dict mapping phase names to lists of AgentResults
        """
        if phases is None:
            phases = ["recon", "scan", "analyze", "report"]

        self._ensure_phase_tools()
        lifecycle_results: dict[str, list[AgentResult]] = {}

        for phase in phases:
            if self._cancelled:
                logger.info("Agent lifecycle: cancelled at phase %s", phase)
                break

            # Load phase-specific tools
            self.set_phase(phase)
            if tool_runner is not None:
                self.set_tool_runner(tool_runner)

            task_desc = self.PHASE_AGENTS.get(phase, {}).get(
                "description", phase
            )
            logger.info(
                "Agent lifecycle: running phase '%s' — %s",
                phase, task_desc,
            )

            # Run the phase with history preserved across phases
            # (EngagementState provides the canonical cross-phase context;
            #  self.history carries the fallback context when state is absent.)
            phase_results = self.run(
                task=f"{phase}: {target}",
                recon_context=recon_context,
                _reset_history=False,
            )
            lifecycle_results[phase] = phase_results

            # Check if EngagementState signals terminal state
            from feature_flags import is_enabled as _ff_enabled
            if (
                _ff_enabled("ENGAGEMENT_STATE", default=False)
                and self.engagement_state is not None
                and hasattr(self.engagement_state, "is_complete")
                and self.engagement_state.is_complete()
            ):
                logger.info(
                    "Agent lifecycle: engagement %s is terminal — "
                    "stopping after phase %s",
                    self.engagement_id, phase,
                )
                break

            # Log phase transition
            if phase != phases[-1]:
                try:
                    from streaming import emit_thinking
                    if self.engagement_id:
                        emit_thinking(
                            self.engagement_id,
                            f"Phase {phase} complete — transitioning to "
                            f"{phases[phases.index(phase) + 1]}...",
                        )
                except Exception as e:
                    logger.debug("Failed to emit phase transition thinking: %s", e)

        logger.info(
            "Agent lifecycle complete for %s — ran %d phases",
            self.engagement_id, len(lifecycle_results),
        )
        return lifecycle_results
