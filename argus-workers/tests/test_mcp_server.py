"""Tests for mcp_server.py — MCPServer, ToolSchema, ToolDefinition, MCPToolResult."""

import tempfile
from pathlib import Path

from mcp_server import (
    MCPServer,
    MCPToolResult,
    ToolDefinition,
    ToolSchema,
    get_mcp_server,
)


class TestToolSchema:
    def test_minimal(self):
        ts = ToolSchema(name="target", type="string")
        assert ts.name == "target"
        assert ts.type == "string"
        assert ts.description == ""
        assert ts.required is False
        assert ts.enum == []
        assert ts.default is None
        assert ts.flag is None

    def test_full(self):
        ts = ToolSchema(
            name="target",
            type="string",
            description="The target",
            required=True,
            enum=["a", "b"],
            default="x",
            flag="-u",
        )
        assert ts.required is True
        assert ts.enum == ["a", "b"]
        assert ts.default == "x"
        assert ts.flag == "-u"

    def test_extra_kwargs_ignored(self):
        """Extra kwargs from dict unpacking should not cause TypeError."""
        ts = ToolSchema(name="x", type="string", extra_field="ignored")
        assert ts.name == "x"


class TestToolDefinition:
    def test_minimal(self):
        td = ToolDefinition(name="nuclei", command="nuclei")
        assert td.name == "nuclei"
        assert td.command == "nuclei"
        assert td.enabled is True
        assert td.timeout == 300

    def test_parameters_from_dict(self):
        td = ToolDefinition(
            name="test",
            command="test",
            parameters=[{"name": "target", "type": "string", "required": True}],
        )
        assert len(td.parameters) == 1
        assert td.parameters[0].name == "target"
        assert td.parameters[0].required is True

    def test_to_dict(self):
        td = ToolDefinition(
            name="nmap",
            command="nmap",
            description="Port scanner",
        )
        d = td.to_dict()
        assert d["name"] == "nmap"
        assert d["description"] == "Port scanner"
        assert "inputSchema" in d

    def test_to_dict_with_params(self):
        td = ToolDefinition(
            name="nuclei",
            command="nuclei",
            parameters=[{"name": "target", "type": "string", "required": True}],
        )
        d = td.to_dict()
        assert d["inputSchema"]["required"] == ["target"]
        assert "target" in d["inputSchema"]["properties"]


class TestMCPToolResult:
    def test_success_default(self):
        r = MCPToolResult(success=True, output="ok", tool="nuclei")
        d = r.to_dict()
        assert d["isError"] is False
        assert d["content"][0]["text"] == "ok"
        assert d["meta"]["tool"] == "nuclei"
        assert d["meta"]["success"] is True

    def test_error(self):
        r = MCPToolResult(success=False, error="failed", tool="test")
        d = r.to_dict()
        assert d["isError"] is True
        assert d["content"][0]["text"] == "failed"


