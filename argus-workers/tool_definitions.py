"""
Tool Definitions Registry — declarative, single source of truth.

Consolidates tool metadata, phase assignments, timeouts, and adapter
info into one declarative registry. Eliminates duplication between
orchestrator.py, agent_loop.py, and tool_adapter_registry.py.

This is the Python-side single source of truth for tool EXECUTION metadata.
The TypeScript-side planner has its OWN independent tool registry in:
    Argus-Tui/packages/opencode/src/argus/workflows/tool-registry.ts
This separation is intentional — different schema, different purpose:
    - Python side (this file): execution metadata (phases, params, commands, timeouts, signal quality)
    - TS side (tool-registry.ts): planning metadata (capabilities, scoring, consumes/provides, auth gating)

ARCHITECTURE (Python side):
    - _generated_tools.py populates the TOOLS dict FIRST, mirroring
      tools/definitions/*.yaml (hand-kept; there is no generator)
    - Delegated tools skip that mirror: _delegate_tools.py builds them straight
      from their YAML, so the definition and its invocation cannot disagree
    - Inline _register() calls below intentionally OVERRIDE YAML execution policy
      (phases, args, timeout, requires — e.g. the playwright-* gates). An
      override may add information, but it must not lose it: parameters, flags,
      binary and metadata the YAML declares are inherited when unset.
    - tool_core/registry.py is a PATH-scanning CONSUMER, not a competing registry

When adding a new tool:
    1. Create a .yaml file in tools/definitions/
    2. Mirror it in _generated_tools.py (delegates are loaded from YAML instead)
    3. Optionally add an inline _register() override here with richer metadata
    4. If the TS planner needs to know about this tool, also update tool-definitions.yaml

Usage:
    from tool_definitions import ALL_TOOLS, get_tools_for_phase
    from tool_definitions import ToolName, PhaseName

    recon_tools = get_tools_for_phase("recon")
    for tool in recon_tools:
        print(tool.name, tool.timeout)

Stolen from: Shannon's apps/worker/src/session-manager.ts
Pattern: Declarative agent registry with derived types and phase maps.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, fields, replace
from typing import final

logger = logging.getLogger(__name__)

from tool_core._compat import StrEnum
from tool_core.config.models import ToolMetadata

# ── Signal quality tiers for findings prioritization ──


class SignalQuality(StrEnum):
    """Signal quality tier for a tool's findings reliability."""

    CONFIRMED = "confirmed"  # nuclei CVE hit — nearly always real
    PROBABLE = "probable"  # dalfox/sqlmap — tool confirmed the vuln
    CANDIDATE = "candidate"  # nikto, ffuf, naabu — needs investigation


# ── Tool activation conditions ──


@final
@dataclass(frozen=True)
class ToolRequires:
    """Activation condition for a tool — mirrors DeepSec's MatcherGate.

    A tool only runs if all conditions in its `requires` block are met.
    Tools with no `requires` always run.
    """

    tech_contains: list[str] = field(default_factory=list)
    recon_signals: list[str] = field(default_factory=list)
    target_scheme: str | None = None


# ── Phase names ──

#: Ordered list of phases (also serves as the type via 'in' checks)
ALL_PHASES = (
    "recon",
    "source_analysis",  # NEW: AI surface scanning from source code
    "scan",
    "deep_scan",
    "repo_scan",
    "analyze",
    "post_exploit",
    "report",
)
PhaseName = str  # One of ALL_PHASES: "recon" | "scan" | ...


# ── Tool definitions ──


@final
@dataclass(frozen=True)
class ToolParameter:
    """Schema for a tool's parameter."""

    name: str
    description: str
    required: bool = False
    flag: str | None = None
    default: object = None
    enum: list[str] | None = None


@final
@dataclass(frozen=True)
class ToolDefinition:
    """Declarative definition for a security tool.

    NOTE: Keep in sync with mcp_server.py ToolDefinition.
    Key fields shared by both:
        name, description, capabilities, signal_quality, requires, priority, cost
    This class has additional declarative fields (phases, parallel_safe, risk_level, etc.)
    that mcp_server.py does not have. The two classes have diverged
    intentionally — this one is the declarative registry representation,
    mcp_server.py is the runtime MCP server representation.

    All metadata about a tool in one place — no more hunting across
    orchestrator.py, agent_loop.py, and tool_adapter_registry.py.
    """

    #: Unique tool name (matches the binary name, e.g. "nuclei", "httpx")
    name: str

    #: Human-readable description
    description: str

    #: Phases this tool belongs to
    phases: list[PhaseName] = field(default_factory=list)

    #: Binary name on PATH (defaults to `name`)
    binary: str | None = None

    #: Default CLI args
    default_args: list[str] = field(default_factory=list)

    #: Parameter schemas
    parameters: list[ToolParameter] = field(default_factory=list)

    #: What kind of value ``target`` is: "any" | "url" | "host" | "path".
    #: The MCP server refuses to run a "path" tool when the target is a
    #: scheme-bearing URL (gitleaks/semgrep received one and failed with
    #: "stat http://...: no such file or directory"); bare host-shaped values
    #: stay allowed because trivy takes image references like
    #: ``registry.example.com/image:tag``.
    target_kind: str = "any"

    #: Timeout in seconds
    timeout: int = 300

    #: Adapter schema version for tool_adapter_registry.py
    schema_version: str = "1.x"

    #: Whether this tool can run in parallel with others at the same phase
    parallel_safe: bool = True

    #: Model tier hint (for LLM-integrated tools)
    model_tier: str | None = None

    #: Signal quality tier for findings prioritization
    signal_quality: SignalQuality = SignalQuality.CANDIDATE

    #: Activation gate — tool only runs when these conditions are met
    requires: ToolRequires | None = None

    #: Environment variables the tool cannot run without (an API key it reads
    #: from the environment, for example ``GITHUB_TOKEN`` or ``PDCP_API_KEY``).
    #: When any of these is unset the MCP server reports the tool as disabled,
    #: so the planner stops scheduling a tool whose only possible outcome is
    #: ``PDCP_API_KEY not specified``.
    required_env: tuple[str, ...] = ()

    #: Why this tool is not dispatchable, when ``phases`` is empty.
    #: The MCP server forwards this verbatim as the planner's skip reason, so
    #: the log says what is actually wrong ("needs a resolver list", "the
    #: installed build segfaults", "requires root") instead of a generic
    #: "no execution phase".
    disabled_reason: str | None = None

    #: Priority score for tool selection (higher = preferred)
    priority: int | None = None

    #: Cost tier (low, medium, high) for operational cost tracking
    cost: str | None = None

    #: Risk level of running the tool (low, medium, high, critical)
    risk_level: str | None = None

    #: Estimated cost per invocation in USD
    estimated_cost: float | None = None

    #: Estimated runtime in seconds
    estimated_runtime: int | None = None

    #: Maximum concurrent instances (None = no limit)
    concurrency_limit: int | None = None

    #: How sensitive the tool is to out-of-scope targets (low, medium, high)
    scope_sensitivity: str | None = None

    #: Exploit categories this tool covers (e.g. ["xss", "sqli"])
    exploit_categories: list[str] | None = None

    #: Rate limit impact (low, medium, high)
    rate_limit_impact: str | None = None

    #: Optional static metadata (vendor, version, download URL, etc.)
    metadata: ToolMetadata | None = None


