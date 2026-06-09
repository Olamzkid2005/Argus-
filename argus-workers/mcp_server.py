"""
MCP Protocol Server - Wraps tool execution with discoverable schemas
Implements Model Context Protocol for standardized tool calling
"""
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from agent.session_store import AgentSessionStore, ToolExecution
from tool_core.parser import dispatch
from tracing import setup_tracing

# ── Signal quality tiers for planner intelligence ──

class SignalQuality:
    """Signal quality tier for a tool's findings reliability.

    Maps to ConfidenceEngine baseline:
        CONFIRMED  → HIGH   (e.g. sqlmap, nuclei verified templates)
        PROBABLE   → MEDIUM (e.g. dalfox, semgrep)
        CANDIDATE  → LOW    (e.g. ffuf, nikto, passive recon)
    """
    CONFIRMED = "CONFIRMED"
    PROBABLE = "PROBABLE"
    CANDIDATE = "CANDIDATE"


# ── Tool cost tiers for planner ranking ──

class ToolCost:
    """Relative execution cost for a tool.

    Used by planner to select tools appropriate for scan depth:
        low    → quick scan (always run)
        medium → full assessment (run by default)
        high   → deep scan (only when explicitly requested)
    """
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


tracer = setup_tracing()

logger = logging.getLogger(__name__)


class ToolSchema:
    """JSON Schema definition for a tool parameter."""
    def __init__(self, name: str, type: str, description: str = "",
                 required: bool = False, enum: list[str] = None,
                 default: Any = None, flag: str = None, **_kwargs):
        self.name = name
        self.type = type
        self.description = description
        self.required = required
        self.enum = enum or []
        self.default = default
        self.flag = flag
        # Ignore any extra keys from dict unpacking to avoid TypeError


class ToolDefinition:
    """
    A tool definition loaded from YAML or registered programmatically.
    Mirrors CyberStrikeAI's YAML tool definitions pattern.

    Extended with planner intelligence fields:
        capabilities   — capabilities this tool satisfies (e.g. sqli_detection)
        signal_quality — reliability tier for confidence baseline
        requires       — gates that must pass before this tool is eligible
        priority       — ranking weight (0-100, higher = preferred)
        cost           — execution cost tier for scan-depth filtering
    """
    def __init__(self, name: str, command: str, description: str = "",
                 args: list[str] = None, parameters: list[dict] = None,
                 enabled: bool = True, timeout: int = 300,
                 env: dict[str, str] = None,
                 binary: str | None = None,
                 capabilities: list[str] = None,
                 signal_quality: str = None,
                 requires: dict = None,
                 priority: int = None,
                 cost: str = None):
        self.name = name
        self.command = command
        self.description = description
        self.args = args or []
        self.parameters = [ToolSchema(**p) if isinstance(p, dict) else p for p in (parameters or [])]
        self.enabled = enabled
        self.timeout = timeout
        self.env = env or {}
        self.binary = binary
        # Planner intelligence fields
        self.capabilities = capabilities or []
        self.signal_quality = signal_quality
        self.requires = requires or {}
        self.priority = priority
        self.cost = cost

    def to_dict(self) -> dict:
        """Serialize to MCP tool schema format (includes planner metadata)."""
        result = {
            "name": self.name,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": {
                    p.name: {
                        "type": p.type,
                        "description": p.description,
                        **({"enum": p.enum} if p.enum else {}),
                        **({"default": p.default} if p.default is not None else {}),
                    }
                    for p in self.parameters
                },
                "required": [p.name for p in self.parameters if p.required],
            },
            "capabilities": self.capabilities,
            "signal_quality": self.signal_quality,
            "requires": self.requires,
            "priority": self.priority,
            "cost": self.cost,
        }
        # Strip None values for cleaner output
        return {k: v for k, v in result.items() if v is not None and v != []}


class MCPToolResult:
    """Result of an MCP tool execution."""
    def __init__(self, success: bool, output: str = "", error: str = "",
                 duration_ms: int = 0, tool: str = "", data: dict = None,
                 signal_quality: str = None):
        self.success = success
        self.output = output
        self.error = error
        self.duration_ms = duration_ms
        self.tool = tool
        self.data = data or {}
        self.signal_quality = signal_quality

    def to_dict(self) -> dict:
        meta = {
            "tool": self.tool,
            "duration_ms": self.duration_ms,
            "success": self.success,
        }
        if self.signal_quality:
            meta["signal_quality"] = self.signal_quality
        if self.data:
            meta["data"] = dict(self.data)
        return {
            "content": [{"type": "text", "text": self.output or self.error}],
            "isError": not self.success,
            "meta": meta,
        }