class TestMCPServer:
    def test_init(self):
        # Pass a non-existent tools_dir to avoid auto-loading all YAML tool defs
        server = MCPServer(tools_dir="/tmp/nonexistent_tools_dir_xyz")
        assert server._tools == {}
        assert server._execution_stats == {}

    def test_register_tool(self):
        server = MCPServer()
        td = ToolDefinition(name="test", command="test")
        server.register_tool(td)
        assert "test" in server._tools
        assert server._execution_stats["test"]["calls"] == 0

    def test_get_tools_returns_enabled(self):
        server = MCPServer()
        server.register_tool(ToolDefinition(name="enabled", command="e", enabled=True))
        server.register_tool(
            ToolDefinition(name="disabled", command="d", enabled=False)
        )
        tools = server.get_tools()
        names = [t["name"] for t in tools]
        assert "enabled" in names
        assert "disabled" not in names

    def test_get_tool_returns_none_for_missing(self):
        server = MCPServer()
        assert server.get_tool("nonexistent") is None

    def test_call_unknown_tool(self):
        server = MCPServer()
        result = server.call_tool("unknown")
        assert result["isError"] is True
        assert "Unknown tool" in result["content"][0]["text"]

    def test_call_disabled_tool(self):
        server = MCPServer()
        server.register_tool(ToolDefinition(name="off", command="off", enabled=False))
        result = server.call_tool("off")
        assert result["isError"] is True
        assert "disabled" in result["content"][0]["text"]

    def test_call_tool_args_sanitized(self):
        """Shell metacharacters are safe with subprocess list form (no shell=True).
        Only null bytes and control chars are blocked.
        Uses sys.executable (cross-platform) instead of 'echo' (Unix-only).
        """
        import sys
        server = MCPServer()
        td = ToolDefinition(
            name="test",
            command=sys.executable,
            args=["-c", "import sys; print(sys.argv[1])"],
            parameters=[{"name": "target", "type": "string"}],
        )
        server.register_tool(td)
        result = server.call_tool("test", {"target": "hello; rm -rf /"})
        # List-form subprocess (no shell=True) passes args literally — safe
        assert result["isError"] is False

    def test_call_tool_blocks_null_bytes(self):
        """Null bytes in args should be rejected.
        Uses sys.executable (cross-platform) instead of 'echo' (Unix-only).
        """
        import sys
        server = MCPServer()
        td = ToolDefinition(
            name="test",
            command=sys.executable,
            args=["-c", "import sys; print(sys.argv[1])"],
            parameters=[{"name": "msg", "type": "string"}],
        )
        server.register_tool(td)
        result = server.call_tool("test", {"msg": "cat\x00/etc/passwd"})
        assert result["isError"] is True
        assert "shell metacharacters" in result["content"][0]["text"].lower()

    def test_get_stats(self):
        server = MCPServer()
        td = ToolDefinition(name="test", command="test")
        server.register_tool(td)
        stats = server.get_stats()
        assert "test" in stats
        assert stats["test"]["calls"] == 0

    def test_yaml_loading_nonexistent_dir(self):
        """Server should handle missing tools directory gracefully."""
        with tempfile.TemporaryDirectory() as tmp:
            server = MCPServer(tools_dir=str(Path(tmp) / "nonexistent"))
            assert server._tools == {}


class TestGetMCPServer:
    def test_singleton(self):
        s1 = get_mcp_server()
        s2 = get_mcp_server()
        assert s1 is s2


# ── Phase 1.2: _fallback_phase_complete ──────────────────────────────