# ═══════════════════════════════════════════════════════════════
# Registry — single source of truth for all tool definitions
# ═══════════════════════════════════════════════════════════════

#: Tool name constants — derived from the dict keys below.
#: Using string literals so tools don't need to import this module.
#: Tools access by name: TOOLS["nuclei"], TOOLS["httpx"], etc.
TOOLS: dict[str, ToolDefinition] = {}

#: Names whose re-registration inherited YAML data it would otherwise have
#: dropped — reported once, after the module finishes importing (bottom of file).
_REGISTRY_MERGES: dict[str, list[str]] = {}

#: Fields an inline re-registration deliberately controls: the inline copy is
#: the newer, verified invocation, so these are never inherited from YAML.
#: ``requires`` belongs here too — playwright-* intentionally dropped the
#: auto-generated ``target_scheme`` gate whose list-literal form never passed
#: ``evaluate_gate`` — so an inline ``requires=None`` must not be undone.
_INLINE_POLICY_FIELDS = frozenset(
    {"description", "phases", "default_args", "timeout", "signal_quality", "requires"}
)

#: Names whose definition comes from a YAML file. Populated right after the
#: generated import below — that import runs before every inline ``_register()``
#: call, so every name already in ``TOOLS`` at that point is YAML-defined.
_YAML_DEFINED: set[str] = set()


def _restore_parameter_flag(
    written: ToolParameter, declared: ToolParameter
) -> tuple[ToolParameter, bool]:
    """Give ``written`` back the CLI flag its YAML counterpart declares.

    A same-named parameter without a flag is appended positionally instead of
    as an option. That is how ``httpx`` received its target as a stray argument
    and exited 0 having scanned nothing, and how ``cloud_metadata_probe`` lost
    ``--extra``. ``required`` is deliberately not inherited: pip-audit and
    npm-audit audit the current directory when no target is given.
    """
    if written.flag is None and declared.flag is not None:
        return replace(written, flag=declared.flag), True
    return written, False


def _register(tool: ToolDefinition) -> None:
    """Register a tool definition (internal helper).

    The generated definitions (from ``tools/definitions/*.yaml``) are imported
    below, and inline entries follow them. An inline entry for a YAML-defined
    name intentionally overrides execution policy, but it must not silently
    *lose* what the YAML carries. Two ways that happened:

    - 17 tools lost the ``binary`` their YAML declares — every ``python3``
      launcher plus ``npm-audit``'s ``npm`` — so the MCP bridge asked PATH for a
      binary that was never meant to exist and skipped the tool as
      "unavailable": browser_security_operator, verification_agent, the
      executive report generator and the intelligence engines among them.
    - ``httpx``'s target lost its ``-u`` flag, so the URL was appended
      positionally and httpx exited 0 having scanned nothing; the launcher tools
      lost their ``extra`` parameter, so the credentials JSON was dropped and
      every credentialed report/analysis phase failed to parse its own argv.

    A re-registration therefore inherits: parameters the YAML declares that the
    inline entry omits, the flag of any same-named parameter that lost one,
    ``binary`` and empty ``default_args``, and metadata fields the inline entry
    left unset. Fields in ``_INLINE_POLICY_FIELDS`` stay with the inline entry.
    What was merged is summarised at the bottom of the module.
    """
    existing = TOOLS.get(tool.name)
    if existing is not None and tool.name in _YAML_DEFINED:
        notes: list[str] = []
        merged_params: list[ToolParameter] = []
        for param in tool.parameters:
            declared = next(
                (p for p in existing.parameters if p.name == param.name), None
            )
            if declared is not None:
                param, restored = _restore_parameter_flag(param, declared)
                if restored:
                    notes.append(f"param:{param.name}(flag)")
            merged_params.append(param)
        written_names = {p.name for p in tool.parameters}
        added = [p for p in existing.parameters if p.name not in written_names]
        if added:
            merged_params.extend(added)
            notes.append("param+:" + ",".join(p.name for p in added))
        filled: dict[str, object] = {}
        if tool.binary is None and existing.binary is not None:
            filled["binary"] = existing.binary
        if not tool.default_args and existing.default_args:
            filled["default_args"] = list(existing.default_args)
        for f in fields(ToolDefinition):
            if f.name in _INLINE_POLICY_FIELDS or f.name == "parameters":
                continue
            _written_value = getattr(tool, f.name, None)
            _declared_value = getattr(existing, f.name, None)
            if f.name == "target_kind":
                # "any" is the unset/lenient default: a YAML path/url/host
                # restriction survives an inline block that does not restate
                # it (no inline block can quietly widen a path-only tool).
                if _written_value in (None, "any") and _declared_value not in (
                    None,
                    "any",
                ):
                    filled[f.name] = _declared_value
                continue
            if _written_value is None and _declared_value is not None:
                filled[f.name] = _declared_value
        if filled:
            notes.extend(sorted(filled))
        if notes:
            _REGISTRY_MERGES[tool.name] = sorted(set(notes))
            tool = replace(tool, parameters=merged_params, **filled)
        TOOLS[tool.name] = tool
        return
    if existing is not None:
        filled = {}
        if tool.binary is None and existing.binary is not None:
            filled["binary"] = existing.binary
        if not tool.default_args and existing.default_args:
            filled["default_args"] = list(existing.default_args)
        if filled:
            _REGISTRY_MERGES[tool.name] = sorted(filled)
            tool = replace(tool, **filled)
    TOOLS[tool.name] = tool


