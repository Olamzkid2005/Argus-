"""
MCP Protocol Server - Wraps tool execution with discoverable schemas
Implements Model Context Protocol for standardized tool calling
"""

import hashlib
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import sysconfig
import threading
import time
from pathlib import Path
from typing import Any

# Load Argus's own worker configuration (LLM_MODEL / LLM_API_KEY / DATABASE_URL)
# from argus-workers/.env. Without this the worker only saw whatever the parent
# shell exported, so it fell back to an ambient provider key — or to no key at
# all. Ambient provider keys are additionally ignored by policy
# (config/llm_env.py); an explicitly exported variable still wins because
# load_dotenv() does not override existing values.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:  # python-dotenv is optional at runtime
    pass

from agent.react_agent import ReActAgent
from agent.session_store import AgentSessionStore, ToolExecution
from agent.tool_registry import ToolRegistry
from cache import CacheMode, WorkerCache
from config.llm_env import InvalidWorkerLlmConfig, set_worker_llm_config
from llm_client import LLMClient
from tool_core.parser import dispatch, has_parser
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

#: A URL with an explicit scheme (``http://``, ``https://``, ``ftp://``, ...).
#: Only scheme-bearing URLs are rejected for ``target_kind == "path"``: bare
#: host-shaped values ARE valid path-kind targets for some tools (govulncheck
#: takes Go module paths, trivy takes ``registry.example.com/image:tag``), so
#: those must stay allowed.
_URL_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


def _target_kind_violation(tool: "ToolDefinition", arguments: dict | None) -> str | None:
    """Return a refusal message when ``target`` contradicts the definition.

    ``target_kind`` is part of the tool definition so the guard lives in one
    place instead of being patched into each path-only parser or caller. A
    ``path`` tool that receives a URL is rejected before any subprocess runs;
    ``url``/``host`` tools are only advisory today because their CLIs accept
    bare hosts as well as full URLs.
    """
    kind = getattr(tool, "target_kind", "any") or "any"
    if kind != "path":
        return None
    raw = (arguments or {}).get("target")
    if not isinstance(raw, str) or not _URL_SCHEME_RE.match(raw):
        return None
    return (
        f"Tool '{tool.name}' scans filesystem paths (target_kind=path); "
        f"it cannot be handed the URL '{raw}'. Pass a local path instead."
    )


def _augmented_tool_path() -> str:
    """PATH used for BOTH tool discovery and tool execution.

    ``~/go/bin`` comes first on purpose. The venv ships Python console scripts
    whose names collide with the ProjectDiscovery binaries — ``venv/bin/httpx``
    is the *Python* HTTPX CLI — so with the venv first, a call to ``httpx``
    executed the Python CLI and failed with ``Usage: httpx [OPTIONS] URL /
    Error: No such option: -s`` while the availability check (which looked in
    ``~/go/bin``) reported the tool as present. Discovery and execution now
    share this helper so they cannot disagree; ``ARGUS_EXTRA_PATH`` is honored
    by both (previously it was only consulted for discovery).
    """
    _go_bin = os.path.expanduser("~/go/bin")
    _venv_bin = str(Path(sys.executable).parent)
    _homebrew_bin = "/opt/homebrew/bin"
    _project_venv = str(Path(__file__).resolve().parent.parent / "venv" / "bin")
    _pip_scripts = sysconfig.get_path("scripts")
    parts = [
        _go_bin,
        _venv_bin,
        _homebrew_bin,
        _project_venv,
        _pip_scripts,
        "/snap/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        os.environ.get("ARGUS_EXTRA_PATH", ""),
        os.environ.get("PATH", ""),
    ]
    return os.pathsep.join(part for part in parts if part)


