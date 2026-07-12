"""
Tool Definitions Registry — declarative, single source of truth.

Consolidates tool metadata, phase assignments, timeouts, and adapter
info into one declarative registry. Eliminates duplication between
orchestrator.py, agent_loop.py, and tool_adapter_registry.py.

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

from dataclasses import dataclass, field
from typing import final

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


def _register(tool: ToolDefinition) -> None:
    """Register a tool definition (internal helper)."""
    TOOLS[tool.name] = tool


# ── Import generated tool registrations from YAML definitions ──
# Generated by: scripts/generate_tool_defs.py --check
# Source: tools/definitions/*.yaml
from _generated_tools import *  # noqa: F403,E402

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

_register(
    ToolDefinition(
        name="amass",
        description="Subdomain enumeration and reconnaissance",
        phases=["recon"],
        default_args=["enum", "-json"],
        parameters=[
            ToolParameter("target", "Target domain", flag="-d", required=True),
            ToolParameter("brute", "Enable brute forcing", flag="-brute"),
        ],
        timeout=600,
        signal_quality=SignalQuality.CANDIDATE,
    )
)

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
        name="whatweb",
        description="Web technology fingerprinting",
        phases=["recon"],
        default_args=["--format=json"],
        parameters=[
            ToolParameter("target", "Target URL", required=True),
        ],
        timeout=120,
        signal_quality=SignalQuality.CANDIDATE,
    )
)

_register(
    ToolDefinition(
        name="nikto",
        description="Web server vulnerability scanner",
        phases=["recon", "scan", "deep_scan"],
        default_args=["-Format", "csv"],
        parameters=[
            ToolParameter("target", "Target URL", flag="-h", required=True),
        ],
        timeout=300,
        signal_quality=SignalQuality.CANDIDATE,
    )
)

_register(
    ToolDefinition(
        name="gau",
        description="Get all URLs from web archives",
        phases=["recon"],
        default_args=["--json"],
        parameters=[
            ToolParameter("target", "Target domain", required=True),
        ],
        timeout=180,
        signal_quality=SignalQuality.CANDIDATE,
    )
)

_register(
    ToolDefinition(
        name="waybackurls",
        description="Fetch URLs from Wayback Machine",
        phases=["recon"],
        default_args=[],
        parameters=[
            ToolParameter("target", "Target domain", required=True),
        ],
        timeout=120,
        signal_quality=SignalQuality.CANDIDATE,
    )
)

_register(
    ToolDefinition(
        name="nmap",
        description="Network port scanner",
        phases=[],  # Disabled: no nmap parser exists. Use naabu for port scanning.
        default_args=["-oX", "-"],
        parameters=[
            ToolParameter("target", "Target host", required=True),
            ToolParameter("ports", "Port range", flag="-p"),
        ],
        timeout=600,
    )
)

_register(
    ToolDefinition(
        name="gospider",
        description="Web spider for endpoint discovery",
        phases=["recon"],  # Enabled: gospider parser exists
        default_args=["-q", "-j"],
        parameters=[
            ToolParameter("target", "Target URL", flag="-s", required=True),
            ToolParameter("depth", "Crawl depth", flag="-d", default=3),
        ],
        timeout=300,
        signal_quality=SignalQuality.CANDIDATE,
    )
)

_register(
    ToolDefinition(
        name="subfinder",
        description="Fast passive subdomain enumeration tool",
        phases=["recon"],
        default_args=["-silent"],
        parameters=[
            ToolParameter("target", "Target domain", flag="-d", required=True),
            ToolParameter("all", "Use all sources", flag="-all"),
        ],
        timeout=300,
        signal_quality=SignalQuality.CANDIDATE,
    )
)

_register(
    ToolDefinition(
        name="alterx",
        description="Subdomain permutation generator",
        phases=["recon"],
        default_args=["-silent"],
        parameters=[
            ToolParameter("target", "Input subdomains (pipe via stdin)"),
            ToolParameter("domain", "Root domain", flag="-d"),
        ],
        timeout=120,
        signal_quality=SignalQuality.CANDIDATE,
    )
)


# ── Scanning phase ──

_register(
    ToolDefinition(
        name="nuclei",
        description="Vulnerability scanner based on YAML templates",
        phases=["scan", "deep_scan"],
        default_args=["-json", "-silent"],
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
        default_args=["--json"],
        parameters=[
            ToolParameter("target", "Target URL", required=True),
            ToolParameter("blind", "Blind XSS mode", flag="-b"),
            ToolParameter("deep_dom", "Deep DOM scanning", flag="--deep-dom"),
        ],
        timeout=600,
        signal_quality=SignalQuality.PROBABLE,
    )
)

_register(
    ToolDefinition(
        name="sqlmap",
        description="SQL injection detection and exploitation",
        phases=["scan", "deep_scan"],
        default_args=["--batch"],
        parameters=[
            ToolParameter("target", "Target URL", flag="-u", required=True),
            ToolParameter("level", "Test level (1-5)", flag="--level", default=1),
            ToolParameter("risk", "Risk level (1-3)", flag="--risk", default=1),
        ],
        timeout=600,
        signal_quality=SignalQuality.PROBABLE,
    )
)

_register(
    ToolDefinition(
        name="arjun",
        description="HTTP parameter discovery",
        phases=["scan"],
        default_args=["-m", "GET"],
        parameters=[
            ToolParameter("target", "Target URL", flag="-u", required=True),
            ToolParameter("threads", "Thread count", flag="-t", default=10),
        ],
        timeout=300,
        signal_quality=SignalQuality.CANDIDATE,
    )
)

_register(
    ToolDefinition(
        name="jwt_tool",
        description="JWT security testing tool",
        phases=["scan"],
        default_args=["-C", "-d"],
        parameters=[
            ToolParameter("target", "Target URL", flag="-u", required=True),
        ],
        timeout=120,
        signal_quality=SignalQuality.PROBABLE,
        requires=ToolRequires(recon_signals=["has_api", "has_login_page"]),
    )
)

_register(
    ToolDefinition(
        name="commix",
        description="Command injection detection",
        phases=["scan"],
        default_args=["--batch"],
        parameters=[
            ToolParameter("target", "Target URL", flag="--url", required=True),
        ],
        timeout=300,
        signal_quality=SignalQuality.PROBABLE,
        requires=ToolRequires(recon_signals=["has_file_upload"]),
    )
)

_register(
    ToolDefinition(
        name="testssl",
        description="TLS/SSL security testing",
        phases=["scan"],
        default_args=[],
        parameters=[
            ToolParameter("target", "Target host:port", required=True),
        ],
        timeout=300,
        signal_quality=SignalQuality.CANDIDATE,
        requires=ToolRequires(target_scheme="https"),
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
        phases=["repo_scan"],
        default_args=["detect", "--verbose", "--no-color"],
        parameters=[
            ToolParameter("target", "Target path", flag="--source", required=True),
            ToolParameter("report_format", "Report format", default="json"),
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
        name="trufflehog",
        description="High-entropy secret scanner for git history",
        phases=["repo_scan"],
        default_args=["git", "--json", "--no-update"],
        parameters=[
            ToolParameter("target", "Target path", required=True),
            ToolParameter("since_commit", "Scan from commit", flag="--since-commit"),
            ToolParameter("max_depth", "Max commit depth", flag="--max-depth"),
        ],
        timeout=600,
        signal_quality=SignalQuality.PROBABLE,
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
    )
)

_register(
    ToolDefinition(
        name="bandit",
        description="Python security linter",
        phases=["repo_scan"],
        default_args=["-f", "json"],
        parameters=[
            ToolParameter("target", "Target path", flag="-r", required=True),
            ToolParameter("severity", "Severity filter", flag="-ll"),
        ],
        timeout=300,
        signal_quality=SignalQuality.PROBABLE,
        requires=ToolRequires(tech_contains=["python"]),
    )
)

_register(
    ToolDefinition(
        name="govulncheck",
        description="Go vulnerability scanner for dependencies",
        phases=["repo_scan"],
        default_args=["./...", "-json"],
        parameters=[
            ToolParameter("target", "Target path (module pattern)", required=True),
        ],
        timeout=300,
        signal_quality=SignalQuality.PROBABLE,
        requires=ToolRequires(tech_contains=["go"]),
    )
)

_register(
    ToolDefinition(
        name="brakeman",
        description="Ruby on Rails security scanner",
        phases=["repo_scan"],
        default_args=["--format", "json"],
        parameters=[
            ToolParameter("target", "Target path", required=True),
            ToolParameter(
                "confidence", "Confidence level", flag="--confidence-level", default="2"
            ),
        ],
        timeout=600,
        signal_quality=SignalQuality.PROBABLE,
        requires=ToolRequires(tech_contains=["ruby"]),
    )
)

_register(
    ToolDefinition(
        name="gosec",
        description="Go security code scanner",
        phases=["repo_scan"],
        default_args=["-fmt=json", "-quiet"],
        parameters=[
            ToolParameter("target", "Target path", required=True),
        ],
        timeout=600,
        signal_quality=SignalQuality.PROBABLE,
        requires=ToolRequires(tech_contains=["go"]),
    )
)

_register(
    ToolDefinition(
        name="eslint",
        description="JavaScript/TypeScript linter with security plugins",
        phases=["repo_scan"],
        default_args=["--format", "json"],
        parameters=[
            ToolParameter("target", "Target path", required=True),
            ToolParameter(
                "ext", "File extensions", flag="--ext", default=".js,.jsx,.ts,.tsx"
            ),
        ],
        timeout=600,
        signal_quality=SignalQuality.PROBABLE,
        requires=ToolRequires(tech_contains=["javascript", "typescript"]),
    )
)

_register(
    ToolDefinition(
        name="phpcs",
        description="PHP CodeSniffer security audit",
        phases=["repo_scan"],
        default_args=["--standard=Security", "--extensions=php", "--report=json"],
        parameters=[
            ToolParameter("target", "Target path", required=True),
        ],
        timeout=600,
        signal_quality=SignalQuality.PROBABLE,
        requires=ToolRequires(tech_contains=["php"]),
    )
)

_register(
    ToolDefinition(
        name="spotbugs",
        description="Java/Kotlin bytecode security scanner with find-sec-bugs",
        phases=["repo_scan"],
        default_args=["-textui", "-low", "-effort:max"],
        parameters=[
            ToolParameter(
                "target", "Target path (JAR/WAR/class directory)", required=True
            ),
        ],
        timeout=600,
        signal_quality=SignalQuality.PROBABLE,
        requires=ToolRequires(tech_contains=["java", "kotlin"]),
    )
)


# ── Specialized tools ──

_register(
    ToolDefinition(
        name="wafw00f",
        description="Web Application Firewall fingerprinting and detection",
        phases=["recon", "scan"],
        binary="wafw00f",
        default_args=["-a"],
        parameters=[
            ToolParameter("target", "Target URL", required=True),
            ToolParameter("verbose", "Enable verbose output", flag="-v"),
        ],
        timeout=120,
        signal_quality=SignalQuality.CONFIRMED,
    )
)

_register(
    ToolDefinition(
        name="wpscan",
        description="WordPress vulnerability scanner",
        phases=["scan"],
        default_args=["-f", "json", "--no-banner"],
        parameters=[
            ToolParameter("target", "WordPress URL", flag="--url", required=True),
            ToolParameter("api_token", "WPScan API token", flag="--api-token"),
        ],
        timeout=600,
        signal_quality=SignalQuality.CANDIDATE,
        requires=ToolRequires(tech_contains=["wordpress", "wp-"]),
    )
)

_register(
    ToolDefinition(
        name="pip-audit",
        description="Python dependency vulnerability scanner (overrides _generated_tools.py)",
        phases=["repo_scan"],
        binary="pip-audit",
        default_args=["--format", "json", "--quiet"],
        parameters=[
            ToolParameter("target", "Audit target path"),
        ],
        timeout=300,
        signal_quality=SignalQuality.CANDIDATE,
        requires=ToolRequires(tech_contains=["python"]),
    )
)

_register(
    ToolDefinition(
        name="dependency_check",
        description="OWASP Dependency-Check for known vulnerability scanning in dependencies (overrides _generated_tools.py)",
        phases=["repo_scan"],
        binary="dependency-check",
        default_args=["--format", "JSON"],
        parameters=[
            ToolParameter("target", "Target project directory", flag="--scan", required=True),
        ],
        timeout=600,
        signal_quality=SignalQuality.CONFIRMED,
    )
)

_register(
    ToolDefinition(
        name="npm-audit",
        description="Node.js dependency vulnerability scanner",
        phases=["repo_scan"],
        default_args=["--json"],
        parameters=[
            ToolParameter("target", "Audit target path"),
        ],
        timeout=300,
        signal_quality=SignalQuality.CANDIDATE,
        requires=ToolRequires(tech_contains=["javascript", "typescript"]),
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
        signal_quality=SignalQuality.PROBABLE,
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
        phases=["repo_scan"],
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
        signal_quality=SignalQuality.PROBABLE,
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
        if not target.startswith(req.target_scheme):
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
            )
        )
    return mcp_tools
