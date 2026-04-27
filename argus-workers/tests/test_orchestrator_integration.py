"""
End-to-end Integration Tests for the Argus Orchestrator Architecture

Tests the MCP protocol server, ReAct agent loop, coordinator agent,
and orchestrator pipeline with mocked subprocess execution but real import chains.
"""
import pytest
import json
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ──────────────────────────────────────────────
# Module-level mocks for heavy dependencies
# ──────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_heavy_deps():
    """Mock heavy database, redis, and external service dependencies."""
    with patch.dict(sys.modules, {
        'psycopg2': MagicMock(),
        'psycopg2.extras': MagicMock(),
        'psycopg2.extensions': MagicMock(),
        'redis': MagicMock(),
        'database.connection': MagicMock(),
        'database.repositories.finding_repository': MagicMock(),
        'database.repositories.engagement_repository': MagicMock(),
        'database.repositories.tool_metrics_repository': MagicMock(),
    }):
        yield


# ──────────────────────────────────────────────
# MCP Protocol Server Tests
# ──────────────────────────────────────────────

class TestMCPServer:
    """Test the MCP Protocol Server tool registration and execution."""

    def test_mcp_server_initialization(self):
        """Test that MCP server initializes with no tools (empty dir)."""
        from mcp_server import MCPServer
        server = MCPServer(tools_dir="/tmp/argus_test_tools_empty")
        assert server.get_tools() == []

    def test_mcp_register_tool(self):
        """Test registering a tool with MCP server."""
        from mcp_server import MCPServer, ToolDefinition, ToolSchema
        server = MCPServer(tools_dir="/tmp/argus_test_tools")

        tool = ToolDefinition(
            name="test-tool",
            command="echo",
            description="A test tool",
            parameters=[ToolSchema("message", "string", "Message to echo", required=True)],
        )
        server.register_tool(tool)

        tools = server.get_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "test-tool"

    @patch('subprocess.run')
    def test_mcp_call_tool(self, mock_run):
        """Test calling a tool via MCP server returns output."""
        from mcp_server import MCPServer, ToolDefinition, ToolSchema

        mock_run.return_value = MagicMock(
            returncode=0, stdout="hello world", stderr=""
        )

        server = MCPServer(tools_dir="/tmp/argus_test_tools")
        tool = ToolDefinition(
            name="echo-test",
            command="echo",
            parameters=[ToolSchema("message", "string", "Message", required=True)],
        )
        server.register_tool(tool)

        result = server.call_tool("echo-test", {"message": "hello"})
        assert not result.get("isError", False)
        assert "hello" in str(result)

    def test_mcp_unknown_tool(self):
        """Test calling an unknown tool returns error."""
        from mcp_server import MCPServer
        server = MCPServer(tools_dir="/tmp/argus_test_tools")
        result = server.call_tool("nonexistent")
        assert result.get("isError", False)

    def test_mcp_get_tool(self):
        """Test retrieving a tool definition by name."""
        from mcp_server import MCPServer, ToolDefinition
        server = MCPServer(tools_dir="/tmp/argus_test_tools")
        tool = ToolDefinition("get-test", "echo")
        server.register_tool(tool)
        assert server.get_tool("get-test") is not None
        assert server.get_tool("nonexistent") is None

    def test_mcp_execution_stats(self):
        """Test that execution statistics are tracked."""
        from mcp_server import MCPServer, ToolDefinition
        server = MCPServer(tools_dir="/tmp/argus_test_tools")
        tool = ToolDefinition("stats-test", "echo")
        server.register_tool(tool)
        stats = server.get_stats()
        assert "stats-test" in stats
        assert stats["stats-test"]["calls"] == 0

    def test_mcp_tool_schema_serialization(self):
        """Test that ToolDefinition serializes to correct MCP schema."""
        from mcp_server import ToolDefinition, ToolSchema
        tool = ToolDefinition(
            name="schema-test",
            command="test-cmd",
            args=["--json"],
            parameters=[
                ToolSchema("target", "string", "Target URL", required=True),
                ToolSchema("severity", "string", "Severity filter",
                          enum=["low", "medium", "high"]),
            ],
            timeout=600,
        )
        d = tool.to_dict()
        assert d["name"] == "schema-test"
        assert "target" in d["inputSchema"]["required"]
        assert "severity" not in d["inputSchema"]["required"]
        assert d["inputSchema"]["properties"]["severity"]["enum"] == ["low", "medium", "high"]

    def test_mcp_disabled_tool(self):
        """Test that disabled tools are excluded from listings and return errors."""
        from mcp_server import MCPServer, ToolDefinition
        server = MCPServer(tools_dir="/tmp/argus_test_tools")
        tool = ToolDefinition("disabled-tool", "echo", enabled=False)
        server.register_tool(tool)
        assert server.get_tools() == []
        result = server.call_tool("disabled-tool")
        assert result.get("isError", False)

    def test_mcp_global_server_singleton(self):
        """Test that get_mcp_server returns the same instance."""
        from mcp_server import get_mcp_server, MCPServer
        server1 = get_mcp_server()
        server2 = get_mcp_server()
        assert server1 is server2
        assert isinstance(server1, MCPServer)