# ── Import generated tool registrations from YAML definitions ──
# Generated by: scripts/generate_tool_defs.py --check
# Source: tools/definitions/*.yaml
from _generated_tools import *  # noqa: F403,E402

#: Every name registered so far came from a YAML definition: the generated
#: module is imported above, before any inline ``_register()`` call.
_YAML_DEFINED.update(TOOLS)

# ── Source analysis phase (AI attack-surface scanning) ──
# NOTE: ai-surface is registered from tools/definitions/ai-surface.yaml via
# _generated_tools.py above. A hand-written _register() for the same name was
# removed — it silently overwrote the generated (superset) definition, which
# includes the `verbose` parameter and richer descriptions. Keep the two in
# sync by editing the YAML and re-running scripts/generate_tool_defs.py.


# ── Reconnaissance phase ──

_register(
    ToolDefinition(
        name="httpx",
        description="HTTP probing tool for web service discovery",
        phases=["recon"],
        default_args=["-json", "-silent"],
        parameters=[
            ToolParameter("target", "Target URL", required=True),
        ],
        timeout=300,
        signal_quality=SignalQuality.CANDIDATE,
    )
)

_register(
    ToolDefinition(
        name="katana",
        description="Web crawling and endpoint discovery",
        phases=["recon"],
        default_args=["-jsonl", "-silent"],
        parameters=[
            ToolParameter("target", "Target URL", flag="-u", required=True),
            ToolParameter("depth", "Crawl depth", flag="-d", default=3),
        ],
        timeout=300,
        signal_quality=SignalQuality.CANDIDATE,
    )
)

_register(
    ToolDefinition(
        name="ffuf",
        description="Web fuzzing tool for directory/parameter discovery",
        phases=["recon", "scan", "deep_scan"],
        default_args=["-json"],
        parameters=[
            ToolParameter(
                "target", "Target URL with FUZZ keyword", flag="-u", required=True
            ),
            ToolParameter("wordlist", "Path to wordlist", flag="-w", required=True),
            ToolParameter("threads", "Thread count", flag="-t", default=40),
        ],
        timeout=300,
        signal_quality=SignalQuality.CANDIDATE,
    )
)

# NOTE: amass is registered from tools/definitions/amass.yaml via
# _generated_tools.py above. The hand-written _register() that used to live
# here was removed: `amass` is a YAML-defined name, so its `default_args`
# (inline policy) won over the YAML, and the inline copy passed
# `enum -json` — a flag the installed build does not define, which made every
# amass invocation exit with "flag provided but not defined: -json". The YAML
# entry is a strict superset (priority, cost, risk_level, enabled), so the
# inline copy contributed nothing but staleness. Keep it in the YAML.

_register(
    ToolDefinition(
        name="naabu",
        description="Port scanning tool",
        phases=["recon"],
        default_args=["-json"],
        parameters=[
            ToolParameter("target", "Target host", flag="-host", required=True),
            ToolParameter("top_ports", "Top ports to scan", flag="-top-ports"),
            ToolParameter("port_range", "Port range", flag="-p"),
        ],
        timeout=300,
        signal_quality=SignalQuality.CANDIDATE,
    )
)

_register(
    ToolDefinition(
        name="nikto",
        description="Web server vulnerability scanner",
        phases=["recon", "scan", "deep_scan"],
        # No -Format: nikto writes nicely-formatted output to a
        # nikto_<host>_<timestamp>.<ext> file in the *current directory*
        # rather than stdout, which both loses the findings and litters the
        # working tree. Plain stdout is parsed by the nikto text parser.
        default_args=[
            "-Tuning",
            "123456",
            "-timeout",
            "10",
            "-ask",
            "no",
            "-nointeractive",
        ],
        parameters=[
            ToolParameter("target", "Target URL", flag="-h", required=True),
        ],
        timeout=300,
        signal_quality=SignalQuality.CANDIDATE,
    )
)

_register(
    ToolDefinition(
        name="nmap",
        description="Network port scanner",
        # Enabled: parsers/parsers/nmap.py parses the `-oX -` XML into
        # OPEN_PORT findings. The earlier "no nmap parser exists" note was
        # stale — the parser is auto-discovered from that package. `-sT`
        # because the worker runs unprivileged (a SYN scan needs
        # CAP_NET_RAW) and `-Pn` for the same reason (host discovery uses raw
        # sockets); the scope guard has already fixed the host, so skipping
        # discovery only costs time.
        phases=["recon"],
        default_args=["-sT", "-Pn", "-oX", "-", "-T4", "--top-ports", "200"],
        parameters=[
            ToolParameter("target", "Target host", required=True),
            ToolParameter("ports", "Port range", flag="-p"),
        ],
        timeout=600,
        signal_quality=SignalQuality.CONFIRMED,
    )
)

_register(
    ToolDefinition(
        name="gospider",
        description="Web spider for endpoint discovery",
        # Enabled: gospider v1.1.6 (provisioned by the install script) crawls
        # and emits JSONL without the segfault the older build showed under -v.
        phases=["recon"],
        default_args=["-q", "--json"],
        parameters=[
            ToolParameter("target", "Target URL", flag="-s", required=True),
            ToolParameter("depth", "Crawl depth", flag="-d", default=3),
        ],
        timeout=300,
        signal_quality=SignalQuality.CANDIDATE,
    )
)


# ── Scanning phase ──

# nuclei's vendor metadata has no YAML key, so it stays here; every field the
# YAML carries (arguments, phases, timeout, signal quality, priority) comes
# from tools/definitions/nuclei.yaml. Do not restate default_args: doing so
# discarded the tuned -timeout/-retries/-bulk-size flags.
_register(
    ToolDefinition(
        name="nuclei",
        description="Vulnerability scanner based on YAML templates",
        phases=["scan", "deep_scan"],
        parameters=[
            ToolParameter("target", "Target URL", flag="-u", required=True),
            ToolParameter(
                "severity",
                "Severity filter",
                flag="-severity",
                enum=["info", "low", "medium", "high", "critical"],
            ),
            ToolParameter("templates", "Custom template directory", flag="-t"),
            ToolParameter("tags", "Template tags to run", flag="-tags"),
        ],
        timeout=600,
        signal_quality=SignalQuality.CONFIRMED,
        metadata=ToolMetadata(
            vendor="projectdiscovery",
            homepage="https://github.com/projectdiscovery/nuclei",
            license="MIT",
            default_version="3.2.0",
        ),
    )
)

