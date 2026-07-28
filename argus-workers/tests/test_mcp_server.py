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
    def setup_method(self) -> None:
        """Patch slow/potentially-hanging initialization steps.
        socket.getaddrinfo can hang on some systems (DNS timeout).
        """
        import mcp_server as ms
        self._orig_getaddrinfo = ms.socket.getaddrinfo
        ms.socket.getaddrinfo = lambda *a, **kw: None  # no-op DNS check

    def teardown_method(self) -> None:
        """Restore original DNS."""
        import mcp_server as ms
        ms.socket.getaddrinfo = self._orig_getaddrinfo

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
    def setup_method(self) -> None:
        """Patch DNS to prevent hang during MCPServer init."""
        import mcp_server as ms
        self._orig_getaddrinfo = ms.socket.getaddrinfo
        ms.socket.getaddrinfo = lambda *a, **kw: None

    def teardown_method(self) -> None:
        """Restore original DNS."""
        import mcp_server as ms
        ms.socket.getaddrinfo = self._orig_getaddrinfo

    def test_singleton(self):
        s1 = get_mcp_server()
        s2 = get_mcp_server()
        assert s1 is s2


# ── Binary availability cache & PATH validation ──


class TestBinaryOnPath:
    """Tests for MCPServer._binary_on_path() and execution-time
    binary validation in call_tool().

    Uses mocker to patch shutil.which() so tests don't hit the
    filesystem (which is extremely slow on Windows).
    """

    def setup_method(self) -> None:
        """Clear the class-level binary cache and patch DNS
        before each test. DNS can hang on some systems.
        """
        MCPServer._binary_cache.clear()
        import mcp_server as ms
        self._orig_getaddrinfo = ms.socket.getaddrinfo
        ms.socket.getaddrinfo = lambda *a, **kw: None

    def teardown_method(self) -> None:
        """Restore original DNS."""
        import mcp_server as ms
        ms.socket.getaddrinfo = self._orig_getaddrinfo

    def make_server(self):
        return MCPServer(tools_dir="/tmp/nonexistent_tools_dir_xyz")

    def test_binary_found(self, mocker):
        """_binary_on_path returns the path when binary exists."""
        mocker.patch("mcp_server.shutil.which", return_value="/usr/bin/nuclei")
        server = self.make_server()
        path = server._binary_on_path("nuclei")
        assert path == "/usr/bin/nuclei"

    def test_binary_not_found(self, mocker):
        """_binary_on_path returns None when binary doesn't exist."""
        mocker.patch("mcp_server.shutil.which", return_value=None)
        server = self.make_server()
        path = server._binary_on_path("nonexistent_tool")
        assert path is None

    def test_binary_cache_hit(self, mocker):
        """Repeated lookups for the same binary hit the cache.

        Uses a non-critical tool name so _check_critical_tools()
        during __init__() doesn't populate the cache for this tool.
        The CRITICAL_TOOLS are looked up during init, so
        mock_which.call_count starts at len(CRITICAL_TOOLS)
        after make_server().
        """
        INIT_TOOL_CHECKS = len(MCPServer.CRITICAL_TOOLS)
        mock_which = mocker.patch("mcp_server.shutil.which", return_value="/usr/bin/my_tool")
        server = self.make_server()
        assert mock_which.call_count == INIT_TOOL_CHECKS

        # First call for a non-critical tool — should call shutil.which
        path1 = server._binary_on_path("my_tool")
        assert path1 == "/usr/bin/my_tool"
        assert mock_which.call_count == INIT_TOOL_CHECKS + 1

        # Second call — should use cache, not call shutil.which again
        path2 = server._binary_on_path("my_tool")
        assert path2 == "/usr/bin/my_tool"
        assert mock_which.call_count == INIT_TOOL_CHECKS + 1  # Still cached

    def test_binary_cache_separate_tools(self, mocker):
        """Different tool names get separate cache entries.

        Uses non-critical tool names (not in CRITICAL_TOOLS) so
        _check_critical_tools() doesn't interfere.
        """
        INIT_TOOL_CHECKS = len(MCPServer.CRITICAL_TOOLS)
        # Provide side_effect for init's calls + 3 test calls
        mock_which = mocker.patch(
            "mcp_server.shutil.which",
            side_effect=(
                # CRITICAL_TOOLS names for init (values don't matter)
                ["/usr/bin/critical"] * INIT_TOOL_CHECKS
                + ["/usr/bin/tool_a", "/usr/bin/tool_b", None]
            ),
        )
        server = self.make_server()
        assert mock_which.call_count == INIT_TOOL_CHECKS

        assert server._binary_on_path("tool_a") == "/usr/bin/tool_a"
        assert server._binary_on_path("tool_b") == "/usr/bin/tool_b"
        assert server._binary_on_path("tool_c") is None
        assert mock_which.call_count == INIT_TOOL_CHECKS + 3

    def test_binary_cache_shared_across_instances(self, mocker):
        """Cache is class-level so different instances share it.

        Uses a non-critical tool name so init's critical tool checks
        don't pollute the cache for this test.
        """
        INIT_TOOL_CHECKS = len(MCPServer.CRITICAL_TOOLS)
        mock_which = mocker.patch("mcp_server.shutil.which", return_value="/usr/bin/my_tool")

        server1 = self.make_server()
        assert mock_which.call_count == INIT_TOOL_CHECKS
        server1._binary_on_path("my_tool")
        assert mock_which.call_count == INIT_TOOL_CHECKS + 1

        server2 = self.make_server()
        server2._binary_on_path("my_tool")
        # Should use server1's cached result — no additional shutil.which calls
        assert mock_which.call_count == INIT_TOOL_CHECKS + 1

    def test_binary_cache_reset(self, mocker):
        """Clearing the class-level cache forces re-lookup.

        Uses a non-critical tool name so init's critical tool checks
        don't pollute the cache for this test.
        """
        INIT_TOOL_CHECKS = len(MCPServer.CRITICAL_TOOLS)
        mock_which = mocker.patch("mcp_server.shutil.which", return_value="/usr/bin/my_tool")
        server = self.make_server()
        assert mock_which.call_count == INIT_TOOL_CHECKS

        # Look up a non-critical tool — should call shutil.which
        server._binary_on_path("my_tool")
        assert mock_which.call_count == INIT_TOOL_CHECKS + 1

        # Clear the cache
        MCPServer._binary_cache.clear()

        # Re-lookup should call shutil.which again
        server._binary_on_path("my_tool")
        assert mock_which.call_count == INIT_TOOL_CHECKS + 2  # Re-fetched

    def test_check_critical_tools_all_found(self, mocker):
        """When all critical tools are on PATH, log info."""
        mocker.patch("mcp_server.shutil.which", return_value="/usr/bin/tool")
        mock_logger = mocker.patch("mcp_server.logger.info")
        server = self.make_server()

        server._check_critical_tools()
        mock_logger.assert_any_call(
            "All %d critical tool(s) are available",
            len(server.CRITICAL_TOOLS),
        )

    def test_check_critical_tools_some_missing(self, mocker):
        """When some critical tools are missing, log warning."""
        # Return None for some critical tools to trigger warning
        which_results = {
            "nuclei": "/usr/bin/nuclei",
            "nmap": None,  # missing
            "sqlmap": "/usr/bin/sqlmap",
            "subfinder": None,  # missing
            "httpx": "/usr/bin/httpx",
            "whatweb": None,  # missing
        }
        mocker.patch(
            "mcp_server.shutil.which",
            side_effect=lambda name, **kw: which_results.get(name),
        )
        mock_logger = mocker.patch("mcp_server.logger.warning")
        server = self.make_server()

        server._check_critical_tools()
        # Should log a warning about missing tools
        assert mock_logger.called
        # call_args[0][0] = "STARTUP GUARD: %s", call_args[0][1] = the formatted msg
        warning_msg = mock_logger.call_args[0][1]
        assert "critical tool(s) missing" in warning_msg


