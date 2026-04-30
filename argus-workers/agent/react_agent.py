"""
ReAct Agent - LLM-driven tool selection and execution loop.

1. LLM receives context + available tools
2. LLM decides which tool to call and why
3. Tool executes, result feeds back to context
4. LLM decides next action (another tool or stop)
"""
import json
import logging
import time
from typing import Dict, List, Optional, Any
from enum import Enum

from .agent_action import AgentAction
from .agent_result import AgentResult
from .tool_registry import ToolRegistry
from .agent_prompts import (
    TOOL_SELECTION_SYSTEM_PROMPT,
    build_tool_selection_prompt,
)
from config.constants import (
    LLM_AGENT_MAX_ITERATIONS,
    LLM_AGENT_TEMPERATURE,
    LLM_AGENT_CONTEXT_MAX_TOKENS,
    LLM_AGENT_MAX_COST_USD,
    LLM_AGENT_TIMEOUT_SECONDS,
    LLM_AGENT_ZERO_FINDING_STOP,
)

logger = logging.getLogger(__name__)

class _DoneSentinel:
    """Sentinel value returned when LLM signals __done__."""
    pass


_DONE = _DoneSentinel()


class ReActAgent:
    """
    ReAct (Reasoning + Acting) Agent Loop.

    The agent:
    1. Receives a task description and context
    2. Has access to tools via ToolRegistry
    3. In each iteration, decides: call a tool or finish (via LLM or fallback)
    4. Maintains an observation history for context
    """

    PHASE_TOOLS = {
        "recon": ["httpx", "katana", "gau", "waybackurls", "nmap", "naabu", "whatweb"],
        "scan": ["nuclei", "dalfox", "sqlmap", "testssl", "ffuf", "arjun", "jwt_tool", "commix"],
        "deep_scan": ["nuclei", "dalfox", "sqlmap", "nikto"],
        "repo_scan": ["semgrep", "bandit", "gitleaks", "npm-audit"],
        "analyze": ["intelligence-engine"],
        "report": ["report-generator"],
    }

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
        self.history: List[Dict] = []
        self._phase = phase

    def add_to_history(self, role: str, content: str, data: Dict = None):
        """Add an entry to the agent's history/context."""
        self.history.append({
            "role": role,
            "content": content,
            "data": data or {},
            "timestamp": time.time(),
        })

    def get_context(self, max_tokens: int = LLM_AGENT_CONTEXT_MAX_TOKENS) -> str:
        """Build context string from history. Trims to stay under token budget."""
        recent = self.history[-5:]
        parts = [f'[{e["role"]}]: {e["content"]}' for e in recent]
        context = "\n".join(parts)

        if len(context) / 4 > max_tokens:
            parts = [f'[{e["role"]}]: {e["content"]}' for e in self.history[-2:]]
            context = "\n".join(parts)

        return context

    def set_phase(self, phase: str):
        """Set the current phase to determine which tools to use."""
        self._phase = phase

    def set_tool_runner(self, tool_runner):
        """Register all tools from a ToolRunner instance."""
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
                self.registry.register(
                    tool_name,
                    make_runner(tool_name),
                    {"name": tool_name, "description": f"Run {tool_name}", "parameters": []}
                )

    def _call_llm_for_action(
        self,
        task: str,
        context: str,
        tried_tools: set,
        recon_context: Any,
        llm_client: Any = None,
    ) -> Optional[AgentAction]:
        """Call LLM to decide next tool. Returns None if __done__ or on failure."""
        client = llm_client or self.llm_client
        if not client:
            return None

        from llm_client import LLMResponse

        messages = [
            {"role": "system", "content": TOOL_SELECTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_tool_selection_prompt(
                    recon_context.to_llm_summary() if hasattr(recon_context, "to_llm_summary") else str(recon_context),
                    self.registry.list_tools(),
                    tried_tools,
                    context,
                ),
            },
        ]

        try:
            raw = client.chat_sync(
                messages,
                temperature=LLM_AGENT_TEMPERATURE,
                max_tokens=300,
                response_format={"type": "json_object"},
                timeout=LLM_AGENT_TIMEOUT_SECONDS,
            )

            if isinstance(raw, LLMResponse):
                response_text = raw.text
                input_tokens = raw.input_tokens
                output_tokens = raw.output_tokens
                cost_usd = raw.cost_usd
            else:
                response_text = raw
                input_tokens = 0
                output_tokens = 0
                cost_usd = 0.0

            decision = json.loads(response_text)
            tool_name = decision.get("tool")

            if tool_name == "__done__":
                return _DONE

            if not self.registry.get_tool(tool_name):
                logger.warning(f"LLM selected unknown tool {tool_name}, falling back")
                raise ValueError(f"Unknown tool: {tool_name}")

            return AgentAction(
                tool=tool_name,
                arguments=decision.get("arguments", {}),
                reasoning=decision.get("reasoning", ""),
                cost_usd=cost_usd,
            )

        except Exception as e:
            logger.warning(f"LLM tool selection failed: {e}. Using deterministic fallback.")
            return None

    def _deterministic_plan(self, task: str, tried_tools: set) -> Optional[AgentAction]:
        """Fallback: deterministic phase-based tool planning."""
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
                        tool_name,
                        {"target": task},
                        f"Phase tool: {tool_name}"
                    )

        return None

    def _validate_arguments(self, action: AgentAction) -> bool:
        """Validate tool arguments against schema (Risk 5: hallucination guard)."""
        tool_meta = None
        for t in self.registry.list_tools():
            if t.get("name") == action.tool:
                tool_meta = t
                break

        if not tool_meta:
            return True  # No schema to validate against

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
    ) -> Optional[AgentAction]:
        """
        Decide the next action.

        LLM branch: uses LLM to select tools dynamically.
        Fallback: deterministic phase-based iteration (zero regression).
        """
        tried_tools = tried_tools or set()
        llm_client = llm_client or self.llm_client

        if llm_client and hasattr(llm_client, "is_available") and llm_client.is_available() and recon_context:
            action = self._call_llm_for_action(task, context, tried_tools, recon_context, llm_client=llm_client)
            if action is _DONE:
                return None
            if action is not None:
                return action

        return self._deterministic_plan(task, tried_tools)

    def run(
        self,
        task: str,
        initial_context: Dict = None,
        recon_context: Any = None,
    ) -> List[AgentResult]:
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
        zero_finding_consecutive = 0

        self.add_to_history("system", f"Task: {task}")
        initial_target = task.split(":")[-1].strip() if ":" in task else task

        for iteration in range(self.max_iterations):
            plan_kwargs = dict(tried_tools=tried_tools)
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
                logger.info("Agent: no more actions for iteration %d", iteration)
                break

            tried_tools.add(action.tool)

            # Track cost (Risk 2 mitigation in Phase 4)
            total_cost_usd += getattr(action, "cost_usd", 0.0)
            if total_cost_usd > LLM_AGENT_MAX_COST_USD:
                logger.warning(
                    f"Cost guard: ${total_cost_usd:.4f} exceeds ${LLM_AGENT_MAX_COST_USD:.4f}. "
                    f"Switching to deterministic for remaining."
                )
                for tool_name in self.PHASE_TOOLS.get(self._phase, []):
                    if tool_name not in tried_tools:
                        result = self.registry.call(tool_name, target=initial_target)
                        results.append(result)
                break

            logger.info("Agent iteration %d: calling %s (cost: $%.6f)",
                        iteration, action.tool, action.cost_usd)

            # Step 23: Emit agent decision event for frontend reasoning feed
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
                pass

            # Execute tool (Risk 3: tool error handling — tool errors are captured as failed AgentResults)
            result = self.registry.call(action.tool, **action.arguments)
            results.append(result)

            # Risk 6: auto-stop on low finding yield
            new_findings_count = len(result.findings) if hasattr(result, "findings") else 0
            if new_findings_count == 0:
                zero_finding_consecutive += 1
            else:
                zero_finding_consecutive = 0

            if zero_finding_consecutive >= LLM_AGENT_ZERO_FINDING_STOP:
                logger.info("Two consecutive tools found nothing – stopping agent early")
                break

            self.add_to_history(
                "observation",
                f"Tool {action.tool} {'succeeded' if result.success else 'failed'}"
                + (f" — {result.error[:100]}" if not result.success else "")
            )

            # Log decision to repository if available
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
