"""
MCP Bridge - Connects ToolRunner to the MCP Protocol Server

Allows existing tools to be called via MCP protocol while
maintaining backward compatibility with the current ToolRunner API.
"""
import logging
import os
import shutil

from mcp_server import ToolDefinition, ToolSchema, get_mcp_server
from tools.tool_runner import ToolRunner
from utils.logging_utils import ScanLogger

logger = logging.getLogger(__name__)


def _is_binary_available(binary: str) -> bool:
    """Check if a tool binary is available on the system PATH or in expected locations.

    Args:
        binary: Name of the binary to check (e.g., 'nuclei', 'httpx').

    Returns:
        True if the binary is found, False otherwise.
    """
    # Augmented PATH matching ToolRunner.resolve_tool_path
    venv_bin = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "venv", "bin")
    go_bin = os.path.expanduser("~/go/bin")
    extra_dirs = [
        venv_bin,
        "/usr/local/bin",
        "/opt/homebrew/bin",
        go_bin,
    ]
    current_path = os.environ.get("PATH", "")
    for d in extra_dirs:
        if d not in current_path and os.path.isdir(d):
            current_path = f"{d}:{current_path}"

    resolved = shutil.which(binary, path=current_path)
    if resolved:
        return True
    for d in extra_dirs:
        candidate = os.path.join(d, binary)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return True
    return False