_register(
    ToolDefinition(
        name="dalfox",
        description="XSS vulnerability scanner",
        phases=["scan", "deep_scan"],
        # dalfox v2 is a Cobra CLI: the target belongs to the `url`
        # subcommand, and JSON Lines output is `--format jsonl` (the old
        # `--json` flag was removed). The JSONL schema is read by the
        # dalfox parser, so keep the two in step.
        default_args=[
            "url",
            "--format",
            "jsonl",
            "--no-color",
            "--no-spinner",
        ],
        parameters=[
            ToolParameter("target", "Target URL", required=True),
            ToolParameter("blind", "Blind XSS callback URL", flag="-b"),
            ToolParameter("deep_dom", "Deep DOM scanning", flag="--deep-domxss"),
        ],
        timeout=600,
        signal_quality=SignalQuality.PROBABLE,
    )
)


_register(
    ToolDefinition(
        name="register",
        description="Register a new test account on the target application. "
        "Auto-generates a unique email and password. "
        "Discovers registration form fields automatically. "
        "On success, stores authenticated session for subsequent tools. "
        "Handles email verification fallback gracefully.",
        phases=["scan"],
        parameters=[
            ToolParameter(
                name="target",
                description="Base URL of the target application",
                required=True,
                flag="--target",
            ),
        ],
        timeout=300,
        parallel_safe=False,
        signal_quality=SignalQuality.CONFIRMED,
        exploit_categories=["auth"],
        estimated_cost=0.0,
        estimated_runtime=30,
    )
)

_register(
    ToolDefinition(
        name="login",
        description="Log in to the target application with stored or provided credentials. "
        "Auto-discovers login form fields. "
        "If email/password omitted, uses credentials from prior register() call. "
        "On success, stores authenticated session for subsequent tools.",
        phases=["scan"],
        parameters=[
            ToolParameter(
                name="target",
                description="Base URL of the target application",
                required=True,
                flag="--target",
            ),
            ToolParameter(
                name="email",
                description="Email to log in with (auto-fills from register if empty)",
                required=False,
            ),
            ToolParameter(
                name="password",
                description="Password to log in with (auto-fills from register if empty)",
                required=False,
            ),
        ],
        timeout=60,
        parallel_safe=False,
        signal_quality=SignalQuality.CONFIRMED,
        exploit_categories=["auth"],
        estimated_cost=0.0,
        estimated_runtime=15,
    )
)


# ── Repository scanning phase ──

_register(
    ToolDefinition(
        name="semgrep",
        description="Static code analysis tool",
        phases=["repo_scan"],
        default_args=["--json"],
        parameters=[
            ToolParameter("target", "Target path", required=True),
            ToolParameter("config", "Rule config path", flag="--config"),
        ],
        timeout=600,
        signal_quality=SignalQuality.CONFIRMED,
    )
)

_register(
    ToolDefinition(
        name="gitleaks",
        description="Git repository secret scanning",
        # Secrets only (see tools/definitions/gitleaks.yaml). Claiming
        # `vulnerability_scanning` made gitleaks eligible for the HTTP
        # vulnerability-scan phase, which handed it a URL it can only reject
        # ("stat http://...: no such file or directory") — gitleaks scans
        # filesystem paths.
        phases=["repo_scan"],
        # --no-git scans the path directly instead of requiring a git
        # repository; --report-path - writes the JSON report to stdout where
        # the parser can read it.
        default_args=[
            "detect",
            "--no-git",
            "--no-color",
            "--report-format",
            "json",
            "--report-path",
            "-",
        ],
        parameters=[
            ToolParameter(
                "target",
                "Filesystem path or repository directory to scan",
                flag="--source",
                required=True,
            ),
            ToolParameter(
                "max_target_mb", "Max target size", flag="--max-target-megabytes"
            ),
        ],
        timeout=300,
        signal_quality=SignalQuality.CONFIRMED,
    )
)


_register(
    ToolDefinition(
        name="trivy",
        description="Container and filesystem vulnerability scanner",
        phases=["repo_scan"],
        default_args=[
            "fs",
            "--format",
            "json",
            "--skip-dirs",
            "node_modules,vendor,dist,build,.git,coverage",
        ],
        parameters=[
            ToolParameter("target", "Image name or path", required=True),
            ToolParameter(
                "scanners",
                "Comma-separated scanners",
                flag="--scanners",
                default="vuln,misconfig,secret",
            ),
        ],
        timeout=600,
        signal_quality=SignalQuality.PROBABLE,
    )
)


# ── Specialized tools ──

# gau, waybackurls, subfinder, alterx, wafw00f, whatweb and dnsx are defined
# only by their YAML files: each runs a repository shim (recon_shim.py,
# whatweb_shim.py, dnsx_shim.py). Inline copies here overrode default_args and
# binary, so the Python runner invoked `gau --json` / `wafw00f -a` — binaries
# that do not exist — while the MCP server used the shim from the same YAML.
# Keep invocation in the YAML; add policy here only when it differs.


# ── Playwright browser verification tools ──
# These override _generated_tools.py definitions which had an incorrectly
# auto-generated target_scheme="['http', 'https']" (Python list-literal string)
# that would never pass evaluate_gate's target.startswith() check.
# Playwright tools work on any HTTP(S) target — no scheme gate needed.

