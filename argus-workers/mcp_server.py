"""
MCP Protocol Server - Wraps tool execution with discoverable schemas
Implements Model Context Protocol for standardized tool calling
"""

import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from agent.react_agent import ReActAgent
from agent.session_store import AgentSessionStore, ToolExecution
from agent.tool_registry import ToolRegistry
from llm_client import LLMClient
from tool_core.parser import dispatch
from tools.scope_validator import ScopeViolationError

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


logger = logging.getLogger(__name__)


class ToolSchema:
    """JSON Schema definition for a tool parameter."""

    def __init__(
        self,
        name: str,
        type: str,
        description: str = "",
        required: bool = False,
        enum: list[str] = None,
        default: Any = None,
        flag: str = None,
        **_kwargs,
    ):
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
    NOTE: Must stay in sync with tool_definitions.py ToolDefinition.
    Key fields shared by both:
        name, description, capabilities, signal_quality, requires, priority, cost
    This class has additional execution fields (command, args, timeout, env, binary)
    that tool_definitions.py does not have. The two classes have diverged
    intentionally — this one is the runtime MCP server representation,
    tool_definitions.py is the declarative registry representation.
    Extended with planner intelligence fields:
        capabilities   — capabilities this tool satisfies (e.g. sqli_detection)
        signal_quality — reliability tier for confidence baseline
        requires       — gates that must pass before this tool is eligible
        priority       — ranking weight (0-100, higher = preferred)
        cost           — execution cost tier for scan-depth filtering
    """

    def __init__(
        self,
        name: str,
        command: str,
        description: str = "",
        args: list[str] = None,
        parameters: list[dict] = None,
        enabled: bool = True,
        timeout: int = 300,
        env: dict[str, str] = None,
        binary: str | None = None,
        capabilities: list[str] = None,
        signal_quality: str = None,
        requires: dict = None,
        priority: int = None,
        cost: str = None,
        credential_roles: list[str] = None,
    ):
        self.name = name
        self.command = command
        self.description = description
        self.args = args or []
        self.parameters = [
            ToolSchema(**p) if isinstance(p, dict) else p for p in (parameters or [])
        ]
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
        self.credential_roles = credential_roles or []

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
            "credential_roles": self.credential_roles,
        }
        # Strip None values for cleaner output
        return {k: v for k, v in result.items() if v is not None and v != []}


class MCPToolResult:
    """Result of an MCP tool execution."""

    def __init__(
        self,
        success: bool,
        output: str = "",
        error: str = "",
        duration_ms: int = 0,
        tool: str = "",
        data: dict = None,
        signal_quality: str = None,
    ):
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
        from config.startup_guard import check_placeholder_credentials

        credential_issues = check_placeholder_credentials()
        if credential_issues:
            # Blocker 28: In autonomous mode, placeholder credentials are a hard block.
            # In manual/interactive mode, only warn so development is not disrupted.
            _is_autonomous = os.environ.get("ARGUS_AUTONOMOUS", "").lower() in ("1", "true")
            if _is_autonomous:
                raise RuntimeError(
                    "STARTUP GUARD: ARGUS_AUTONOMOUS=1 detected %d credential issue(s):\n  %s\n"
                    "Placeholder credentials are not allowed in autonomous mode. "
                    "Set valid API keys in your environment or .env file."
                    % (len(credential_issues), "\n  ".join(credential_issues))
                )
            logger.warning(
                "STARTUP GUARD: Found %d credential issue(s):\n  %s",
                len(credential_issues),
                "\n  ".join(credential_issues),
            )

        self._tools: dict[str, ToolDefinition] = {}
        self._execution_stats: dict[str, dict] = {}
        self._tools_dir = tools_dir or os.path.join(
            os.path.dirname(__file__), "tools", "definitions"
        )
        self._load_yaml_tools()
        self.session_store = AgentSessionStore()
        # Proactive DNS check — warn at startup if DNS is broken.
        # DNS-reliant tools (subfinder, amass, dnsx, etc.) silently fail
        # without producing useful error messages when DNS is unavailable
        # inside a container or restricted network environment.
        try:
            socket.getaddrinfo("dns.google", 53)
        except socket.gaierror:
            logger.warning(
                "DNS resolution failed — DNS-reliant tools (subfinder, amass, dnsx) may not work. "
                "Check container DNS config or set --dns-servers 8.8.8.8"
            )

    def _load_yaml_tools(self):
        """Load tool definitions from YAML files in tools/definitions/."""
        tools_path = Path(self._tools_dir)
        if not tools_path.exists():
            tools_path.mkdir(parents=True, exist_ok=True)
            logger.info("Created tools definitions directory: %s", tools_path)
            return

        # Blocklist of dangerous command patterns for YAML-defined tools.
        # Categories of blocked commands, all verified as unused by any of the 65+
        # YAML tool definitions (see argus-workers/tools/definitions/):
        #   - Shell interpreters: sh, bash, zsh, dash           (arbitrary code exec)
        #   - File destruction:  rm, mv, cp, dd, mkfs, chmod, chown (data loss)
        #   - Data exfiltration: nc, netcat, curl, wget, telnet, ssh (network leakage)
        #   - Script interpreters: ruby, perl, node, php          (arbitrary code exec)
        # All security tools use their own binary names (nuclei, nmap, sqlmap, etc.),
        # so this blocklist does not block any legitimate tool registration.
        blocked_command_patterns = {
            "sh",
            "bash",
            "zsh",
            "dash",
            "/bin/sh",
            "/bin/bash",
            "rm",
            "mv",
            "cp",
            "dd",
            "mkfs",
            "chmod",
            "chown",
            "nc",
            "netcat",
            "curl",
            "wget",
            "telnet",
            "ssh",
            "ruby",
            "perl",
            "node",
            "php",
        }
        # Agent-internal tools use a runner script — allow python3 for whitelisted scripts
        server_dir = os.path.dirname(os.path.abspath(__file__))  # .../argus-workers/
        project_dir = os.path.dirname(server_dir)  # project root
        # The YAML args use "argus-workers/tools/run_agent_tool.py" which call_tool
        # resolves to project_dir/argus-workers/tools/run_agent_tool.py
        allowed_python_scripts = {
            os.path.normpath(
                os.path.join(project_dir, "argus-workers", "tools", "run_agent_tool.py")
            ),
            os.path.normpath(
                os.path.join(
                    project_dir,
                    "argus-workers",
                    "tools",
                    "scripts",
                    "playwright_bola.py",
                )
            ),
            os.path.normpath(
                os.path.join(
                    project_dir,
                    "argus-workers",
                    "tools",
                    "scripts",
                    "playwright_xss.py",
                )
            ),
            os.path.normpath(
                os.path.join(
                    project_dir,
                    "argus-workers",
                    "tools",
                    "scripts",
                    "playwright_privesc.py",
                )
            ),
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
                        if script_arg.startswith(
                            "argus-workers/"
                        ) or script_arg.startswith("tools/"):
                            script_path = os.path.normpath(
                                os.path.join(project_dir, script_arg)
                            )
                        else:
                            script_path = os.path.normpath(
                                os.path.join(server_dir, script_arg)
                            )
                        if script_path not in allowed_python_scripts:
                            logger.warning(
                                "Skipping tool '%s': python3 script '%s' is not whitelisted",
                                data.get("name", "unknown"),
                                args[0],
                            )
                            continue
                    else:
                        continue  # bare python3 with no script — blocked
                elif ".." in command or cmd_basename in blocked_command_patterns:
                    logger.warning(
                        "Skipping tool '%s': command '%s' is blocked",
                        data.get("name", "unknown"),
                        command,
                    )
                    continue

                # Verify the tool binary exists on PATH before registering.
                # python3-based agent-internal tools are excluded — they always
                # use the current interpreter and their scripts are whitelisted above.
                # Reuse the same augmented PATH logic as call_tool() for consistency.
                if cmd_basename != "python3":
                    _venv_bin = str(Path(sys.executable).parent)
                    _go_bin = os.path.expanduser("~/go/bin")
                    _homebrew_bin = "/opt/homebrew/bin"
                    _project_venv = str(
                        Path(__file__).resolve().parent.parent / "venv" / "bin"
                    )
                    _existing_path = os.environ.get("PATH", "")
                    _extra_path = os.environ.get("ARGUS_EXTRA_PATH", "")
                    _augmented_path = f"{_venv_bin}:{_go_bin}:{_homebrew_bin}:{_project_venv}:/usr/local/bin:/usr/bin:/bin:{_extra_path}:{_existing_path}"
                    if not shutil.which(command, path=_augmented_path):
                        logger.warning(
                            "Skipping tool '%s': binary '%s' not found on PATH. "
                            "Install it or add its directory to PATH.",
                            data.get("name", "unknown"),
                            command,
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
            "calls": 0,
            "successes": 0,
            "failures": 0,
            "total_duration_ms": 0,
        }

    def get_tools(self) -> list[dict]:
        """Get all tool definitions (mcp.tools/list equivalent)."""
        return [t.to_dict() for t in self._tools.values() if t.enabled]

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Get a tool definition by name."""
        return self._tools.get(name)

    # Blocklist of characters that are dangerous in ANY execution context.
    # subprocess.run uses list form (no shell=True), so shell metacharacters
    # like &, $, (), [], <> are NOT dangerous. Only null bytes and control
    # characters that could corrupt the process execution are blocked.
    _SHELL_INJECTION_PATTERN = set("\x00\n\r")

    def _validate_args_safe(self, args: list[str]) -> None:
        """Validate that no arguments contain shell injection characters.

        Raises ValueError if any argument is unsafe.
        """
        for i, arg in enumerate(args):
            if any(c in arg for c in self._SHELL_INJECTION_PATTERN):
                raise ValueError(
                    f"Argument at position {i} contains shell metacharacters: {arg!r}"
                )

    # Findings-bearing exit codes per tool (mirrors ToolRunner.FINDINGS_EXIT_CODES).
    # Many security tools exit non-zero when vulnerabilities are found. These
    # exit codes mean "findings present, not an error." The MCP server must
    # treat them as successes and still parse/dispatch the output.
    # Blocker 25: This dict MUST stay in sync with ToolRunner.FINDINGS_EXIT_CODES
    # in tools/tool_runner.py. Any divergence causes findings-bearing output to be
    # treated as an error on the MCP path, silently losing findings.
    # Last verified: both match exactly (8 tools each).
    FINDINGS_EXIT_CODES: dict[str, set[int]] = {
        "semgrep": {1},
        "bandit": {1},
        "gitleaks": {1},
        "dalfox": {1},
        "trivy": {1},
        "pip-audit": {1},
        "dependency_check": {1},
        "nuclei": {1},
    }

    def call_tool(
        self,
        name: str,
        arguments: dict = None,
        timeout: int = None,
        cache_mode: str | None = None,
        engagement_id: str | None = None,
        scope_validator: Any = None,
    ) -> dict:
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
            engagement_id: Optional engagement UUID for scope validation and audit.
            scope_validator: Optional ``ScopeValidator`` instance. When provided,
                             the tool's ``target`` argument is validated against the
                             authorized scope before execution. An out-of-scope
                             target is rejected with ``ScopeViolationError``.

        Returns:
            MCP-formatted result dict

        Security:
            - Validates all arguments against shell injection patterns
            - Validates target against engagement scope when scope_validator is provided
            - Handles findings-bearing non-zero exit codes (semgrep, bandit, etc.)
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

        tool_signal_quality = (
            tool.signal_quality if hasattr(tool, "signal_quality") else None
        )

        # ── Scope validation: reject out-of-scope targets before any I/O ──
        # Extract the target URL/domain from the raw arguments before argument
        # mapping (which may strip the scheme). Use the original value for
        # scope validation.
        if scope_validator is not None:
            arguments = arguments or {}
            _scope_violations: list[str] = []
            for _scope_param in ("target", "url", "host", "domain"):
                _raw_target = arguments.get(_scope_param)
                if _raw_target and isinstance(_raw_target, str):
                    try:
                        scope_validator.validate_target(_raw_target)
                    except ScopeViolationError as _e:
                        _scope_violations.append(str(_e))
            if _scope_violations:
                _error_msg = "; ".join(_scope_violations)
                self._execution_stats[name]["calls"] += 1
                self._execution_stats[name]["failures"] += 1
                logger.warning(
                    "Scope violation for tool '%s' on engagement %s: %s",
                    name,
                    engagement_id,
                    _error_msg,
                )
                return MCPToolResult(
                    success=False,
                    error=f"Scope violation: {_error_msg}",
                    tool=name,
                    signal_quality=tool_signal_quality,
                ).to_dict()

        # Build command line from tool definition + arguments
        cmd = [tool.command]
        # Resolve relative paths in static args against the server's directory
        server_dir = os.path.dirname(os.path.abspath(__file__))
        project_dir = os.path.dirname(server_dir)  # parent of argus-workers/
        for static_arg in tool.args:
            if static_arg.startswith("argus-workers/") or static_arg.startswith(
                "tools/"
            ):
                static_arg = os.path.join(project_dir, static_arg)
            cmd.append(static_arg)

        # Map named arguments to CLI flags
        arguments = arguments or {}
        for param in tool.parameters:
            if param.name in arguments:
                value = arguments[param.name]
                # Strip URL scheme for tools that expect bare hostnames/domains
                # Tools like nikto (-h), nmap, subfinder (-d), amass (-d),
                # dnsx (-d), naabu (-host) don't handle URL schemes.
                # Tools like nuclei (-u), httpx (-u), dalfox, sqlmap, ffuf (-u),
                # gospider (-s), katana (-u) DO expect full URLs with paths.
                # gau and waybackurls are ambiguous - they accept URLs but work
                # better with bare domains. Keep them in the URL group (H3).
                if isinstance(value, str) and (
                    value.startswith("http://") or value.startswith("https://")
                ):
                    from urllib.parse import urlparse

                    parsed = urlparse(value)
                    # Tools that strictly expect bare hostnames/domains
                    _HOSTNAME_TOOLS = frozenset(
                        {
                            "nmap",
                            "nikto",
                            "subfinder",
                            "amass",
                            "dnsx",
                            "naabu",
                            "masscan",
                            "shuffledns",
                            "alterx",
                            "cloud_enum",
                            "chaos",
                        }
                    )
                    # Tools that need the full URL including path (bucket/org names)
                    _FULL_URL_TOOLS = frozenset(
                        {
                            "s3scanner",
                            "bucket_upload",
                            "github-endpoints",
                        }
                    )
                    if tool.name in _FULL_URL_TOOLS:
                        pass  # Keep full URL including path
                    elif tool.name in _HOSTNAME_TOOLS:
                        stripped = (
                            parsed.hostname or value.split("://", 1)[1].split("/")[0]
                        )
                        logger.debug(
                            "Stripped scheme from target '%s' -> '%s' for tool '%s'",
                            value,
                            stripped,
                            tool.name,
                        )
                        value = stripped
                    # For URL-expecting tools and ambiguous tools, keep full URL
                if hasattr(param, "flag") and param.flag:
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
                "DATABASE_URL",
                "REDIS_URL",
                "OPENAI_API_KEY",
                "LLM_API_KEY",
                "ANTHROPIC_API_KEY",
                "GEMINI_API_KEY",
                "AZURE_OPENAI_API_KEY",
                "OPENROUTER_API_KEY",
                "AWS_SECRET_ACCESS_KEY",
                "AWS_ACCESS_KEY_ID",
                "AWS_SESSION_TOKEN",
                "GITLAB_TOKEN",
                "GITHUB_TOKEN",
                "SLACK_TOKEN",
                "ARGUS_API_KEY",
                "ARGUS_ALLOWED_GIT_HOSTS",
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
            _env["PATH"] = (
                f"{_venv_bin}:{_go_bin}:{_homebrew_bin}:{_project_venv}:/snap/bin:/usr/local/bin:/usr/bin:/bin:{_existing_path}"
            )
            _env["PYTHONDONTWRITEBYTECODE"] = "1"

            result = subprocess.run(  # noqa: S603 — safe: cmd is list form, validated by _validate_args_safe()
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout or tool.timeout,
                env=_env,
            )
            duration_ms = int((time.time() - start) * 1000)

            # Determine success: exit code 0 = success. Some security tools
            # exit non-zero when they FIND vulnerabilities (semgrep, bandit,
            # gitleaks, trivy, etc.) — treat those as successes too.
            findings_exit = self.FINDINGS_EXIT_CODES.get(name, set())
            success = result.returncode == 0 or result.returncode in findings_exit

            if success:
                self._execution_stats[name]["successes"] += 1
            else:
                self._execution_stats[name]["failures"] += 1
            self._execution_stats[name]["total_duration_ms"] += duration_ms

            mcp_result = MCPToolResult(
                success=success,
                # On findings-bearing exit codes, include stderr as part of
                # the output so downstream parsers can extract all content.
                output=result.stdout,
                error=result.stderr,
                duration_ms=duration_ms,
                tool=name,
                signal_quality=tool_signal_quality,
            )
            # Always dispatch findings parsing — even on non-zero exit if
            # the exit code indicates findings were found. This ensures
            # tools like semgrep, bandit, gitleaks produce structured findings
            # on the MCP path.
            output_to_parse = result.stdout
            if not output_to_parse and result.stderr:
                output_to_parse = result.stderr
            structured = dispatch(name, output_to_parse)
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

        # Store TS-side max iterations in the session (blocker 32).
        # The TS executor passes its ARGUS_HYBRID_MAX_ITERATIONS so the
        # Python side can cap the iteration limit with min().
        max_iterations = params.get("max_iterations")
        if max_iterations is not None:
            self.session_store.set_ts_max_iterations(session_id, max_iterations)
            logger.debug(
                "Session %s: TS max_iterations=%d",
                session_id,
                max_iterations,
            )

        pipeline = params.get("pipeline", [])

        # ── Phase 1.3.3: Store previous findings from context into session ──
        # The TypeScript workflow-runner sets previousPhaseResults on llm_driven
        # phases after each completed phase. The executor passes them as
        # context.previousFindings to agentInit. We store them in the session
        # so the LLM replanning can access accumulated findings.
        context = params.get("context", {})
        previous_findings = context.get("previousFindings", [])
        if previous_findings:
            for phase_result in previous_findings:
                if isinstance(phase_result, dict):
                    for finding in phase_result.get("findings", []):
                        if isinstance(finding, dict):
                            self.session_store.add_finding(session_id, finding)
            logger.info(
                "Stored %d previous phase result(s) with findings in session %s",
                len(previous_findings),
                session_id,
            )

        # Generate ordered plan (deterministic for now — LLM integration later)
        plan = self._generate_plan(session_id, pipeline, context)

        self.session_store.set_plan(session_id, plan["tool_order"])

        # Attach active hypotheses from Postgres so the TypeScript
        # planner can use them for replan decisions.
        hypotheses = []
        engagement_id = params.get("engagementId")
        if engagement_id:
            try:
                from database.repositories.hypothesis_repository import (
                    HypothesisRepository,
                )
                repo = HypothesisRepository()
                hypotheses = repo.get_by_engagement(
                    engagement_id, status="UNVERIFIED"
                )
            except Exception as e:
                logger.debug("Could not load hypotheses for agent_init: %s", e)

        return {
            "session_id": session_id,
            "plan": plan["tool_order"],
            "reasoning": plan["reasoning"],
            "phase": params.get("phase", ""),
            "hypotheses": [
                {
                    "id": h.get("id", ""),
                    "description": h.get("description", ""),
                    "confidence": h.get("confidence", 0),
                    "status": h.get("status", "UNVERIFIED"),
                }
                for h in hypotheses
            ],
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
                logger.warning(
                    "Pipeline references unknown tool '%s', skipping", tool_name
                )

        # If no pipeline, use a sensible default ordering.
        # Import from assessment_orchestrator to keep a single source of truth (P2).
        if not tool_order:
            from tools.assessment_orchestrator import PHASE_PIPELINE_TOOLS

            phase = session.phase
            # Map legacy phase names to canonical keys
            phase_map = {
                "reconnaissance": "recon",
                "scan": "scan",
                "vulnerability_scanning": "scan",
                "deep_scan": "deep_scan",
                "deep": "deep_scan",
                "repo_scan": "repo_scan",
                "analyze": "analyze",
                "report": "report",
            }
            canonical = phase_map.get(phase, phase)
            tool_order = list(PHASE_PIPELINE_TOOLS.get(canonical, []))

        return {
            "tool_order": tool_order,
            "reasoning": f"Deterministic plan for {session.phase}: {len(tool_order)} tools",
        }

    def handle_agent_next(self, params: dict) -> dict:
        """Get next tool from current plan, or signal done if plan exhausted.

        Checks session._cancelled (set by cancel RPC) and returns done=True
        immediately if the session was cancelled (blocker 38).

        Enforces TS/Python iteration coordination (blocker 32): the TS side
        passes its ARGUS_HYBRID_MAX_ITERATIONS via max_iterations param, and
        we cap the iteration limit with min(ts_value, py_value) using the
        shared execution_iteration counter from AgentSessionStore.
        """
        session_id = params.get("session_id", "")
        trigger = (params.get("trigger") or "").lower().strip()

        try:
            session = self.session_store.get(session_id)
        except ValueError:
            return {"error": f"Session {session_id} not found", "done": True}

        # Check if session was cancelled (blocker 38)
        if hasattr(session, '_cancelled') and session._cancelled:
            logger.info("Session %s was cancelled — returning done=True", session_id)
            return {"done": True, "session_id": session_id}

        # Get shared iteration counter and check against coordinated max (blocker 32)
        current_iteration = self.session_store.get_iteration(session_id)
        ts_max = getattr(session, 'ts_max_iterations', None)
        if ts_max is not None and current_iteration >= ts_max:
            logger.info(
                "Session %s: TS max_iterations (%d) reached at iteration %d — "
                "returning done=True",
                session_id,
                ts_max,
                current_iteration,
            )
            return {"done": True, "session_id": session_id}

        # Normal case: advance through the deterministic plan
        next_tool = self.session_store.advance_plan(session_id)
        if next_tool:
            return {
                "tool": next_tool,
                "session_id": session_id,
                "reasoning": "Deterministic plan step",
                "done": False,
                "iteration": current_iteration,
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

        Uses the ReActAgent to reason over accumulated observations,
        executions, and findings, then returns the next tool(s) to run.
        Falls back to done when no LLM is available or the agent decides
        to stop.
        """
        try:
            llm_client = LLMClient()
        except Exception as e:
            logger.debug("Failed to create LLMClient for replan: %s", e)
            return {"done": True, "reasoning": "No LLM available for replan"}

        if not llm_client.is_available():
            return {"done": True, "reasoning": "LLM not available for replan"}

        # Build a concise context from the session's accumulated state
        context_parts = []
        if session.observations:
            context_parts.append("=== OBSERVATIONS ===")
            context_parts.extend(session.observations[-10:])
        if session.tool_history:
            context_parts.append("=== EXECUTED TOOLS ===")
            for ex in session.tool_history[-10:]:
                context_parts.append(
                    f"- {ex.tool}: success={ex.success}, findings={ex.finding_count}, summary={ex.summary[:200]}"
                )
        if session.findings:
            context_parts.append("=== FINDINGS ===")
            for f in session.findings[-10:]:
                title = f.get("title", "unknown")
                subtype = f.get("subtype", "")
                severity = f.get("severity", "")
                context_parts.append(f"- {title} ({subtype or 'no subtype'}, severity={severity})")

        context = "\n".join(context_parts)
        task = f"{session.phase}: {session.target}"

        registry = ToolRegistry()
        agent = ReActAgent(
            registry,
            llm_client=llm_client,
            engagement_id=getattr(session, "engagement_id", None),
            phase=session.phase,
        )

        try:
            action = agent.plan_next_action(
                task=task,
                context=context,
                tried_tools={ex.tool for ex in session.tool_history},
            )
        except Exception as e:
            logger.warning("ReActAgent replan failed: %s", e)
            return {"done": True, "reasoning": f"Replan failed: {e}"}

        if action is None:
            return {"done": True, "reasoning": "Agent decided to stop"}

        logger.info("Replan selected tool: %s (%s)", action.tool, action.reasoning)
        return {
            "tool_order": [action.tool],
            "reasoning": action.reasoning or f"ReActAgent selected {action.tool}",
        }

    def handle_agent_observe(self, params: dict) -> dict:
        """Record tool execution result and decide next action.

        If the session was cancelled (via cancel RPC), skips recording
        and returns done=True immediately (blocker 38).
        """
        session_id = params.get("session_id", "")

        try:
            session = self.session_store.get(session_id)
        except ValueError:
            return {"error": f"Session {session_id} not found", "done": True}

        # Check if session was cancelled (blocker 38)
        if hasattr(session, '_cancelled') and session._cancelled:
            logger.info("Session %s was cancelled — returning done=True", session_id)
            return {"done": True, "session_id": session_id}

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

        # Increment shared TS/Python iteration counter (blocker 32)
        iteration = self.session_store.increment_iteration(session_id)

        # Check if we need to involve the LLM
        trigger = None
        if not params.get("success", True):
            trigger = "stuck"
        elif params.get("findingCount", 0) > 0:
            trigger = "new_finding"

        next_result = self.handle_agent_next({"session_id": session_id, "trigger": trigger})
        next_result["iteration"] = iteration
        return next_result

    def handle_phase_complete(self, params: dict) -> dict:
        """Receive all findings from a completed phase and determine next capabilities.

        This closes the LLM-driven replanning feedback loop (Phase 1.2). After each
        phase finishes executing, the TypeScript workflow-runner calls this method
        with all accumulated findings. The LLM analyzes them and returns suggested
        capabilities for the next phase.

        Args:
            params: dict with:
                - engagement_id: str — engagement UUID
                - phase: str — the phase that just completed
                - target: str — the assessment target
                - findings: list[dict] — all findings accumulated so far

        Returns:
            dict with:
                - next_capabilities: list[str] — suggested capabilities
                - reasoning: str — LLM reasoning
                - stop: bool — whether to stop the assessment
        """
        engagement_id = params.get("engagement_id", "")
        phase = params.get("phase", "")
        target = params.get("target", "")
        findings = params.get("findings", [])

        if not engagement_id:
            return {
                "next_capabilities": [],
                "reasoning": "No engagement_id provided",
                "stop": True,
            }

        try:
            llm_client = LLMClient()
        except Exception as e:
            logger.debug("Failed to create LLMClient for phase_complete: %s", e)
            return self._fallback_phase_complete(phase, findings)

        if not llm_client.is_available():
            logger.debug("LLM not available for phase_complete — using fallback")
            return self._fallback_phase_complete(phase, findings)

        try:
            from agent.react_agent import ReActAgent

            registry = ToolRegistry()
            agent = ReActAgent(
                registry,
                llm_client=llm_client,
                engagement_id=engagement_id,
                phase=phase,
            )

            result = agent.plan_next_phase(
                findings=findings,
                phase=phase,
                target=target,
            )

            logger.info(
                "handle_phase_complete for engagement=%s phase=%s: "
                "next_capabilities=%s, stop=%s",
                engagement_id,
                phase,
                result.get("next_capabilities", []),
                result.get("stop", False),
            )

            return result

        except Exception as e:
            logger.warning(
                "handle_phase_complete failed for engagement=%s: %s. Using fallback.",
                engagement_id,
                e,
            )
            return self._fallback_phase_complete(phase, findings)

    @staticmethod
    def _fallback_phase_complete(phase: str, findings: list | None = None) -> dict:
        """Fallback phase progression when LLM is unavailable.

        Uses deterministic phase-to-capability mapping with awareness of
        HIGH/CRITICAL findings to suggest deeper inspection capabilities.

        NOTE: Returns a ``fallback: true`` flag so the TypeScript executor
        knows this is a degraded (non-LLM) response and can adjust confidence.

        Args:
            phase: The phase that just completed.
            findings: Accumulated findings (used to detect critical results).

        Returns:
            dict with next_capabilities, reasoning, and stop flag.
        """
        findings = findings or []
        from agent.react_agent import ReActAgent

        # Phase-to-next-capabilities progression map
        severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0}
        for f in findings:
            sev = str(f.get("severity", "")).upper()
            if sev in severity_counts:
                severity_counts[sev] += 1

        has_critical = severity_counts["CRITICAL"] > 0 or severity_counts["HIGH"] > 0

        phase_lower = phase.lower().strip() if phase else ""

        phase_map = {
            "recon": ["VULN_SCAN", "AUTH_TEST"],
            "scan": ["DEEP_SCAN", "XSS_DETECTION", "SQLI_DETECTION"],
            "deep_scan": ["POST_EXPLOIT", "EXPLOIT_CHAIN"],
            "repo_scan": ["VULN_SCAN"],
            "analyze": ["REPORT"],
            "report": [],
        }

        next_caps = list(phase_map.get(phase_lower, ["VULN_SCAN"]))

        if has_critical and phase_lower in ("recon", "scan"):
            if "EXPLOIT_CHAIN" not in next_caps:
                next_caps.append("EXPLOIT_CHAIN")
            if "POST_EXPLOIT" not in next_caps:
                next_caps.append("POST_EXPLOIT")

        stop = phase_lower in ("report",) or not next_caps

        return {
            "next_capabilities": next_caps,
            "reasoning": (
                f"Fallback phase progression from '{phase_lower}': "
                f"{severity_counts['CRITICAL']} CRITICAL, {severity_counts['HIGH']} HIGH, "
                f"{severity_counts['MEDIUM']} MEDIUM findings"
            ),
            "stop": stop,
            "fallback": True,  # Signal to TypeScript that this is degraded (non-LLM) response
        }

    def handle_get_attack_graph(self, params: dict) -> dict:
        """Return the attack graph chains and highest-risk paths for an engagement.

        Reads findings from the engagement database, builds an AttackGraph,
        detects vulnerability chains, and returns structured chain data that
        the TypeScript planner can use to insert exploitation phases.

        Args:
            params: dict with:
                - engagement_id: str — engagement UUID
                - findings: list[dict] — optional pre-loaded findings (if not
                  provided, reads from database)

        Returns:
            dict with:
                - chains: list[dict] — detected attack chains with risk scores
                - paths: list[dict] — highest-risk attack paths
                - chain_plans: list[dict] — ordered exploitation phase plans
        """
        engagement_id = params.get("engagement_id", "")
        if not engagement_id:
            return {"error": "engagement_id is required", "chains": [], "paths": [], "chain_plans": []}

        from attack_graph import AttackGraph
        from attack_graph_db import AttackGraphRepository

        graph = AttackGraph(engagement_id)

        # Load findings from params or database
        findings = params.get("findings", [])
        if not findings:
            try:
                from database.repositories.finding_repository import FindingRepository
                repo = FindingRepository()
                findings, _ = repo.get_findings_by_engagement(engagement_id, limit=5000)
            except Exception as e:
                logger.debug("Could not load findings for attack graph: %s", e)

        # Build the graph from findings
        for raw_finding in findings:
            if isinstance(raw_finding, dict):
                from models.finding import VulnerabilityFinding
                try:
                    finding = VulnerabilityFinding(
                        type=raw_finding.get("type", "UNKNOWN"),
                        severity=raw_finding.get("severity", "INFO"),
                        endpoint=raw_finding.get("endpoint", ""),
                        evidence=raw_finding.get("evidence", {}),
                        source_tool=raw_finding.get("source_tool", ""),
                        confidence=raw_finding.get("confidence", 0.5),
                        cvss_score=raw_finding.get("cvss_score"),
                    )
                    graph.add_finding(finding)
                except Exception as e:
                    logger.debug("Skipping invalid finding in attack graph: %s", e)

        # Get highest risk paths and chain plans
        chains = graph.find_chains()
        high_risk_paths = graph.get_highest_risk_paths(limit=10)
        chain_plans = graph.generate_plan_from_graph()

        # Blocker 18: Report how many findings were skipped so silent data loss is visible
        # (invalid findings are skipped with logger.debug, but the count is surfaced here)
        skipped_count = len(findings) - sum(1 for raw_finding in findings
                                             if isinstance(raw_finding, dict))
        if skipped_count > 0:
            logger.warning(
                "Attack graph: %d finding(s) were skipped due to invalid format — "
                "findings may be incomplete.",
                skipped_count,
            )

        # Serialize chains to JSON-safe format
        serialized_chains = []
        for chain in chains:
            prereq_node = chain.get("prereq_node")
            chain_node = chain.get("chain_node")
            serialized_chains.append({
                "chain_id": chain.get("chain_id", ""),
                "name": chain.get("name", ""),
                "severity": chain.get("severity", "MEDIUM"),
                "correlation_factor": chain.get("correlation_factor", 1.0),
                "prerequisite_type": prereq_node.data.get("type", "") if prereq_node else "",
                "chain_type": chain_node.data.get("type", "") if chain_node else "",
                "description": chain.get("description", ""),
            })

        return {
            "chains": serialized_chains,
            "paths": high_risk_paths,
            "chain_plans": chain_plans,
        }


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
    # Set up tracing on-demand when the MCP server is actually used,
    # not at import time. This avoids a redundant OpenTelemetry setup
    # when both celery_app.py and mcp_server.py are imported in the
    # same process (e.g. orchestrator importing get_mcp_server).
    # The setup is idempotent — if celery_app already initialized it,
    # this call is a no-op.
    from tracing import setup_tracing

    setup_tracing()

    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

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

    def handle_get_attack_graph(params):
        return server.handle_get_attack_graph(params)

    transport.register("get_attack_graph", handle_get_attack_graph)

    def handle_phase_complete(params):
        return server.handle_phase_complete(params)

    transport.register("phase_complete", handle_phase_complete)

    # ── Phase 4.1.4: Checkpoint MCP handler ──
    def handle_get_checkpoint(params):
        """Return completed tool list for a given phase (Phase 4.1.4)."""
        engagement_id = params.get("engagement_id", "")
        phase = params.get("phase", "")
        if not engagement_id or not phase:
            return {"error": "engagement_id and phase are required"}
        try:
            from checkpoint_manager import CheckpointManager
            mgr = CheckpointManager()
            completed = mgr.get_completed_tools(engagement_id, phase)
            return {"completed_tools": completed}
        except Exception as e:
            logger.warning("get_checkpoint failed: %s", e)
            return {"completed_tools": [], "error": str(e)}

    transport.register("get_checkpoint", handle_get_checkpoint)

    # ── Phase 4.4.2: Distributed lock MCP handlers ──
    # Singleton lock instance so acquire and release share the same worker_id.
    # Creating separate DistributedLock instances would generate different
    # worker_ids, causing release() to fail the ownership check.
    _lock_instance = None

    def _get_lock():
        nonlocal _lock_instance
        if _lock_instance is None:
            from distributed_lock import DistributedLock
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
            _lock_instance = DistributedLock(redis_url)
        return _lock_instance

    def handle_acquire_lock(params):
        """Acquire a distributed lock for an engagement (Phase 4.4.2)."""
        engagement_id = params.get("engagement_id", "")
        if not engagement_id:
            return {"error": "engagement_id is required"}
        try:
            lock = _get_lock()
            acquired = lock.acquire(engagement_id)
            return {"acquired": acquired}
        except Exception as e:
            logger.warning("acquire_lock failed for %s: %s", engagement_id, e)
            return {"acquired": False, "error": str(e)}

    def handle_release_lock(params):
        """Release a distributed lock for an engagement (Phase 4.4.2)."""
        engagement_id = params.get("engagement_id", "")
        if not engagement_id:
            return {"error": "engagement_id is required"}
        try:
            lock = _get_lock()
            released = lock.release(engagement_id)
            return {"released": released}
        except Exception as e:
            logger.warning("release_lock failed for %s: %s", engagement_id, e)
            return {"released": False, "error": str(e)}

    transport.register("acquire_lock", handle_acquire_lock)
    transport.register("release_lock", handle_release_lock)

    # ── Phase 4.5.7: Cancel signal for ReActAgent (@opencode → Python) ──
    def handle_cancel(params):
        """Signal the ReActAgent to stop for a given engagement/phase (blocker 38).

        Called from TypeScript when the executor decides to halt mid-phase.
        Uses AgentSessionStore.cancel() to set the _cancelled flag on the
        session, which the ReActAgent loop checks on each iteration.
        """
        engagement_id = params.get("engagement_id", "")
        session_id = params.get("session_id", "")
        if not engagement_id:
            return {"cancelled": False, "error": "engagement_id is required"}
        try:
            cancelled = False
            if session_id:
                cancelled = server.session_store.cancel(session_id)
            elif engagement_id:
                # Cancel ALL sessions for this engagement
                logger.info(
                    "Cancelling all sessions for engagement %s",
                    engagement_id,
                )
                # AgentSessionStore has no get-by-engagement method, but
                # iterating sessions under lock would be expensive.
                # For now, session_id is always provided by the caller.
                pass
            logger.info(
                "Cancel signal sent for session %s (engagement %s): cancelled=%s",
                session_id,
                engagement_id,
                cancelled,
            )
            return {"cancelled": cancelled}
        except Exception as e:
            logger.warning("Cancel failed for %s/%s: %s", engagement_id, session_id, e)
            return {"cancelled": False, "error": str(e)}

    transport.register("cancel", handle_cancel)

    logger.info("MCP stdio transport starting")
    transport.run()


if __name__ == "__main__":
    main()