class MCPToolBridge:
    """
    Bridges between the existing ToolRunner and the new MCP protocol.

    Each tool in ToolRunner gets registered with MCP, enabling:
    - Discovery via tools/list
    - Execution via tools/call
    - Streaming output
    - Schema validation
    """

    def __init__(self, tool_runner: ToolRunner, engagement_id: str = None):
        self.tool_runner = tool_runner
        self.engagement_id = engagement_id
        self.mcp = get_mcp_server()
        self._register_tools()

    def _register_tools(self):
        """Register ToolRunner tools with MCP server."""
        slog = ScanLogger("mcp_bridge", engagement_id=self.engagement_id)
        tools = [
            # ── Reconnaissance tools ──
            ToolDefinition("httpx", "httpx",
                description="HTTP probing tool for web service discovery",
                args=["-json", "-silent"],
                parameters=[ToolSchema("target", "string", "Target URL", required=True)],
                timeout=300),
            ToolDefinition("katana", "katana",
                description="Web crawling and endpoint discovery",
                args=["-jsonl", "-silent"],
                parameters=[
                    ToolSchema("target", "string", "Target URL", flag="-u", required=True),
                    ToolSchema("depth", "number", "Crawl depth", flag="-d", default=3),
                ],
                timeout=300),
            ToolDefinition("ffuf", "ffuf",
                description="Web fuzzing tool for directory/parameter discovery",
                args=["-json"],
                parameters=[
                    ToolSchema("target", "string", "Target URL with FUZZ keyword", flag="-u", required=True),
                    ToolSchema("wordlist", "string", "Path to wordlist", flag="-w", required=True),
                    ToolSchema("threads", "number", "Thread count", flag="-t", default=40),
                ],
                timeout=300),
            ToolDefinition("amass", "amass",
                description="Subdomain enumeration and reconnaissance",
                args=["enum", "-json"],
                parameters=[
                    ToolSchema("target", "string", "Target domain", flag="-d", required=True),
                    ToolSchema("brute", "boolean", "Enable brute forcing", flag="-brute"),
                ],
                timeout=600),
            ToolDefinition("naabu", "naabu",
                description="Port scanning tool",
                args=["-json"],
                parameters=[
                    ToolSchema("target", "string", "Target host", flag="-host", required=True),
                    ToolSchema("top_ports", "string", "Top ports to scan", flag="-top-ports"),
                    ToolSchema("port_range", "string", "Port range", flag="-p"),
                ],
                timeout=300),
            ToolDefinition("whatweb", "whatweb",
                description="Web technology fingerprinting",
                args=["--format=json"],
                parameters=[ToolSchema("target", "string", "Target URL", required=True)],
                timeout=120),
            ToolDefinition("nikto", "nikto",
                description="Web server vulnerability scanner",
                args=["-Format", "csv"],
                parameters=[ToolSchema("target", "string", "Target URL", flag="-h", required=True)],
                timeout=300),
            ToolDefinition("gau", "gau",
                description="Get all URLs from web archives",
                args=["--json"],
                parameters=[ToolSchema("target", "string", "Target domain", required=True)],
                timeout=180),
            ToolDefinition("waybackurls", "waybackurls",
                description="Fetch URLs from Wayback Machine",
                args=[],
                parameters=[ToolSchema("target", "string", "Target domain", required=True)],
                timeout=120),
            ToolDefinition("nmap", "nmap",
                description="Network port scanner",
                args=["-oX", "-"],
                parameters=[
                    ToolSchema("target", "string", "Target host", required=True),
                    ToolSchema("ports", "string", "Port range", flag="-p"),
                ],
                timeout=600),
            # ── Scanning tools ──
            ToolDefinition("nuclei", "nuclei",
                description="Vulnerability scanner based on YAML templates",
                args=["-json", "-silent"],
                parameters=[
                    ToolSchema("target", "string", "Target URL", flag="-u", required=True),
                    ToolSchema("severity", "string", "Severity filter", flag="-severity",
                             enum=["info", "low", "medium", "high", "critical"]),
                    ToolSchema("templates", "string", "Custom template directory", flag="-t"),
                    ToolSchema("tags", "string", "Template tags to run", flag="-tags"),
                ],
                timeout=600),
            ToolDefinition("dalfox", "dalfox",
                description="XSS vulnerability scanner",
                args=["--json"],
                parameters=[
                    ToolSchema("target", "string", "Target URL", required=True),
                    ToolSchema("blind", "boolean", "Blind XSS mode", flag="-b"),
                    ToolSchema("deep_dom", "boolean", "Deep DOM scanning", flag="--deep-dom"),
                ],
                timeout=600),
            ToolDefinition("sqlmap", "sqlmap",
                description="SQL injection detection and exploitation",
                args=["--batch"],
                parameters=[
                    ToolSchema("target", "string", "Target URL", flag="-u", required=True),
                    ToolSchema("level", "number", "Test level (1-5)", flag="--level", default=1),
                    ToolSchema("risk", "number", "Risk level (1-3)", flag="--risk", default=1),
                ],
                timeout=600),
            ToolDefinition("arjun", "arjun",
                description="HTTP parameter discovery",
                args=["-m", "GET"],
                parameters=[
                    ToolSchema("target", "string", "Target URL", flag="-u", required=True),
                    ToolSchema("threads", "number", "Thread count", flag="-t", default=10),
                ],
                timeout=300),
            ToolDefinition("jwt_tool", "jwt_tool",
                description="JWT security testing tool",
                args=["-C", "-d"],
                parameters=[ToolSchema("target", "string", "Target URL", flag="-u", required=True)],
                timeout=120),
            ToolDefinition("commix", "commix",
                description="Command injection detection",
                args=["--batch"],
                parameters=[ToolSchema("target", "string", "Target URL", flag="--url", required=True)],
                timeout=300),
            ToolDefinition("testssl", "testssl",
                description="TLS/SSL security testing",
                args=[],
                parameters=[ToolSchema("target", "string", "Target host:port", required=True)],
                timeout=300),
            # ── Repository scanning tools ──
            ToolDefinition("semgrep", "semgrep",
                description="Static code analysis tool",
                args=["--json"],
                parameters=[
                    ToolSchema("target", "string", "Target path", required=True),
                    ToolSchema("config", "string", "Rule config path", flag="--config"),
                ],
                timeout=600),
            ToolDefinition("gitleaks", "gitleaks",
                description="Git repository secret scanning",
                args=["detect", "--verbose", "--no-color"],
                parameters=[
                    ToolSchema("target", "string", "Target path", flag="--source", required=True),
                    ToolSchema("report_format", "string", "Report format", default="json"),
                    ToolSchema("max_target_mb", "number", "Max target size", flag="--max-target-megabytes"),
                ],
                timeout=300),
            ToolDefinition("trivy", "trivy",
                description="Container and filesystem vulnerability scanner",
                args=["fs", "--format", "json", "--skip-dirs", "node_modules,vendor,dist,build,.git,coverage"],
                parameters=[
                    ToolSchema("target", "string", "Image name or path", required=True),
                    ToolSchema("scanners", "string", "Comma-separated scanners", flag="--scanners",
                             default="vuln,misconfig,secret"),
                ],
                timeout=600),
            ToolDefinition("bandit", "bandit",
                description="Python security linter",
                args=["-f", "json"],
                parameters=[
                    ToolSchema("target", "string", "Target path", flag="-r", required=True),
                    ToolSchema("severity", "string", "Severity filter", flag="-ll"),
                ],
                timeout=300),
            # ── Specialized tools ──
            ToolDefinition("gospider", "gospider",
                description="Web spider for endpoint discovery",
                args=["-q", "-j"],
                parameters=[
                    ToolSchema("target", "string", "Target URL", flag="-s", required=True),
                    ToolSchema("depth", "number", "Crawl depth", flag="-d", default=3),
                ],
                timeout=300),
            ToolDefinition("wpscan", "wpscan",
                description="WordPress vulnerability scanner",
                args=["-f", "json", "--no-banner"],
                parameters=[
                    ToolSchema("target", "string", "WordPress URL", flag="--url", required=True),
                    ToolSchema("api_token", "string", "WPScan API token", flag="--api-token"),
                ],
                timeout=600),
            ToolDefinition("pip_audit", "pip-audit",
                description="Python dependency vulnerability scanner",
                args=["--format", "json", "--quiet"],
                parameters=[ToolSchema("target", "string", "Audit target path")],
                timeout=300),
        ]
        registered_count = 0
        skipped_tools = []
        for tool in tools:
            if not _is_binary_available(tool.binary or tool.name):
                skipped_tools.append(tool.name)
                slog.info(f"Skipping tool '{tool.name}' — binary not found on PATH")
                continue
            self.mcp.register_tool(tool)
            registered_count += 1

        if skipped_tools:
            logger.warning(f"Skipped {len(skipped_tools)} unavailable tool(s): {', '.join(skipped_tools)}")
        slog.info(f"Registered {registered_count} tools with MCP ({len(skipped_tools)} skipped)")

    def call_via_mcp(self, tool: str, arguments: dict = None) -> dict:
        """
        Call a tool via MCP, falling back to direct ToolRunner.run() if needed.
        """
        slog = ScanLogger("mcp_bridge", engagement_id=self.engagement_id)
        slog.tool_start(f"mcp_call:{tool}")
        result = self.mcp.call_tool(tool, arguments or {})
        slog.tool_complete(f"mcp_call:{tool}")
        return result

    def call_via_runner(self, tool: str, args: list[str], timeout: int = None) -> dict:
        """Call a tool via the existing ToolRunner."""
        timeout = timeout or 300
        return self.tool_runner.run(tool, args, timeout=timeout)