class TestFallbackPhaseComplete:
    """Tests for MCPServer._fallback_phase_complete()."""

    def test_recon_returns_scan_and_auth(self):
        """recon phase should return VULN_SCAN and AUTH_TEST."""
        result = MCPServer._fallback_phase_complete("recon")
        caps = result["next_capabilities"]
        assert "VULN_SCAN" in caps
        assert "AUTH_TEST" in caps
        assert result["stop"] is False

    def test_scan_returns_deep_scan_and_detection(self):
        """scan phase should return DEEP_SCAN, XSS_DETECTION, SQLI_DETECTION."""
        result = MCPServer._fallback_phase_complete("scan")
        caps = result["next_capabilities"]
        assert "DEEP_SCAN" in caps
        assert "XSS_DETECTION" in caps
        assert "SQLI_DETECTION" in caps
        assert result["stop"] is False

    def test_deep_scan_returns_post_exploit(self):
        """deep_scan phase should return POST_EXPLOIT and EXPLOIT_CHAIN."""
        result = MCPServer._fallback_phase_complete("deep_scan")
        caps = result["next_capabilities"]
        assert "POST_EXPLOIT" in caps
        assert "EXPLOIT_CHAIN" in caps
        assert result["stop"] is False

    def test_repo_scan_returns_vuln_scan(self):
        """repo_scan phase should return VULN_SCAN."""
        result = MCPServer._fallback_phase_complete("repo_scan")
        assert "VULN_SCAN" in result["next_capabilities"]
        assert result["stop"] is False

    def test_analyze_returns_report(self):
        """analyze phase should return REPORT."""
        result = MCPServer._fallback_phase_complete("analyze")
        assert "REPORT" in result["next_capabilities"]
        assert result["stop"] is False

    def test_report_stops(self):
        """report phase should stop the assessment."""
        result = MCPServer._fallback_phase_complete("report")
        assert result["next_capabilities"] == []
        assert result["stop"] is True

    def test_empty_phase_falls_back_to_vuln_scan(self):
        """Empty/unknown phase should return VULN_SCAN and not stop."""
        result = MCPServer._fallback_phase_complete("")
        assert "VULN_SCAN" in result["next_capabilities"]
        assert result["stop"] is False

    def test_critical_findings_add_exploit_capabilities_in_recon(self):
        """CRITICAL findings in recon should add exploit capabilities."""
        findings = [
            {"type": "RCE", "severity": "CRITICAL", "endpoint": "/exec"},
        ]
        result = MCPServer._fallback_phase_complete("recon", findings)
        caps = result["next_capabilities"]
        assert "EXPLOIT_CHAIN" in caps
        assert "POST_EXPLOIT" in caps

    def test_critical_findings_add_exploit_capabilities_in_scan(self):
        """HIGH findings in scan should add exploit capabilities."""
        findings = [
            {"type": "SQL_INJECTION", "severity": "HIGH", "endpoint": "/api"},
        ]
        result = MCPServer._fallback_phase_complete("scan", findings)
        caps = result["next_capabilities"]
        assert "EXPLOIT_CHAIN" in caps
        assert "POST_EXPLOIT" in caps

    def test_low_findings_do_not_add_exploit(self):
        """LOW findings should NOT add exploit capabilities."""
        findings = [
            {"type": "INFO", "severity": "LOW", "endpoint": "/robots.txt"},
        ]
        result = MCPServer._fallback_phase_complete("recon", findings)
        caps = result["next_capabilities"]
        assert "EXPLOIT_CHAIN" not in caps
        assert "POST_EXPLOIT" not in caps

    def test_severity_counts_in_reasoning(self):
        """Reasoning should include severity counts."""
        findings = [
            {"type": "RCE", "severity": "CRITICAL"},
            {"type": "XSS", "severity": "HIGH"},
            {"type": "INFO", "severity": "MEDIUM"},
        ]
        result = MCPServer._fallback_phase_complete("recon", findings)
        reasoning = result["reasoning"]
        assert "1 CRITICAL" in reasoning
        assert "1 HIGH" in reasoning
        assert "1 MEDIUM" in reasoning

    def test_no_duplicate_exploit_capabilities(self):
        """Exploit capabilities should not be duplicated."""
        findings = [{"type": "RCE", "severity": "CRITICAL"}]
        result = MCPServer._fallback_phase_complete("deep_scan", findings)
        caps = result["next_capabilities"]
        # POST_EXPLOIT and EXPLOIT_CHAIN are already in deep_scan's map
        assert caps.count("EXPLOIT_CHAIN") == 1
        assert caps.count("POST_EXPLOIT") == 1