def _param_is_true(value: Any) -> bool:
    """Interpret a boolean tool parameter from MCP arguments.

    Callers pass booleans as real bools, but JSON round-trips can turn them
    into strings; treat the usual spellings as true and everything else as
    false rather than relying on Python truthiness of the string "false".
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


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
        name, description, capabilities, signal_quality, requires, priority, cost,
        risk_level
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
        risk_level     — risk tier (low, medium, high, critical) for tool execution
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
        risk_level: str | None = None,
        target_kind: str = "any",
        phases: list[str] = None,
        pipeline_step: bool = False,
        disabled_reason: str | None = None,
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
        self.risk_level = risk_level
        #: What kind of value ``target`` is: "any" | "url" | "host" | "path".
        #: Enforced before execution: a "path" tool handed a URL is rejected
        #: (gitleaks/semgrep received one and failed with "stat http://...: no
        #: such file or directory").
        self.target_kind = target_kind or "any"
        #: Phases the declarative registry (tool_definitions.TOOLS) assigns this
        #: tool. ``[]`` means "not runnable in any phase" — see disabled_reason.
        self.phases = phases
        #: True when this entry names an in-process pipeline step rather than an
        #: executable (see tool_definitions.is_pipeline_step).
        self.pipeline_step = pipeline_step
        #: Set when the worker cannot currently run this tool, with the reason.
        #: Published over MCP so the TypeScript planner stops scheduling it:
        #: phase selection happens TS-side, so a worker-side `phases=[]` had no
        #: effect and dnsx/gospider were dispatched and failed on usage errors.
        self.disabled_reason = disabled_reason

    @property
    def disabled(self) -> bool:
        """True when the worker cannot run this tool at all right now."""
        return bool(self.disabled_reason)

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
            "risk_level": self.risk_level,
            "target_kind": self.target_kind,
            # Execution truth the TS planner needs before it schedules a tool.
            # `disabled` is always present (never stripped) so a consumer can
            # tell "worker says runnable" from "worker said nothing" — the
            # latter only happens against an older worker build.
            "disabled": self.disabled,
            "pipeline_step": self.pipeline_step,
        }
        if self.disabled_reason:
            result["disabled_reason"] = self.disabled_reason
        if self.phases:
            result["phases"] = self.phases
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


# MCP tool result cache (5-minute default TTL)
_mcp_cache = WorkerCache(ttl=300)


def _mcp_cache_key(
    name: str,
    arguments: dict | None,
    tool: "ToolDefinition | None" = None,
) -> str:
    """Build a deterministic cache key from tool name, arguments and definition.

    The tool's command, static args and parameter flags are folded into the key
    so that editing a definition (for example adding a missing ``flag``)
    invalidates entries produced by the previous definition instead of replaying
    a stale result for up to the cache TTL.
    """
    definition = ""
    if tool is not None:
        definition = repr(
            (
                tool.command,
                tuple(tool.args or ()),
                tuple(
                    (param.name, getattr(param, "flag", None))
                    for param in (tool.parameters or ())
                ),
            )
        )
    key_data = (
        f"mcp:{name}:{definition}:{json.dumps(arguments or {}, sort_keys=True)}"
    )
    return hashlib.sha256(key_data.encode()).hexdigest()[:16]


# Legacy TS-side phase names → canonical ReActAgent phase keys.
_PHASE_NAME_MAP = {
    "reconnaissance": "recon",
    "scan": "scan",
    "vulnerability_scanning": "scan",
    "deep_scan": "deep_scan",
    "deep": "deep_scan",
    "repo_scan": "repo_scan",
    "analyze": "analyze",
    "report": "report",
}


def _canonical_phase_name(phase: str) -> str:
    """Normalize a (possibly legacy) phase name to its canonical key."""
    return _PHASE_NAME_MAP.get(phase, phase)


class _PlanningOnlyToolRunner:
    """Stand-in ToolRunner used by MCP replanning.

    Replanning only SELECTS the next tool — execution is handled by the TS
    executor via handle_execute. This runner lets ReActAgent.create_for_phase
    register the phase's real tool definitions (so the LLM branch of
    plan_next_action has valid tools to choose from) without executing
    anything.
    """

    def run(self, tool_name: str, args: list | None = None, timeout: int = 300):
        from agent import AgentResult

        return AgentResult(
            tool=tool_name,
            success=False,
            error="planning-only registration — execution handled by executor",
        )


#: Cap on how many tools the LLM chooses per phase when the MCP path builds a
#: plan. Each choice is one LLM call (seconds to tens of seconds on free tiers),
#: and the deterministic order covers whatever the cap leaves out.
_MAX_PLANNED_TOOLS = int(os.getenv("ARGUS_MAX_PLANNED_TOOLS", "6"))

#: Wall-clock cap on plan generation. `agent_init` is blocked on this work and
#: the engine may spend one LLM call per planned tool, so the loop stops asking
#: once the budget is spent and labels the rest of the phase deterministic. A
#: provider slow enough to exhaust it still gets the phase run with a recorded
#: partial plan, instead of the driver's RPC timing out. Zero disables the cap.
_PLAN_BUDGET_SECONDS = float(os.getenv("ARGUS_PLAN_BUDGET_SECONDS", "90"))


def _planning_noop(**_kwargs) -> dict:
    """Stand-in callable for a tool registered for selection only.

    The MCP path selects tools; the driver executes them. Registration exists so
    an LLM choice passes the registry check in `_call_llm_for_action`, which
    rejects any tool the registry does not know.
    """
    return {}


def _agent_decision_repo():
    """An `AgentDecisionRepository` when a database is configured, else None.

    `agent_decisions` is the audit log for tool selection, so it pays to write
    whenever DATABASE_URL is available — for the worker that is the normal case,
    since `argus-workers/.env` provides it. Constructing the repository does not
    open a connection; `log_decision` does that per row and swallows its own
    failures.
    """
    if not os.getenv("DATABASE_URL"):
        return None
    try:
        from database.repositories.agent_decision_repository import (
            AgentDecisionRepository,
        )

        return AgentDecisionRepository()
    except Exception as exc:  # pragma: no cover - depends on deployment
        logger.debug("Agent decision logging unavailable: %s", exc)
        return None


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
                issues_str = "\n  ".join(credential_issues)
                raise RuntimeError(
                    f"STARTUP GUARD: ARGUS_AUTONOMOUS=1 detected {len(credential_issues)} credential issue(s):\n"
                    f"  {issues_str}\n"
                    "Placeholder credentials are not allowed in autonomous mode. "
                    "Set valid API keys in your environment or .env file."
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
        # An explicit tools_dir selects an isolated registry (tests, alternate
        # definition sets). Only the default deployment path overlays the
        # declarative worker registry.
        if tools_dir is None:
            self._apply_declarative_registry()
        self._check_critical_tools()
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

        # ── Startup preflight is intentionally NOT run here ──
        # The preflight check (log_startup_preflight) is redundant with the
        # background health check thread started in main() via log_startup_health().
        # Running it synchronously here would block transport startup by ~8-12s
        # on systems where shutil.which() is slow (Windows) or DNS takes time.
        # The background health check in log_startup_health() handles preflight,
        # Celery ping, and LLM checks asynchronously.

    # Critical tools that must be available for full functionality.
    # Used by _check_critical_tools() to warn or enforce at startup.
    CRITICAL_TOOLS: frozenset = frozenset({
        "nuclei",
        "nmap",
        "sqlmap",
        "subfinder",
        "httpx",
        "whatweb",
    })

    def _binary_on_path(self, name: str) -> str | None:
        """Check if a binary is available on the augmented PATH (cached).

        Positive lookups are cached for the process lifetime. Negative lookups
        (binary not found) are cached for ``_BINARY_CACHE_MISS_TTL_SECS`` and
        re-checked afterwards, so a tool installed while the server is running
        (or a fixed PATH) is discovered without a restart.

        The augmented PATH is built by ``_augmented_tool_path()`` and is the
        same PATH tool execution receives.
        """
        _cache = self.__class__._binary_cache
        _now = time.monotonic()
        _cached = _cache.get(name)
        if _cached is not None:
            _path, _checked_at = _cached
            if _path is not None or (_now - _checked_at) < self._BINARY_CACHE_MISS_TTL_SECS:
                return _path
        _augmented_path = _augmented_tool_path()
        _found = shutil.which(name, path=_augmented_path)
        _cache[name] = (_found, time.monotonic())
        return _found

    def _check_critical_tools(self) -> None:
        """Check critical tools are available after YAML loading.

        Logs a consolidated warning listing all missing critical tools.
        If ``ARGUS_ENFORCE_TOOLS`` env var is set to "1" or "true",
        raises ``RuntimeError`` instead of just warning.

        Critical tools are defined in ``CRITICAL_TOOLS``.
        """
        # Check actual binary availability on PATH (not just registry)
        missing = [
            name for name in self.CRITICAL_TOOLS
            if not self._binary_on_path(name)
        ]
        if not missing:
            logger.info(
                "All %d critical tool(s) are available",
                len(self.CRITICAL_TOOLS),
            )
            return

        _enforce = os.environ.get("ARGUS_ENFORCE_TOOLS", "").lower() in ("1", "true")
        _msg = (
            f"{len(missing)} of {len(self.CRITICAL_TOOLS)} critical tool(s) missing:\n"
            f"  Missing: {', '.join(missing)}\n"
            f"  Available: {', '.join(sorted(self.CRITICAL_TOOLS - set(missing)))}\n"
            "Install the missing tools or add their directories to PATH. "
            "Set ARGUS_EXTRA_PATH for non-standard install locations.\n"
            "To enforce (abort on missing tools), set ARGUS_ENFORCE_TOOLS=1."
        )
        if _enforce:
            raise RuntimeError(f"ARGUS_ENFORCE_TOOLS=1: {_msg}")
        logger.warning("STARTUP GUARD: %s", _msg)

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
            os.path.normpath(
                os.path.join(
                    project_dir,
                    "argus-workers",
                    "tools",
                    "scripts",
                    "run_finding_verifier.py",
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

                # NOTE: Binary existence check is deferred to execution time
                # (in call_tool) to keep startup fast. shutil.which() is extremely
                # slow on Windows (~100ms per call). Skipping it here means all
                # YAML-defined tools are registered regardless of whether their
                # binary is on PATH. If a tool's binary is missing when call_tool
                # is invoked, a clear error message is returned.

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
                    risk_level=data.get("risk_level"),
                )
                self.register_tool(tool)
                logger.info("Loaded tool definition: %s", tool.name)
            except Exception as e:
                logger.warning("Failed to load tool %s: %s", yaml_file, e)

    def _apply_declarative_registry(self) -> None:
        """Merge the declarative worker registry (``tool_definitions.TOOLS``).

        ``tools/definitions/*.yaml`` is the file-level source of truth for how a
        tool is *invoked*; ``tool_definitions.TOOLS`` is the source of truth for
        whether it is currently *runnable at all*. This server only ever read
        the YAML, so two classes of tool ended up in the planner's hands that
        the worker could not run:

        - Tools that exist only as inline entries in ``tool_definitions.py``
          (``post_exploitation``, ``credential_replay``, ``internal_probe``,
          ``attack-graph``, ``report-generator`` and friends) were absent from
          the MCP registry entirely, so calling one returned "Unknown tool".
        - Tools whose YAML says ``enabled: true`` but whose registry entry is
          ``phases=[]`` because their installed build does not work (``dnsx``
          needs a wordlist, ``gospider`` segfaults). The YAML cannot express
          this, so the planner kept scheduling them.

        YAML invocation metadata is never overwritten here; the overlay only
        adds missing names and stamps ``disabled_reason``/``pipeline_step``
        onto entries it knows cannot run. Phase selection happens in
        TypeScript, so this is the only channel that tells the planner.
        """
        try:
            from tool_definitions import TOOLS as _DECLARED_TOOLS
            from tool_definitions import is_pipeline_step
        except Exception as e:  # pragma: no cover - import machinery failure
            logger.debug("Declarative tool registry unavailable: %s", e)
            return

        missing = [name for name in _DECLARED_TOOLS if name not in self._tools]
        if missing:
            try:
                from tool_definitions import build_mcp_tool_definitions

                by_name = {t.name: t for t in build_mcp_tool_definitions()}
                for name in missing:
                    declared_def = by_name.get(name)
                    if declared_def is None:
                        continue
                    self.register_tool(declared_def)
                    logger.info("Registered declarative-only tool: %s", name)
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("Could not register declarative-only tools: %s", e)

        disabled: list[str] = []
        for name, declared in _DECLARED_TOOLS.items():
            tool = self._tools.get(name)
            if tool is None:
                continue
            # A YAML target_kind restriction must survive: `any` is the lenient
            # default and never widens a path/url/host-only tool.
            declared_kind = getattr(declared, "target_kind", "any")
            if declared_kind not in (None, "any"):
                tool.target_kind = declared_kind
            if declared.phases:
                tool.phases = list(declared.phases)
            missing_env = [
                var
                for var in getattr(declared, "required_env", ()) or ()
                if not os.environ.get(var)
            ]
            if missing_env:
                # The tool reads its credentials straight from the environment
                # (chaos, uncover, github-endpoints), so running it without the
                # key can only produce "PDCP_API_KEY not specified".
                tool.disabled_reason = (
                    f"requires environment variable(s) not set: "
                    f"{', '.join(missing_env)}"
                )
                disabled.append(name)
            elif is_pipeline_step(name):
                # In-process step: the orchestrator runs it, and no install can
                # make it a subprocess. Dispatching the name over MCP can only
                # fail (that is how `credential_replay` reached the run as
                # "Unknown tool").
                tool.pipeline_step = True
                tool.disabled_reason = (
                    "in-process pipeline step — run by the orchestrator, not "
                    "dispatchable as an MCP tool"
                )
                disabled.append(name)
            elif not declared.phases:
                tool.disabled_reason = (
                    "no execution phase in the worker registry "
                    "(tool_definitions.TOOLS)"
                )
                disabled.append(name)

        if disabled:
            logger.info(
                "%d tool(s) marked disabled for planner dispatch: %s",
                len(disabled),
                ", ".join(sorted(disabled)),
            )

    def register_tool(self, tool: ToolDefinition):
        """Register a tool definition.

        Re-registering an existing name preserves the execution-state fields set
        by ``_apply_declarative_registry()`` (``disabled_reason``,
        ``pipeline_step``, ``phases``). Callers such as ``MCPToolBridge``
        re-register from ``build_mcp_tool_definitions()``, which only carries
        invocation metadata — without this, a second registration of ``dnsx``
        would silently clear the "no execution phase" verdict and put the tool
        back in front of the planner.
        """
        existing = self._tools.get(tool.name)
        if existing is not None:
            if tool.disabled_reason is None:
                tool.disabled_reason = existing.disabled_reason
            if not tool.pipeline_step:
                tool.pipeline_step = existing.pipeline_step
            if tool.phases is None:
                tool.phases = existing.phases
        self._tools[tool.name] = tool
        self._execution_stats[tool.name] = {
            "calls": 0,
            "successes": 0,
            "failures": 0,
            "total_duration_ms": 0,
        }

    def get_tools(self) -> list[dict]:
        """Get all tool definitions (mcp.tools/list equivalent).

        Each entry carries the worker's *execution truth* alongside the
        static invocation metadata: ``disabled``/``disabled_reason`` (the
        declarative registry gives this tool no phase), ``pipeline_step``
        (in-process step, never runnable as a subprocess) and ``available``
        (its binary exists on the augmented PATH). The TypeScript planner is
        the component that picks phases and tools, so it can only avoid
        dispatching dead tools if the worker tells it which ones are dead.
        """
        tools: list[dict] = []
        for tool in self._tools.values():
            if not tool.enabled:
                continue
            entry = tool.to_dict()
            entry["available"] = self._tool_is_available(tool)
            tools.append(entry)
        return tools

    def _tool_is_available(self, tool: ToolDefinition) -> bool:
        """Whether *tool*'s binary is present on the execution PATH.

        Cheap enough to call from ``get_tools()``: positive results are cached
        for the process lifetime and negative results for
        ``_BINARY_CACHE_MISS_TTL_SECS``, so a 70-tool list does not turn into
        70 ``shutil.which`` calls on every poll.
        """
        binary = tool.binary or tool.command
        if not binary:
            # No command at all (agent-internal / pipeline step): nothing to
            # shell out to, so nothing can be missing.
            return True
        return self._binary_on_path(binary) is not None

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
    # Shared binary availability cache (class-level, shared across all instances)
    # Maps tool name -> (absolute_path_or_None, monotonic_check_time). Positive
    # hits live for the process lifetime; negative hits (None) are re-checked
    # after _BINARY_CACHE_MISS_TTL_SECS so tools installed mid-session are
    # picked up instead of being reported missing forever.
    _binary_cache: dict[str, tuple[str | None, float]] = {}
    _BINARY_CACHE_MISS_TTL_SECS = 60.0

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
                        router path. For direct subprocess calls,                        cache_mode controls whether tool results are cached.
                        "normal" -> read cache, write cache.
                        "no_cache" -> skip cache read AND write (fresh execution).
                        "refresh" -> skip cache read, still write (update cache).
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
        # The entry exists so the planner can see it and know not to schedule it
        # (see _apply_declarative_registry). Calling it anyway gets the reason
        # rather than a confusing "binary not found" for a name that is not a
        # binary at all.
        if tool.disabled_reason:
            return MCPToolResult(
                success=False,
                error=f"Tool '{name}' is not runnable: {tool.disabled_reason}",
                tool=name,
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

        # Reject a target whose kind contradicts the definition before any
        # subprocess runs (path-only tools must never receive a URL).
        _kind_error = _target_kind_violation(tool, arguments)
        if _kind_error:
            logger.warning("Target kind mismatch for tool '%s': %s", name, _kind_error)
            return MCPToolResult(
                success=False,
                error=_kind_error,
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
                # Boolean parameters are switches, not value options: emit the
                # flag on its own when the value is truthy and never pass the
                # bool through as an argument ("--deep-domxss True" is not
                # something any CLI accepts).
                if getattr(param, "type", None) == "boolean" or isinstance(
                    value, bool
                ):
                    if _param_is_true(value) and param.flag:
                        cmd.append(param.flag)
                    continue
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
                    # Tools that strictly expect bare hostnames/domains.
                    # NOTE: stripping also drops the port, which is harmless
                    # for the domain-discovery tools here but would take the
                    # service port away from a web scanner — nikto is therefore
                    # NOT in this set and receives the full URL (its -h accepts
                    # one and reports the right Target Port).
                    _HOSTNAME_TOOLS = frozenset(
                        {
                            "nmap",
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

        # Verify the tool binary exists on PATH before executing.
        # Binary existence is cached per tool so this check is fast after
        # the first call for each tool (and is a no-op for python3 tools
        # since they use the current interpreter).
        _tool_command = Path(tool.command).name.lower() if tool.command else ""
        if _tool_command != "python3" and not self._binary_on_path(tool.command):
            return MCPToolResult(
                success=False,
                error=(
                    f"Tool '{name}' binary '{tool.command}' not found on PATH. "
                    f"Install it or add its directory to PATH. "
                    f"Set ARGUS_EXTRA_PATH for custom install locations."
                ),
                tool=name,
                signal_quality=tool_signal_quality,
            ).to_dict()

        # Gap 4.4: Check cache before executing
        _cache_mode = (cache_mode or CacheMode.NORMAL.value)
        _cache_key = _mcp_cache_key(name, arguments, tool)
        if _cache_mode == CacheMode.NORMAL.value:
            _cached = _mcp_cache.get(_cache_key)
            if _cached is not None:
                logger.debug("MCP cache HIT for tool '%s'", name)
                # Zero out stale duration so consumers don't see old timestamps
                if "meta" in _cached and isinstance(_cached["meta"], dict):
                    _cached["meta"]["duration_ms"] = 0
                return _cached

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
            # Use the same augmented PATH as the availability check so the
            # binary that was found is the binary that runs (see
            # _augmented_tool_path).
            _env["PATH"] = _augmented_tool_path()
            _env["PYTHONDONTWRITEBYTECODE"] = "1"

            result = subprocess.run(  # noqa: S603 — safe: cmd is list form, validated by _validate_args_safe()
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout or tool.timeout,
                env=_env,
                # Never hand the worker's stdin to a scanner: tools like alterx
                # switch to stdin input mode when stdin is any pipe (even at
                # EOF) and then report "no input found" instead of using their
                # flags. The MCP path never feeds stdin deliberately, so
                # /dev/null is both deterministic and correct.
                stdin=subprocess.DEVNULL,
            )
            duration_ms = int((time.time() - start) * 1000)

            # Always dispatch findings parsing — even on non-zero exit if
            # the exit code indicates findings were found. This ensures
            # tools like semgrep, bandit, gitleaks produce structured findings
            # on the MCP path.
            output_to_parse = result.stdout
            if not output_to_parse and result.stderr:
                output_to_parse = result.stderr
            structured = dispatch(name, output_to_parse)

            # Determine success: exit code 0 = success. Some security tools
            # exit non-zero when they FIND vulnerabilities (semgrep, bandit,
            # gitleaks, trivy, etc.) — treat those as successes too, but only
            # when the tool's own parser can actually extract findings from the
            # output. A findings-bearing exit code with nothing to parse is the
            # signature of a CLI error ("unknown flag", bad path, ...), and
            # reporting it as success lets the error text be promoted into a
            # finding downstream.
            findings_exit = self.FINDINGS_EXIT_CODES.get(name, set())
            success = result.returncode == 0 or result.returncode in findings_exit
            if (
                success
                and result.returncode != 0
                and has_parser(name)
                and not dispatch(name, output_to_parse, allow_generic=False)
            ):
                success = False
                structured = []
                logger.info(
                    "Tool '%s' exited %d (findings code) but its parser produced no findings — reporting failure",
                    name,
                    result.returncode,
                )

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
            if structured and success:
                # ``getattr`` keeps a parser that returns plain dicts from
                # failing the whole tool run (see parser dispatcher).
                mcp_result.data["structured"] = [
                    getattr(f, "__dict__", f) for f in structured
                ]

            # Cache the result (NO_CACHE mode skips writes). Failures are never
            # cached: a transient or already-fixed failure must not be replayed
            # for the next 5 minutes in place of a real attempt.
            if _cache_mode != CacheMode.NO_CACHE.value and success:
                _mcp_cache.set(_cache_key, mcp_result.to_dict(), ttl=300)
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
        # Adopt the model the planner resolved from OpenCode's provider registry.
        # The planner is the only runtime that can see that registry, so its
        # choice is authoritative for the whole run: the worker's own .env is
        # only a fallback for runs started without a driver (CLI/celery).
        llm_block = params.get("llm")
        if llm_block is not None:
            try:
                adopted = set_worker_llm_config(llm_block)
            except InvalidWorkerLlmConfig as e:
                logger.error(
                    "Ignoring invalid agent_init.llm block, falling back to this "
                    "worker's own LLM configuration: %s",
                    e,
                )
            else:
                if adopted is not None:
                    logger.info(
                        "Adopted planner-resolved LLM config for this run: "
                        "provider_id=%s model=%s",
                        adopted.provider_id or adopted.source,
                        adopted.model,
                    )

        # The engagement id travels on the session: without it the agent cannot
        # load the persisted ReconContext (so the LLM branch of
        # plan_next_action never sees real recon) and cannot record decisions.
        session_id = self.session_store.create(
            target=params.get("target", ""),
            phase=params.get("phase", ""),
            tech_stack=params.get("techStack", []),
            engagement_id=params.get("engagementId"),
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

        # Ask the engine to choose this phase's tools, in order.
        #
        # This used to be a deterministic re-ordering of the driver's own
        # pipeline, so an `assess` run executed a plan nobody chose: the
        # selection prompt, the recon context and the decision log all existed,
        # but the LLM was never asked. `_agentic_plan` asks it and records each
        # choice; when it cannot (no LLM, no candidates, provider failure) the
        # deterministic order is used and labelled as such, so a fallback is
        # never dressed up as an engine decision.
        session = self.session_store.get(session_id)
        plan = self._agentic_plan(session, pipeline) or self._generate_plan(
            session_id, pipeline, context
        )
        sources = plan.get("sources") or ["deterministic"] * len(plan["tool_order"])
        engine_chosen = sum(1 for source in sources if source == "llm")
        self.session_store.set_plan(session_id, plan["tool_order"], sources=sources)
        self.session_store.set_plan_provenance(
            session_id, plan.get("source", "deterministic")
        )
        if engine_chosen:
            logger.info(
                "Session %s: engine chose %d of %d tool(s) for phase %s: %s",
                session_id,
                engine_chosen,
                len(plan["tool_order"]),
                session.phase,
                ", ".join(plan["tool_order"]),
            )
        else:
            logger.info(
                "Session %s: deterministic plan for phase %s (%d tool(s)) — %s",
                session_id,
                session.phase,
                len(plan["tool_order"]),
                plan.get("reasoning", "no LLM plan available"),
            )

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

    def _planning_registry(self, pipeline: list) -> ToolRegistry:
        """Registry holding this phase's candidate tools, for selection only.

        `_call_llm_for_action` rejects any tool the registry does not know, so
        the candidates have to be registered before the LLM is asked. They are
        the phase's pipeline steps: the set the driver is actually willing to
        run. Offering the whole tool catalogue would let the model pick a tool
        this phase cannot execute.
        """
        registry = ToolRegistry()
        for step in pipeline or []:
            name = step.get("tool") if isinstance(step, dict) else None
            if not name:
                continue
            tool = self._tools.get(name)
            if tool is None:
                logger.warning(
                    "Pipeline references unknown tool '%s', skipping", name
                )
                continue
            registry.register(
                name,
                _planning_noop,
                {
                    "name": name,
                    "description": tool.description or "",
                    "parameters": [
                        {
                            "name": param.name,
                            "type": param.type,
                            "description": param.description,
                            "required": param.required,
                        }
                        for param in (tool.parameters or [])
                    ],
                    "phases": list(tool.phases or []),
                },
            )
        return registry

    def _recon_context_for(self, session):
        """The recon context the agent reasons over, or a minimal stand-in.

        The persisted context is what lets the selection branch react to what
        recon actually found. A bare `ReconContext` keeps the branch engaged for
        phases that run before recon or without it.
        """
        engagement_id = getattr(session, "engagement_id", "") or ""
        if engagement_id:
            try:
                from tasks.utils import load_recon_context

                loaded = load_recon_context(engagement_id)
                if loaded is not None:
                    return loaded
            except Exception as exc:
                logger.debug(
                    "Could not load recon context for %s: %s", engagement_id, exc
                )
        if getattr(session, "target", None):
            from models.recon_context import ReconContext

            return ReconContext(target_url=session.target)
        return None

    def _agentic_plan(self, session, pipeline: list) -> dict | None:
        """Let the engine choose the phase's tools, in order; None if it cannot.

        One tool per LLM call, each recorded as a decision the moment it is
        chosen — with the tokens the call cost and the model's own reasoning.
        The loop stops as soon as the engine stops contributing, or once
        `_PLAN_BUDGET_SECONDS` is spent, so a partly agentic plan is never
        presented as a fully agentic one: the caller falls back to the
        deterministic order and labels it.
        """
        if not pipeline:
            return None

        try:
            llm_client = LLMClient()
        except Exception as exc:
            logger.debug("No LLM client for plan generation: %s", exc)
            return None
        if not llm_client.is_available():
            logger.info(
                "No LLM available for plan generation — using the pipeline order"
            )
            return None

        registry = self._planning_registry(pipeline)
        if not registry.list_tools():
            return None

        agent = ReActAgent(
            registry,
            llm_client=llm_client,
            decision_repo=_agent_decision_repo(),
            engagement_id=getattr(session, "engagement_id", "") or None,
            phase=_canonical_phase_name(session.phase),
        )
        recon_context = self._recon_context_for(session)
        task = f"{session.phase}: {session.target}"

        deadline = (
            time.monotonic() + _PLAN_BUDGET_SECONDS
            if _PLAN_BUDGET_SECONDS > 0
            else None
        )
        order: list[str] = []
        reasons: list[str] = []
        tried: set[str] = set()
        for _ in range(_MAX_PLANNED_TOOLS):
            if deadline is not None and time.monotonic() >= deadline:
                logger.info(
                    "Plan generation budget (%.0fs) spent after %d tool(s) — "
                    "running the rest of the phase deterministically",
                    _PLAN_BUDGET_SECONDS,
                    len(order),
                )
                break
            try:
                action = agent.plan_next_action(
                    task=task,
                    context="Choosing this phase's tools and the order to run them.",
                    tried_tools=set(tried),
                    recon_context=recon_context,
                )
            except Exception as exc:
                logger.warning("Plan generation failed: %s", exc)
                break
            if action is None or ReActAgent.is_fallback_action(action):
                break
            order.append(action.tool)
            if action.reasoning:
                reasons.append(action.reasoning)
            tried.add(action.tool)
            agent.record_decision(action, len(order) - 1)

        if not order:
            # The engine contributed nothing — let the caller use (and label)
            # the deterministic order.
            return None

        # The engine can stop early: the cap, a provider failure, or its own
        # answer that nothing more is needed. Keep the phase's coverage by
        # running the pipeline tools it did not reach, and label those steps
        # deterministic so a stop is visible rather than silently shrinking the
        # phase to the tools chosen so far.
        engine_chosen = len(order)
        remainder = [
            step.get("tool")
            for step in pipeline
            if isinstance(step, dict)
            and step.get("tool") in self._tools
            and step.get("tool") not in tried
        ]
        order.extend(remainder)

        return {
            "tool_order": order,
            "sources": ["llm"] * engine_chosen
            + ["deterministic"] * len(remainder),
            "reasoning": "; ".join(reasons)[:500]
            or f"Engine chose {engine_chosen} tool(s)",
            "source": "llm",
        }

    def _record_plan_step(
        self, session, tool_name: str, iteration: int, source: str
    ) -> None:
        """Record a deterministic plan step as a fallback decision.

        Steps the engine chose are recorded when it chose them. Steps from the
        deterministic order are recorded here as they are consumed, so the trail
        shows a labelled fallback instead of an unexplained gap.

        `source` is passed in rather than read off the session: callers hold a
        deep copy, so a plan set moments ago would not be visible on it.
        """
        if session is None or source == "llm":
            return
        engagement_id = getattr(session, "engagement_id", "") or ""
        repo = _agent_decision_repo()
        if repo is None or not engagement_id:
            return
        try:
            repo.log_decision(
                engagement_id=engagement_id,
                phase=_canonical_phase_name(session.phase),
                iteration=iteration,
                tool_selected=tool_name,
                arguments={"target": session.target},
                reasoning=f"Deterministic plan step for {session.phase}",
                was_fallback=True,
            )
        except Exception as exc:
            logger.warning("Failed to record plan step: %s", exc)

    def _generate_plan(self, session_id: str, pipeline: list, context: dict) -> dict:
        """Generate an ordered plan from the pipeline, deterministically.

        The fallback for when no engine choice is available: the driver's own
        pipeline order, marked `source="deterministic"` so the audit trail does
        not present it as an engine decision.
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

            canonical = _canonical_phase_name(session.phase)
            tool_order = list(PHASE_PIPELINE_TOOLS.get(canonical, []))

        return {
            "tool_order": tool_order,
            "sources": ["deterministic"] * len(tool_order),
            "reasoning": f"Deterministic plan for {session.phase}: {len(tool_order)} tools",
            "source": "deterministic",
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

        # The TS executor passes its ARGUS_HYBRID_MAX_ITERATIONS on every
        # agent_next call (blocker 32). Record it when present so the shared
        # iteration counter below can actually cap against it: the TS side does
        # not send this value to agent_init, so relying on agent_init alone left
        # ts_max_iterations unset and the coordinated cap dead.
        _max_iterations = params.get("max_iterations")
        if _max_iterations is not None:
            try:
                self.session_store.set_ts_max_iterations(session_id, _max_iterations)
                session = self.session_store.get(session_id)
            except Exception as e:
                logger.debug(
                    "Could not record TS max_iterations=%s for session %s: %s",
                    _max_iterations,
                    session_id,
                    e,
                )

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

        # Normal case: advance through the plan
        advanced = self.session_store.advance_plan_with_source(session_id)
        if advanced:
            next_tool, step_source = advanced
            self._record_plan_step(
                session, next_tool, current_iteration, step_source
            )
            reasoning = (
                "Engine-chosen plan step"
                if step_source == "llm"
                else "Deterministic plan step"
            )
            return {
                "tool": next_tool,
                "session_id": session_id,
                "reasoning": reasoning,
                "done": False,
                "iteration": current_iteration,
            }

        # Plan exhausted
        if trigger in ("stuck", "new_finding", "phase_complete"):
            # Re-plan based on accumulated observations
            new_plan = self._replan(session)
            if new_plan.get("done"):
                return {"done": True, "session_id": session_id}
            replan_source = new_plan.get("source", "llm")
            self.session_store.set_plan(
                session_id, new_plan["tool_order"], sources=[replan_source]
            )
            self.session_store.set_plan_provenance(session_id, replan_source)
            advanced = self.session_store.advance_plan_with_source(session_id)
            if advanced:
                next_tool, step_source = advanced
                self._record_plan_step(
                    session, next_tool, current_iteration, step_source
                )
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

        # Register the phase's tools so the LLM branch of plan_next_action has
        # valid tools to choose from: _call_llm_for_action lists tools via
        # registry.list_tools() and rejects anything not in the registry via
        # registry.get_tool(). A bare registry would force the deterministic
        # fallback every time even with an LLM available. The phase name is
        # normalized so legacy TS names (e.g. "vulnerability_scanning") map to
        # canonical keys and still register their tools.
        phase = _canonical_phase_name(session.phase)
        # A replan is also a tool selection, so it belongs in the same audit log
        # as the initial plan; without the repo attached the engine's choices
        # during replanning were invisible.
        decision_repo = _agent_decision_repo()
        engagement_id = getattr(session, "engagement_id", "") or None
        try:
            agent = ReActAgent.create_for_phase(
                phase=phase,
                tool_runner=_PlanningOnlyToolRunner(),
                llm_client=llm_client,
                engagement_id=engagement_id,
                decision_repo=decision_repo,
            )
        except Exception as e:
            logger.debug(
                "create_for_phase failed for replan (phase=%s): %s — using bare agent",
                phase,
                e,
            )
            registry = ToolRegistry()
            agent = ReActAgent(
                registry,
                llm_client=llm_client,
                engagement_id=engagement_id,
                decision_repo=decision_repo,
                phase=phase,
            )

        # The LLM branch of plan_next_action() is gated on recon_context —
        # without one the agent silently falls back to deterministic ordering
        # and the interactive replan loop never actually reasons over
        # observations. Load the persisted ReconContext when available;
        # otherwise build a minimal one from the session target so the LLM
        # branch still engages.
        recon_context = None
        _engagement_id = getattr(session, "engagement_id", None)
        if _engagement_id:
            try:
                from tasks.utils import load_recon_context

                recon_context = load_recon_context(_engagement_id)
            except Exception as e:
                logger.debug(
                    "Failed to load recon context for replan (engagement=%s): %s",
                    _engagement_id,
                    e,
                )
                recon_context = None
        if recon_context is None and getattr(session, "target", None):
            from models.recon_context import ReconContext

            recon_context = ReconContext(target_url=session.target)

        try:
            action = agent.plan_next_action(
                task=task,
                context=context,
                tried_tools={ex.tool for ex in session.tool_history},
                recon_context=recon_context,
            )
        except Exception as e:
            logger.warning("ReActAgent replan failed: %s", e)
            return {"done": True, "reasoning": f"Replan failed: {e}"}

        if action is None:
            return {"done": True, "reasoning": "Agent decided to stop"}

        logger.info("Replan selected tool: %s (%s)", action.tool, action.reasoning)
        agent.record_decision(action, getattr(session, "execution_iteration", 0) or 0)
        return {
            "tool_order": [action.tool],
            "reasoning": action.reasoning or f"ReActAgent selected {action.tool}",
            "source": "deterministic"
            if ReActAgent.is_fallback_action(action)
            else "llm",
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
            "source_analysis": ["VULN_SCAN"],
            "scan": ["DEEP_SCAN", "XSS_DETECTION", "SQLI_DETECTION"],
            "deep_scan": ["POST_EXPLOIT", "EXPLOIT_CHAIN"],
            "repo_scan": ["VULN_SCAN"],
            "analyze": ["REPORT"],
            "report": [],
        }

        next_caps = list(phase_map.get(phase_lower, ["VULN_SCAN"]))

        if has_critical and phase_lower in ("recon", "scan", "deep_scan", "analyze"):
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

    @staticmethod
    def _build_attack_graph(
        engagement_id: str,
        params_findings: list | None = None,
    ) -> tuple[Any, int, list]:
        """Build and populate an AttackGraph from findings.

        Shared helper used by both handle_get_attack_graph and
        handle_get_attack_graph_snapshot to avoid duplicate graph-building
        logic.

        Args:
            engagement_id: Engagement UUID
            params_findings: Optional pre-loaded findings from params.
                             If None or empty, reads from the database.

        Returns:
            tuple of (graph, skipped_count, raw_findings)
        """
        from attack_graph import AttackGraph

        graph = AttackGraph(engagement_id)
        findings = params_findings or []

        # Load from database if no findings provided
        if not findings:
            try:
                from database.repositories.finding_repository import FindingRepository
                repo = FindingRepository()
                findings, _ = repo.get_findings_by_engagement(engagement_id, limit=5000)
            except Exception as e:
                logger.debug("Could not load findings for attack graph: %s", e)

        # Build the graph from findings
        skipped_count = 0
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
                        repro_steps=None,
                        owasp_category=None,
                        cwe_id=None,
                        evidence_strength=None,
                        tool_agreement_level=None,
                        fp_likelihood=None,
                        discovered_at=None,
                        engagement_id=None,
                    )
                    graph.add_finding(finding)
                except Exception as e:
                    logger.debug("Skipping invalid finding in attack graph: %s", e)
                    skipped_count += 1
            else:
                skipped_count += 1

        return graph, skipped_count, findings

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

        from attack_composition import generate_plan_from_graph

        graph, skipped_count, findings = self._build_attack_graph(
            engagement_id,
            params.get("findings"),
        )

        # Get highest risk paths and chain plans
        chains = graph.find_chains()
        high_risk_paths = graph.get_highest_risk_paths(limit=10)
        chain_plans = generate_plan_from_graph(graph)

        # Blocker 18: Report how many findings were skipped so silent data loss is visible
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

        # get_highest_risk_paths() embeds raw Path objects under "path" —
        # not JSON-serializable. Drop the key (risk_score + nodes carry the
        # data the TS side consumes) so the strict transport serializer
        # doesn't reject the whole response with -32603.
        serialized_paths = [
            {
                "risk_score": p.get("risk_score"),
                "nodes": p.get("nodes", []),
            }
            for p in high_risk_paths
        ]

        return {
            "chains": serialized_chains,
            "paths": serialized_paths,
            "chain_plans": chain_plans,
        }

    def handle_get_attack_graph_snapshot(self, params: dict) -> dict:
        """Return the full attack graph snapshot for the frontend visualizer.

        Builds an AttackGraph from engagement findings, computes risk scores
        and chain metadata, and returns the complete `to_snapshot_dict()`
        output enriched with chain IDs and names for interactive visualization.

        Args:
            params: dict with:
                - engagement_id: str — engagement UUID
                - findings: list[dict] — optional pre-loaded findings

        Returns:
            dict with:
                - paths: list[dict] — serialized attack paths with nodes, edges, risk
                - metadata: dict — summary statistics (totalPaths, totalFindings,
                  highestRiskScore, chainsDetected)
        """
        engagement_id = params.get("engagement_id", "")
        if not engagement_id:
            return {
                "paths": [],
                "metadata": {
                    "totalPaths": 0,
                    "totalFindings": 0,
                    "highestRiskScore": 0,
                    "chainsDetected": 0,
                },
            }

        from attack_graph_db import AttackGraphRepository

        # Try loading from repository first (persisted graph)
        try:
            repo = AttackGraphRepository()
            graph = repo.load_graph(engagement_id)
        except Exception as e:
            logger.debug("Could not load persisted graph for %s: %s", engagement_id, e)
            graph = None

        # Load persisted chain_exploit_script data from DB if available
        chain_scripts: dict[str, Any] = {}
        try:
            import json as _json
            conn = None
            cursor = None
            try:
                from database.connection import get_db
                conn = get_db().get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, path_nodes, chain_exploit_script FROM attack_paths "
                    "WHERE engagement_id = %s AND chain_exploit_script IS NOT NULL",
                    (engagement_id,),
                )
                for row in cursor.fetchall():
                    old_path_id, old_path_nodes_json, script = row
                    if script:
                        try:
                            old_nodes = (
                                _json.loads(old_path_nodes_json)
                                if isinstance(old_path_nodes_json, str)
                                else old_path_nodes_json
                            )
                            node_types = tuple(
                                n.get("data", {}).get("type", "")
                                for n in (old_nodes.get("nodes") or [])
                            )
                            # Parse script if it's a JSON string
                            if isinstance(script, str):
                                try:
                                    script = _json.loads(script)
                                except (_json.JSONDecodeError, TypeError):
                                    pass
                            chain_scripts[str(node_types)] = script
                        except (_json.JSONDecodeError, AttributeError, TypeError):
                            pass
            except Exception as e:
                logger.debug("Could not load chain_exploit_script data: %s", e)
            finally:
                if cursor:
                    cursor.close()
                if conn:
                    try:
                        get_db().release_connection(conn)
                    except Exception:
                        pass
        except Exception as e:
            logger.debug("Failed to query chain_exploit_script for %s: %s", engagement_id, e)

        if graph is None:
            # Build fresh from findings using the shared helper
            graph, _, _ = self._build_attack_graph(
                engagement_id,
                params.get("findings"),
            )

        # Get snapshot and enrich with chain metadata
        snapshot = graph.to_snapshot_dict()
        chains = graph.find_chains()

        # Enrich paths with chain IDs, names, and exploit scripts
        for path_data in snapshot.get("paths", []):
            for chain in chains:
                prereq_type = chain["prereq_node"].data.get("type", "")
                chain_type = chain["chain_node"].data.get("type", "")
                path_types = [
                    n.get("data", {}).get("type", "")
                    for n in path_data.get("nodes", [])
                    if n.get("type") == "vulnerability"
                ]
                if prereq_type in path_types and chain_type in path_types:
                    path_data["chain_id"] = chain["chain_id"]
                    path_data["chain_name"] = chain["name"]
                    break

            # Attach chain_exploit_script if available
            # Fingerprint MUST match the DB-side convention (see loader above
            # and attack_graph_db.py): ALL node types in path order — not just
            # vulnerability nodes. Filtering here previously produced tuples
            # that never matched the stored keys, silently dropping scripts
            # from every path in the visualizer.
            if path_data.get("chain_id"):
                node_types = tuple(
                    n.get("data", {}).get("type", "")
                    for n in path_data.get("nodes", [])
                )
                if str(node_types) in chain_scripts:
                    path_data["chain_exploit_script"] = chain_scripts[str(node_types)]

        # Compute metadata
        all_nodes = set()
        for p in snapshot.get("paths", []):
            for n in p.get("nodes", []):
                all_nodes.add(n.get("id", ""))

        risk_scores = [
            p.get("risk_score", 0)
            for p in snapshot.get("paths", [])
            if p.get("risk_score") is not None
        ]

        return {
            "paths": snapshot.get("paths", []),
            "metadata": {
                "totalPaths": len(snapshot.get("paths", [])),
                "totalFindings": len(all_nodes),
                "highestRiskScore": max(risk_scores) if risk_scores else 0,
                "chainsDetected": len(chains),
            },
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
        engagement_id = params.get("engagement_id", "")

        # Create ScopeValidator when engagement_id is provided
        # This ensures target validation against authorized scope even
        # when call_tool is invoked directly via MCP transport.
        _scope_validator = None
        if engagement_id:
            try:
                from orchestrator_pkg.engagement import EngagementService
                from tools.scope_validator import ScopeValidator

                _authorized_scope = EngagementService.load_authorized_scope(
                    engagement_id
                )
                if _authorized_scope:
                    _scope_validator = ScopeValidator(
                        engagement_id, _authorized_scope
                    )
            except Exception:
                logger.debug(
                    "Could not create scope validator for engagement %s in MCP call_tool",
                    engagement_id,
                    exc_info=True,
                )

        return server.call_tool(
            name,
            arguments,
            timeout,
            cache_mode,
            engagement_id=engagement_id,
            scope_validator=_scope_validator,
        )

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

    def handle_get_attack_graph_snapshot(params):
        return server.handle_get_attack_graph_snapshot(params)

    transport.register("get_attack_graph_snapshot", handle_get_attack_graph_snapshot)

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

    # ── Gap 8.3: Log startup health diagnostics ──
    # Run in a background daemon thread so it doesn't block the transport
    # from starting. The health check is slow (~8-10s) due to Celery ping
    # and preflight checks that scan for tools on PATH.
    from health_server import log_startup_health, start_health_server_from_env

    def _run_health_check():
        try:
            health = log_startup_health()
            if health["status"] == "degraded":
                logger.warning(
                    "Startup health: DEGRADED — %d/%d tools available, LLM=%s, Celery=%s",
                    health["tools"]["available"],
                    health["tools"]["total"],
                    health["llm_available"],
                    health["celery_worker"]["alive"],
                )
            else:
                logger.info("Startup health: OK")
        except Exception:
            logger.debug("Startup health diagnostics failed", exc_info=True)

    _health_thread = threading.Thread(target=_run_health_check, daemon=True)
    _health_thread.start()

    # ── Phase 5.1: Start health/metrics HTTP server (blocker 57) ──
    # Runs on a daemon thread so it doesn't block stdio transport shutdown.
    # Configurable via ARGUS_METRICS_PORT (default 9090) and
    # ARGUS_METRICS_HOST (default 127.0.0.1).
    # Set ARGUS_METRICS_PORT=0 or empty to disable.
    start_health_server_from_env()

    logger.info("MCP stdio transport starting")
    transport.run()


if __name__ == "__main__":
    main()