class TestCallToolBinaryValidation:
    """Tests for execution-time binary validation in call_tool()."""

    def setup_method(self) -> None:
        """Clear the class-level binary cache and patch DNS
        before each test. DNS can hang on some systems.
        """
        MCPServer._binary_cache.clear()
        import mcp_server as ms
        self._orig_getaddrinfo = ms.socket.getaddrinfo
        ms.socket.getaddrinfo = lambda *a, **kw: None

    def teardown_method(self) -> None:
        """Restore original DNS."""
        import mcp_server as ms
        ms.socket.getaddrinfo = self._orig_getaddrinfo

    def make_server(self):
        server = MCPServer(tools_dir="/tmp/nonexistent_tools_dir_xyz")
        server.register_tool(ToolDefinition(
            name="nuclei",
            command="nuclei",
            description="Fast vulnerability scanner",
        ))
        return server

    def test_binary_not_found_returns_clean_error(self, mocker):
        """When binary is not on PATH, call_tool returns clean error."""
        mocker.patch("mcp_server.shutil.which", return_value=None)
        server = self.make_server()
        result = server.call_tool("nuclei", {"target": "http://test.com"})
        assert result["isError"] is True
        error_text = result["content"][0]["text"]
        assert "not found on PATH" in error_text
        assert "nuclei" in error_text

    def test_binary_found_proceeds_to_execution(self, mocker):
        """When binary is on PATH, call_tool proceeds to subprocess.

        Uses sys.executable (always available) to verify the happy path.
        """
        import sys
        mocker.patch("mcp_server.shutil.which", return_value=sys.executable)
        server = MCPServer(tools_dir="/tmp/nonexistent_tools_dir_xyz")
        server.register_tool(ToolDefinition(
            name="test",
            command=sys.executable,
            args=["-c", "print('hello')"],
        ))
        result = server.call_tool("test")
        assert result["isError"] is False
        assert "hello" in result["content"][0]["text"]

    def test_python3_tool_skips_binary_check(self, mocker):
        """Python3-based tools skip the binary check entirely."""
        mocker.patch("mcp_server.shutil.which", return_value=None)
        server = MCPServer(tools_dir="/tmp/nonexistent_tools_dir_xyz")
        server.register_tool(ToolDefinition(
            name="agent-tool",
            command="python3",
            args=["-c", "print('hello')"],
        ))
        # Even though shutil.which would fail, python3 tools bypass the check
        # and are executed via the current interpreter
        result = server.call_tool("agent-tool")
        assert result["isError"] is False

    def test_binary_check_cached_per_tool(self, mocker):
        """Binary check is cached so repeated calls for the same tool are fast."""
        import sys
        INIT_TOOL_CHECKS = len(MCPServer.CRITICAL_TOOLS)
        mock_which = mocker.patch("mcp_server.shutil.which", return_value=sys.executable)
        server = MCPServer(tools_dir="/tmp/nonexistent_tools_dir_xyz")
        server.register_tool(ToolDefinition(
            name="test",
            command=sys.executable,
            args=["-c", "print('hello')"],
        ))

        # First call — 6 init calls + 1 binary check = 7
        server.call_tool("test")
        assert mock_which.call_count == INIT_TOOL_CHECKS + 1

        # Second call — should use cached result, no additional shutil.which
        server.call_tool("test")
        # Still INIT_TOOL_CHECKS + 1 — second call used cache
        assert mock_which.call_count == INIT_TOOL_CHECKS + 1


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

    def setup_method(self) -> None:
        """Patch DNS to prevent hang during MCPServer init."""
        import mcp_server as ms
        self._orig_getaddrinfo = ms.socket.getaddrinfo
        ms.socket.getaddrinfo = lambda *a, **kw: None

    def teardown_method(self) -> None:
        """Restore original DNS."""
        import mcp_server as ms
        ms.socket.getaddrinfo = self._orig_getaddrinfo

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