class TestHandlePhaseComplete:
    """Tests for MCPServer.handle_phase_complete().

    Verifies error handling and fallback behavior. LLM integration tests
    require a live API key and are not included here.
    """

    def make_server(self):
        return MCPServer(tools_dir="/tmp/nonexistent_tools_dir_xyz")

    def test_missing_engagement_id(self):
        """Without engagement_id, should return error with stop=True."""
        server = self.make_server()
        result = server.handle_phase_complete({
            "phase": "scan",
            "target": "http://test.com",
        })
        assert result["stop"] is True
        assert "No engagement_id" in result["reasoning"]

    def test_falls_back_on_no_llm_client(self, mocker):
        """When LLMClient() fails, should use _fallback_phase_complete."""
        server = self.make_server()

        mocker.patch("mcp_server.LLMClient", side_effect=Exception("No API key"))
        result = server.handle_phase_complete({
            "engagement_id": "ENG-001",
            "phase": "scan",
        })

        assert "DEEP_SCAN" in result["next_capabilities"]
        assert result["stop"] is False
        assert "Fallback" in result["reasoning"]

    def test_falls_back_when_llm_unavailable(self, mocker):
        """When llm_client.is_available() is False, should use fallback."""
        server = self.make_server()

        mock_client = mocker.MagicMock()
        mock_client.is_available.return_value = False
        mocker.patch("mcp_server.LLMClient", return_value=mock_client)

        result = server.handle_phase_complete({
            "engagement_id": "ENG-002",
            "phase": "deep_scan",
        })

        assert "POST_EXPLOIT" in result["next_capabilities"]
        assert "Fallback" in result["reasoning"]

    def test_passes_findings_to_fallback_on_llm_failure(self, mocker):
        """Findings should be passed to fallback when LLM is unavailable."""
        server = self.make_server()
        findings = [{"type": "RCE", "severity": "CRITICAL"}]

        mock_client = mocker.MagicMock()
        mock_client.is_available.return_value = False
        mocker.patch("mcp_server.LLMClient", return_value=mock_client)

        result = server.handle_phase_complete({
            "engagement_id": "ENG-003",
            "phase": "recon",
            "findings": findings,
        })

        # Critical findings should propagate through fallback
        assert "EXPLOIT_CHAIN" in result["next_capabilities"]
        assert "POST_EXPLOIT" in result["next_capabilities"]

    def test_successful_llm_path(self, mocker):
        """When LLM is available and works, should return LLM result."""
        server = self.make_server()

        mock_client = mocker.MagicMock()
        mock_client.is_available.return_value = True
        mocker.patch("mcp_server.LLMClient", return_value=mock_client)

        # Mock the ReActAgent.plan_next_phase to return a canned result
        expected = {
            "next_capabilities": ["SQLI_DETECTION", "XSS_DETECTION"],
            "reasoning": "LLM found SQL patterns requiring deeper inspection",
            "stop": False,
        }
        mocker.patch(
            "mcp_server.ReActAgent.plan_next_phase",
            return_value=expected,
        )

        result = server.handle_phase_complete({
            "engagement_id": "ENG-004",
            "phase": "scan",
            "target": "http://test.com",
            "findings": [{"type": "SQLI", "severity": "HIGH"}],
        })

        assert result["next_capabilities"] == ["SQLI_DETECTION", "XSS_DETECTION"]
        assert "LLM found" in result["reasoning"]
        assert result["stop"] is False

    def test_llm_exception_falls_back(self, mocker):
        """When plan_next_phase raises, should fall back."""
        server = self.make_server()

        mock_client = mocker.MagicMock()
        mock_client.is_available.return_value = True
        mocker.patch("mcp_server.LLMClient", return_value=mock_client)

        mocker.patch(
            "mcp_server.ReActAgent.plan_next_phase",
            side_effect=Exception("LLM timeout"),
        )

        result = server.handle_phase_complete({
            "engagement_id": "ENG-005",
            "phase": "scan",
        })

        assert "DEEP_SCAN" in result["next_capabilities"]
        assert "Fallback" in result["reasoning"]

    def test_phase_complete_with_report_stops(self, mocker):
        """report phase should stop the assessment even via handle_phase_complete."""
        server = self.make_server()

        mocker.patch("mcp_server.LLMClient", side_effect=Exception("No API key"))
        result = server.handle_phase_complete({
            "engagement_id": "ENG-006",
            "phase": "report",
        })

        assert result["next_capabilities"] == []
        assert result["stop"] is True
