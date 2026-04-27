"""
ReAct Agent Loop - LLM-driven tool selection and execution

Replaces the rigid Orchestrator tool sequence with a dynamic loop:
1. LLM receives context + available tools
2. LLM decides which tool to call and why
3. Tool executes, result feeds back to context
4. LLM decides next action (another tool or stop)

This mirrors CyberStrikeAI's Eino agent architecture pattern.
"""
import json
import logging
import time
from typing import Dict, List, Optional, Any, Callable
from enum import Enum

logger = logging.getLogger(__name__)


class AgentAction:
    """An action the agent decided to take."""
    def __init__(self, tool: str, arguments: Dict, reasoning: str = ""):
        self.tool = tool
        self.arguments = arguments
        self.reasoning = reasoning

    def to_dict(self) -> Dict:
        return {
            "tool": self.tool,
            "arguments": self.arguments,
            "reasoning": self.reasoning,
        }


class AgentResult:
    """Result from a tool execution within the agent loop."""
    def __init__(self, tool: str, success: bool, output: str = "",
                 error: str = "", duration_ms: int = 0):
        self.tool = tool
        self.success = success
        self.output = output
        self.error = error
        self.duration_ms = duration_ms

    def to_dict(self) -> Dict:
        return {
            "tool": self.tool,
            "success": self.success,
            "summary": (self.output[:500] if self.output else self.error)[:500],
            "duration_ms": self.duration_ms,
        }


class ToolRegistry:
    """
    Registry of available tools for the agent to use.
    Bridges to the MCP protocol server for tool discovery.
    """

    def __init__(self):
        self._tools: Dict[str, Callable] = {}
        self._tool_metadata: Dict[str, Dict] = {}

    def register(self, name: str, func: Callable, metadata: Dict = None):
        """Register a callable tool function."""
        self._tools[name] = func
        self._tool_metadata[name] = metadata or {
            "name": name,
            "description": "",
            "parameters": [],
        }

    def get_tool(self, name: str) -> Optional[Callable]:
        """Get a tool function by name."""
        return self._tools.get(name)

    def list_tools(self) -> List[Dict]:
        """List all available tools with their metadata."""
        return list(self._tool_metadata.values())

    def call(self, name: str, **kwargs) -> AgentResult:
        """Call a tool function by name with arguments."""
        start = time.time()
        func = self._tools.get(name)
        if not func:
            return AgentResult(
                tool=name, success=False,
                error=f"Unknown tool: {name}"
            )
        try:
            result = func(**kwargs)
            duration = int((time.time() - start) * 1000)
            if isinstance(result, AgentResult):
                return result
            return AgentResult(
                tool=name, success=True,
                output=str(result), duration_ms=duration
            )
        except Exception as e:
            duration = int((time.time() - start) * 1000)
            return AgentResult(
                tool=name, success=False,
                error=str(e), duration_ms=duration
            )


class ReActAgent:
    """
    ReAct (Reasoning + Acting) Agent Loop.

    The agent:
    1. Receives a task description and context
    2. Has access to tools via ToolRegistry
    3. In each iteration, decides: call a tool or finish
    4. Maintains an observation history for context

    In this initial implementation, the "LLM decision" is replaced
    with a rule-based strategy planner. An LLM integration point
    is provided for the full ReAct loop.
    """

    def __init__(self, registry: ToolRegistry, max_iterations: int = 20):
        self.registry = registry
        self.max_iterations = max_iterations
        self.history: List[Dict] = []

    def add_to_history(self, role: str, content: str, data: Dict = None):
        """Add an entry to the agent's history/context."""
        self.history.append({
            "role": role,
            "content": content,
            "data": data or {},
            "timestamp": time.time(),
        })

    def get_context(self) -> str:
        """Build context string from history for LLM consumption."""
        parts = []
        for entry in self.history[-10:]:  # Last 10 entries for context window
            parts.append(f"[{entry['role']}]: {entry['content']}")
        return "\n".join(parts)

    def plan_next_action(self, task: str, context: str) -> Optional[AgentAction]:
        """
        Decide the next action based on task and context.

        In a full implementation, this would call an LLM with:
        - System prompt describing available tools
        - Task description
        - Observation history
        - Tool schemas

        For now, uses a strategy-based planner that mirrors
        the existing Orchestrator's decision logic but is
        extensible to LLM-driven decisions.
        """
        # LLM integration point:
        # return self._llm_decide(task, context, self.registry.list_tools())

        # Fallback: return None to signal "no more actions"
        return None

    def run(self, task: str, initial_context: Dict = None) -> List[AgentResult]:
        """
        Run the agent loop for a given task.

        Args:
            task: Task description
            initial_context: Initial context data

        Returns:
            List of tool execution results
        """
        self.history = []
        results = []
        context = json.dumps(initial_context or {})

        self.add_to_history("system", f"Task: {task}")
        self.add_to_history("context", context)

        for iteration in range(self.max_iterations):
            action = self.plan_next_action(task, self.get_context())

            if action is None:
                logger.info("Agent: no more actions, finishing")
                break

            logger.info("Agent iteration %d: calling %s with %s",
                       iteration, action.tool, action.arguments)

            result = self.registry.call(action.tool, **action.arguments)
            results.append(result)

            self.add_to_history(
                "observation",
                f"Tool {action.tool} {'succeeded' if result.success else 'failed'}: {result.output[:200] if result.output else result.error[:200]}",
                {"action": action.to_dict(), "result": result.to_dict()}
            )

            if not result.success:
                logger.warning("Agent: tool %s failed, continuing", action.tool)

        return results


