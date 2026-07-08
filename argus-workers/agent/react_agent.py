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

from agent.auth_context import AuthContext
from config.constants import (
    LLM_AGENT_CONTEXT_MAX_TOKENS,
    LLM_AGENT_MAX_COST_USD,
    LLM_AGENT_MAX_ITERATIONS,
    LLM_AGENT_TEMPERATURE,
    LLM_AGENT_ZERO_FINDING_STOP,
)
from feature_flags import is_enabled as _ff_enabled
from llm_service import LLMService
from runtime.engagement_state import OBSERVATION_TRUNCATION_LIMIT
from streaming import emit_error_hint
from utils.error_hints import ErrorHint
from utils.logging_utils import ScanLogger

from .agent_action import AgentAction
from .agent_prompts import (
    BUGBOUNTY_TOOL_SELECTION_SYSTEM_PROMPT,
    REPO_TOOL_SELECTION_SYSTEM_PROMPT,
    _load_bugbounty_context,
    _sanitize_for_llm,
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
                for phase in [
                    "recon",
                    "scan",
                    "deep_scan",
                    "repo_scan",
                    "analyze",
                    "report",
                ]
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
                # register and login are agent-internal tools, not external binaries.
                # They are registered in set_tool_runner() which has access to self.
                if tool_name in ("register", "login"):
                    continue

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
                    parameters = [
                        {
                            "name": "target",
                            "description": "Target URL or path",
                            "required": True,
                        }
                    ]

                registry.register(
                    tool_name,
                    make_runner(tool_name),
                    {
                        "name": tool_name,
                        "description": description,
                        "parameters": parameters,
                    },
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
        self._auth_context: AuthContext | None = None
        # Tracks consecutive LLM tool selection failures for alerting
        self._llm_failure_count = 0

    def set_candidate_list(self, candidate_list) -> None:
        """Accept a CandidateList from the scan phase for agent reasoning."""
        self._candidate_list = candidate_list

    def set_auth_context(self, ctx: AuthContext) -> None:
        """Store an authenticated AuthContext for all subsequent tool calls.

        Once set, the tool wrappers automatically inject cookies/headers
        into CLI arguments for tools like sqlmap, nuclei, dalfox, etc.
        """
        self._auth_context = ctx

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
        max_history_entry = 2000
        if (
            _ff_enabled("ENGAGEMENT_STATE", default=False)
            and self.engagement_state is not None
            and hasattr(self.engagement_state, "add_observation")
        ):
            self.engagement_state.add_observation(
                role, content[:max_history_entry], data
            )
        else:
            self.history.append(
                {
                    "role": role,
                    "content": content[:max_history_entry],
                    "data": data or {},
                    "timestamp": time.time(),
                }
            )
            # Cap history to OBSERVATION_TRUNCATION_LIMIT entries to prevent
            # memory growth. When EngagementState is active, observations are
            # delegated to it and this branch is NOT reached — see the `if`
            # check above. The limit is imported from engagement_state.py so
            # both layers are always coordinated (blocker 49).
            if len(self.history) > OBSERVATION_TRUNCATION_LIMIT:
                dropped = len(self.history) - OBSERVATION_TRUNCATION_LIMIT
                logger.warning(
                    "Agent history truncated: %d entries dropped from engagement %s — "
                    "LLM may lose context of earlier tool results.",
                    dropped,
                    self.engagement_id,
                )
                self.history = self.history[-OBSERVATION_TRUNCATION_LIMIT:]

    def get_context(self, max_tokens: int = LLM_AGENT_CONTEXT_MAX_TOKENS) -> str:
        """
        Build observation history string from tool results.
        Trims to stay under token budget — keeps most recent entries.

        When EngagementState is available, reads from state.observations
        for canonical state tracking. Falls back to self.history.
        """
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
                self._phase,
                next_phase,
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
                    # Inject auth context for tools that support it
                    if self._auth_context:
                        from agent.auth_injectors import inject_auth

                        args = inject_auth(tn, args, self._auth_context)
                    return tool_runner.run(tn, args, timeout=timeout)

                run_tool.__name__ = tn
                return run_tool

            def make_auth_tool(tn):
                """Factory for register/login tools that wire AuthContext."""

                def run_auth_tool(target: str = "", **kwargs):
                    import requests

                    http_session = requests.Session()
                    if tn == "register":
                        from agent.tools.register_tool import run_register

                        result, ctx = run_register(
                            target=target,
                            http_session=http_session,
                            auth_context=self._auth_context,
                        )
                    else:
                        from agent.tools.login_tool import run_login

                        email = kwargs.pop("email", None)
                        password = kwargs.pop("password", None)
                        result, ctx = run_login(
                            target=target,
                            http_session=http_session,
                            auth_context=self._auth_context,
                            email=email,
                            password=password,
                        )
                    if ctx and ctx.is_authenticated():
                        self.set_auth_context(ctx)
                        # Persist for Celery retry resilience
                        if self.engagement_id:
                            from agent.auth_checkpoint import save_auth_checkpoint

                            save_auth_checkpoint(self.engagement_id, ctx)
                    return result

                run_auth_tool.__name__ = tn
                return run_auth_tool

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
                    parameters = [
                        {
                            "name": "target",
                            "description": "Target URL or path",
                            "required": True,
                        }
                    ]

                # register and login are agent-internal tools — use make_auth_tool
                if tool_name in ("register", "login"):
                    tool_fn = make_auth_tool(tool_name)
                else:
                    tool_fn = make_runner(tool_name)

                self.registry.register(
                    tool_name,
                    tool_fn,
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

        if (
            recon_context
            and hasattr(recon_context, "scan_type")
            and recon_context.scan_type == "repo"
        ):
            return REPO_TOOL_SELECTION_SYSTEM_PROMPT

        return build_tech_aware_system_prompt(recon_context)

    def _call_llm_for_action(
        self,
        _task: str,
        context: str,
        tried_tools: set,
        recon_context: Any,
        llm_service: LLMService | None = None,
        hypotheses: list[dict] | None = None,
    ) -> AgentAction | None:
        """
        Call LLM to decide next tool via LLMService.
        Returns _DONE, AgentAction, or None on failure.

        When LLMService is used, this method also tracks actual token
        counts from the LLM response so they can be passed to Governance
        (blocker 48). The counts are stored on the action if governance
        is active.

        Args:
            hypotheses: Optional list of active hypotheses to guide tool selection
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
        # Uses the comprehensive _sanitize_for_llm() from agent_prompts which handles
        # backtick fences, prompt override patterns, and command injection patterns (H-v4-07).
        recon_section = f"""=== RECON FINDINGS (STRUCTURED) ===
{_sanitize_for_llm(str(recon_structured))}

=== RECON SUMMARY (PROSE) ===
{_sanitize_for_llm(str(recon_summary))}"""

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
                    self,
                    max_tokens=800,
                )
            except Exception as e:
                logger.debug("Memory retrieval failed: %s", e)

        # ── Load active hypotheses from EngagementState ──
        _hypotheses = hypotheses
        if (
            _hypotheses is None
            and _ff_enabled("ENGAGEMENT_STATE", default=False)
            and self.engagement_state is not None
            and hasattr(self.engagement_state, "get_active_hypotheses")
        ):
                try:
                    _hypotheses = self.engagement_state.get_active_hypotheses(
                        max_count=10
                    )
                except Exception as e:
                    logger.debug("Failed to load hypotheses from state: %s", e)

        user_prompt = build_tool_selection_prompt(
            recon_section,
            self.registry.list_tools(),
            tried_tools,
            context,  # observation history
            target_profile=_target_profile,
            bugbounty_context=bugbounty_context,
            candidate_list=self._candidate_list,
            memory_context=_memory_context,
            hypotheses=_hypotheses,
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
                logger.warning("LLM fallback: %s", decision.get("_reason"))
                return None

            tool_name = decision.get("tool")

            if tool_name == "__done__":
                return _DONE

            if not self.registry.get_tool(tool_name):
                logger.warning(
                    "LLM selected unknown tool '%s', falling back", tool_name
                )
                raise ValueError(f"Unknown tool: {tool_name}")

            return AgentAction(
                tool=tool_name,
                arguments=decision.get("arguments", {}),
                reasoning=decision.get("reasoning", ""),
                cost_usd=decision.get("cost_usd", 0.0),
            )

        except Exception as e:
            logger.warning(
                "LLM tool selection failed: %s. Using deterministic fallback.",
                e,
            )
            return None

    def _deterministic_plan(self, task: str, tried_tools: set) -> AgentAction | None:
        """Fallback: deterministic phase-based tool planning when LLM is unavailable."""
        self._ensure_phase_tools()
        phase_tools = None

        for phase_name, tools in self.PHASE_TOOLS.items():
            if task.lower().startswith(phase_name + ":") or task.lower() == phase_name:
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
                return AgentAction(
                    tool_name, {"target": task}, f"Phase tool: {tool_name}"
                )

        for tool_meta in self.registry.list_tools():
            tool_name = tool_meta.get("name", "")
            if tool_name not in tried_tools and tool_name not in phase_tools:
                return AgentAction(
                    tool_name, {"target": task}, f"Registered tool: {tool_name}"
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
                    logger.warning(
                        "Missing required param '%s' for %s", param_name, action.tool
                    )
                    return False

        # Validate target is not internal/SSRF target (SSOT: ScopeValidator).
        # Consolidated from the inline IP/hostname check that was duplicated
        # from tools/scope_validator.py into this method.
        from urllib.parse import urlparse

        _target_params = ["target", "url", "host", "hostname", "domain", "endpoint"]
        for param_name in _target_params:
            target = action.arguments.get(param_name, "")
            if target:
                try:
                    # Extract hostname the same way ScopeValidator._extract_hostname does
                    from tools.scope_validator import ScopeValidator

                    hostname = urlparse(target).hostname
                    if not hostname:
                        # urlparse treats scheme-less targets (e.g. "169.254.169.254")
                        # as paths — .hostname is None. Use raw split instead.
                        hostname = target.split("/")[0].split(":")[0]

                    if ScopeValidator.is_internal_address(hostname):
                        logger.warning(
                            "Blocked internal target '%s' (param=%s) for tool '%s'",
                            target,
                            param_name,
                            action.tool,
                        )
                        return False
                except Exception as e:
                    logger.debug(
                        "Target validation failed for '%s' (param=%s): %s",
                        target,
                        param_name,
                        e,
                    )

        return True

    def plan_next_phase(
        self,
        findings: list[dict],
        phase: str = "",
        target: str = "",
        llm_client: Any = None,
    ) -> dict:
        """
        Given all findings from completed phases, determine the next capabilities
        that should be applied. This is the Phase 1.2 LLM-driven replanning hook
        that closes the feedback loop from findings to tool selection.

        Uses the LLM to analyze accumulated findings and suggest a ranked list of
        capabilities for the next phase. Falls back to deterministic phase ordering
        when no LLM is available.

        Args:
            findings: All findings accumulated so far (list of finding dicts)
            phase: The phase that just completed (e.g. "recon", "scan")
            target: The target URL or hostname
            llm_client: Optional LLM client override

        Returns:
            dict with:
                - next_capabilities: list[str] — suggested capabilities for next phase
                - reasoning: str — LLM reasoning or fallback explanation
                - stop: bool — whether the LLM suggests stopping assessment
        """
        llm_client = llm_client or self.llm_client

        # If no LLM, use deterministic phase progression
        if (
            not llm_client
            or not hasattr(llm_client, "is_available")
            or not llm_client.is_available()
        ):
            return self._deterministic_next_phase(findings, phase)

        try:
            from llm_service import LLMService

            llm_service = LLMService(llm_client=llm_client)

            # Build a concise summary of findings for the LLM
            finding_summaries = []
            severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}
            finding_types = set()

            for f in findings:
                f_type = f.get("type", f.get("subtype", "UNKNOWN"))
                f_sev = str(f.get("severity", "INFO")).upper()
                f_endpoint = f.get("endpoint", f.get("url", ""))

                finding_types.add(f_type)
                if f_sev in severity_counts:
                    severity_counts[f_sev] += 1

                if f_sev in ("CRITICAL", "HIGH"):
                    finding_summaries.append(
                        f"- [{f_sev}] {f_type} at {f_endpoint}"
                    )

            # Cap finding summaries to prevent token overflow
            if len(finding_summaries) > 20:
                finding_summaries = finding_summaries[:20]
                finding_summaries.append(f"- ... and {len(findings) - 20} more")

            severities = ", ".join(f"{k}={v}" for k, v in severity_counts.items() if v > 0)
            unique_types = ", ".join(sorted(finding_types)[:15])

            system_prompt = """You are an autonomous red-team assessment planner. Your job is to analyze
accumulated findings and decide what capabilities the next phase of the assessment
should use. Available capability categories include:

- WEB_RECON: Subdomain discovery, endpoint enumeration, tech fingerprinting
- VULN_SCAN: General vulnerability scanning (nuclei, nikto)
- DEEP_SCAN: Deep/aggressive scanning (sqlmap, testssl, commix)
- AUTH_TEST: Authentication/authorization testing
- XSS_DETECTION: Cross-site scripting detection
- SQLI_DETECTION: SQL injection detection
- SSRF_DETECTION: Server-side request forgery detection
- LFI_DETECTION: Local file inclusion detection
- PRIVESC_DETECTION: Privilege escalation detection
- POST_EXPLOIT: Post-exploitation (credential replay, lateral movement)
- EXPLOIT_CHAIN: Attack chain exploitation
- REPORT: Report generation
- SCAN_DIFF: Differential scan analysis

Respond with JSON: {"next_capabilities": ["CAPABILITY_1", ...], "reasoning": "...", "stop": false}
Set stop=true only if the assessment is complete (all findings gathered, no further probing needed).
"""

            user_prompt = f"""=== COMPLETED PHASE ===
{phase or 'unknown'}

=== TARGET ===
{target or 'unknown'}

=== FINDING SUMMARY ===
{_sanitize_for_llm(str(severities))}
Unique finding types: {_sanitize_for_llm(unique_types)}
Total findings: {len(findings)}

Top findings:
{_sanitize_for_llm(chr(10).join(finding_summaries) if finding_summaries else 'No HIGH/CRITICAL findings')}

Based on these findings, what capabilities should the next phase use?
"""

            result = llm_service.chat_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=400,
                temperature=0.3,
            )

            if result.get("_fallback"):
                logger.warning(
                    "LLM phase planning fallback: %s", result.get("_reason")
                )
                return self._deterministic_next_phase(findings, phase)

            next_caps = result.get("next_capabilities", [])
            reasoning = result.get("reasoning", "LLM-determined next capabilities")
            stop = result.get("stop", False)

            logger.info(
                "plan_next_phase: suggested capabilities=%s, stop=%s, reasoning=%s",
                next_caps,
                stop,
                reasoning[:100],
            )

            return {
                "next_capabilities": next_caps,
                "reasoning": reasoning,
                "stop": stop,
            }

        except Exception as e:
            logger.warning("LLM phase planning failed: %s. Using deterministic fallback.", e)
            return self._deterministic_next_phase(findings, phase)

    def _deterministic_next_phase(
        self,
        findings: list[dict],
        phase: str = "",
    ) -> dict:
        """Fallback: deterministic phase progression when LLM is unavailable.

        Maps the completed phase to the standard next capabilities based on
        the canonical assessment pipeline, respecting any HIGH/CRITICAL findings
        that warrant deeper investigation.
        """
        # Default phase progression map
        phase_to_next_capabilities = {
            "recon": ["VULN_SCAN", "AUTH_TEST"],
            "scan": ["DEEP_SCAN", "XSS_DETECTION", "SQLI_DETECTION"],
            "deep_scan": ["POST_EXPLOIT", "EXPLOIT_CHAIN"],
            "repo_scan": ["VULN_SCAN"],
            "analyze": ["REPORT"],
            "report": [],
        }

        phase_lower = phase.lower().strip() if phase else ""

        # Check for HIGH/CRITICAL findings — suggest deeper inspection
        has_critical = any(
            str(f.get("severity", "")).upper() in ("CRITICAL", "HIGH")
            for f in findings
        )

        next_caps = list(phase_to_next_capabilities.get(phase_lower, ["VULN_SCAN"]))

        if has_critical and phase_lower in ("recon", "scan"):
            # Add exploit/post-exploit capabilities when critical findings exist
            if "EXPLOIT_CHAIN" not in next_caps:
                next_caps.append("EXPLOIT_CHAIN")
            if "POST_EXPLOIT" not in next_caps:
                next_caps.append("POST_EXPLOIT")

        stop = phase_lower in ("report",) or not next_caps

        return {
            "next_capabilities": next_caps,
            "reasoning": f"Deterministic phase progression from '{phase_lower}': {len(next_caps)} next capability(ies)",
            "stop": stop,
        }

    def plan_next_action(
        self,
        task: str,
        context: str,
        tried_tools: set = None,
        recon_context: Any = None,
        llm_client: Any = None,
        hypotheses: list[dict] | None = None,
    ) -> AgentAction | None:
        """
        Decide the next action.
        LLM branch: uses rich tool descriptions + recon context to select intelligently.
        Fallback: deterministic phase-based iteration (zero regression).

        Args:
            task: Task description
            context: Observation context string
            tried_tools: Set of tool names already tried
            recon_context: ReconContext for LLM tool selection
            llm_client: Optional LLM client override
            hypotheses: Optional list of active hypotheses to guide tool selection
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
                task,
                context,
                tried_tools,
                recon_context,
                llm_service=llm_service,
                hypotheses=hypotheses,
            )
            if action is _DONE:
                return None
            if action is not None:
                # LLM succeeded — reset failure counter
                self._llm_failure_count = 0
                # Attach actual LLM token counts to the action for governance (blocker 48)
                # These are read from the LLMService which tracks them from the LLMResponse.
                if (
                    _ff_enabled("GOVERNANCE_V2", default=False)
                    and self.governance is not None
                    and hasattr(llm_service, 'last_input_tokens')
                ):
                    action.input_tokens = llm_service.last_input_tokens
                    action.output_tokens = llm_service.last_output_tokens
                return action

        # Blocker 31: LLM → deterministic fallback should not be silent.
        # When the LLM is available but returned None (failed/fallback),
        # log a warning so operators can detect degraded performance.
        # Guard: only warn if we actually TRIED the LLM (recon_context was present).
        if (
            llm_client
            and hasattr(llm_client, "is_available")
            and llm_client.is_available()
            and recon_context
        ):
            self._llm_failure_count += 1
            logger.warning(
                "LLM tool selection returned None (failure #%d) — falling back to "
                "deterministic plan for %s. Check LLM availability and response format "
                "if this recurs.",
                self._llm_failure_count,
                task[:80],
            )
            # Emit an error hint so the UI knows the agent is running in degraded mode
            try:
                if self.engagement_id:
                    _hint = ErrorHint(
                        summary="Agent running in degraded mode",
                        detail=(
                            f"LLM returned no valid tool selection after "
                            f"{self._llm_failure_count} consecutive attempt(s). "
                            f"Falling back to deterministic tool ordering."
                        ),
                        remediation=(
                            "The LLM may be unavailable, rate-limited, or returning "
                            "unparseable responses. Verify API key and quota. "
                            "The assessment continues with deterministic tools "
                            "but may have reduced coverage."
                        ),
                        tool="react_agent",
                    )
                    emit_error_hint(self.engagement_id, _hint)
            except Exception:
                logger.debug("Failed to emit fallback error hint", exc_info=True)

        return self._deterministic_plan(task, tried_tools)

    def _update_hypotheses_from_result(
        self, tool_name: str, result: AgentResult
    ) -> None:
        """Update hypothesis state after a tool result.

        Called after each tool execution in run(). Evaluates whether the
        tool result confirms or refutes active hypotheses and updates
        their confidence and status accordingly.

        Writes to Postgres first, then in-memory cache. Skips cache update
        on Postgres failure (snapshot-before-mutation pattern).
        """
        from copy import deepcopy

        from exceptions import HypothesisPersistenceError

        if not self.engagement_state:
            return

        hypotheses = getattr(self.engagement_state, "hypotheses", [])
        if not hypotheses:
            return

        snapshot = deepcopy(hypotheses)
        try:
            for h in hypotheses:
                if h.get("status") != "UNVERIFIED":
                    continue
                suggested = h.get("suggested_tools", [])
                if tool_name not in suggested:
                    continue
                hyp_id = h.get("id")
                if not hyp_id:
                    continue

                if result.success and getattr(result, "findings", None):
                    updates = {
                        "confidence": min(
                            1.0, h.get("confidence", 0.5) + 0.1
                        ),
                        "supporting_finding_ids": h.get(
                            "supporting_finding_ids", []
                        )
                        + [
                            f.get("id")
                            for f in (getattr(result, "findings", []) or [])
                            if isinstance(f, dict) and f.get("id")
                        ],
                    }
                    if updates["confidence"] >= 0.85:
                        updates["status"] = "CONFIRMED"
                elif result.success is False:
                    updates = {
                        "confidence": max(
                            0.0, h.get("confidence", 0.5) - 0.1
                        ),
                        "refuting_finding_ids": h.get(
                            "refuting_finding_ids", []
                        ) + [tool_name],
                    }
                    if updates["confidence"] <= 0.2:
                        updates["status"] = "REJECTED"
                else:
                    # Tool succeeded but no findings — neutral evidence
                    if hasattr(result, "output") and (
                        not result.output
                        or len(str(result.output).strip()) < 30
                    ):
                        # Empty output = slight negative signal
                        updates = {
                            "confidence": max(
                                0.0, h.get("confidence", 0.5) - 0.05
                            ),
                        }
                    else:
                        continue

                try:
                    from database.repositories.hypothesis_repository import (
                        HypothesisRepository,
                    )

                    HypothesisRepository().update(hyp_id, updates)
                except Exception as e:
                    raise HypothesisPersistenceError(
                        f"Postgres update failed for {hyp_id}",
                    ) from e

                self.engagement_state.update_hypothesis(hyp_id, updates)

                # Emit metrics
                try:
                    from metrics import increment_counter

                    if updates.get("status") == "CONFIRMED":
                        increment_counter("hypothesis.confirmed")
                    elif updates.get("status") == "REJECTED":
                        increment_counter("hypothesis.rejected")
                except Exception:
                    pass

        except HypothesisPersistenceError:
            # Revert in-memory cache on Postgres write failure
            self.engagement_state.hypotheses = snapshot
            self.engagement_state._hypothesis_write_failures += 1
            logger.warning(
                "Hypothesis update failed — reverted to last-known-good state",
                extra={"tool": tool_name},
                exc_info=True,
            )
        except Exception as e:
            self.engagement_state.hypotheses = snapshot
            self.engagement_state._hypothesis_write_failures += 1
            logger.exception(
                "Unexpected error in _update_hypotheses_from_result — reverted: %s",
                e,
            )

    def _persist_decision_checkpoint(
        self, action: AgentAction, observation_context: str, reasoning: str
    ) -> str | None:
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
        # Parse initial_target robustly: only split on first colon if the prefix
        # is a known phase name. Otherwise treat the whole task as the target,
        # avoiding mangling URLs like "https://example.com:8080" → "//example.com:8080".
        _known_phases = {"recon", "scan", "deep_scan", "repo_scan", "analyze", "report"}
        if ":" in task:
            phase_part = task.split(":", 1)[0].strip().lower()
            if phase_part in _known_phases:
                initial_target = task.split(":", 1)[-1].strip()
            else:
                initial_target = task
        else:
            initial_target = task

        # Restore AuthContext from checkpoint if available (Celery retry resilience)
        if self._auth_context is None and self.engagement_id:
            try:
                from agent.auth_checkpoint import load_auth_checkpoint

                checkpoint = load_auth_checkpoint(self.engagement_id)
                if checkpoint and checkpoint.email and checkpoint.password:
                    import concurrent.futures

                    import requests

                    from agent.tools.login_tool import run_login

                    http_session = requests.Session()

                    def _restore_login():
                        return run_login(
                            target=initial_target,
                            http_session=http_session,
                            email=checkpoint.email,
                            password=checkpoint.password,
                        )

                    _login_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                    try:
                        login_future = _login_pool.submit(_restore_login)
                        result, ctx = login_future.result(timeout=30)
                        if ctx and ctx.is_authenticated():
                            self.set_auth_context(ctx)
                            slog.info(
                                "Auth session restored from checkpoint for %s",
                                checkpoint.email,
                            )
                    except concurrent.futures.TimeoutError:
                        slog.warning(
                            "Auth checkpoint restore timed out after 30s for %s",
                            checkpoint.email,
                        )
                        # Gap 9.8: Emit auth_error hint when checkpoint restore fails silently
                        try:
                            if self.engagement_id:
                                _hint = ErrorHint(
                                    summary="Auth checkpoint restore timed out",
                                    detail=(
                                        f"Login restoration for {checkpoint.email} timed out "
                                        f"after 30s. The agent will continue without authentication."
                                    ),
                                    remediation=(
                                        "The saved authentication session could not be restored. "
                                        "The target may be rate-limiting login attempts or the "
                                        "credentials may no longer be valid. Try providing fresh "
                                        "credentials for this engagement."
                                    ),
                                    tool="react_agent",
                                )
                                emit_error_hint(self.engagement_id, _hint)
                        except Exception:
                            logger.debug("Failed to emit auth checkpoint error hint", exc_info=True)
                    finally:
                        # Blocker 33: shutdown(wait=False) + cancel_futures=True ensures
                        # the executor's worker threads are interrupted immediately rather
                        # than lingering until garbage collection.
                        _login_pool.shutdown(wait=False, cancel_futures=True)
            except Exception as exc:
                slog.warning("Failed to restore auth checkpoint: %s", exc)

        for iteration in range(self.max_iterations):
            if self._cancelled:
                logger.info("Agent: cancelled at iteration %d", iteration)
                break

            # Check if engagement state signals completion
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

            # Load active hypotheses from EngagementState for tool selection
            _active_hypotheses = None
            if (
                _ff_enabled("ENGAGEMENT_STATE", default=False)
                and self.engagement_state is not None
                and hasattr(self.engagement_state, "get_active_hypotheses")
            ):
                try:
                    _active_hypotheses = (
                        self.engagement_state.get_active_hypotheses(max_count=10)
                    )
                except Exception as e:
                    logger.debug("Failed to load hypotheses: %s", e)

            plan_kwargs["hypotheses"] = _active_hypotheses

            action = self.plan_next_action(
                task,
                self.get_context(),
                **plan_kwargs,
            )

            if action is None:
                logger.info("Agent: no more actions at iteration %d", iteration)
                break

            # ── Track cost regardless of governance mode ──
            # Cost tracking must run BEFORE the governance cost guard check, so it's
            # not lost when GOVERNANCE_V2 is active (which previously skipped the
            # legacy `else` branch containing `total_cost_usd += ...`).
            total_cost_usd += getattr(action, "cost_usd", 0.0)

            # ── Governance check (Phase 6) ──
            # When GOVERNANCE_V2 flag is enabled and a Governance instance
            # is provided, use unified safety controls instead of ad-hoc cost guard.
            # Fix (blocker 29): Always check the REAL cost against max_cost_usd,
            # even in GOVERNANCE_V2 mode, to prevent unbounded cost accumulation.
            if (
                _ff_enabled("GOVERNANCE_V2", default=False)
                and self.governance is not None
            ):
                can_proceed, reason = self.governance.check(action)
                if not can_proceed:
                    logger.warning(
                        "Governance: %s — engagement %s, switching to deterministic for remaining tools",
                        reason,
                        self.engagement_id,
                    )
                    # Run remaining phase tools deterministically before shutdown
                    for tool_name in self.PHASE_TOOLS.get(self._phase, []):
                        if (
                            tool_name not in tried_tools
                            and self.registry.get_tool(tool_name) is not None
                        ):
                            result = self.registry.call(
                                tool_name, target=initial_target
                            )
                            results.append(result)
                    break

            # Blocker 29 fix: Cost guard applies in ALL modes, not just legacy.
            # This prevents unbounded LLM cost accumulation in GOVERNANCE_V2 mode.
            # (The legacy cost guard block was removed — this single check covers all modes.)
            if total_cost_usd > LLM_AGENT_MAX_COST_USD:
                logger.warning(
                    "Cost guard: $%.4f exceeds $%.4f (engagement %s). "
                    "Switching to deterministic for remaining tools.",
                    total_cost_usd,
                    LLM_AGENT_MAX_COST_USD,
                    self.engagement_id,
                )
                for tool_name in self.PHASE_TOOLS.get(self._phase, []):
                    if (
                        tool_name not in tried_tools
                        and self.registry.get_tool(tool_name) is not None
                    ):
                        result = self.registry.call(
                            tool_name, target=initial_target
                        )
                        results.append(result)
                break

            slog.agent_iteration(
                iteration,
                action.tool,
                action.reasoning[:80] if action.reasoning else "",
                cost=action.cost_usd,
            )
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
                action,
                observation_context,
                action.reasoning,
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
                        was_fallback=not (
                            self.llm_client and self.llm_client.is_available()
                        ),
                    )
            except Exception:
                logger.warning(
                    "Agent: failed to emit decision event (non-fatal)", exc_info=True
                )

            # Execute tool with scope validation
            if not self._validate_arguments(action):
                logger.warning(
                    "Blocked tool %s due to scope validation failure", action.tool
                )
                result = AgentResult(
                    tool=action.tool,
                    success=False,
                    error=f"Blocked by scope validation: {action.tool}",
                )
                tried_tools.add(action.tool)
                results.append(result)
                continue
            # ── Active time tracking (blocker 58) ──
            # Wrap tool execution with governance timer so that only active
            # execution time counts against the runtime budget, not idle time
            # between tool calls. Uses try/finally to ensure the timer is
            # stopped even if registry.call() raises an exception.
            if (
                _ff_enabled("GOVERNANCE_V2", default=False)
                and self.governance is not None
            ):
                self.governance.start_active_timer()
            try:
                result = self.registry.call(action.tool, **action.arguments)
            finally:
                if (
                    _ff_enabled("GOVERNANCE_V2", default=False)
                    and self.governance is not None
                ):
                    self.governance.stop_active_timer()
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
                        result_summary=str(result.output)[:500]
                        if hasattr(result, "output") and result.output
                        else "",
                        execution_cost=getattr(action, "cost_usd", 0.0),
                        success=getattr(result, "success", False),
                        failure_state=getattr(result, "stderr", "")[:200]
                        if not getattr(result, "success", True)
                        else "",
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
                        error=result.stderr
                        if hasattr(result, "stderr") and not result.success
                        else "",
                    )
                except Exception as e:
                    logger.debug("Failed to mark checkpoint result: %s", e)

            # ── Record result with governance (Phase 6) ──
            if (
                _ff_enabled("GOVERNANCE_V2", default=False)
                and self.governance is not None
            ):
                # Pass actual token counts when available (blocker 48)
                actual_input = getattr(result, 'input_tokens', None)
                actual_output = getattr(result, 'output_tokens', None)
                self.governance.record_result(
                    result,
                    action,
                    actual_input_tokens=actual_input,
                    actual_output_tokens=actual_output,
                )
                # Check low-signal threshold
                is_low_signal, signal_reason = self.governance.check_low_signal()
                if is_low_signal:
                    logger.warning(
                        "Governance: %s — stopping agent for engagement %s",
                        signal_reason,
                        self.engagement_id,
                    )
                    break

            # Legacy empty-output detection (only when governance is not active)
            if not (
                _ff_enabled("GOVERNANCE_V2", default=False)
                and self.governance is not None
            ):
                if not result.success:
                    pass
                else:
                    # Safely handle non-string output (e.g. dict from tool wrappers)
                    raw_output = result.output
                    if not isinstance(raw_output, str):
                        try:
                            raw_output = str(raw_output)
                        except Exception:
                            raw_output = ""
                    output_content = (raw_output or "").strip()
                    if len(output_content) < 30:
                        if output_content.startswith(("{", "[")):
                            import json as _json

                            try:
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
                if (
                    empty_output_consecutive >= LLM_AGENT_ZERO_FINDING_STOP
                    and len(tried_tools) >= 4
                ):
                    logger.info(
                        "Agent: %d consecutive empty tools after %d runs — stopping",
                        empty_output_consecutive,
                        len(tried_tools),
                    )
                    break

            # FIX: build meaningful observation from actual output content
            observation = build_observation_summary(action.tool, result)
            self.add_to_history("observation", observation)

            # ── Update hypothesis state after tool result ──
            if _ff_enabled("HYPOTHESIS_ENGINE", default=False):
                self._update_hypotheses_from_result(action.tool, result)

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
                        was_fallback=not (
                            self.llm_client and self.llm_client.is_available()
                        ),
                        input_tokens=None,
                        output_tokens=None,
                    )
                except Exception as e:
                    logger.warning("Failed to log decision: %s", e)

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

            task_desc = self.PHASE_AGENTS.get(phase, {}).get("description", phase)
            logger.info(
                "Agent lifecycle: running phase '%s' — %s",
                phase,
                task_desc,
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
            if (
                _ff_enabled("ENGAGEMENT_STATE", default=False)
                and self.engagement_state is not None
                and hasattr(self.engagement_state, "is_complete")
                and self.engagement_state.is_complete()
            ):
                logger.info(
                    "Agent lifecycle: engagement %s is terminal — "
                    "stopping after phase %s",
                    self.engagement_id,
                    phase,
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
            self.engagement_id,
            len(lifecycle_results),
        )
        return lifecycle_results