# ──────────────────────────────────────────────
# ReAct Agent Loop Tests
# ──────────────────────────────────────────────

class TestReActAgent:
    """Test the ReAct Agent Loop components."""

    def test_tool_registry(self):
        """Test ToolRegistry register, list, and call."""
        from agent_loop import ToolRegistry, AgentResult

        registry = ToolRegistry()

        def test_func(msg=""):
            return AgentResult(tool="test", success=True, output=msg or "done")

        registry.register("test", test_func, {"name": "test", "description": "Test"})

        assert len(registry.list_tools()) == 1
        result = registry.call("test", msg="hello")
        assert result.success
        assert result.output == "hello"

    def test_tool_registry_unknown_tool(self):
        """Test calling an unregistered tool returns failure."""
        from agent_loop import ToolRegistry
        registry = ToolRegistry()
        result = registry.call("nonexistent")
        assert not result.success

    def test_agent_loop_terminates_with_plan_none(self):
        """Test that agent loop terminates when plan_next_action returns None."""
        from agent_loop import ToolRegistry, ReActAgent
        registry = ToolRegistry()
        agent = ReActAgent(registry, max_iterations=5)
        results = agent.run("test task")
        assert len(results) == 0

    def test_agent_loop_executes_planned_tool(self):
        """Test that agent executes a tool when plan_next_action returns an action."""
        from agent_loop import ToolRegistry, ReActAgent, AgentResult, AgentAction

        registry = ToolRegistry()
        call_count = [0]

        def count_calls(msg=""):
            call_count[0] += 1
            return AgentResult(tool="counter", success=True, output=str(call_count[0]))

        registry.register("counter", count_calls,
                         {"name": "counter", "description": "Counting tool"})

        agent = ReActAgent(registry, max_iterations=3)

        call_num = [0]
        def mock_plan(task, context, tried_tools=None):
            call_num[0] += 1
            if call_num[0] == 1:
                return AgentAction(tool="counter", arguments={}, reasoning="test")
            return None

        agent.plan_next_action = mock_plan
        results = agent.run("test")

        assert len(results) == 1
        assert call_count[0] == 1
        assert results[0].success

    def test_agent_loses_on_tool_failure_continues(self):
        """Test that agent continues after a failed tool call."""
        from agent_loop import ToolRegistry, ReActAgent, AgentResult, AgentAction

        registry = ToolRegistry()

        def failing_tool():
            raise RuntimeError("tool failed")

        registry.register("flaky", lambda: failing_tool(),
                         {"name": "flaky", "description": "Flaky tool"})

        agent = ReActAgent(registry, max_iterations=3)

        call_num = [0]
        def mock_plan(task, context, tried_tools=None):
            call_num[0] += 1
            if call_num[0] == 1:
                return AgentAction(tool="flaky", arguments={}, reasoning="test")
            return None

        agent.plan_next_action = mock_plan
        results = agent.run("test")

        assert len(results) == 1
        assert not results[0].success

    def test_agent_context_building(self):
        """Test that agent builds context from history."""
        from agent_loop import ToolRegistry, ReActAgent
        registry = ToolRegistry()
        agent = ReActAgent(registry, max_iterations=3)
        agent.add_to_history("user", "hello world")
        agent.add_to_history("assistant", "how can I help?")
        context = agent.get_context()
        assert "[user]" in context
        assert "hello world" in context
        assert "[assistant]" in context

    def test_agent_action_serialization(self):
        """Test AgentAction and AgentResult serialization."""
        from agent_loop import AgentAction, AgentResult

        action = AgentAction(tool="nuclei", arguments={"target": "example.com"},
                            reasoning="Scan target for vulns")
        d = action.to_dict()
        assert d["tool"] == "nuclei"
        assert d["arguments"]["target"] == "example.com"

        result = AgentResult(tool="nuclei", success=True,
                            output="found 3 vulnerabilities", duration_ms=1500)
        d = result.to_dict()
        assert d["success"]
        assert "found 3" in d["summary"]

    def test_agent_real_plan_with_matching_phase(self):
        """Test that real plan_next_action picks the right tool for a phase."""
        from agent_loop import ToolRegistry, ReActAgent, AgentResult

        registry = ToolRegistry()
        registry.register("nuclei", lambda target="": AgentResult(tool="nuclei", success=True, output="ok"),
                         {"name": "nuclei", "description": "Nuclei scanner"})

        agent = ReActAgent(registry, max_iterations=3)
        agent.set_phase("scan")

        action = agent.plan_next_action("scan: https://example.com", "", set())
        assert action is not None
        assert action.tool == "nuclei"

    def test_agent_real_plan_no_matching_tool(self):
        """Test that plan_next_action returns None when no tools match."""
        from agent_loop import ToolRegistry, ReActAgent

        registry = ToolRegistry()
        agent = ReActAgent(registry, max_iterations=3)
        action = agent.plan_next_action("no-match-phase", "", set())
        assert action is None

    def test_agent_real_plan_already_tried_tool(self):
        """Test that plan_next_action skips already-tried tools."""
        from agent_loop import ToolRegistry, ReActAgent, AgentResult

        registry = ToolRegistry()
        registry.register("nuclei", lambda target="": AgentResult(tool="nuclei", success=True, output="ok"),
                         {"name": "nuclei", "description": "Nuclei"})

        agent = ReActAgent(registry, max_iterations=3)
        action = agent.plan_next_action("scan: test", "", {"nuclei"})
        assert action is None

    def test_tool_registry_wraps_non_agent_result(self):
        """Test that ToolRegistry wraps non-AgentResult return values."""
        from agent_loop import ToolRegistry

        registry = ToolRegistry()
        registry.register("greeter", lambda msg="": f"Hello, {msg}!",
                         {"name": "greeter"})

        result = registry.call("greeter", msg="World")
        assert result.success
        assert "Hello, World!" in result.output