class CoordinatorAgent:
    """
    Multi-Agent Coordinator — delegates phases to specialized sub-agents.

    Mirrors CyberStrikeAI's Eino ADK multi-agent pattern:
    - Orchestrator (this) decides phase transitions
    - Sub-agents handle specific phases (recon, scan, analyze, report)

    Each phase has a focused set of tools and can run independently.
    """

    PHASE_AGENTS = {
        "recon": {
            "description": "Reconnaissance and asset discovery",
            "tools": ["httpx", "subfinder", "gau", "waybackurls", "nmap"],
        },
        "scan": {
            "description": "Active vulnerability scanning",
            "tools": ["nuclei", "dalfox", "sqlmap", "testssl", "ffuf"],
        },
        "deep_scan": {
            "description": "Deep targeted scanning on priority targets",
            "tools": ["nuclei", "dalfox", "sqlmap", "nikto"],
        },
        "repo_scan": {
            "description": "Repository code analysis",
            "tools": ["semgrep", "bandit", "gitleaks", "npm-audit"],
        },
        "analyze": {
            "description": "Findings analysis and intelligence",
            "tools": ["llm-review", "attack-graph"],
        },
        "report": {
            "description": "Report generation",
            "tools": ["compliance-check", "report-generator"],
        },
    }

    VALID_TRANSITIONS = {
        "recon": ["scan"],
        "scan": ["analyze", "deep_scan"],
        "deep_scan": ["analyze"],
        "repo_scan": ["scan"],
        "analyze": ["report", "recon"],  # Can loop back for deeper analysis
        "report": [],
    }

    def __init__(self, engagement_id: str):
        self.engagement_id = engagement_id
        self.current_phase = "recon"
        self.phase_results: Dict[str, List[AgentResult]] = {}

    def can_transition_to(self, next_phase: str) -> bool:
        """Check if transition to next phase is valid."""
        return next_phase in self.VALID_TRANSITIONS.get(self.current_phase, [])

    def transition_to(self, next_phase: str) -> bool:
        """Transition to next phase if valid."""
        if not self.can_transition_to(next_phase):
            logger.warning("Invalid transition: %s -> %s",
                          self.current_phase, next_phase)
            return False
        self.current_phase = next_phase
        return True

    def get_phase_agent(self, phase: str) -> ReActAgent:
        """Create a ReAct agent for a specific phase."""
        registry = ToolRegistry()
        phase_info = self.PHASE_AGENTS.get(phase, {})
        for tool_name in phase_info.get("tools", []):
            pass
        return ReActAgent(registry)

    def run_phase(self, phase: str, context: Dict) -> List[AgentResult]:
        """Run a single phase and return results."""
        agent = self.get_phase_agent(phase)
        results = agent.run(
            task=self.PHASE_AGENTS.get(phase, {}).get("description", ""),
            initial_context=context
        )
        self.phase_results[phase] = results
        return results