_register(
    ToolDefinition(
        name="playwright-xss",
        description="Stored Cross-Site Scripting detection via browser automation (overrides _generated_tools.py)",
        phases=["scan", "deep_scan"],
        binary="python3",
        default_args=["argus-workers/tools/scripts/playwright_xss.py"],
        parameters=[
            ToolParameter(name="target", description="Target URL", required=True, flag="--target"),
            ToolParameter(name="creds_file", description="Path to JSON credentials file (alternative to --username/--password)", flag="--creds-file"),
            ToolParameter(name="username", description="Login username", flag="--username"),
            ToolParameter(name="password", description="Login password", flag="--password"),
            ToolParameter(name="form-page", description="Path to the form page", flag="--form-page", default="/feedback"),
            ToolParameter(name="payload", description="XSS payload to inject", flag="--payload"),
            ToolParameter(name="username-selector", description="CSS selector for username input", flag="--username-selector", default="input[name=username]"),
            ToolParameter(name="password-selector", description="CSS selector for password input", flag="--password-selector", default="input[name=password]"),
            ToolParameter(name="submit-selector", description="CSS selector for submit button", flag="--submit-selector", default="button[type=submit]"),
        ],
        timeout=120,
        signal_quality=SignalQuality.CONFIRMED,
        priority=80,
        cost="medium",
        risk_level="low",
        # No requires gate — works on all HTTP/HTTPS targets
    )
)

_register(
    ToolDefinition(
        name="playwright-bola",
        description="Broken Object Level Authorization detection via browser automation (overrides _generated_tools.py)",
        phases=["scan", "deep_scan"],
        binary="python3",
        default_args=["argus-workers/tools/scripts/playwright_bola.py"],
        parameters=[
            ToolParameter(name="target", description="Target URL", required=True, flag="--target"),
            ToolParameter(name="creds_file", description="Path to JSON credentials file (alternative to --attacker-username/--attacker-password and --victim-username/--victim-password)", flag="--creds-file"),
            ToolParameter(name="attacker-username", description="Attacker username", flag="--attacker-username"),
            ToolParameter(name="attacker-password", description="Attacker password", flag="--attacker-password"),
            ToolParameter(name="victim-username", description="Victim username", flag="--victim-username"),
            ToolParameter(name="victim-password", description="Victim password", flag="--victim-password"),
            ToolParameter(name="resource-pattern", description="URL pattern for victim resource", flag="--resource-pattern", default="/api/users/{username}/details"),
            ToolParameter(name="username-selector", description="CSS selector for username input", flag="--username-selector", default="input[name=username]"),
            ToolParameter(name="password-selector", description="CSS selector for password input", flag="--password-selector", default="input[name=password]"),
            ToolParameter(name="submit-selector", description="CSS selector for submit button", flag="--submit-selector", default="button[type=submit]"),
        ],
        timeout=120,
        signal_quality=SignalQuality.CONFIRMED,
        priority=80,
        cost="medium",
        risk_level="low",
    )
)

_register(
    ToolDefinition(
        name="playwright-privesc",
        description="Privilege Escalation detection via browser automation (overrides _generated_tools.py)",
        phases=["scan", "deep_scan"],
        binary="python3",
        default_args=["argus-workers/tools/scripts/playwright_privesc.py"],
        parameters=[
            ToolParameter(name="target", description="Target URL", required=True, flag="--target"),
            ToolParameter(name="creds_file", description="Path to JSON credentials file (alternative to --low-priv-username/--low-priv-password)", flag="--creds-file"),
            ToolParameter(name="low-priv-username", description="Low-privilege user username", flag="--low-priv-username"),
            ToolParameter(name="low-priv-password", description="Low-privilege user password", flag="--low-priv-password"),
            ToolParameter(name="admin-paths", description="Comma-separated admin endpoints to probe", flag="--admin-paths"),
            ToolParameter(name="username-selector", description="CSS selector for username input", flag="--username-selector", default="input[name=username]"),
            ToolParameter(name="password-selector", description="CSS selector for password input", flag="--password-selector", default="input[name=password]"),
            ToolParameter(name="submit-selector", description="CSS selector for submit button", flag="--submit-selector", default="button[type=submit]"),
        ],
        timeout=120,
        signal_quality=SignalQuality.CONFIRMED,
        priority=80,
        cost="medium",
        risk_level="low",
    )
)


# ── Analysis / intelligence phase ──

_register(
    ToolDefinition(
        name="intelligence-engine",
        description="LLM-powered findings analysis and correlation",
        phases=["analyze"],
        default_args=[],
        parameters=[
            ToolParameter("engagement_id", "Engagement ID to analyze", required=True),
        ],
        timeout=600,
        model_tier="medium",
    )
)

_register(
    ToolDefinition(
        name="attack-graph",
        description="Build attack graph from findings",
        phases=["analyze"],
        default_args=[],
        parameters=[
            ToolParameter("engagement_id", "Engagement ID", required=True),
        ],
        timeout=300,
    )
)

# ── Post-exploitation phase ──

_register(
    ToolDefinition(
        name="post_exploitation",
        description="Orchestrate post-exploitation: extract credentials from findings, replay against other endpoints, "
        "and probe internal network ranges for lateral movement opportunities. "
        "Only runs when findings indicate a foothold (HIGH/CRITICAL findings with confidence >= 0.75).",
        phases=["post_exploit"],
        parameters=[
            ToolParameter(
                name="target",
                description="Engagement ID or target scope",
                required=True,
            ),
        ],
        timeout=1800,
        parallel_safe=False,
        signal_quality=SignalQuality.CONFIRMED,
        exploit_categories=["post_exploitation", "lateral_movement", "credential_replay"],
        estimated_cost=0.0,
        estimated_runtime=0,
        risk_level="high",
    )
)

_register(
    ToolDefinition(
        name="credential_replay",
        description="Extract credentials (passwords, API keys, JWT tokens, session cookies) from finding evidence "
        "and replay them against other discovered endpoints to test credential reuse. "
        "Replays via Bearer tokens, cookies, form login, and API key headers. "
        "Successful replays are reported as HIGH-severity findings.",
        phases=["post_exploit"],
        parameters=[
            ToolParameter(
                name="target",
                description="Target endpoint URL to replay credentials against",
                required=True,
            ),
        ],
        timeout=300,
        parallel_safe=False,
        signal_quality=SignalQuality.CONFIRMED,
        exploit_categories=["credential_replay", "privilege_escalation"],
        estimated_cost=0.0,
        estimated_runtime=0,
        risk_level="high",
    )
)