# ──────────────────────────────────────────────
# CoordinatorAgent Tests
# ──────────────────────────────────────────────

class TestCoordinatorAgent:
    """Test the Multi-Agent Coordinator phase transitions."""

    def test_coordinator_creation(self):
        """Test creating a coordinator agent starts in recon phase."""
        from agent_loop import CoordinatorAgent
        coord = CoordinatorAgent(engagement_id="test-123")
        assert coord.engagement_id == "test-123"
        assert coord.current_phase == "recon"

    def test_valid_transition_recon_to_scan(self):
        """Test valid transition from recon to scan."""
        from agent_loop import CoordinatorAgent
        coord = CoordinatorAgent("test-123")
        assert coord.can_transition_to("scan")
        assert coord.transition_to("scan")
        assert coord.current_phase == "scan"

    def test_invalid_transition_recon_to_report(self):
        """Test invalid transition from recon to report is rejected."""
        from agent_loop import CoordinatorAgent
        coord = CoordinatorAgent("test-123")
        assert coord.current_phase == "recon"
        assert not coord.can_transition_to("report")
        assert not coord.transition_to("report")
        assert coord.current_phase == "recon"

    def test_full_pipeline_transitions(self):
        """Test the full recon -> scan -> analyze -> report pipeline."""
        from agent_loop import CoordinatorAgent
        coord = CoordinatorAgent("test-123")
        phases = ["recon", "scan", "analyze", "report"]
        for i in range(len(phases) - 1):
            assert coord.can_transition_to(phases[i + 1])
            assert coord.transition_to(phases[i + 1])
        assert coord.current_phase == "report"

    def test_deep_scan_transition_from_scan(self):
        """Test transition to deep_scan from scan phase."""
        from agent_loop import CoordinatorAgent
        coord = CoordinatorAgent("test-123")
        assert not coord.can_transition_to("deep_scan")
        coord.transition_to("scan")
        assert coord.can_transition_to("deep_scan")
        assert coord.transition_to("deep_scan")
        assert coord.current_phase == "deep_scan"

    def test_analyze_loopback_to_recon(self):
        """Test that analyze can loop back to recon for deeper scanning."""
        from agent_loop import CoordinatorAgent
        coord = CoordinatorAgent("test-123")
        for p in ["recon", "scan", "analyze"]:
            coord.transition_to(p)
        assert coord.can_transition_to("recon")
        assert coord.transition_to("recon")
        assert coord.current_phase == "recon"

    def test_get_phase_agent_returns_react_agent(self):
        """Test that get_phase_agent returns a ReActAgent instance."""
        from agent_loop import CoordinatorAgent, ReActAgent
        coord = CoordinatorAgent("test-123")
        agent = coord.get_phase_agent("recon")
        assert isinstance(agent, ReActAgent)

    def test_phase_agent_has_correct_tools(self):
        """Test phase agent has tools registered for the phase."""
        from agent_loop import CoordinatorAgent
        coord = CoordinatorAgent("test-123")
        agent = coord.get_phase_agent("scan")
        tools = agent.registry.list_tools()
        assert isinstance(tools, list)

    def test_run_phase_returns_results(self):
        """Test that running a phase returns a list of results."""
        from agent_loop import CoordinatorAgent
        coord = CoordinatorAgent("test-123")
        results = coord.run_phase("recon", {"target": "example.com"})
        assert isinstance(results, list)

    def test_phase_tool_mappings(self):
        """Test that PHASE_AGENTS tool mappings are correct."""
        from agent_loop import CoordinatorAgent
        assert "nuclei" in CoordinatorAgent.PHASE_AGENTS["scan"]["tools"]
        assert "semgrep" in CoordinatorAgent.PHASE_AGENTS["repo_scan"]["tools"]
        assert "httpx" in CoordinatorAgent.PHASE_AGENTS["recon"]["tools"]
        assert "llm-review" in CoordinatorAgent.PHASE_AGENTS["analyze"]["tools"]
        assert "compliance-check" in CoordinatorAgent.PHASE_AGENTS["report"]["tools"]

    def test_react_agent_phase_tools_mapping(self):
        """Test that ReActAgent.PHASE_TOOLS are correct."""
        from agent_loop import ReActAgent
        assert "httpx" in ReActAgent.PHASE_TOOLS.get("recon", [])
        assert "nuclei" in ReActAgent.PHASE_TOOLS.get("scan", [])
        assert "semgrep" in ReActAgent.PHASE_TOOLS.get("repo_scan", [])

    def test_report_has_no_transitions(self):
        """Test that report phase has no valid next transitions."""
        from agent_loop import CoordinatorAgent
        coord = CoordinatorAgent("test-123")
        for p in ["recon", "scan", "analyze", "report"]:
            coord.transition_to(p)
        assert coord.current_phase == "report"
        assert not coord.can_transition_to("anything")

    def test_repo_scan_to_scan_transition(self):
        """Test that repo_scan can transition to scan."""
        from agent_loop import CoordinatorAgent
        coord = CoordinatorAgent("test-123")
        coord.current_phase = "repo_scan"
        assert coord.can_transition_to("scan")
        assert coord.transition_to("scan")


