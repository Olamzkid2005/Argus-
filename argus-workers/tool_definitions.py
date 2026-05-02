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

# ── Phase names ──

#: Ordered list of phases (also serves as the type via 'in' checks)
ALL_PHASES = (
    "recon",
    "scan",
    "deep_scan",
    "repo_scan",
    "analyze",
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


# ── Reconnaissance phase ──

_register(ToolDefinition(
    name="httpx",
    description="HTTP probing tool for web service discovery",
    phases=["recon"],
    default_args=["-json", "-silent"],
    parameters=[
        ToolParameter("target", "Target URL", required=True),
    ],
    timeout=300,
))

_register(ToolDefinition(
    name="katana",
    description="Web crawling and endpoint discovery",
    phases=["recon"],
    default_args=["-jsonl", "-silent"],
    parameters=[
        ToolParameter("target", "Target URL", flag="-u", required=True),
        ToolParameter("depth", "Crawl depth", flag="-d", default=3),
    ],
    timeout=300,
))

_register(ToolDefinition(
    name="ffuf",
    description="Web fuzzing tool for directory/parameter discovery",
    phases=["recon", "scan", "deep_scan"],
    default_args=["-json"],
    parameters=[
        ToolParameter("target", "Target URL with FUZZ keyword", flag="-u", required=True),
        ToolParameter("wordlist", "Path to wordlist", flag="-w", required=True),
        ToolParameter("threads", "Thread count", flag="-t", default=40),
    ],
    timeout=300,
))

_register(ToolDefinition(
    name="amass",
    description="Subdomain enumeration and reconnaissance",
    phases=["recon"],
    default_args=["enum", "-json"],
    parameters=[
        ToolParameter("target", "Target domain", flag="-d", required=True),
        ToolParameter("brute", "Enable brute forcing", flag="-brute"),
    ],
    timeout=600,
))

_register(ToolDefinition(
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
))

_register(ToolDefinition(
    name="whatweb",
    description="Web technology fingerprinting",
    phases=["recon"],
    default_args=["--format=json"],
    parameters=[
        ToolParameter("target", "Target URL", required=True),
    ],
    timeout=120,
))

_register(ToolDefinition(
    name="nikto",
    description="Web server vulnerability scanner",
    phases=["recon", "scan", "deep_scan"],
    default_args=["-Format", "csv"],
    parameters=[
        ToolParameter("target", "Target URL", flag="-h", required=True),
    ],
    timeout=300,
))

_register(ToolDefinition(
    name="gau",
    description="Get all URLs from web archives",
    phases=["recon"],
    default_args=["--json"],
    parameters=[
        ToolParameter("target", "Target domain", required=True),
    ],
    timeout=180,
))

_register(ToolDefinition(
    name="waybackurls",
    description="Fetch URLs from Wayback Machine",
    phases=["recon"],
    default_args=[],
    parameters=[
        ToolParameter("target", "Target domain", required=True),
    ],
    timeout=120,
))

_register(ToolDefinition(
    name="nmap",
    description="Network port scanner",
    phases=["recon"],
    default_args=["-oX", "-"],
    parameters=[
        ToolParameter("target", "Target host", required=True),
        ToolParameter("ports", "Port range", flag="-p"),
    ],
    timeout=600,
))

_register(ToolDefinition(
    name="gospider",
    description="Web spider for endpoint discovery",
    phases=["recon"],
    default_args=["-q", "-j"],
    parameters=[
        ToolParameter("target", "Target URL", flag="-s", required=True),
        ToolParameter("depth", "Crawl depth", flag="-d", default=3),
    ],
    timeout=300,
))

_register(ToolDefinition(
    name="subfinder",
    description="Fast passive subdomain enumeration tool",
    phases=["recon"],
    default_args=["-silent"],
    parameters=[
        ToolParameter("target", "Target domain", flag="-d", required=True),
        ToolParameter("all", "Use all sources", flag="-all"),
    ],
    timeout=300,
))

_register(ToolDefinition(
    name="alterx",
    description="Subdomain permutation generator",
    phases=["recon"],
    default_args=["-silent"],
    parameters=[
        ToolParameter("target", "Input subdomains (pipe via stdin)"),
        ToolParameter("domain", "Root domain", flag="-d"),
    ],
    timeout=120,
))


# ── Scanning phase ──

_register(ToolDefinition(
    name="nuclei",
    description="Vulnerability scanner based on YAML templates",
    phases=["scan", "deep_scan"],
    default_args=["-json", "-silent"],
    parameters=[
        ToolParameter("target", "Target URL", flag="-u", required=True),
        ToolParameter("severity", "Severity filter", flag="-severity",
                     enum=["info", "low", "medium", "high", "critical"]),
        ToolParameter("templates", "Custom template directory", flag="-t"),
        ToolParameter("tags", "Template tags to run", flag="-tags"),
    ],
    timeout=600,
))

_register(ToolDefinition(
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
))

_register(ToolDefinition(
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
))

_register(ToolDefinition(
    name="arjun",
    description="HTTP parameter discovery",
    phases=["scan"],
    default_args=["-m", "GET"],
    parameters=[
        ToolParameter("target", "Target URL", flag="-u", required=True),
        ToolParameter("threads", "Thread count", flag="-t", default=10),
    ],
    timeout=300,
))

_register(ToolDefinition(
    name="jwt_tool",
    description="JWT security testing tool",
    phases=["scan"],
    default_args=["-C", "-d"],
    parameters=[
        ToolParameter("target", "Target URL", flag="-u", required=True),
    ],
    timeout=120,
))

_register(ToolDefinition(
    name="commix",
    description="Command injection detection",
    phases=["scan"],
    default_args=["--batch"],
    parameters=[
        ToolParameter("target", "Target URL", flag="--url", required=True),
    ],
    timeout=300,
))

_register(ToolDefinition(
    name="testssl",
    description="TLS/SSL security testing",
    phases=["scan"],
    default_args=[],
    parameters=[
        ToolParameter("target", "Target host:port", required=True),
    ],
    timeout=300,
))


# ── Repository scanning phase ──

_register(ToolDefinition(
    name="semgrep",
    description="Static code analysis tool",
    phases=["repo_scan"],
    default_args=["--json"],
    parameters=[
        ToolParameter("target", "Target path", required=True),
        ToolParameter("config", "Rule config path", flag="--config"),
    ],
    timeout=600,
))

_register(ToolDefinition(
    name="gitleaks",
    description="Git repository secret scanning",
    phases=["repo_scan"],
    default_args=["detect", "--verbose", "--no-color"],
    parameters=[
        ToolParameter("target", "Target path", flag="--source", required=True),
        ToolParameter("report_format", "Report format", default="json"),
        ToolParameter("max_target_mb", "Max target size", flag="--max-target-megabytes"),
    ],
    timeout=300,
))

_register(ToolDefinition(
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
))

_register(ToolDefinition(
    name="trivy",
    description="Container and filesystem vulnerability scanner",
    phases=["repo_scan"],
    default_args=["fs", "--format", "json",
                  "--skip-dirs", "node_modules,vendor,dist,build,.git,coverage"],
    parameters=[
        ToolParameter("target", "Image name or path", required=True),
        ToolParameter("scanners", "Comma-separated scanners", flag="--scanners",
                     default="vuln,misconfig,secret"),
    ],
    timeout=600,
))

_register(ToolDefinition(
    name="bandit",
    description="Python security linter",
    phases=["repo_scan"],
    default_args=["-f", "json"],
    parameters=[
        ToolParameter("target", "Target path", flag="-r", required=True),
        ToolParameter("severity", "Severity filter", flag="-ll"),
    ],
    timeout=300,
))

_register(ToolDefinition(
    name="brakeman",
    description="Ruby on Rails security scanner",
    phases=["repo_scan"],
    default_args=["--format", "json"],
    parameters=[
        ToolParameter("target", "Target path", required=True),
        ToolParameter("confidence", "Confidence level", flag="--confidence-level", default="2"),
    ],
    timeout=600,
))

_register(ToolDefinition(
    name="gosec",
    description="Go security code scanner",
    phases=["repo_scan"],
    default_args=["-fmt=json", "-quiet"],
    parameters=[
        ToolParameter("target", "Target path", required=True),
    ],
    timeout=600,
))

_register(ToolDefinition(
    name="eslint",
    description="JavaScript/TypeScript linter with security plugins",
    phases=["repo_scan"],
    default_args=["--format", "json"],
    parameters=[
        ToolParameter("target", "Target path", required=True),
        ToolParameter("ext", "File extensions", flag="--ext", default=".js,.jsx,.ts,.tsx"),
    ],
    timeout=600,
))

_register(ToolDefinition(
    name="phpcs",
    description="PHP CodeSniffer security audit",
    phases=["repo_scan"],
    default_args=["--standard=Security", "--extensions=php", "--report=json"],
    parameters=[
        ToolParameter("target", "Target path", required=True),
    ],
    timeout=600,
))

_register(ToolDefinition(
    name="spotbugs",
    description="Java/Kotlin bytecode security scanner with find-sec-bugs",
    phases=["repo_scan"],
    default_args=["-textui", "-low", "-effort:max"],
    parameters=[
        ToolParameter("target", "Target path (JAR/WAR/class directory)", required=True),
    ],
    timeout=600,
))


# ── Specialized tools ──

_register(ToolDefinition(
    name="wpscan",
    description="WordPress vulnerability scanner",
    phases=["scan"],
    default_args=["-f", "json", "--no-banner"],
    parameters=[
        ToolParameter("target", "WordPress URL", flag="--url", required=True),
        ToolParameter("api_token", "WPScan API token", flag="--api-token"),
    ],
    timeout=600,
))

_register(ToolDefinition(
    name="pip_audit",
    description="Python dependency vulnerability scanner",
    phases=["repo_scan", "scan"],
    default_args=["--format", "json", "--quiet"],
    parameters=[
        ToolParameter("target", "Audit target path"),
    ],
    timeout=300,
))

_register(ToolDefinition(
    name="npm-audit",
    description="Node.js dependency vulnerability scanner",
    phases=["repo_scan"],
    default_args=["--json"],
    parameters=[
        ToolParameter("target", "Audit target path"),
    ],
    timeout=300,
))

# ── Analysis / intelligence phase ──

_register(ToolDefinition(
    name="intelligence-engine",
    description="LLM-powered findings analysis and correlation",
    phases=["analyze"],
    default_args=[],
    parameters=[
        ToolParameter("engagement_id", "Engagement ID to analyze", required=True),
    ],
    timeout=600,
    model_tier="medium",
))

_register(ToolDefinition(
    name="attack-graph",
    description="Build attack graph from findings",
    phases=["analyze"],
    default_args=[],
    parameters=[
        ToolParameter("engagement_id", "Engagement ID", required=True),
    ],
    timeout=300,
))

# ── Reporting phase ──

_register(ToolDefinition(
    name="report-generator",
    description="Generate executive security report",
    phases=["report"],
    default_args=[],
    parameters=[
        ToolParameter("engagement_id", "Engagement ID", required=True),
        ToolParameter("format", "Report format", default="markdown",
                     enum=["markdown", "pdf", "html"]),
    ],
    timeout=300,
    model_tier="small",
))

_register(ToolDefinition(
    name="compliance-check",
    description="Check findings against compliance frameworks (SOC 2, HIPAA, PCI)",
    phases=["report"],
    default_args=[],
    parameters=[
        ToolParameter("engagement_id", "Engagement ID", required=True),
        ToolParameter("framework", "Compliance framework",
                     default="soc2", enum=["soc2", "hipaa", "pci"]),
    ],
    timeout=120,
))


# ═══════════════════════════════════════════════════════════════
# Helper functions
# ═══════════════════════════════════════════════════════════════

# Frozen dict to prevent runtime modification

# Register the definitions module
TOOLS_DEFINED = list(TOOLS.keys())


def get_tools_for_phase(phase: PhaseName) -> list[ToolDefinition]:
    """Get all tool definitions for a given phase.

    Args:
        phase: Phase name (e.g., "recon", "scan").

    Returns:
        List of ToolDefinition objects for that phase.
    """
    return [
        tool for tool in TOOLS.values()
        if phase in tool.phases
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
    return [
        tool.name for tool in get_tools_for_phase(phase)
    ]


def build_phase_tools_dict() -> dict[str, list[str]]:
    """Build the PHASE_TOOLS dict expected by ReActAgent.

    Returns:
        Dict mapping phase names to tool name lists.
    """
    return {
        phase: get_phase_tool_names(phase)
        for phase in ALL_PHASES
    }


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
        mcp_tools.append(MCPToolDef(
            name=tool.name,
            command=tool.binary or tool.name,
            description=tool.description,
            args=list(tool.default_args),
            parameters=schema_params,
            timeout=tool.timeout,
        ))
    return mcp_tools
