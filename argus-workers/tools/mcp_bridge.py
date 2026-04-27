"""
MCP Bridge - Connects ToolRunner to the MCP Protocol Server

Allows existing tools to be called via MCP protocol while
maintaining backward compatibility with the current ToolRunner API.
"""
import logging
from typing import Dict, List, Optional
from mcp_server import get_mcp_server, ToolDefinition, ToolSchema
from tools.tool_runner import ToolRunner

logger = logging.getLogger(__name__)


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
        for tool in tools:
            self.mcp.register_tool(tool)
    
    def call_via_mcp(self, tool: str, arguments: Dict = None) -> Dict:
        """
        Call a tool via MCP, falling back to direct ToolRunner.run() if needed.
        """
        return self.mcp.call_tool(tool, arguments or {})
    
    def call_via_runner(self, tool: str, args: List[str], timeout: int = None) -> Dict:
        """Call a tool via the existing ToolRunner."""
        timeout = timeout or 300
        return self.tool_runner.run(tool, args, timeout=timeout)