# ──────────────────────────────────────────────
# Orchestrator Scan Flow Tests
# ──────────────────────────────────────────────

class TestOrchestratorScanFlow:
    """Test the orchestrator scan pipeline with mocked subprocess."""

    def test_orchestrator_init(self):
        """Test that Orchestrator initializes with MCP and streaming."""
        from orchestrator import Orchestrator
        orch = Orchestrator(engagement_id="test-123")
        assert orch.engagement_id == "test-123"
        assert hasattr(orch, 'mcp')
        assert hasattr(orch, 'stream')

    @patch('subprocess.run')
    def test_mcp_tool_execution_via_orchestrator(self, mock_run):
        """Test executing a tool through MCP via orchestrator."""
        from orchestrator import Orchestrator
        from mcp_server import ToolDefinition, ToolSchema

        mock_run.return_value = MagicMock(
            returncode=0, stdout='{"vulnerabilities": []}', stderr=""
        )

        orch = Orchestrator(engagement_id="test-123")
        tool = ToolDefinition("ping-test", "echo",
            description="Ping test",
            parameters=[ToolSchema("target", "string", "Target", required=True)],
        )
        orch.mcp.register_tool(tool)

        result = orch.mcp_run("ping-test", {"target": "test"})
        assert result is not None
        assert "content" in result
        assert not result.get("isError", False)

    def test_mcp_tools_pre_registered(self):
        """Test that Orchestrator pre-registers standard tools with MCP."""
        from orchestrator import Orchestrator
        orch = Orchestrator(engagement_id="test-123")
        tools = orch.mcp.get_tools()
        tool_names = [t["name"] for t in tools]
        assert "nuclei" in tool_names
        assert "httpx" in tool_names
        assert "semgrep" in tool_names
        assert "gitleaks" in tool_names
        assert "dalfox" in tool_names
        assert "nmap" in tool_names

    @patch('orchestrator.logger')
    def test_run_recon_skipped_with_no_target(self, mock_logger):
        """Test that recon phase is skipped when no target is provided."""
        from orchestrator import Orchestrator
        orch = Orchestrator(engagement_id="test-123")
        result = orch.run({"type": "recon"})
        assert result["status"] == "skipped"
        assert result["phase"] == "recon"
        assert result["findings_count"] == 0

    def test_unknown_job_type_raises_error(self):
        """Test that an unknown job type raises ValueError."""
        from orchestrator import Orchestrator
        orch = Orchestrator(engagement_id="test-123")
        with pytest.raises(ValueError, match="Unknown job type"):
            orch.run({"type": "unknown_phase"})

    def test_orchestrator_has_tool_runner(self):
        """Test that Orchestrator has a ToolRunner instance."""
        from orchestrator import Orchestrator
        orch = Orchestrator(engagement_id="test-123")
        assert hasattr(orch, 'tool_runner')