_register(
    ToolDefinition(
        name="internal_probe",
        description="Probe internal network ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16) for "
        "additional services after a foothold is established. "
        "Checks common ports (SSH, HTTP, HTTPS, MySQL, PostgreSQL, Redis, Elasticsearch, MongoDB) "
        "and reports discovered services as findings for lateral movement planning. "
        "All probes are validated against authorized scope before execution.",
        phases=["post_exploit"],
        parameters=[
            ToolParameter(
                name="target",
                description="Known host IP to start probing from",
                required=True,
            ),
        ],
        timeout=600,
        parallel_safe=False,
        signal_quality=SignalQuality.PROBABLE,
        exploit_categories=["lateral_movement", "internal_discovery"],
        estimated_cost=0.0,
        estimated_runtime=0,
        risk_level="high",
    )
)

_register(
    ToolDefinition(
        name="cloud_metadata_probe",
        description="Probe cloud metadata endpoints (169.254.169.254) for IAM credentials, "
        "instance metadata, and cloud provider token exposure. "
        "Checks AWS, GCP, Azure, and Alibaba Cloud metadata endpoints. "
        "Only runs when findings indicate a cloud-hosted target.",
        phases=["post_exploit"],
        binary="python3",
        default_args=["argus-workers/tools/run_agent_tool.py", "cloud_metadata_probe"],
        parameters=[
            ToolParameter(
                name="target",
                description="Target URL or IP to probe for cloud metadata",
                required=True,
                flag="--target",
            ),
            ToolParameter(
                name="extra",
                description="JSON-encoded extra parameters",
            ),
        ],
        timeout=60,
        parallel_safe=False,
        signal_quality=SignalQuality.CONFIRMED,
        exploit_categories=["cloud_metadata", "credential_disclosure"],
        estimated_cost=0.0,
        estimated_runtime=10,
        risk_level="high",
    )
)


# ── Reporting phase ──

_register(
    ToolDefinition(
        name="report-generator",

        description="Generate executive security report",
        phases=["report"],
        default_args=[],
        parameters=[
            ToolParameter("engagement_id", "Engagement ID", required=True),
            ToolParameter(
                "format",
                "Report format",
                default="markdown",
                enum=["markdown", "pdf", "html"],
            ),
        ],
        timeout=300,
        model_tier="small",
    )
)

_register(
    ToolDefinition(
        name="compliance-check",
        description="Check findings against compliance frameworks (SOC 2, HIPAA, PCI)",
        phases=["report"],
        default_args=[],
        parameters=[
            ToolParameter("engagement_id", "Engagement ID", required=True),
            ToolParameter(
                "framework",
                "Compliance framework",
                default="soc2",
                enum=["soc2", "hipaa", "pci"],
            ),
        ],
        timeout=120,
    )
)


# ═══════════════════════════════════════════════════════════════
# Advanced Security Tools (14 new tools)
# ═══════════════════════════════════════════════════════════════

_register(
    ToolDefinition(
        name="finding_correlation_engine",
        description="Correlates findings: semantic deduplication, root cause analysis, attack chain detection, priority ranking",
        phases=["analyze"],
        parameters=[
            ToolParameter(
                "target", "Target URL or scope", required=True, flag="--target"
            )
        ],
        timeout=120,
        signal_quality=SignalQuality.CONFIRMED,
        parallel_safe=False,
    )
)

_register(
    ToolDefinition(
        name="attack_path_generator",
        description="Generates attack paths from findings using graph analysis and narrative generation",
        phases=["analyze"],
        parameters=[
            ToolParameter(
                "target", "Target URL or scope", required=True, flag="--target"
            )
        ],
        timeout=120,
        signal_quality=SignalQuality.CONFIRMED,
        parallel_safe=False,
    )
)

_register(
    ToolDefinition(
        name="verification_agent",
        description="Verifies findings by attempting reproduction, collecting evidence, and scoring confidence",
        phases=["deep_scan", "analyze"],
        parameters=[
            ToolParameter(
                "target", "Target URL to verify against", required=True, flag="--target"
            )
        ],
        timeout=300,
        signal_quality=SignalQuality.CONFIRMED,
        parallel_safe=False,
    )
)

_register(
    ToolDefinition(
        name="finding_verifier",
        description="Verifies specific findings by re-testing with independent HTTP-based methods. "
        "Validates SQLi, XSS, and Open Redirect via httpx probes. "
        "Generates confirmation evidence for high-confidence reporting.",
        phases=["deep_scan", "analyze"],
        binary="python3",
        default_args=["argus-workers/tools/scripts/run_finding_verifier.py"],
        parameters=[
            ToolParameter(
                name="target",
                description="Target URL to verify",
                required=True,
                flag="--target",
            ),
            ToolParameter(
                name="finding_type",
                description="Type of finding to verify (sqli, xss, open_redirect)",
                required=True,
                flag="--finding-type",
            ),
            ToolParameter(
                name="payload",
                description="Payload used in the original finding",
                flag="--payload",
            ),
            ToolParameter(
                name="endpoint",
                description="Specific endpoint URL where the finding was detected",
                flag="--endpoint",
            ),
            ToolParameter(
                name="engagement_id",
                description="Engagement ID for logging",
                flag="--engagement-id",
            ),
        ],
        timeout=60,
        signal_quality=SignalQuality.CONFIRMED,
        parallel_safe=True,
    )
)

_register(
    ToolDefinition(
        name="browser_security_operator",
        description="Comprehensive browser-based security testing: DOM analysis, auth testing, XSS/CSRF verification",
        phases=["scan", "deep_scan"],
        parameters=[
            ToolParameter(
                "target", "Target URL to test", required=True, flag="--target"
            )
        ],
        timeout=600,
        signal_quality=SignalQuality.CONFIRMED,
        parallel_safe=False,
    )
)

_register(
    ToolDefinition(
        name="attack_surface_mapper",
        description="Maps complete attack surface using subfinder, amass, naabu, httpx, katana, gau, waybackurls",
        phases=["recon"],
        parameters=[
            ToolParameter(
                "target", "Target domain or URL", required=True, flag="--target"
            )
        ],
        timeout=600,
        signal_quality=SignalQuality.CONFIRMED,
        parallel_safe=True,
    )
)

_register(
    ToolDefinition(
        name="evidence_intelligence_engine",
        description="Collects, hashes, and scores evidence for findings with chain of custody",
        phases=["analyze", "report"],
        parameters=[
            ToolParameter(
                "target", "Target URL or scope", required=True, flag="--target"
            )
        ],
        timeout=120,
        signal_quality=SignalQuality.CONFIRMED,
        parallel_safe=True,
    )
)