class MCPServer:
    """
    MCP Protocol Server for tool execution.

    Supports:
    - tools/list - discover available tools
    - tools/call - execute a tool by name with parameters
    - Tool registration from YAML definitions
    - Execution tracking and statistics

    This is the foundation for replacing direct subprocess.run() calls
    with a discoverable, schematized protocol layer.
    """

    def __init__(self, tools_dir: str | None = None):
        self._tools: dict[str, ToolDefinition] = {}
        self._execution_stats: dict[str, dict] = {}
        self._tools_dir = tools_dir or os.path.join(
            os.path.dirname(__file__), "tools", "definitions"
        )
        self._load_yaml_tools()
        self.session_store = AgentSessionStore()

    def _load_yaml_tools(self):
        """Load tool definitions from YAML files in tools/definitions/."""
        tools_path = Path(self._tools_dir)
        if not tools_path.exists():
            tools_path.mkdir(parents=True, exist_ok=True)
            logger.info("Created tools definitions directory: %s", tools_path)
            return

        # Blocklist of dangerous command patterns for YAML-defined tools
        blocked_command_patterns = {
            "sh", "bash", "zsh", "dash", "/bin/sh", "/bin/bash",
            "rm", "mv", "cp", "dd", "mkfs", "chmod", "chown",
            "nc", "netcat", "curl", "wget", "telnet", "ssh",
            "ruby", "perl", "node", "php",
        }
        # Agent-internal tools use a runner script — allow python3 for whitelisted scripts
        server_dir = os.path.dirname(os.path.abspath(__file__))  # .../argus-workers/
        project_dir = os.path.dirname(server_dir)                 # project root
        # The YAML args use "argus-workers/tools/run_agent_tool.py" which call_tool
        # resolves to project_dir/argus-workers/tools/run_agent_tool.py
        allowed_python_scripts = {
            os.path.normpath(os.path.join(project_dir, "argus-workers", "tools", "run_agent_tool.py")),
            os.path.normpath(os.path.join(project_dir, "argus-workers", "tools", "scripts", "playwright_bola.py")),
            os.path.normpath(os.path.join(project_dir, "argus-workers", "tools", "scripts", "playwright_xss.py")),
            os.path.normpath(os.path.join(project_dir, "argus-workers", "tools", "scripts", "playwright_privesc.py")),
        }

        try:
            import yaml
        except ImportError:
            logger.info("PyYAML not installed, skipping YAML tool loading")
            return

        for yaml_file in sorted(tools_path.glob("*.yaml")):
            try:
                with open(yaml_file) as f:
                    data = yaml.safe_load(f)
                if not data:
                    continue

                command = data.get("command", "")
                cmd_basename = Path(command).name.lower() if command else ""

                # Allow python3 for whitelisted runner scripts, block everything else
                if cmd_basename == "python3":
                    args = data.get("args", [])
                    if args:
                        # Resolve path the same way call_tool does
                        script_arg = args[0]
                        if script_arg.startswith("argus-workers/") or script_arg.startswith("tools/"):
                            script_path = os.path.normpath(os.path.join(project_dir, script_arg))
                        else:
                            script_path = os.path.normpath(os.path.join(server_dir, script_arg))
                        if script_path not in allowed_python_scripts:
                            logger.warning(
                                "Skipping tool '%s': python3 script '%s' is not whitelisted",
                                data.get("name", "unknown"), args[0],
                            )
                            continue
                    else:
                        continue  # bare python3 with no script — blocked
                elif ".." in command or cmd_basename in blocked_command_patterns:
                    logger.warning(
                        "Skipping tool '%s': command '%s' is blocked",
                        data.get("name", "unknown"), command,
                    )
                    continue

                tool = ToolDefinition(
                    name=data["name"],
                    command=command,
                    description=data.get("description", ""),
                    args=data.get("args", []),
                    parameters=data.get("parameters", []),
                    enabled=data.get("enabled", True),
                    timeout=data.get("timeout", 300),
                    capabilities=data.get("capabilities", []),
                    signal_quality=data.get("signal_quality"),
                    requires=data.get("requires", {}),
                    priority=data.get("priority"),
                    cost=data.get("cost"),
                )
                self.register_tool(tool)
                logger.info("Loaded tool definition: %s", tool.name)
            except Exception as e:
                logger.warning("Failed to load tool %s: %s", yaml_file, e)

    def register_tool(self, tool: ToolDefinition):
        """Register a tool definition."""
        self._tools[tool.name] = tool
        self._execution_stats[tool.name] = {
            "calls": 0, "successes": 0, "failures": 0, "total_duration_ms": 0
        }

    def get_tools(self) -> list[dict]:
        """Get all tool definitions (mcp.tools/list equivalent)."""
        return [t.to_dict() for t in self._tools.values() if t.enabled]

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Get a tool definition by name."""
        return self._tools.get(name)

    # Blocklist of dangerous shell metacharacters in argument values
    # to prevent command injection via tool arguments
    _SHELL_INJECTION_PATTERN = set(";&|`$(){}[]!<>\n\t\x00")

    def _validate_args_safe(self, args: list[str]) -> None:
        """Validate that no arguments contain shell injection characters.

        Raises ValueError if any argument is unsafe.
        """
        for i, arg in enumerate(args):
            if any(c in arg for c in self._SHELL_INJECTION_PATTERN):
                raise ValueError(
                    f"Argument at position {i} contains shell metacharacters: {arg!r}"
                )

    def call_tool(self, name: str, arguments: dict = None, timeout: int = None, cache_mode: str | None = None) -> dict:
        """
        Execute a tool by name with arguments (mcp.tools/call equivalent).

        Args:
            name: Tool name
            arguments: Tool parameters (will be mapped to CLI args based on schema)
            timeout: Execution timeout in seconds
            cache_mode: Cache execution mode ("normal", "no_cache", "refresh").
                        Passed through to tool execution when using the pipeline
                        router path. For direct subprocess calls, cache_mode is
                        accepted but not enforced (the cache lives in ToolRunner,
                        which is used by the orchestrator path).

        Returns:
            MCP-formatted result dict

        Security:
            - Validates all arguments against shell injection patterns
            - Uses subprocess.run WITHOUT shell=True (safe by design)
            - Commands are vetted at registration time against a dangerous-command blocklist
        """
        tool = self._tools.get(name)
        if not tool:
            return MCPToolResult(
                success=False, error=f"Unknown tool: {name}", tool=name
            ).to_dict()
        if not tool.enabled:
            return MCPToolResult(
                success=False, error=f"Tool disabled: {name}", tool=name
            ).to_dict()

        tool_signal_quality = tool.signal_quality if hasattr(tool, 'signal_quality') else None

        # Build command line from tool definition + arguments
        cmd = [tool.command]
        # Resolve relative paths in static args against the server's directory
        server_dir = os.path.dirname(os.path.abspath(__file__))
        project_dir = os.path.dirname(server_dir)  # parent of argus-workers/
        for static_arg in tool.args:
            if static_arg.startswith("argus-workers/") or static_arg.startswith("tools/"):
                static_arg = os.path.join(project_dir, static_arg)
            cmd.append(static_arg)

        # Map named arguments to CLI flags
        arguments = arguments or {}
        for param in tool.parameters:
            if param.name in arguments:
                value = arguments[param.name]
                if hasattr(param, 'flag') and param.flag:
                    cmd.append(param.flag)
                    cmd.append(str(value))
                else:
                    cmd.append(str(value))

        # Validate all arguments for shell injection before executing
        try:
            self._validate_args_safe(cmd[1:])
        except ValueError as e:
            self._execution_stats[name]["calls"] += 1
            self._execution_stats[name]["failures"] += 1
            return MCPToolResult(
                success=False,
                error=f"Security validation failed: {e}",
                tool=name,
                signal_quality=tool_signal_quality,
            ).to_dict()

        # Track execution
        start = time.time()
        self._execution_stats[name]["calls"] += 1

        try:
            # Build a locked-down environment to prevent credential leakage
            # to subprocesses (same pattern as ToolRunner._locked_env).
            _env = os.environ.copy()
            # Strip sensitive variables that should not leak to tool subprocesses
            BLOCKED_ENV_VARS = {
                "DATABASE_URL", "REDIS_URL", "OPENAI_API_KEY", "LLM_API_KEY",
                "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "AZURE_OPENAI_API_KEY",
                "OPENROUTER_API_KEY", "AWS_SECRET_ACCESS_KEY", "AWS_ACCESS_KEY_ID",
                "AWS_SESSION_TOKEN", "GITLAB_TOKEN", "GITHUB_TOKEN", "SLACK_TOKEN",
                "ARGUS_API_KEY", "ARGUS_ALLOWED_GIT_HOSTS",
            }
            for _key in BLOCKED_ENV_VARS:
                _env.pop(_key, None)
            # Add venv to PATH so pip-installed tools are findable
            _venv_bin = str(Path(sys.executable).parent)
            _go_bin = os.path.expanduser("~/go/bin")
            _homebrew_bin = "/opt/homebrew/bin"
            _project_venv = str(Path(__file__).resolve().parent.parent / "venv" / "bin")
            # Preserve any existing PATH customizations (e.g. from start-argus.sh)
            _existing_path = _env.get("PATH", "")
            _env["PATH"] = f"{_venv_bin}:{_go_bin}:{_homebrew_bin}:{_project_venv}:/usr/local/bin:/usr/bin:/bin:{_existing_path}"
            _env["PYTHONDONTWRITEBYTECODE"] = "1"

            result = subprocess.run(  # noqa: S603 — safe: cmd is list form, validated by _validate_args_safe()
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout or tool.timeout,
                env=_env,
            )
            duration_ms = int((time.time() - start) * 1000)

            success = result.returncode == 0
            if success:
                self._execution_stats[name]["successes"] += 1
            else:
                self._execution_stats[name]["failures"] += 1
            self._execution_stats[name]["total_duration_ms"] += duration_ms

            mcp_result = MCPToolResult(
                success=success,
                output=result.stdout,
                error=result.stderr,
                duration_ms=duration_ms,
                tool=name,
                signal_quality=tool_signal_quality,
            )
            structured = dispatch(name, result.stdout if success else "")
            if structured:
                mcp_result.data["structured"] = [f.__dict__ for f in structured]
            return mcp_result.to_dict()

        except subprocess.TimeoutExpired:
            duration_ms = int((time.time() - start) * 1000)
            self._execution_stats[name]["failures"] += 1
            self._execution_stats[name]["total_duration_ms"] += duration_ms
            return MCPToolResult(
                success=False,
                error=f"Tool execution timed out after {timeout or tool.timeout}s",
                duration_ms=duration_ms,
                tool=name,
                signal_quality=tool_signal_quality,
            ).to_dict()
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            self._execution_stats[name]["failures"] += 1
            return MCPToolResult(
                success=False,
                error=str(e),
                duration_ms=duration_ms,
                tool=name,
                signal_quality=tool_signal_quality,
            ).to_dict()

    def get_stats(self) -> dict:
        """Get execution statistics for all tools."""
        return dict(self._execution_stats)

    # ── Hybrid planning methods ──

    def handle_agent_init(self, params: dict) -> dict:
        """Create session and generate hybrid plan (1 LLM call per phase)."""
        session_id = self.session_store.create(
            target=params.get("target", ""),
            phase=params.get("phase", ""),
            tech_stack=params.get("techStack", []),
        )

        pipeline = params.get("pipeline", [])

        # Generate ordered plan (deterministic for now — LLM integration later)
        plan = self._generate_plan(session_id, pipeline, params.get("context", {}))

        self.session_store.set_plan(session_id, plan["tool_order"])

        return {
            "session_id": session_id,
            "plan": plan["tool_order"],
            "reasoning": plan["reasoning"],
            "phase": params.get("phase", ""),
        }

    def _generate_plan(self, session_id: str, pipeline: list, context: dict) -> dict:
        """Generate an ordered plan from the available pipeline.

        For now, uses deterministic ordering. LLM integration will come later
        via the ReActAgent. Returns tool_order and reasoning.
        """
        session = self.session_store.get(session_id)

        # Extract tool names from pipeline steps, validating they exist
        tool_order = []
        for step in pipeline:
            tool_name = step.get("tool")
            if tool_name and tool_name in self._tools:
                tool_order.append(tool_name)
            elif tool_name:
                logger.warning("Pipeline references unknown tool '%s', skipping", tool_name)

        # If no pipeline, use a sensible default ordering
        if not tool_order:
            phase = session.phase
            if phase in ("recon", "reconnaissance"):
                tool_order = ["subfinder", "httpx", "whatweb", "nmap", "gospider"]
            elif phase in ("scan", "vulnerability_scanning"):
                tool_order = ["nuclei", "nikto", "dalfox", "wafw00f"]
            elif phase in ("deep_scan", "deep"):
                tool_order = ["nuclei", "sqlmap", "testssl", "commix"]
            else:
                tool_order = []

        return {
            "tool_order": tool_order,
            "reasoning": f"Deterministic plan for {session.phase}: {len(tool_order)} tools",
        }

    def handle_agent_next(self, params: dict) -> dict:
        """Get next tool from current plan, or signal done if plan exhausted."""
        session_id = params.get("session_id", "")
        trigger = (params.get("trigger") or "").lower().strip()

        try:
            session = self.session_store.get(session_id)
        except ValueError:
            return {"error": f"Session {session_id} not found", "done": True}

        # Normal case: advance through the deterministic plan
        next_tool = self.session_store.advance_plan(session_id)
        if next_tool:
            return {
                "tool": next_tool,
                "session_id": session_id,
                "reasoning": "Deterministic plan step",
                "done": False,
            }

        # Plan exhausted
        if trigger in ("stuck", "new_finding", "phase_complete"):
            # Re-plan based on accumulated observations
            new_plan = self._replan(session)
            if new_plan.get("done"):
                return {"done": True, "session_id": session_id}
            self.session_store.set_plan(session_id, new_plan["tool_order"])
            next_tool = self.session_store.advance_plan(session_id)
            if next_tool:
                return {
                    "tool": next_tool,
                    "session_id": session_id,
                    "reasoning": new_plan.get("reasoning", "Re-plan after trigger"),
                    "done": False,
                }

        return {"done": True, "session_id": session_id}

    def _replan(self, session) -> dict:
        """Re-plan based on current session state.

        For now, returns done if plan exhausted. LLM integration later.
        """
        return {"done": True, "reasoning": "Plan complete"}

    def handle_agent_observe(self, params: dict) -> dict:
        """Record tool execution result and decide next action."""
        session_id = params.get("session_id", "")

        try:
            self.session_store.get(session_id)
        except ValueError:
            return {"error": f"Session {session_id} not found", "done": True}

        execution = ToolExecution(
            tool=params.get("tool", ""),
            arguments=params.get("arguments", {}),
            reasoning=params.get("reasoning", ""),
            success=params.get("success", False),
            duration_ms=params.get("durationMs", 0),
            finding_count=params.get("findingCount", 0),
            summary=params.get("summary", ""),
        )
        self.session_store.add_execution(session_id, execution)
        self.session_store.add_observation(session_id, params.get("summary", ""))

        # Check if we need to involve the LLM
        trigger = None
        if not params.get("success", True):
            trigger = "stuck"
        elif params.get("findingCount", 0) > 0:
            trigger = "new_finding"

        return self.handle_agent_next({"session_id": session_id, "trigger": trigger})


# Global MCP server instance
_mcp_server: MCPServer | None = None
_mcp_server_lock = threading.Lock()


def get_mcp_server() -> MCPServer:
    """Get the singleton MCP server instance."""
    global _mcp_server
    if _mcp_server is None:
        with _mcp_server_lock:
            if _mcp_server is None:
                _mcp_server = MCPServer()
    return _mcp_server


def main():
    """Entry point for stdio JSON-RPC transport mode."""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    from mcp_transport import MCPTransport, create_ping_handler

    server = get_mcp_server()
    transport = MCPTransport()

    transport.register("ping", create_ping_handler())

    def handle_list_tools(params: dict) -> dict:
        return {"tools": server.get_tools()}

    def handle_call_tool(params: dict) -> dict:
        name = params.get("name", "")
        arguments = params.get("arguments", {})
        timeout = params.get("timeout")
        cache_mode = params.get("cache_mode")
        return server.call_tool(name, arguments, timeout, cache_mode)

    transport.register("list_tools", handle_list_tools)
    transport.register("call_tool", handle_call_tool)

    def handle_agent_init(params):
        return server.handle_agent_init(params)

    def handle_agent_next(params):
        return server.handle_agent_next(params)

    def handle_agent_observe(params):
        return server.handle_agent_observe(params)

    transport.register("agent_init", handle_agent_init)
    transport.register("agent_next", handle_agent_next)
    transport.register("agent_observe", handle_agent_observe)

    logger.info("MCP stdio transport starting")
    transport.run()


if __name__ == "__main__":
    main()