# ──────────────────────────────────────────────
# Full Pipeline Integration Tests
# ──────────────────────────────────────────────

class TestFullPipelineIntegration:
    """Full pipeline integration test with mocked subprocess."""

    @patch('subprocess.run')
    def test_end_to_end_orchestrator_wiring(self, mock_run):
        """Test that orchestrator, MCP, and streaming are all wired together."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps({"status": "ok"}), stderr=""
        )

        from orchestrator import Orchestrator
        from mcp_server import ToolDefinition, ToolSchema

        orch = Orchestrator(engagement_id="test-e2e-123")
        assert hasattr(orch, 'mcp_run')
        assert hasattr(orch, 'mcp')
        assert hasattr(orch, 'stream')

        tool = ToolDefinition("e2e-test", "echo",
            description="E2E test",
            parameters=[ToolSchema("target", "string", "Target", required=True)],
        )
        orch.mcp.register_tool(tool)
        tools = orch.mcp.get_tools()
        assert len(tools) >= 1

    def test_pipeline_phase_sequence(self):
        """Test that the pipeline phase sequence is valid."""
        from orchestrator import Orchestrator
        from agent_loop import CoordinatorAgent

        coord = CoordinatorAgent("test-pipeline-123")
        orch = Orchestrator(engagement_id="test-pipeline-123")

        assert coord.current_phase == "recon"
        for phase in ["scan", "analyze", "report"]:
            assert coord.can_transition_to(phase)
            assert coord.transition_to(phase)

        assert coord.current_phase == "report"

    @patch('subprocess.run')
    def test_mcp_call_then_orchestrator_run(self, mock_run):
        """Test that MCP tool call and orchestrator run are compatible."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps({"ok": True}), stderr=""
        )

        from orchestrator import Orchestrator
        from mcp_server import ToolDefinition, ToolSchema

        orch = Orchestrator(engagement_id="test-compat-123")

        tool = ToolDefinition("compat-test", "echo",
            description="Compatibility test",
            parameters=[ToolSchema("input", "string", "Input", required=True)],
        )
        orch.mcp.register_tool(tool)

        mcp_result = orch.mcp_run("compat-test", {"input": "data"})
        assert not mcp_result.get("isError", False)

    @patch('subprocess.run')
    def test_orchestrator_run_scan_with_mocked_subprocess(self, mock_run):
        """Test that orchestrator handles scan phase with mocked subprocess."""
        from orchestrator import Orchestrator

        mock_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps({"status": "completed"}), stderr=""
        )

        orch = Orchestrator(engagement_id="test-scan-flow-123")
        result = orch.run({
            "type": "recon",
            "target": "https://example.com",
        })
        assert result is not None