_register(
    ToolDefinition(
        name="executive_report_generator",
        description="Generates executive security reports with summary, attack paths, and remediation guidance",
        phases=["report"],
        parameters=[
            ToolParameter(
                "target", "Target URL or scope", required=True, flag="--target"
            )
        ],
        timeout=120,
        signal_quality=SignalQuality.CONFIRMED,
        parallel_safe=False,
    )
)

_register(
    ToolDefinition(
        name="threat_intelligence_aggregator",
        description="Aggregates threat intelligence from Shodan, Censys, VirusTotal, AbuseIPDB, crt.sh, WHOIS",
        phases=["recon", "analyze"],
        parameters=[
            ToolParameter(
                "target", "Target domain to investigate", required=True, flag="--target"
            )
        ],
        timeout=300,
        signal_quality=SignalQuality.CONFIRMED,
        parallel_safe=True,
    )
)

_register(
    ToolDefinition(
        name="vulnerability_knowledge_engine",
        description="Looks up CVE, CWE, CAPEC, OWASP, ExploitDB knowledge for findings",
        phases=["analyze"],
        parameters=[
            ToolParameter(
                "target", "Target URL or scope", required=True, flag="--target"
            )
        ],
        timeout=120,
        signal_quality=SignalQuality.CONFIRMED,
        parallel_safe=True,
    )
)

_register(
    ToolDefinition(
        name="secure_code_intelligence_engine",
        description="Unified SAST/SCA/secret scanning combining gitleaks, semgrep, bandit, trivy",
        phases=["source_analysis", "analyze", "repo_scan"],
        parameters=[
            ToolParameter(
                "target", "Target repository path", required=True, flag="--target"
            )
        ],
        timeout=600,
        signal_quality=SignalQuality.CONFIRMED,
        parallel_safe=False,
    )
)

_register(
    ToolDefinition(
        name="infrastructure_security_analyzer",
        description="Analyzes Terraform, Kubernetes, Docker configs for misconfigurations and attack paths",
        phases=["repo_scan", "analyze"],
        parameters=[
            ToolParameter(
                "target",
                "Target directory containing IaC files",
                required=True,
                flag="--target",
            )
        ],
        timeout=300,
        signal_quality=SignalQuality.CONFIRMED,
        parallel_safe=True,
    )
)

_register(
    ToolDefinition(
        name="assessment_orchestrator",
        description="Coordinates all assessment phases: recon, scan, deep_scan, repo_scan, analyze, report",
        phases=["analyze"],
        parameters=[
            ToolParameter(
                "target", "Target URL or scope", required=True, flag="--target"
            )
        ],
        timeout=300,
        signal_quality=SignalQuality.CONFIRMED,
        parallel_safe=False,
    )
)

_register(
    ToolDefinition(
        name="workflow_intelligence_engine",
        description="Analyzes execution metrics, detects bottlenecks, recommends workflow optimizations",
        phases=["analyze", "report"],
        parameters=[
            ToolParameter(
                "target",
                "Target engagement ID or scope",
                required=True,
                flag="--target",
            )
        ],
        timeout=120,
        signal_quality=SignalQuality.CONFIRMED,
        parallel_safe=True,
    )
)

_register(
    ToolDefinition(
        name="engagement_analytics_engine",
        description="Cross-engagement analytics: trends, benchmarks, portfolio risk scoring",
        phases=["analyze", "report"],
        parameters=[
            ToolParameter(
                "target", "Target scope for analytics", required=True, flag="--target"
            )
        ],
        timeout=120,
        signal_quality=SignalQuality.CONFIRMED,
        parallel_safe=True,
    )
)


# ═══════════════════════════════════════════════════════════════
# Advisory-only tools (not in any exploitation phase)
# ═══════════════════════════════════════════════════════════════

_register(
    ToolDefinition(
        name="ai_surface_detected",
        description="Advisory finding: AI/LLM surface detected. "
        "Indicates that the target appears to use AI chat interfaces, LLM APIs, "
        "or chatbot widgets. Manual AI red-team review (e.g. using PyRIT) is "
        "recommended to test for prompt injection, data leakage, and insecure "
        "LLM access controls.",
        phases=[],  # NOT in any exploitation phase — advisory only
        parameters=[
            ToolParameter(
                name="target",
                description="Target URL where AI surface was detected",
                required=True,
            ),
        ],
        timeout=10,
        signal_quality=SignalQuality.CONFIRMED,
        priority=10,  # Low priority — informational only
        cost="low",
        risk_level="low",
    )
)


# ═══════════════════════════════════════════════════════════════
# Helper functions
# ═══════════════════════════════════════════════════════════════

# Frozen dict to prevent runtime modification

# Register the definitions module
TOOLS_DEFINED = list(TOOLS.keys())


# Agent-internal tools that have no external binary.
# These are always "available" because they are implemented as
# Python functions within the agent itself.
_AGENT_INTERNAL_TOOLS = frozenset(
    {
        "register",
        "login",
        "post_exploitation",
        "credential_replay",
        "internal_probe",
        "cloud_metadata_probe",
        "ai_surface_detected",
        "finding_correlation_engine",
        "attack_path_generator",
        "verification_agent",
        "browser_security_operator",
        "attack_surface_mapper",
        "evidence_intelligence_engine",
        "executive_report_generator",
        "threat_intelligence_aggregator",
        "vulnerability_knowledge_engine",
        "secure_code_intelligence_engine",
        "infrastructure_security_analyzer",
        "assessment_orchestrator",
        "workflow_intelligence_engine",
        "engagement_analytics_engine",
    }
)


#: Registry entries that name an in-process pipeline step, not an executable.
#:
#: The orchestrator runs these itself — post-exploitation, credential replay
#: and the internal probe through ``run_post_exploitation()``, attack-graph
#: building, report generation and compliance scoring through their services —
#: and ``ai_surface_detected`` is an advisory marker with no phase at all.
#:
#: They are declared so registry consumers can tell them apart from a tool
#: whose external binary simply is not installed: no install can make these
#: runnable, and handing their name to a PATH-based runner (ToolRunner, the MCP
#: bridge) can only fail. Note that these are deliberately *not* in
#: ``_AGENT_INTERNAL_TOOLS``: that set means "available without a binary", and
#: everything in it is offered to the ReAct agent as a callable tool.
_PIPELINE_STEP_TOOLS = frozenset(
    {
        "intelligence-engine",
        "attack-graph",
        "post_exploitation",
        "credential_replay",
        "internal_probe",
        "report-generator",
        "compliance-check",
        "ai_surface_detected",
    }
)


