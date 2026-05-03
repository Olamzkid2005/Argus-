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
from llm_service import LLMService

from .agent_action import AgentAction
from .agent_prompts import (
    TOOL_SELECTION_SYSTEM_PROMPT,
    REPO_TOOL_SELECTION_SYSTEM_PROMPT,
    build_tool_selection_prompt,
    build_observation_summary,
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
    """

    _phase_tools_loaded = False

    @classmethod
    def _ensure_phase_tools(cls):
        """Lazy-load PHASE_TOOLS from tool_definitions SSOT."""
        if not cls._phase_tools_loaded:
            from tool_definitions import build_phase_tools_dict
            cls.PHASE_TOOLS = build_phase_tools_dict()
            cls._phase_tools_loaded = True

    PHASE_TOOLS = {}

    def __init__(
        self,
        registry: ToolRegistry,
        max_iterations: int = LLM_AGENT_MAX_ITERATIONS,
        llm_client: Any = None,
        decision_repo: Any = None,
        engagement_id: str = None,
        phase: str = "scan",
    ):
        self.registry = registry
        self.max_iterations = max_iterations
        self.llm_client = llm_client
        self.decision_repo = decision_repo
        self.engagement_id = engagement_id
        self.history: list[dict] = []
        self._phase = phase

    def add_to_history(self, role: str, content: str, data: dict = None):
        """Add an entry to the agent's history/context."""
        self.history.append(
            {
                "role": role,
                "content": content,
                "data": data or {},
                "timestamp": time.time(),
            }
        )

    def get_context(self, max_tokens: int = LLM_AGENT_CONTEXT_MAX_TOKENS) -> str:
        """
        Build observation history string from tool results.
        Trims to stay under token budget — keeps most recent entries.
        """
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

    def set_tool_runner(self, tool_runner):
        """
        Register all tools from a ToolRunner instance.

        FIX: reads real descriptions and parameter schemas from tool_definitions.py
        so the LLM receives meaningful tool information, not generic "Run <tool>" strings.
        """
        self._ensure_phase_tools()

        # Import SSOT so we can read real descriptions
        try:
            from tool_definitions import TOOLS as TOOL_DEFS
        except ImportError:
            TOOL_DEFS = {}

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
                tool_def = TOOL_DEFS.get(tool_name)
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
        Return the correct system prompt based on scan type.
        Repo scans get the SAST-focused prompt; web scans get the webapp prompt.
        """
        if recon_context and hasattr(recon_context, "scan_type"):
            if recon_context.scan_type == "repo":
                return REPO_TOOL_SELECTION_SYSTEM_PROMPT
        return TOOL_SELECTION_SYSTEM_PROMPT

    def _call_llm_for_action(
        self,
        task: str,
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

        recon_summary = (
            recon_context.to_llm_summary()
            if hasattr(recon_context, "to_llm_summary")
            else str(recon_context)
        )

        user_prompt = build_tool_selection_prompt(
            recon_summary,
            self.registry.list_tools(),
            tried_tools,
            context,  # observation history — now has real content
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
            if tool_name not in tried_tools:
                if self.registry.get_tool(tool_name) is not None:
                    return AgentAction(
                        tool_name, {"target": task}, f"Phase tool: {tool_name}"
                    )

        return None

    def _validate_arguments(self, action: AgentAction) -> bool:
        """Validate tool arguments against schema."""
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

    def run(
        self,
        task: str,
        initial_context: dict = None,
        recon_context: Any = None,
    ) -> list[AgentResult]:
        """
        Run the agent loop for a given task.

        Args:
            task: Task description (e.g., "scan: https://example.com")
            initial_context: Initial context data
            recon_context: ReconContext for LLM tool selection

        Returns:
            List of tool execution results
        """
        self.history = []
        results = []
        tried_tools = set()
        total_cost_usd = 0.0
        empty_output_consecutive = 0  # FIX: track empty output, not findings count

        self._ensure_phase_tools()
        self.add_to_history("system", f"Task: {task}")
        initial_target = task.split(":")[-1].strip() if ":" in task else task

        for iteration in range(self.max_iterations):
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

            tried_tools.add(action.tool)

            # Cost guard
            total_cost_usd += getattr(action, "cost_usd", 0.0)
            if total_cost_usd > LLM_AGENT_MAX_COST_USD:
                logger.warning(
                    f"Cost guard: ${total_cost_usd:.4f} exceeds ${LLM_AGENT_MAX_COST_USD:.4f}. "
                    f"Switching to deterministic for remaining tools."
                )
                for tool_name in self.PHASE_TOOLS.get(self._phase, []):
                    if tool_name not in tried_tools:
                        result = self.registry.call(tool_name, target=initial_target)
                        results.append(result)
                break

            logger.info(
                "Agent iteration %d: %s — %s (cost: $%.6f)",
                iteration,
                action.tool,
                action.reasoning[:80] if action.reasoning else "no reasoning",
                action.cost_usd,
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
            results.append(result)

            # FIX: use actual output length to detect empty results
            # AgentResult.findings is always [] because registry.call() never sets it.
            # Use output content length as the real signal.
            output_content = (result.output or "").strip()
            output_is_empty = not result.success or len(output_content) < 30

            if output_is_empty:
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

        return results