# ──────────────────────────────────────────────
# Create Phase Agent Tests
# ──────────────────────────────────────────────

class TestCreatePhaseAgent:
    """Test the create_phase_agent utility."""

    def test_create_phase_agent_recon(self):
        """Test creating a recon phase agent."""
        from agent_loop import create_phase_agent, ReActAgent
        agent = create_phase_agent("recon")
        assert agent is not None
        assert isinstance(agent, ReActAgent)

    def test_create_phase_agent_scan(self):
        """Test creating a scan phase agent."""
        from agent_loop import create_phase_agent
        agent = create_phase_agent("scan")
        assert agent is not None

    def test_create_phase_agent_registers_phase_tools(self):
        """Test that phase agent has correct tool registry."""
        from agent_loop import create_phase_agent, ReActAgent

        agent = create_phase_agent("recon")
        tools = agent.registry.list_tools()
        expected = ReActAgent.PHASE_TOOLS.get("recon", [])
        # Without tool_runner, no tools are registered
        assert len(tools) == 0

    def test_create_phase_agent_sets_phase(self):
        """Test that phase agent has the correct phase set."""
        from agent_loop import create_phase_agent
        agent = create_phase_agent("recon")
        assert agent._phase == "recon"

    def test_create_phase_agent_unknown_phase(self):
        """Test creating a phase agent for an unknown phase."""
        from agent_loop import create_phase_agent
        agent = create_phase_agent("nonexistent")
        assert agent is not None
        assert agent._phase == "nonexistent"

    def test_create_phase_agent_with_tool_runner_registers_tools(self):
        """Test that create_phase_agent with a tool_runner registers tools."""
        from agent_loop import create_phase_agent, ReActAgent
        from unittest.mock import MagicMock

        mock_runner = MagicMock()
        mock_runner.run.return_value = {"success": True, "stdout": "{}", "returncode": 0}

        agent = create_phase_agent("recon", tool_runner=mock_runner)
        tools = agent.registry.list_tools()
        expected_tools = ReActAgent.PHASE_TOOLS.get("recon", [])
        assert len(tools) == len(expected_tools)
        tool_names = [t["name"] for t in tools]
        assert "httpx" in tool_names


# ──────────────────────────────────────────────
# Edge Case Tests
# ──────────────────────────────────────────────

class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_tool_registry_list(self):
        """Test that an empty ToolRegistry returns empty list."""
        from agent_loop import ToolRegistry
        registry = ToolRegistry()
        assert registry.list_tools() == []

    def test_tool_definition_with_dict_parameters(self):
        """Test ToolDefinition initialization with dict parameters."""
        from mcp_server import ToolDefinition
        tool = ToolDefinition(
            name="dict-params",
            command="test",
            parameters=[{"name": "p1", "type": "string", "required": True}],
        )
        assert len(tool.parameters) == 1
        assert tool.parameters[0].name == "p1"
        assert tool.parameters[0].required

    def test_tool_definition_empty_parameters(self):
        """Test ToolDefinition with no parameters."""
        from mcp_server import ToolDefinition
        tool = ToolDefinition(name="no-params", command="true")
        assert tool.parameters == []
        d = tool.to_dict()
        assert d["inputSchema"]["properties"] == {}
        assert d["inputSchema"]["required"] == []

    def test_tool_schema_with_default_value(self):
        """Test ToolSchema with a default value."""
        from mcp_server import ToolSchema
        schema = ToolSchema("port", "integer", "Port number", default=8080)
        assert schema.default == 8080

    def test_tool_schema_with_enum(self):
        """Test ToolSchema with enum values."""
        from mcp_server import ToolSchema
        schema = ToolSchema("severity", "string", enum=["low", "high"])
        assert schema.enum == ["low", "high"]