def is_pipeline_step(tool_name: str) -> bool:
    """True when *tool_name* is an in-process step, not an executable tool."""
    return tool_name in _PIPELINE_STEP_TOOLS


def is_tool_available(tool_name: str) -> bool:
    """Check if a tool binary is available on the system PATH.

    Agent-internal tools (register, login) always return True since
    they are Python functions, not external binaries.

    Delegates to tools.tool_utils for the augmented PATH resolution
    (venv/bin, ~/go/bin, /opt/homebrew/bin, etc.).

    Args:
        tool_name: Name of the tool binary to check.

    Returns:
        True if the tool is found, False otherwise.
    """
    # Agent-internal tools are always available
    if tool_name in _AGENT_INTERNAL_TOOLS:
        return True

    from tools.tool_utils import is_tool_available as _check_binary

    # A tool may run through another binary (a Python shim, a delegated engine).
    # Resolve that first, so declared availability matches what the MCP worker
    # can actually dispatch, instead of requiring a binary named after the tool.
    declared = TOOLS.get(tool_name)
    binary = declared.binary if declared is not None else None
    if binary and _check_binary(binary):
        return True

    return _check_binary(tool_name)


def get_tools_for_phase(phase: PhaseName) -> list[ToolDefinition]:
    """Get all tool definitions for a given phase, filtering to available tools only.

    Args:
        phase: Phase name (e.g., "recon", "scan").

    Returns:
        List of ToolDefinition objects for that phase whose binaries are installed.
    """
    return [
        tool
        for tool in TOOLS.values()
        if phase in tool.phases and is_tool_available(tool.name)
    ]


def get_tool(name: str) -> ToolDefinition | None:
    """Get a tool definition by name.

    Args:
        name: Tool name (e.g., "nuclei", "httpx").

    Returns:
        ToolDefinition if found, None otherwise.
    """
    return TOOLS.get(name)


def get_phase_tool_names(phase: PhaseName) -> list[str]:
    """Get tool names for a phase (compatible with ReActAgent.PHASE_TOOLS).

    Args:
        phase: Phase name.

    Returns:
        List of tool name strings.
    """
    return [tool.name for tool in get_tools_for_phase(phase)]


def build_phase_tools_dict() -> dict[str, list[str]]:
    """Build the PHASE_TOOLS dict expected by ReActAgent.

    Returns:
        Dict mapping phase names to tool name lists.
    """
    return {phase: get_phase_tool_names(phase) for phase in ALL_PHASES}


def evaluate_gate(tool_name: str, recon_context) -> bool:
    """Check if a tool's requires gate is satisfied.

    Called before dispatching a tool in the scan phase. Returns True
    if the tool should run, False if it should be skipped.

    Args:
        tool_name: Tool name (e.g. 'wpscan', 'jwt_tool')
        recon_context: ReconContext dataclass with target_url, tech_stack, etc.

    Returns:
        True if tool should run, False to skip.
    """
    tool_def = TOOLS.get(tool_name)
    if not tool_def or not tool_def.requires:
        return True  # no gate → always run

    req = tool_def.requires

    if req.tech_contains:
        stack = " ".join(
            str(t) for t in (getattr(recon_context, "tech_stack", []) or [])
        ).lower()
        if not any(t in stack for t in req.tech_contains):
            return False

    if req.recon_signals:
        for signal in req.recon_signals:
            attr_val = getattr(recon_context, signal, None)
            if attr_val is None:
                # Context doesn't have this signal — permissive: don't gate on it
                continue
            if not attr_val:
                # All required signals must be truthy (AND logic)
                return False

    if req.target_scheme:
        target = getattr(recon_context, "target_url", "") or ""
        # Defense-in-depth: some auto-generated definitions emit list-literal
        # strings like "['http', 'https']" instead of plain "https".
        # Handle both formats by checking if ANY scheme in the string matches.
        _scheme = req.target_scheme
        if _scheme.startswith("[") and _scheme.endswith("]"):
            # Parse list-literal format: "['http', 'https']"
            _schemes = [
                s.strip().strip("'\"")
                for s in _scheme.strip("[]").split(",")
            ]
            _matched = any(target.startswith(s) for s in _schemes if s)
            if not _matched:
                return False
        elif not target.startswith(_scheme):
            return False

    return True


def build_mcp_tool_definitions() -> list:
    """Build MCP tool definitions for orchestrator._register_mcp_tools().

    Returns:
        List of ToolDefinition objects compatible with the MCP server.
    """
    from mcp_server import ToolDefinition as MCPToolDef
    from mcp_server import ToolSchema

    mcp_tools = []
    for tool in TOOLS.values():
        schema_params = [
            ToolSchema(
                name=p.name,
                type="string" if not isinstance(p.default, bool) else "boolean",
                description=p.description,
                flag=p.flag,
                required=p.required,
                default=p.default,
                enum=p.enum,
            )
            for p in tool.parameters
        ]
        mcp_tools.append(
            MCPToolDef(
                name=tool.name,
                command=tool.binary or tool.name,
                description=tool.description,
                args=list(tool.default_args),
                parameters=schema_params,  # type: ignore[arg-type]
                timeout=tool.timeout,
                signal_quality=tool.signal_quality.value if hasattr(tool.signal_quality, 'value') else tool.signal_quality,
                priority=tool.priority,
                cost=tool.cost,
                requires=tool.requires,  # type: ignore[arg-type]
                capabilities=getattr(tool, 'capabilities', None),
                credential_roles=getattr(tool, 'credential_roles', None),
                risk_level=tool.risk_level,
                target_kind=getattr(tool, 'target_kind', 'any'),
            )
        )
    return mcp_tools


if _REGISTRY_MERGES:
    logger.debug(
        "%d inline tool definition(s) inherited fields from their YAML "
        "definition: %s",
        len(_REGISTRY_MERGES),
        ", ".join(
            f"{name} ({'/'.join(merged)})"
            for name, merged in sorted(_REGISTRY_MERGES.items())
        ),
    )
